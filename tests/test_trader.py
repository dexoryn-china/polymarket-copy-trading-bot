"""CopyTrader.handle_fill against a fake CLOB (no network)."""

from __future__ import annotations

import asyncio
import time

from app import events
from app.control import Control
from app.core.orders import OrderTracker
from app.core.portfolio import BalanceMonitor, Collateral
from app.core.trader import CopyTrader
from app.events import EventBus
from app.pm.clob import OrderResult
from app.targets import VENUE_PREDICTIONS
from tests.fakes import (
    DummyOrderSource,
    FakeClob,
    make_copy_trader,
    make_fill,
    make_pred_target,
    trader_config,
)


def test_partial_fak_records_only_filled_amounts():
    asyncio.run(_partial_fak())


async def _partial_fak():
    clob = FakeClob()
    clob.queue_result(OrderResult(
        success=True, order_id="p1", status="matched",
        filled_shares=3.5, filled_usd=1.75,
    ))
    trader, _, _, acts = make_copy_trader(clob=clob)
    await trader.handle_fill(make_fill())
    assert len(trader.positions) == 1
    assert trader.positions[0].size_shares == 3.5
    assert trader.positions[0].cost_basis_usd == 1.75
    assert trader.target_buy_accumulator["1001"] == 0.0
    assert any(a.kind == events.COPY_SUCCESS for a in acts)


def test_unmatched_fak_keeps_buffer_and_emits_failure():
    asyncio.run(_unmatched())


async def _unmatched():
    clob = FakeClob()
    clob.queue_result(OrderResult(
        success=True, order_id="u1", status="unmatched",
        filled_shares=0.0, filled_usd=0.0,
    ))
    trader, _, _, acts = make_copy_trader(
        clob=clob, target=make_pred_target(min_target_shares_to_copy=10.0),
    )
    fill = make_fill(size=12.0)
    await trader.handle_fill(fill)
    assert trader.positions == []
    assert trader.target_buy_accumulator["1001"] == 12.0  # not reset
    assert any(a.kind == events.COPY_FAILURE for a in acts)

    clob.queue_result(OrderResult(
        success=True, order_id="u2", status="matched",
        filled_shares=5.0, filled_usd=2.5,
    ))
    await trader.handle_fill(make_fill(size=1.0, tx="0x2"))
    assert trader.target_buy_accumulator["1001"] == 0.0
    assert trader.positions[0].size_shares == 5.0


def test_resting_live_order_tracked_until_done():
    asyncio.run(_resting())


async def _resting():
    clob = FakeClob()
    clob.queue_result(OrderResult(
        success=True, order_id="live-1", status="live",
        filled_shares=0.0, filled_usd=0.0,
    ))
    cfg = trader_config(execution={"order_type": "maker"}, maker_settings={"rest_timeout_s": 30})
    bus = EventBus()
    orders = OrderTracker(DummyOrderSource(), bus, VENUE_PREDICTIONS)
    trader, _, _, _ = make_copy_trader(clob=clob, config=cfg, bus=bus, orders=orders)
    t0 = int(time.time() * 1000)
    await trader.handle_fill(make_fill())
    open_ = orders.open_orders()
    assert len(open_) == 1
    tracked = open_[0]
    assert tracked.order_id == "live-1"
    assert tracked.expires_at_ms is not None
    assert abs(tracked.expires_at_ms - (t0 + 30_000)) < 2_000
    reserved = trader.ctx.portfolio.reserved_usd(trader.target_id)
    assert reserved > 0
    # Simulate fill + done: reservation released.
    tracked.on_fill(2.0)
    assert trader.positions[0].size_shares == 2.0
    tracked.on_done()
    assert trader.ctx.portfolio.reserved_usd(trader.target_id) == 0.0


def test_balance_check_failure_skips_with_warning():
    asyncio.run(_balance_skip())


async def _balance_skip():
    class Src:
        async def get_collateral(self):
            return Collateral(0.01, 1000.0)

    bal = BalanceMonitor(Src(), lambda: 0.0)
    await bal.refresh()
    trader, clob, _, acts = make_copy_trader(balance=bal)
    await trader.handle_fill(make_fill())
    assert clob.place_calls == []
    skips = [a for a in acts if a.kind == events.COPY_SKIPPED]
    assert skips and skips[0].level == events.WARNING
    assert "insufficient" in (skips[0].data.get("reason") or "")


def test_per_target_and_global_caps_limit_size():
    asyncio.run(_caps())


async def _caps():
    # Global cap $12 with $10 copies → second BUY skipped.
    trader, clob, _, acts = make_copy_trader(
        target=make_pred_target(max_open_usd=100.0),
        global_cap=12.0,
    )
    await trader.handle_fill(make_fill(asset="A", slug="m1", tx="0x1"))
    assert len(clob.place_calls) == 1
    await trader.handle_fill(make_fill(asset="B", slug="m2", tx="0x2"))
    assert len(clob.place_calls) == 1
    assert any(a.kind == events.COPY_SKIPPED and "cap" in (a.data.get("reason") or "").lower()
               or (a.kind == events.COPY_SKIPPED and "headroom" in (a.data.get("reason") or "").lower())
               for a in acts)

    # Per-target cap independently.
    trader2, clob2, _, acts2 = make_copy_trader(
        target=make_pred_target(max_open_usd=12.0),
        global_cap=None,
    )
    await trader2.handle_fill(make_fill(asset="A", slug="m1", tx="0x1"))
    await trader2.handle_fill(make_fill(asset="B", slug="m2", tx="0x2"))
    assert len(clob2.place_calls) == 1
    assert any(a.kind == events.COPY_SKIPPED for a in acts2)


def test_paused_and_disabled_block_buys_not_sells():
    asyncio.run(_pause_disable())


async def _pause_disable():
    control = Control(paused=False)
    trader, clob, _, acts = make_copy_trader(control=control)
    await trader.handle_fill(make_fill(side="BUY", size=20, tx="0xbuy"))
    assert len(clob.place_calls) == 1
    held = trader._bot_shares_held("1001")
    assert held > 0

    control.paused = True
    await trader.handle_fill(make_fill(side="BUY", size=20, tx="0xbuy2"))
    assert len(clob.place_calls) == 1
    assert any("paused" in (a.data.get("reason") or "") for a in acts if a.kind == events.COPY_SKIPPED)

    await trader.handle_fill(make_fill(side="SELL", size=20, tx="0xsell"))
    assert len(clob.place_calls) == 2
    assert clob.place_calls[-1].side == "SELL"

    # Disabled target: buys blocked, sells still run. Rebuild with a position.
    target = make_pred_target(enabled=False)
    trader3, clob3, _, acts3 = make_copy_trader(target=target)
    # Seed a long so a SELL has something to mirror.
    trader3.positions  # noqa: B018
    from app.core.trader import PositionEntry
    trader3.positions.append(PositionEntry(
        asset_id="1001", market_slug="some-market", cost_basis_usd=10.0,
        opened_at_ms=int(time.time() * 1000), size_shares=20.0,
    ))
    trader3.target_holdings["1001"] = 20.0
    await trader3.handle_fill(make_fill(side="BUY", tx="0xnb"))
    assert clob3.place_calls == []
    assert any("disabled" in (a.data.get("reason") or "") for a in acts3)

    # Full target exit (holdings still 20 — the skipped BUY did add 20, so reset).
    trader3.target_holdings["1001"] = 20.0
    await trader3.handle_fill(make_fill(side="SELL", size=20, tx="0xns"))
    assert len(clob3.place_calls) == 1
    assert clob3.place_calls[0].side == "SELL"


def test_sell_records_actual_sold_shares():
    asyncio.run(_sell_actual())


async def _sell_actual():
    clob = FakeClob()
    clob.queue_result(OrderResult(
        success=True, status="matched", filled_shares=18.18, filled_usd=9.09, order_id="b",
    ))
    clob.queue_result(OrderResult(
        success=True, status="matched", filled_shares=7.25, filled_usd=3.0, order_id="s",
    ))
    trader, _, _, _ = make_copy_trader(clob=clob)
    await trader.handle_fill(make_fill(side="BUY", size=20, tx="0xb"))
    before = trader._bot_shares_held("1001")
    await trader.handle_fill(make_fill(side="SELL", size=20, tx="0xs"))
    after = trader._bot_shares_held("1001")
    # Full target exit dumps all, but records only filled 7.25.
    assert abs((before - after) - 7.25) < 1e-9


def test_copy_closes_false_skips_sells():
    asyncio.run(_no_closes())


async def _no_closes():
    trader, clob, _, acts = make_copy_trader(target=make_pred_target(copy_closes=False))
    await trader.handle_fill(make_fill(side="BUY", tx="0xb"))
    assert clob.place_calls and clob.place_calls[0].side == "BUY"
    await trader.handle_fill(make_fill(side="SELL", size=20, tx="0xs"))
    assert all(s.side == "BUY" for s in clob.place_calls)
    assert any("sell mirroring disabled" in (a.data.get("reason") or "") for a in acts)


def test_percent_sizing_uses_chunk_usd():
    asyncio.run(_percent())


async def _percent():
    target = make_pred_target(mode="percent_of_target", percent_of_target=10.0)
    trader, clob, _, _ = make_copy_trader(target=target)
    await trader.handle_fill(make_fill(size=20.0, price=0.50))
    spec = clob.place_calls[0]
    # chunk 20 * 0.50 * 10% = $1, but order minimum shares=5 bumps cost.
    # With taker slippage 10%, limit=0.55, min 5 shares → $2.75.
    assert spec.size >= 5.0
    assert spec.side == "BUY"


def test_stage_chunk_single_fill_larger_than_cap_not_truncated():
    threshold = 10.0
    trader, _, _, _ = make_copy_trader(
        target=make_pred_target(min_target_shares_to_copy=threshold),
    )
    size = threshold * CopyTrader.BUFFER_CAP_MULTIPLIER + 17.0
    fill = make_fill(size=size)
    chunk = trader.stage_chunk_if_ready(fill)
    assert chunk == size
    assert trader.target_buy_accumulator[fill.asset] == size


def test_stage_chunk_carryover_still_capped():
    threshold = 10.0
    trader, _, _, _ = make_copy_trader(
        target=make_pred_target(min_target_shares_to_copy=threshold),
    )
    cap = threshold * CopyTrader.BUFFER_CAP_MULTIPLIER
    trader.target_buy_accumulator["1001"] = cap - 1.0
    fill = make_fill(size=threshold + 5.0)  # would exceed cap if summed
    chunk = trader.stage_chunk_if_ready(fill)
    assert chunk == cap
    assert trader.target_buy_accumulator["1001"] == cap


def test_exposure_cap_skip_reasons():
    asyncio.run(_cap_skip_reasons())


async def _cap_skip_reasons():
    trader, clob, _, acts = make_copy_trader(
        target=make_pred_target(max_open_usd=100.0),
        global_cap=0.0,
    )
    await trader.handle_fill(make_fill())
    assert clob.place_calls == []
    reasons = [a.data.get("reason") or "" for a in acts if a.kind == events.COPY_SKIPPED]
    assert reasons == ["exposure cap reached — $0.00 left"]

    trader2, clob2, _, acts2 = make_copy_trader(
        target=make_pred_target(max_open_usd=100.0),
        global_cap=2.0,
    )
    await trader2.handle_fill(make_fill(price=0.50))
    assert clob2.place_calls == []
    reasons2 = [a.data.get("reason") or "" for a in acts2 if a.kind == events.COPY_SKIPPED]
    assert len(reasons2) == 1
    assert reasons2[0] == "exposure cap reached — $2.00 left, order minimum is $2.75"
