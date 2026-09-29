"""Shared fakes and builders for tests (no network)."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional

from app.config import load_config
from app.control import Control
from app.core.orders import OrderState, OrderTracker
from app.core.portfolio import Portfolio
from app.core.schema import PREDICTIONS_SCHEMA
from app.core.trader import CopyTrader, TargetFill, TradingContext
from app.events import EventBus
from app.perps.account import PerpsAccount
from app.perps.client import Instrument, PerpsOrderResult, PublicPosition
from app.perps.schema import PERPS_SCHEMA
from app.perps.trader import PerpsContext, PerpsTrader
from app.pm.clob import MarketMeta, OrderResult, OrderSpec
from app.runtime import Runtime, VenueRuntime
from app.session import CopySession, VenuePipeline
from app.settings import SettingsStore
from app.stats import Stats
from app.storage.history import HistoryStore
from app.targets import (
    VENUE_PERPS,
    VENUE_PREDICTIONS,
    Target,
    TargetStore,
    VenueSchema,
)

SCHEMAS: dict[str, VenueSchema] = {
    VENUE_PREDICTIONS: PREDICTIONS_SCHEMA,
    VENUE_PERPS: PERPS_SCHEMA,
}

WALLET_A = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"
WALLET_B = "0x1111111111111111111111111111111111111111"
WALLET_C = "0x2222222222222222222222222222222222222222"

EXAMPLE_CONFIG = Path(__file__).resolve().parents[1] / "config.yaml.example"


def load_example_config(tmp_path) -> dict:
    dest = tmp_path / "config.yaml"
    dest.write_text(EXAMPLE_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    return load_config(str(dest))


def make_settings_store(tmp_path, config: Optional[dict] = None) -> SettingsStore:
    config = config if config is not None else load_example_config(tmp_path)
    store = SettingsStore(config, str(tmp_path / "settings.yaml"))
    store.load()
    return store


def trader_config(**overrides) -> dict:
    cfg: dict[str, Any] = {
        "mode": "dry_run",
        "execution": {"order_type": "taker"},
        "order_minimum": {"mode": "shares", "min_usd": 1.0, "min_shares": 5.0},
        "maker_settings": {"rest_timeout_s": 30, "price_offset_ticks": 0},
        "position_expiry": {"buffer_s": 60, "fallback_ttl_min": 1440},
        "slippage": {"entry_bps_max": 1000, "exit_bps_max": 1000},
        "dedup": {"seen_cap": 50000},
        "watchdog": {"max_consecutive_errors": 5, "silent_timeout_s": 30},
        "risk": {"max_open_usd_total": None},
        "perps": {
            "poll_interval_s": 1.0,
            "slippage_bps": 50,
            "margin_mode": "isolated",
            "max_open_notional_total": None,
        },
        "web": {"enabled": True, "host": "127.0.0.1", "port": 8787, "token": ""},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            cfg[key] = {**cfg[key], **value}
        else:
            cfg[key] = value
    return cfg


def valid_config_dict(**overrides) -> dict:
    """A mapping that passes validate_config after DEFAULTS are merged."""
    cfg = {
        "mode": "dry_run",
        "slippage": {"entry_bps_max": 1000, "exit_bps_max": 1000},
        "position_expiry": {"buffer_s": 60, "fallback_ttl_min": 1440},
        "dedup": {"seen_cap": 50000},
        "watchdog": {"max_consecutive_errors": 5, "silent_timeout_s": 30},
    }
    cfg.update(overrides)
    return cfg


def pred_sizing(**over) -> dict:
    sizing = {
        "mode": "fixed",
        "fixed_usd_per_fill": 10.0,
        "percent_of_target": 5.0,
        "max_open_usd": 100.0,
        "min_target_shares_to_copy": 1.0,
    }
    sizing.update(over)
    return sizing


def perps_sizing(**over) -> dict:
    sizing = {
        "mode": "percent_of_target",
        "percent_of_target": 10.0,
        "fixed_notional_usd": 50.0,
        "max_open_notional_usd": 500.0,
        "leverage": 3.0,
    }
    sizing.update(over)
    return sizing


def make_pred_target(
    *,
    target_id: str = "tpred",
    name: str = "whale",
    wallet: str = WALLET_A,
    enabled: bool = True,
    copy_closes: bool = True,
    **sizing_over,
) -> Target:
    return Target(
        id=target_id,
        name=name,
        venue=VENUE_PREDICTIONS,
        wallet=wallet.lower(),
        enabled=enabled,
        copy_closes=copy_closes,
        sizing=pred_sizing(**sizing_over),
    )


def make_perps_target(
    *,
    target_id: str = "tperp",
    name: str = "perp-whale",
    wallet: str = WALLET_B,
    enabled: bool = True,
    copy_closes: bool = True,
    **sizing_over,
) -> Target:
    return Target(
        id=target_id,
        name=name,
        venue=VENUE_PERPS,
        wallet=wallet.lower(),
        enabled=enabled,
        copy_closes=copy_closes,
        sizing=perps_sizing(**sizing_over),
    )


def make_fill(
    *,
    asset: str = "1001",
    side: str = "BUY",
    size: float = 20.0,
    price: float = 0.50,
    slug: str = "some-market",
    tx: str = "0xabc",
    outcome: str = "Yes",
    title: str = "T",
    wallet: str = WALLET_A,
    timestamp_ms: int = 1_727_540_000_000,
) -> TargetFill:
    return TargetFill(
        tx_hash=tx,
        asset=asset,
        market_slug=slug,
        side=side,
        size=size,
        price=price,
        price_str=str(price),
        timestamp_ms=timestamp_ms,
        outcome=outcome,
        title=title,
        wallet=wallet.lower(),
    )


class DummyOrderSource:
    async def get_order(self, order_id: str) -> Optional[OrderState]:
        return None

    async def cancel_order(self, order_id: str) -> bool:
        return True


class FakeClob:
    """CLOB double used by CopyTrader tests — no network."""

    def __init__(self) -> None:
        self.cached_slugs: set[str] = set()
        self.meta_calls: list[str] = []
        self.place_calls: list[OrderSpec] = []
        self.tick = 0.01
        self.neg_risk = False
        self.end_date_ms = 1_900_000_000_000
        self.results: list[OrderResult] = []
        self.default_result: Optional[OrderResult] = None
        self.place_raise: Optional[BaseException] = None
        self.dry_run = True

    def has_market_meta(self, slug: str) -> bool:
        return slug in self.cached_slugs

    async def get_market_meta(self, slug: str) -> MarketMeta:
        self.meta_calls.append(slug)
        self.cached_slugs.add(slug)
        return MarketMeta(
            neg_risk=self.neg_risk,
            tick=self.tick,
            end_date_ms=self.end_date_ms,
        )

    async def fetch_market_end_date(self, slug: str):
        return self.end_date_ms

    def queue_result(self, result: OrderResult) -> None:
        self.results.append(result)

    async def place_order(self, spec: OrderSpec) -> OrderResult:
        self.place_calls.append(spec)
        if self.place_raise is not None:
            raise self.place_raise
        if self.results:
            return self.results.pop(0)
        if self.default_result is not None:
            return self.default_result
        return OrderResult(
            success=True,
            dry_run=self.dry_run,
            order_id="ord_1",
            status="matched",
            filled_shares=spec.size,
            filled_usd=spec.size * spec.price,
        )


def make_copy_trader(
    *,
    target: Optional[Target] = None,
    clob: Optional[FakeClob] = None,
    config: Optional[dict] = None,
    global_cap: Optional[float] = None,
    bus: Optional[EventBus] = None,
    control: Optional[Control] = None,
    balance=None,
    orders: Optional[OrderTracker] = None,
    state: Optional[dict] = None,
    activities: Optional[list] = None,
) -> tuple[CopyTrader, FakeClob, EventBus, list]:
    target = target or make_pred_target()
    clob = clob or FakeClob()
    bus = bus or EventBus()
    collected: list = activities if activities is not None else []
    bus.subscribe(collected.append)
    control = control or Control()
    portfolio = Portfolio(global_cap)
    orders = orders or OrderTracker(DummyOrderSource(), bus, VENUE_PREDICTIONS)
    ctx = TradingContext(
        config=config or trader_config(),
        clob=clob,
        portfolio=portfolio,
        orders=orders,
        bus=bus,
        control=control,
        balance=balance,
    )
    trader = CopyTrader(target, ctx, state)
    portfolio.register(trader)
    return trader, clob, bus, collected


class FakePerpsClient:
    """PerpsClient double: instruments, marks, place_ioc, portfolio."""

    def __init__(self, instruments: Optional[dict[int, Instrument]] = None) -> None:
        self.instruments: dict[int, Instrument] = instruments or {}
        self._marks: dict[int, float] = {}
        self.place_calls: list[dict] = []
        self.results: list[PerpsOrderResult] = []
        self.default_result: Optional[PerpsOrderResult] = None
        self.leverage_calls: list[tuple] = []
        self.portfolios: dict[str, dict[int, PublicPosition]] = {}
        self.public_raise: Optional[BaseException] = None
        self.load_calls = 0
        self.dry_run = True

    def mark(self, instrument_id: int) -> Optional[float]:
        return self._marks.get(instrument_id)

    def set_mark(self, instrument_id: int, price: float) -> None:
        self._marks[instrument_id] = price

    def queue_result(self, result: PerpsOrderResult) -> None:
        self.results.append(result)

    async def place_ioc(self, inst, buy: bool, qty, price, reduce_only: bool) -> PerpsOrderResult:
        self.place_calls.append(
            {
                "inst": inst,
                "buy": buy,
                "qty": float(qty),
                "price": float(price) if not isinstance(price, Decimal) else float(price),
                "reduce_only": reduce_only,
            }
        )
        if self.results:
            return self.results.pop(0)
        if self.default_result is not None:
            return self.default_result
        filled = float(qty)
        return PerpsOrderResult(
            success=True,
            status="filled",
            filled_qty=filled,
            avg_price=self.mark(inst.id) or float(price),
            dry_run=True,
            order_id=1,
        )

    async def load_instruments(self) -> dict[int, Instrument]:
        self.load_calls += 1
        return self.instruments

    async def update_leverage(self, inst, leverage: int, cross: bool) -> None:
        self.leverage_calls.append((inst.id, leverage, cross))

    async def public_portfolio(self, address: str) -> dict[int, PublicPosition]:
        if self.public_raise is not None:
            raise self.public_raise
        return dict(self.portfolios.get(address.lower(), {}))


def make_instrument(
    *,
    iid: int = 1,
    symbol: str = "BTC",
    quantity_decimals: int = 4,
    price_decimals: int = 1,
    min_notional: float = 1.0,
    max_market_notional: float = 1_000_000.0,
    max_leverage: int = 20,
    price_bounds: float = 0.05,
    isolated_only: bool = False,
) -> Instrument:
    return Instrument(
        id=iid,
        symbol=symbol,
        quantity_decimals=quantity_decimals,
        price_decimals=price_decimals,
        price_bounds=price_bounds,
        min_notional=min_notional,
        max_market_notional=max_market_notional,
        max_leverage=max_leverage,
        isolated_only=isolated_only,
    )


def make_perps_trader(
    *,
    target: Optional[Target] = None,
    client: Optional[FakePerpsClient] = None,
    inst: Optional[Instrument] = None,
    mark: float = 100.0,
    control: Optional[Control] = None,
    bus: Optional[EventBus] = None,
    global_cap: Optional[float] = None,
    state: Optional[dict] = None,
    config: Optional[dict] = None,
    activities: Optional[list] = None,
) -> tuple[PerpsTrader, FakePerpsClient, EventBus, list, PerpsAccount]:
    inst = inst or make_instrument()
    client = client or FakePerpsClient({inst.id: inst})
    if inst.id not in client.instruments:
        client.instruments[inst.id] = inst
    client.set_mark(inst.id, mark)
    target = target or make_perps_target()
    bus = bus or EventBus()
    collected: list = activities if activities is not None else []
    bus.subscribe(collected.append)
    control = control or Control()
    portfolio = Portfolio(global_cap)
    account = PerpsAccount(client, cross_margin=False)
    ctx = PerpsContext(
        config=config or {"poll_interval_s": 0.25, "slippage_bps": 50, "margin_mode": "isolated"},
        client=client,
        account=account,
        portfolio=portfolio,
        bus=bus,
        control=control,
        balance=None,
    )
    trader = PerpsTrader(target, ctx, state)
    portfolio.register(trader)
    account.register(target.id, trader)
    return trader, client, bus, collected, account


class FakeVenueEngine:
    def __init__(self) -> None:
        self._positions: list[dict] = []
        self.open: dict[str, bool] = {}

    def positions(self, target_id: Optional[str] = None) -> list[dict]:
        if target_id is None:
            return list(self._positions)
        return [p for p in self._positions if p.get("target_id") == target_id]

    def has_open_positions(self, target: Target) -> bool:
        return bool(self.open.get(target.id, False))

    def add_position(self, **row) -> None:
        self._positions.append(row)


async def wait_for_stop(stop: asyncio.Event) -> None:
    await stop.wait()


def idle_jobs(stop: asyncio.Event) -> dict:
    """One job that exits as soon as the session stop event is set."""
    return {"idle": wait_for_stop(stop)}


def make_pipeline(
    label: str = "Prediction markets",
    *,
    jobs: Optional[Callable[[asyncio.Event], dict]] = None,
    prepare=None,
    drain=None,
) -> VenuePipeline:
    return VenuePipeline(label, jobs or idle_jobs, prepare=prepare, drain=drain)


def _noop_fatal(_name: str, _exc: BaseException) -> None:
    pass


def make_copy_session(
    bus: EventBus,
    *,
    venue: str = VENUE_PREDICTIONS,
    grace_s: float = 0.2,
    on_fatal: Optional[Callable[[str, BaseException], None]] = None,
    pipelines: Optional[dict[str, VenuePipeline]] = None,
) -> CopySession:
    if pipelines is None:
        pipelines = {
            VENUE_PREDICTIONS: make_pipeline("Prediction markets"),
            VENUE_PERPS: make_pipeline("Perps"),
        }
    return CopySession(
        pipelines,
        bus,
        venue=venue,
        on_fatal=on_fatal or _noop_fatal,
        grace_s=grace_s,
    )


def make_store(tmp_path, seed: Optional[list[dict]] = None) -> TargetStore:
    store = TargetStore(str(tmp_path / "targets.yaml"), SCHEMAS)
    store.load(seed)
    return store


def make_runtime(tmp_path, *, mode: str = "dry_run", token: str = "", settings=None):
    store = make_store(tmp_path)
    bus = EventBus()
    stats = Stats()
    history = HistoryStore(str(tmp_path / "history.db"))
    bus.subscribe(history.record)
    bus.subscribe(stats.record)
    control = Control()
    session = make_copy_session(bus)
    pred_engine = FakeVenueEngine()
    perps_engine = FakeVenueEngine()
    pred_port = Portfolio()
    perps_port = Portfolio()
    if settings is None:
        settings = make_settings_store(tmp_path)
    runtime = Runtime(
        mode=mode,
        store=store,
        bus=bus,
        stats=stats,
        history=history,
        control=control,
        session=session,
        settings=settings,
        venues={
            VENUE_PREDICTIONS: VenueRuntime(
                schema=PREDICTIONS_SCHEMA,
                engine=pred_engine,
                portfolio=pred_port,
                cap_field="max_open_usd",
                feeds=lambda: [{"id": "predictions-ws", "label": "Predictions feed",
                                 "connected": True, "last_event_ms": 1, "reconnects": 0}],
                open_orders=lambda: [],
            ),
            VENUE_PERPS: VenueRuntime(
                schema=PERPS_SCHEMA,
                engine=perps_engine,
                portfolio=perps_port,
                cap_field="max_open_notional_usd",
                feeds=lambda: [],
            ),
        },
    )
    return runtime, pred_engine, perps_engine


class _FakeResp:
    def __init__(self, body: bytes = b"ok", status: int = 200) -> None:
        self.status = status
        self._body = body

    async def read(self) -> bytes:
        return self._body

    async def text(self) -> str:
        return self._body.decode()

    async def json(self):
        import json
        return json.loads(self._body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None


class FakeSession:
    """aiohttp-like session used by keep-warm tests."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.urls: list[str] = []
        self.error = error
        self.posts: list[dict] = []
        self.post_responses: list[tuple[int, str]] = []

    def get(self, url: str, **_kwargs):
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        return _FakeResp()

    def post(self, url: str, **kwargs):
        self.posts.append({"url": url, **kwargs})
        if self.post_responses:
            status, text = self.post_responses.pop(0)
            return _FakeResp(text.encode(), status)
        return _FakeResp(b'{"success":true}')

    def request(self, method: str, url: str, **kwargs):
        self.urls.append(url)
        return _FakeResp()
