"""OrderState.is_final + OrderTracker with a fake source."""

from __future__ import annotations

import asyncio
import time

from app import events
from app.core.orders import OrderState, OrderTracker, TrackedOrder
from app.events import EventBus
from app.targets import VENUE_PREDICTIONS
from tests.fakes import make_pred_target


def test_order_state_is_final():
    not_final = ["live", "delayed", "ORDER_STATUS_LIVE", "LIVE", "open", "pending", "unknown", ""]
    for status in not_final:
        assert OrderState(status, 0).is_final is False, status
    for status in ("matched", "canceled", "canceled_market_resolved", "invalid",
                   "ORDER_STATUS_MATCHED", "expired"):
        assert OrderState(status, 1).is_final is True, status


class FakeSource:
    def __init__(self) -> None:
        self.states: dict[str, OrderState] = {}
        self.cancels: list[str] = []
        self.cancel_ok = True
        self.get_calls = 0
        self.post_cancel_state: dict[str, OrderState] = {}

    async def get_order(self, order_id: str):
        self.get_calls += 1
        if order_id in self.post_cancel_state and order_id in self.cancels:
            return self.post_cancel_state[order_id]
        return self.states.get(order_id)

    async def cancel_order(self, order_id: str) -> bool:
        self.cancels.append(order_id)
        return self.cancel_ok


def _tracked(oid: str, *, size=10.0, filled=0.0, expires=None, fills=None, dones=None, target=None):
    fills = fills if fills is not None else []
    dones = dones if dones is not None else []
    return TrackedOrder(
        order_id=oid,
        venue=VENUE_PREDICTIONS,
        target=target or make_pred_target(),
        asset="1001",
        label="mkt",
        side="BUY",
        price=0.5,
        size=size,
        filled=filled,
        placed_at_ms=1,
        expires_at_ms=expires,
        on_fill=fills.append,
        on_done=lambda: dones.append(oid),
    )


def test_poll_applies_incremental_fills_and_finishes():
    asyncio.run(_poll_fills())


async def _poll_fills():
    src = FakeSource()
    bus = EventBus()
    acts = []
    bus.subscribe(acts.append)
    tracker = OrderTracker(src, bus, VENUE_PREDICTIONS, poll_interval_s=0.01)
    fills, dones = [], []
    order = _tracked("o1", size=10, fills=fills, dones=dones)
    tracker.track(order)

    src.states["o1"] = OrderState("live", 3.0)
    await tracker._poll(order)
    assert fills == [3.0]
    assert order.filled == 3.0
    assert not dones
    assert tracker.pending_size("tpred", "1001", "BUY") == 7.0

    src.states["o1"] = OrderState("live", 7.0)
    await tracker._poll(order)
    assert fills == [3.0, 4.0]

    src.states["o1"] = OrderState("matched", 10.0)
    await tracker._poll(order)
    assert fills[-1] == 3.0
    assert dones == ["o1"]
    assert tracker.open_orders() == []
    kinds = [a.kind for a in acts]
    assert events.ORDER_UPDATE in kinds
    assert any("matched" in a.summary for a in acts)


def test_cancel_after_expiry_rereads_fills():
    asyncio.run(_cancel_expiry())


async def _cancel_expiry():
    src = FakeSource()
    bus = EventBus()
    tracker = OrderTracker(src, bus, VENUE_PREDICTIONS)
    fills, dones = [], []
    order = _tracked("o2", size=8, filled=1.0, expires=int(time.time() * 1000) - 1000,
                     fills=fills, dones=dones)
    tracker.track(order)
    src.states["o2"] = OrderState("live", 1.0)
    src.post_cancel_state["o2"] = OrderState("canceled", 5.0)
    await tracker._poll(order)
    assert src.cancels == ["o2"]
    assert fills == [4.0]
    assert dones == ["o2"]
    assert tracker.open_orders() == []


def test_pending_size_and_cancel_all():
    asyncio.run(_pending_cancel_all())


async def _pending_cancel_all():
    src = FakeSource()
    bus = EventBus()
    tracker = OrderTracker(src, bus, VENUE_PREDICTIONS)
    t = make_pred_target()
    a = _tracked("a", size=5, filled=1, target=t)
    b = _tracked("b", size=3, filled=0, target=t)
    b.side = "SELL"
    tracker.track(a)
    tracker.track(b)
    assert tracker.pending_size(t.id, "1001", "BUY") == 4.0
    assert tracker.pending_size(t.id, "1001", "SELL") == 3.0
    src.states["a"] = OrderState("canceled", 1.0)
    src.states["b"] = OrderState("canceled", 0.0)
    await tracker.cancel_all()
    assert set(src.cancels) == {"a", "b"}
    assert tracker.open_orders() == []
