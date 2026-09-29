"""PerpsTrader + PerpsEngine with a fake PerpsClient."""

from __future__ import annotations

import asyncio

from app import events
from app.control import Control
from app.core.portfolio import Portfolio
from app.events import EventBus
from app.perps.account import PerpsAccount
from app.perps.client import PerpsOrderResult, PublicPosition
from app.perps.engine import ERROR_ALERT_AFTER, PerpsEngine
from app.perps.trader import PerpsContext, PositionChange
from app.targets import VENUE_PERPS, TargetStore
from tests.fakes import (
    SCHEMAS,
    WALLET_B,
    FakePerpsClient,
    make_instrument,
    make_perps_target,
    make_perps_trader,
)


def _pos(iid=1, symbol="BTC", size=2.0, entry=100.0) -> PublicPosition:
    return PublicPosition(iid, symbol, size, entry)


def _change(prev, now, iid=1, symbol="BTC", entry=100.0) -> PositionChange:
    return PositionChange(iid, symbol, prev, now, entry, 1_727_540_000_000)


def test_first_observe_is_silent_baseline():
    asyncio.run(_baseline())


async def _baseline():
    trader, client, _, acts, _ = make_perps_trader()
    changes = trader.observe({1: _pos(size=5.0)})
    assert changes == []
    assert trader.positions == {}
    assert trader.target_sizes == {1: 5.0}
    assert client.place_calls == []
    assert acts == []


def test_growth_sized_by_percent_and_fixed():
    asyncio.run(_growth())


async def _growth():
    trader, client, _, acts, _ = make_perps_trader(
        target=make_perps_target(percent_of_target=10.0),
        mark=100.0,
    )
    trader.target_sizes = {}
    trader._observed_since_start = True
    await trader.handle_change(_change(0.0, 2.0))
    assert len(client.place_calls) == 1
    # delta 2 × 10% = 0.2
    assert abs(client.place_calls[0]["qty"] - 0.2) < 1e-9
    assert client.place_calls[0]["buy"] is True
    assert client.place_calls[0]["reduce_only"] is False
    assert trader.size(1) == 0.2
    assert any(a.kind == events.COPY_SUCCESS for a in acts)

    trader_f, client_f, _, _, _ = make_perps_trader(
        target=make_perps_target(mode="fixed_notional", fixed_notional_usd=50.0),
        mark=100.0,
    )
    trader_f.target_sizes = {}
    trader_f._observed_since_start = True
    await trader_f.handle_change(_change(0.0, 3.0))
    assert abs(client_f.place_calls[0]["qty"] - 0.5) < 1e-9  # 50/100


def test_reduction_proportional_reduce_only_and_full_close():
    asyncio.run(_reduce_close())


async def _reduce_close():
    trader, client, _, _, _ = make_perps_trader()
    trader.target_sizes = {1: 2.0}
    trader._observed_since_start = True
    await trader.handle_change(_change(0.0, 2.0))
    assert trader.size(1) > 0
    client.place_calls.clear()

    await trader.handle_change(_change(2.0, 1.0))  # 50% reduction
    assert len(client.place_calls) == 1
    assert client.place_calls[0]["reduce_only"] is True
    assert client.place_calls[0]["buy"] is False  # closing a long
    half = client.place_calls[0]["qty"]

    # Full close
    client.place_calls.clear()
    remaining = trader.size(1)
    await trader.handle_change(_change(1.0, 0.0))
    assert client.place_calls[-1]["reduce_only"] is True
    assert abs(client.place_calls[-1]["qty"] - abs(remaining)) < 1e-6
    assert trader.size(1) == 0.0
    assert not trader.positions
    assert half > 0


def test_side_flip_closes_then_opens_opposite():
    asyncio.run(_flip())


async def _flip():
    trader, client, _, _, _ = make_perps_trader()
    trader._observed_since_start = True
    await trader.handle_change(_change(0.0, 2.0))
    client.place_calls.clear()
    await trader.handle_change(_change(2.0, -1.0))
    assert len(client.place_calls) == 2
    assert client.place_calls[0]["buy"] is False  # close long
    assert client.place_calls[0]["reduce_only"] is True
    assert client.place_calls[1]["buy"] is False  # open short
    assert client.place_calls[1]["reduce_only"] is False
    assert trader.size(1) < 0


def test_restart_mirrors_only_reductions_on_first_observe():
    asyncio.run(_restart())


async def _restart():
    inst = make_instrument()
    state = {
        "positions": {
            "1": {
                "instrument_id": 1, "symbol": "BTC", "size": 0.2,
                "entry_price": 100.0, "opened_at_ms": 1, "leverage": 3,
            }
        },
        "target_sizes": {"1": 2.0},
    }
    trader, client, _, _, _ = make_perps_trader(state=state, inst=inst)
    assert trader.size(1) == 0.2

    # Growth while offline — ignored.
    grew = trader.observe({1: _pos(size=5.0)})
    await asyncio.gather(*list(trader._bg_tasks)) if trader._bg_tasks else None
    assert grew == []
    assert client.place_calls == []
    assert trader.size(1) == 0.2

    # Fresh trader for flip-as-close-only on first observation.
    trader2, client2, _, _, _ = make_perps_trader(state=state, inst=inst)
    flipped = trader2.observe({1: _pos(size=-3.0)})
    if trader2._bg_tasks:
        await asyncio.gather(*list(trader2._bg_tasks))
    assert len(flipped) == 1
    assert flipped[0].now == 0.0  # converted to close
    assert client2.place_calls and client2.place_calls[0]["buy"] is False
    assert trader2.size(1) == 0.0


def test_max_open_notional_cap():
    asyncio.run(_cap())


async def _cap():
    trader, client, _, acts, _ = make_perps_trader(
        target=make_perps_target(max_open_notional_usd=15.0, percent_of_target=100.0),
        mark=100.0,
    )
    trader._observed_since_start = True
    await trader.handle_change(_change(0.0, 0.1))  # qty=0.1, notional=10
    assert len(client.place_calls) == 1
    await trader.handle_change(_change(0.1, 0.3))  # would add 0.2 → $20, cap leftover $5
    # Second order sized down by headroom (5/100=0.05) or skipped if below min.
    # min_notional default 1, 0.05*100=5 >= 1 so it should place 0.05.
    if client.place_calls[1:]:
        assert client.place_calls[1]["qty"] <= 0.05 + 1e-9
    else:
        assert any(a.kind == events.COPY_SKIPPED for a in acts)


def test_below_min_notional_accumulates():
    asyncio.run(_accum())


async def _accum():
    inst = make_instrument(min_notional=50.0)
    trader, client, _, _, _ = make_perps_trader(
        inst=inst, mark=100.0,
        target=make_perps_target(percent_of_target=10.0),
    )
    trader._observed_since_start = True
    await trader.handle_change(_change(0.0, 3.0))  # qty=0.3, $30 < $50
    assert client.place_calls == []
    assert trader.positions == {}
    await trader.handle_change(_change(3.0, 6.0))  # +0.3 pending → 0.6, $60
    assert len(client.place_calls) == 1
    assert abs(client.place_calls[0]["qty"] - 0.6) < 1e-9


def test_paused_disabled_block_entries_not_exits():
    asyncio.run(_pause())


async def _pause():
    control = Control(paused=False)
    trader, client, _, acts, _ = make_perps_trader(control=control)
    trader._observed_since_start = True
    await trader.handle_change(_change(0.0, 2.0))
    assert trader.size(1) != 0
    client.place_calls.clear()
    control.paused = True
    await trader.handle_change(_change(2.0, 3.0))
    assert client.place_calls == []
    assert any("paused" in (a.data.get("reason") or "") for a in acts)

    await trader.handle_change(_change(3.0, 0.0))
    assert client.place_calls and client.place_calls[0]["buy"] is False

    trader_d, client_d, _, acts_d, _ = make_perps_trader(
        target=make_perps_target(enabled=False),
    )
    # Seed a long so an exit can fire.
    from app.perps.trader import PerpPosition
    trader_d.positions[1] = PerpPosition(1, "BTC", 0.2, 100.0, 1, 3)
    trader_d._observed_since_start = True
    await trader_d.handle_change(_change(0.0, 2.0))
    assert client_d.place_calls == []
    await trader_d.handle_change(_change(2.0, 0.0))
    assert client_d.place_calls and client_d.place_calls[0]["buy"] is False


def test_copy_closes_false_skips_exits():
    asyncio.run(_no_close())


async def _no_close():
    trader, client, _, acts, _ = make_perps_trader(
        target=make_perps_target(copy_closes=False),
    )
    trader._observed_since_start = True
    await trader.handle_change(_change(0.0, 2.0))
    client.place_calls.clear()
    await trader.handle_change(_change(2.0, 0.0))
    assert client.place_calls == []
    assert any("close mirroring disabled" in (a.data.get("reason") or "") for a in acts)


def test_partial_ioc_recorded_exactly_unfilled_fails():
    asyncio.run(_partial_fail())


async def _partial_fail():
    trader, client, _, acts, _ = make_perps_trader()
    trader._observed_since_start = True
    client.queue_result(PerpsOrderResult(
        success=True, status="ioc_expired", filled_qty=0.4, avg_price=101.0,
    ))
    await trader.handle_change(_change(0.0, 2.0))
    assert abs(trader.size(1) - 0.4) < 1e-9
    assert abs(trader.positions[1].entry_price - 101.0) < 1e-9

    trader2, client2, _, acts2, _ = make_perps_trader()
    trader2._observed_since_start = True
    client2.queue_result(PerpsOrderResult(
        success=True, status="ioc_no_fill", filled_qty=0.0,
    ))
    await trader2.handle_change(_change(0.0, 2.0))
    assert trader2.positions == {}
    assert any(a.kind == events.COPY_FAILURE for a in acts2)


def test_ensure_leverage_only_when_flat():
    asyncio.run(_lev())


async def _lev():
    trader, client, _, _, account = make_perps_trader()
    trader._observed_since_start = True
    await trader.handle_change(_change(0.0, 2.0))
    assert len(client.leverage_calls) == 1
    await trader.handle_change(_change(2.0, 4.0))  # add, still long
    assert len(client.leverage_calls) == 1


def test_export_state_restores_positions():
    asyncio.run(_restore())


async def _restore():
    trader, client, _, _, _ = make_perps_trader()
    trader.observe({})  # silent baseline so target_sizes is persisted
    trader._observed_since_start = True
    await trader.handle_change(_change(0.0, 2.0))
    state = trader.export_state()
    trader2, _, _, _, _ = make_perps_trader(state=state)
    assert trader2.size(1) == trader.size(1)
    assert trader2.target_sizes == trader.target_sizes


def test_never_observed_target_restores_as_fresh_baseline():
    trader, _, _, _, _ = make_perps_trader()
    trader2, _, _, _, _ = make_perps_trader(state=trader.export_state())
    assert trader2.target_sizes is None
    assert trader2.observe({1: PublicPosition(1, "BTC-USD", 1.0, 100.0)}) == []


def _perps_engine(tmp_path, client=None):
    store = TargetStore(str(tmp_path / "targets.yaml"), SCHEMAS)
    store.load([{
        "id": "pt",
        "name": "perp",
        "venue": VENUE_PERPS,
        "wallet": WALLET_B,
    }])
    client = client or FakePerpsClient({1: make_instrument()})
    client.set_mark(1, 100.0)
    bus = EventBus()
    acts = []
    bus.subscribe(acts.append)
    ctx = PerpsContext(
        config={"poll_interval_s": 0.25, "slippage_bps": 50, "margin_mode": "isolated"},
        client=client,
        account=PerpsAccount(client),
        portfolio=Portfolio(),
        bus=bus,
        control=Control(),
    )
    engine = PerpsEngine(ctx, store)
    return engine, client, acts, store, bus


def test_engine_poll_observe_failures_feed_status_and_removal(tmp_path):
    asyncio.run(_engine(tmp_path))


async def _engine(tmp_path):
    engine, client, acts, store, bus = _perps_engine(tmp_path)
    client.portfolios[WALLET_B.lower()] = {1: _pos(size=1.0)}
    trader = engine.traders["pt"]
    await engine._poll(trader)
    assert trader.target_sizes == {1: 1.0}  # baseline
    await engine._poll(trader)  # no change
    assert client.place_calls == []

    client.portfolios[WALLET_B.lower()] = {1: _pos(size=3.0)}
    await engine._poll(trader)
    if trader._bg_tasks:
        await asyncio.gather(*list(trader._bg_tasks))
    assert client.place_calls  # growth copied

    status = engine.feed_status()
    assert status["id"] == "perps-poll"
    assert "label" in status
    assert "connected" in status
    assert "last_event_ms" in status
    assert "reconnects" in status

    # 5 consecutive failures → ERROR
    client.public_raise = RuntimeError("timeout")
    for _ in range(ERROR_ALERT_AFTER):
        await engine._poll(trader)
    assert sum(1 for a in acts if a.kind == events.ERROR) >= 1
    assert engine.poll_failures >= ERROR_ALERT_AFTER

    # Removal unregisters
    store.delete("pt", lambda _t: False)
    assert "pt" not in engine.traders
    assert engine.ctx.account.net_size(1) == 0.0


def test_poll_interval_s_reads_live_config(tmp_path):
    engine, _, _, _, _ = _perps_engine(tmp_path)
    assert engine.poll_interval_s == 0.25
    engine.ctx.config["poll_interval_s"] = 4.0
    assert engine.poll_interval_s == 4.0


def test_resume_skips_growth_but_mirrors_reduction():
    asyncio.run(_resume_offline())


async def _resume_offline():
    trader, client, _, _, _ = make_perps_trader()
    trader.target_sizes = {1: 2.0}
    trader._observed_since_start = True
    trader.resume()
    grew = trader.observe({1: _pos(size=5.0)})
    if trader._bg_tasks:
        await asyncio.gather(*list(trader._bg_tasks))
    assert grew == []
    assert client.place_calls == []

    from app.perps.trader import PerpPosition
    trader2, client2, _, _, _ = make_perps_trader()
    trader2.positions[1] = PerpPosition(1, "BTC", 0.2, 100.0, 1, 3)
    trader2.target_sizes = {1: 2.0}
    trader2._observed_since_start = True
    trader2.resume()
    reduced = trader2.observe({1: _pos(size=1.0)})
    if trader2._bg_tasks:
        await asyncio.gather(*list(trader2._bg_tasks))
    assert reduced
    assert client2.place_calls
    assert client2.place_calls[0]["buy"] is False


def test_engine_run_resumes_traders(tmp_path):
    asyncio.run(_engine_resume(tmp_path))


async def _engine_resume(tmp_path):
    engine, _, _, _, _ = _perps_engine(tmp_path)
    trader = engine.traders["pt"]
    trader.target_sizes = {1: 2.0}
    trader._observed_since_start = True
    stop = asyncio.Event()
    stop.set()
    await engine.run(stop)
    assert trader._observed_since_start is False
