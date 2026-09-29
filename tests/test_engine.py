"""PredictionsEngine routing, live wallet set, legacy state, export_state."""

from __future__ import annotations

from app.control import Control
from app.core.engine import PredictionsEngine
from app.core.orders import OrderTracker
from app.core.portfolio import Portfolio
from app.core.trader import TradingContext
from app.events import EventBus
from app.targets import VENUE_PREDICTIONS, TargetStore
from tests.fakes import (
    SCHEMAS,
    WALLET_A,
    WALLET_B,
    DummyOrderSource,
    FakeClob,
    trader_config,
)


def _engine(tmp_path, seed=None, state=None) -> PredictionsEngine:
    store = TargetStore(str(tmp_path / "targets.yaml"), SCHEMAS)
    store.load(seed or [{
        "id": "first",
        "name": "w1",
        "venue": VENUE_PREDICTIONS,
        "wallet": WALLET_A,
    }])
    bus = EventBus()
    ctx = TradingContext(
        config=trader_config(),
        clob=FakeClob(),
        portfolio=Portfolio(),
        orders=OrderTracker(DummyOrderSource(), bus, VENUE_PREDICTIONS),
        bus=bus,
        control=Control(),
    )
    return PredictionsEngine(ctx, store, state)


def test_routes_fills_by_wallet(tmp_path):
    eng = _engine(tmp_path)
    trader = eng.traders["first"]
    assert trader.target.wallet == WALLET_A.lower()
    assert eng._by_wallet.get(WALLET_A.lower()) is trader
    assert eng._by_wallet.get(WALLET_B.lower()) is None
    assert WALLET_A.lower() in eng.wallets
    assert WALLET_B.lower() not in eng.wallets


def test_wallets_updated_live_on_add_update_remove(tmp_path):
    eng = _engine(tmp_path)
    store = eng.store
    assert eng.wallets == {WALLET_A.lower()}

    added = store.create({
        "name": "w2", "venue": VENUE_PREDICTIONS, "wallet": WALLET_B,
    })
    assert WALLET_B.lower() in eng.wallets
    assert added.id in eng.traders

    store.update(added.id, {"wallet": "0x3333333333333333333333333333333333333333"})
    assert WALLET_B.lower() not in eng.wallets
    assert "0x3333333333333333333333333333333333333333" in eng.wallets

    store.delete(added.id, lambda _t: False)
    assert added.id not in eng.traders
    assert "0x3333333333333333333333333333333333333333" not in eng.wallets
    assert WALLET_A.lower() in eng.wallets


def test_migrate_legacy_state_into_first_target(tmp_path):
    store = TargetStore(str(tmp_path / "t.yaml"), SCHEMAS)
    store.load([{
        "id": "legacy-owner",
        "name": "old",
        "venue": VENUE_PREDICTIONS,
        "wallet": WALLET_A,
    }])
    legacy = {
        "positions": [{"asset_id": "1", "market_slug": "m", "cost_basis_usd": 5.0,
                       "opened_at_ms": 1, "size_shares": 2.0}],
        "target_buy_accumulator": {"1": 4.0},
        "target_holdings": {"1": 9.0},
        "target_sell_accumulator": {},
    }
    migrated = PredictionsEngine.migrate_legacy_state(legacy, store)
    assert "targets" in migrated
    assert "legacy-owner" in migrated["targets"]
    assert migrated["targets"]["legacy-owner"]["positions"][0]["size_shares"] == 2.0

    already = {"predictions": {"targets": {"x": {}}}}
    assert PredictionsEngine.migrate_legacy_state(already, store) == already["predictions"]

    empty_store = TargetStore(str(tmp_path / "empty.yaml"), SCHEMAS)
    empty_store.load([])
    assert PredictionsEngine.migrate_legacy_state(legacy, empty_store) == {}


def test_export_state_shape(tmp_path):
    eng = _engine(tmp_path)
    exported = eng.export_state()
    assert set(exported) == {"targets"}
    inner = exported["targets"]["first"]
    assert "positions" in inner
    assert "target_buy_accumulator" in inner
    assert "target_holdings" in inner
    assert "target_sell_accumulator" in inner
