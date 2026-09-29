"""Tracks resting / delayed CLOB orders until they reach a final state.

Polls order status, reports incremental fills to the owner via callbacks, and
cancels orders still resting after `rest_timeout_s` (maker GTC copies would
otherwise sit on the book forever).
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from app import events
from app.events import EventBus

log = logging.getLogger("orders")

POLL_INTERVAL_S = 2.0
# Anything else the venue reports (matched, canceled, canceled_market_resolved,
# invalid, expired, …) is terminal.
OPEN_STATUSES = {"live", "delayed", "open", "pending", "unknown"}


@dataclass
class OrderState:
    status: str
    size_matched: float

    @property
    def is_final(self) -> bool:
        status = self.status.lower().removeprefix("order_status_")
        return bool(status) and status not in OPEN_STATUSES


class OrderSource(Protocol):
    async def get_order(self, order_id: str) -> Optional[OrderState]: ...
    async def cancel_order(self, order_id: str) -> bool: ...


@dataclass
class TrackedOrder:
    order_id: str
    venue: str
    target: object                       # Target (id / name)
    asset: str                           # instrument id (token id / symbol)
    label: str                           # human-readable market name
    side: str
    price: float
    size: float
    filled: float
    placed_at_ms: int
    expires_at_ms: Optional[int]
    on_fill: Callable[[float], None]     # incremental shares filled
    on_done: Callable[[], None]

    def to_dict(self) -> dict:
        return {
            "id": self.order_id,
            "venue": self.venue,
            "target_id": getattr(self.target, "id", None),
            "target_name": getattr(self.target, "name", None),
            "label": self.label,
            "side": self.side,
            "price": self.price,
            "size": self.size,
            "filled": self.filled,
            "placed_at_ms": self.placed_at_ms,
            "expires_at_ms": self.expires_at_ms,
        }


class OrderTracker:
    def __init__(self, source: OrderSource, bus: EventBus, venue: str,
                 poll_interval_s: float = POLL_INTERVAL_S) -> None:
        self.source = source
        self.bus = bus
        self.venue = venue
        self.poll_interval_s = poll_interval_s
        self._orders: dict[str, TrackedOrder] = {}

    def track(self, order: TrackedOrder) -> None:
        self._orders[order.order_id] = order

    def open_orders(self) -> list[TrackedOrder]:
        return list(self._orders.values())

    def pending_size(self, target_id: str, asset: str, side: str) -> float:
        """Unfilled size resting for (target, asset, side)."""
        return sum(
            o.size - o.filled for o in self._orders.values()
            if getattr(o.target, "id", None) == target_id and o.asset == asset and o.side == side
        )

    async def run(self, shutdown: asyncio.Event) -> None:
        while not shutdown.is_set():
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=self.poll_interval_s)
                return
            except asyncio.TimeoutError:
                pass
            if self._orders:
                await asyncio.gather(*(self._poll(o) for o in list(self._orders.values())))

    async def cancel_all(self) -> None:
        await asyncio.gather(*(self._cancel(o, reason="shutdown") for o in list(self._orders.values())))

    async def _poll(self, order: TrackedOrder) -> None:
        state = await self._fetch(order)
        if state is None:
            return
        self._apply(order, state)
        if state.is_final:
            self._finish(order, state.status.lower())
            return
        if order.expires_at_ms is not None and int(time.time() * 1000) >= order.expires_at_ms:
            await self._cancel(order, reason="rest timeout")

    async def _cancel(self, order: TrackedOrder, reason: str) -> None:
        if order.order_id not in self._orders:
            return
        try:
            ok = await self.source.cancel_order(order.order_id)
        except Exception as e:
            log.warning(f"cancel {order.order_id[:10]}… failed: {e}")
            return
        # Re-read so fills that landed right before the cancel are recorded.
        state = await self._fetch(order)
        if state is not None:
            self._apply(order, state)
        if ok or (state is not None and state.is_final):
            self._finish(order, f"canceled ({reason})")

    async def _fetch(self, order: TrackedOrder) -> Optional[OrderState]:
        try:
            return await self.source.get_order(order.order_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"order status {order.order_id[:10]}… failed: {e}")
            return None

    def _apply(self, order: TrackedOrder, state: OrderState) -> None:
        delta = min(state.size_matched, order.size) - order.filled
        if delta <= 1e-9:
            return
        order.filled += delta
        try:
            order.on_fill(delta)
        except Exception:
            log.exception(f"on_fill failed for order {order.order_id[:10]}…")

    def _finish(self, order: TrackedOrder, outcome: str) -> None:
        if self._orders.pop(order.order_id, None) is None:
            return
        try:
            order.on_done()
        except Exception:
            log.exception(f"on_done failed for order {order.order_id[:10]}…")
        self.bus.emit(
            events.ORDER_UPDATE,
            f"{order.side} {order.label}: {outcome}, filled {order.filled:.2f}/{order.size:.2f}",
            level=events.INFO,
            venue=self.venue,
            target=order.target,
            order_id=order.order_id,
            outcome=outcome,
            filled=order.filled,
            size=order.size,
            price=order.price,
        )
