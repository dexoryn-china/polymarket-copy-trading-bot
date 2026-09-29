"""Polymarket Copy Bot — entrypoint.

Wires both venues (prediction markets via the CLOB, Polymarket Perps), the
activity bus (history / stats / Telegram / dashboard) and the web dashboard.
Only one venue copies at a time: the CopySession starts / stops its pipeline
on request from the dashboard.

Run either way:
  python -m app.main           # canonical (from project root)
  python app/main.py           # also works (path-bootstrapped below)
"""

import sys
from pathlib import Path

# Bootstrap: if launched as `python app/main.py`, the project root isn't on
# sys.path so `from app.* import ...` would fail. Insert parent dir explicitly.
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import asyncio
import atexit
import contextlib
import json
import logging
import logging.handlers
import queue
import signal
from dataclasses import dataclass
from typing import Optional

import aiohttp

from app import events
from app.config import ConfigError, load_config, target_seed
from app.control import Control
from app.core.engine import PredictionsEngine
from app.core.orders import OrderTracker
from app.core.poller import Poller
from app.core.portfolio import BalanceMonitor, Portfolio
from app.core.schema import PREDICTIONS_SCHEMA
from app.core.trader import TradingContext
from app.events import EventBus
from app.notifications.telegram import TelegramNotifier
from app.perps.account import PerpsAccount
from app.perps.client import PerpsClient
from app.perps.engine import PerpsEngine
from app.perps.schema import PERPS_SCHEMA
from app.perps.trader import PerpsContext
from app.pm.clob import ClobClient, make_trace_config
from app.runtime import APP_NAME, Runtime, VenueRuntime
from app.session import CopySession, SessionError, VenuePipeline
from app.settings import SettingsStore
from app.stats import Stats
from app.storage.history import HistoryStore
from app.targets import VENUE_PERPS, VENUE_PREDICTIONS, TargetError, TargetStore
from app.web.server import DashboardServer

CONFIG_FILE = "config.yaml"
STATE_FILE = "state.json"
TARGETS_FILE = "targets.yaml"
SETTINGS_FILE = "settings.yaml"
HISTORY_FILE = "history.db"
LOG_FILE = "logs/copybot.log"
STATE_VERSION = 2
SAVE_INTERVAL_S = 5.0
SHUTDOWN_GRACE_S = 5.0
# Pooled connections outlive the keep-warm interval (ClobClient.keep_warm), so
# the CLOB / Gamma sockets stay open between orders.
HTTP_KEEPALIVE_S = 60
DNS_CACHE_TTL_S = 300

log = logging.getLogger("main")


# ──────────────────────────────────────────────────────────────────────────
# State
# ──────────────────────────────────────────────────────────────────────────


def load_state() -> dict:
    p = Path(STATE_FILE)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"Failed to load {STATE_FILE}: {e} — starting fresh")
        return {}


@dataclass
class StateSources:
    poller: Poller
    predictions: PredictionsEngine
    perps: PerpsEngine
    copier: CopySession

    def _all(self) -> tuple:
        return self.poller, self.predictions, self.perps, self.copier

    @property
    def dirty(self) -> bool:
        return any(s.dirty for s in self._all())

    def mark_clean(self) -> None:
        for s in self._all():
            s.mark_clean()

    def snapshot(self) -> dict:
        return {
            "version": STATE_VERSION,
            **self.poller.export_state(),
            "copy": self.copier.export_state(),
            "predictions": self.predictions.export_state(),
            "perps": self.perps.export_state(),
        }


def save_state(snapshot: dict) -> None:
    tmp = Path(STATE_FILE).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


async def state_saver(sources: StateSources, shutdown: asyncio.Event) -> None:
    # Snapshot on the loop (consistent), serialize + write in a thread so the
    # WS receive loop never stalls on a large seen_tx_keys list.
    while not shutdown.is_set():
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=SAVE_INTERVAL_S)
            break
        except asyncio.TimeoutError:
            pass
        if sources.dirty:
            snapshot = sources.snapshot()
            sources.mark_clean()
            await asyncio.to_thread(save_state, snapshot)
    # Final save happens in amain() after in-flight fills have drained.


# ──────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────


def setup_logging() -> None:
    # Windows consoles default to cp1252, which can't encode glyphs like → … —
    # force UTF-8 with a safe fallback so non-ASCII log output never crashes.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    fmt = logging.Formatter(fmt="%(asctime)s %(levelname)-5s %(name)-7s %(message)s", datefmt="%H:%M:%S")
    # Real handlers do blocking I/O; keep them off the event loop behind a
    # QueueHandler drained by a background QueueListener thread.
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    Path("logs").mkdir(exist_ok=True)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)

    log_queue: "queue.Queue" = queue.Queue(-1)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(logging.handlers.QueueHandler(log_queue))
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

    listener = logging.handlers.QueueListener(log_queue, sh, fh, respect_handler_level=True)
    listener.start()
    atexit.register(listener.stop)


def log_banner(cfg: dict, store: TargetStore, copier: CopySession, autostart: bool) -> None:
    web = cfg["web"]
    targets = store.all(copier.venue)
    log.info("=" * 60)
    log.info(f"{APP_NAME} starting — mode={cfg['mode'].upper()}")
    log.info(f"  copy venue:   {copier.label} — {'starting' if autostart else 'stopped (start from the dashboard)'}")
    log.info(f"  targets:      {len(targets)}, {sum(t.enabled for t in targets)} enabled")
    for t in targets:
        log.info(f"      · {t.name:<16} {t.wallet}  {'on' if t.enabled else 'off'}")
    if copier.venue == VENUE_PREDICTIONS:
        log.info(f"  order type:   {cfg['execution']['order_type']} "
                 f"(maker rest timeout {cfg['maker_settings'].get('rest_timeout_s')}s)")
        if cfg["risk"]["max_open_usd_total"]:
            log.info(f"  global cap:   ${cfg['risk']['max_open_usd_total']:.2f}")
    elif cfg["perps"]["max_open_notional_total"]:
        log.info(f"  global cap:   ${cfg['perps']['max_open_notional_total']:.2f} notional")
    if web["enabled"]:
        log.info(f"  dashboard:    http://{web['host']}:{web['port']}"
                 + (" (token required)" if web.get("token") else ""))
    log.info(f"  telegram:     {'ON' if (cfg.get('telegram') or {}).get('enabled') else 'OFF'}")
    log.info("=" * 60)


def install_signal_handlers(shutdown: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def request_shutdown(signum: int) -> None:
        log.info(f"signal {signum} received, shutting down")
        shutdown.set()

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, request_shutdown, s)
        except NotImplementedError:
            # Windows: no loop signal handlers — hop onto the loop thread instead.
            signal.signal(s, lambda signum, _frame: loop.call_soon_threadsafe(request_shutdown, signum))


# ──────────────────────────────────────────────────────────────────────────
# Venue pipelines (started / stopped by the CopySession)
# ──────────────────────────────────────────────────────────────────────────


def predictions_pipeline(poller: Poller, orders: OrderTracker, engine: PredictionsEngine,
                         clob: ClobClient, balance: Optional[BalanceMonitor]) -> VenuePipeline:
    def jobs(stop: asyncio.Event) -> dict:
        out = {
            "feed": poller.run(stop),
            "watchdog": poller.silent_watchdog(stop),
            "orders": orders.run(stop),
            "gc": engine.gc_loop(stop),
            "keep_warm": clob.keep_warm(stop),
        }
        if balance is not None:
            out["balance"] = balance.run(stop)
        return out

    async def drain(grace_s: float) -> None:
        # Feed is down: let in-flight fills finish, then pull resting maker orders.
        await engine.shutdown(grace_s)
        await orders.cancel_all()

    return VenuePipeline(PREDICTIONS_SCHEMA.label, jobs, drain=drain)


def perps_pipeline(client: PerpsClient, engine: PerpsEngine, balance: Optional[BalanceMonitor],
                   dry_run: bool) -> VenuePipeline:
    def jobs(stop: asyncio.Event) -> dict:
        out = {"poll": engine.run(stop), "market": client.run(stop)}
        if not dry_run:
            out["session"] = client.keep_session(stop)
        if balance is not None:
            out["balance"] = balance.run(stop)
        return out

    return VenuePipeline(PERPS_SCHEMA.label, jobs, prepare=client.open_session, drain=engine.shutdown)


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────


async def amain() -> int:
    setup_logging()
    try:
        cfg = load_config(CONFIG_FILE)
        settings = SettingsStore(cfg, SETTINGS_FILE)
        settings.load()
    except ConfigError as e:
        log.error(f"Config invalid: {e}")
        return 2
    dry_run = cfg["mode"] == "dry_run"
    secrets = cfg.get("polymarket") or {}

    store = TargetStore(TARGETS_FILE, {VENUE_PREDICTIONS: PREDICTIONS_SCHEMA, VENUE_PERPS: PERPS_SCHEMA})
    try:
        store.load(target_seed(cfg))
    except TargetError as e:
        log.error(f"Invalid target in {TARGETS_FILE} / config: {e}")
        return 2

    state = load_state()
    history = HistoryStore(HISTORY_FILE)
    bus = EventBus(start_id=history.max_id() + 1)
    stats = Stats()
    bus.subscribe(history.record)
    bus.subscribe(stats.record)
    control = Control()
    shutdown = asyncio.Event()
    install_signal_handlers(shutdown)

    timeout = aiohttp.ClientTimeout(total=10, connect=5)
    # ThreadedResolver: aiodns/pycares (aiohttp's default when installed) can
    # crash the interpreter on Windows; lookups are cached, so it's off the hot path.
    connector = aiohttp.TCPConnector(
        limit=0, keepalive_timeout=HTTP_KEEPALIVE_S, ttl_dns_cache=DNS_CACHE_TTL_S,
        resolver=aiohttp.ThreadedResolver(),
    )
    async with aiohttp.ClientSession(
        connector=connector, timeout=timeout, trace_configs=[make_trace_config()],
    ) as session:
        notifier = TelegramNotifier(cfg, session)
        notifier.attach(bus)

        # ── Predictions ──
        clob = ClobClient(secrets=cfg.get("polymarket"), dry_run=dry_run, session=session)
        pred_portfolio = Portfolio(cfg["risk"]["max_open_usd_total"])
        pred_balance = None if dry_run else BalanceMonitor(clob, pred_portfolio.reserved_usd)
        orders = OrderTracker(clob, bus, VENUE_PREDICTIONS)
        predictions = PredictionsEngine(
            TradingContext(cfg, clob, pred_portfolio, orders, bus, control, pred_balance),
            store,
            PredictionsEngine.migrate_legacy_state(state, store),
        )
        poller = Poller(cfg, session, predictions.wallets, predictions.submit, state, bus)

        # ── Perps ──
        pcfg = cfg["perps"]
        perps_client = PerpsClient(session, dry_run, secrets.get("private_key"))
        perps_portfolio = Portfolio(pcfg["max_open_notional_total"])
        perps_account = PerpsAccount(perps_client, cross_margin=pcfg["margin_mode"] == "cross")
        perps_balance = None if dry_run else BalanceMonitor(perps_client, perps_account.reserved_margin)
        perps = PerpsEngine(
            PerpsContext(pcfg, perps_client, perps_account, perps_portfolio, bus, control, perps_balance),
            store,
            state.get("perps"),
        )

        # ── Copy session: exactly one venue runs at a time ──
        exit_code = 0

        def on_fatal(name: str, exc: BaseException) -> None:
            nonlocal exit_code
            log.error(f"task {name} crashed — shutting down", exc_info=exc)
            exit_code = 1
            shutdown.set()

        pipelines = {
            VENUE_PREDICTIONS: predictions_pipeline(poller, orders, predictions, clob, pred_balance),
            VENUE_PERPS: perps_pipeline(perps_client, perps, perps_balance, dry_run),
        }
        saved_copy = state.get("copy") or {}
        venue = saved_copy.get("venue") if saved_copy.get("venue") in pipelines else cfg["copy"]["venue"]
        copier = CopySession(pipelines, bus, venue=venue, on_fatal=on_fatal, grace_s=SHUTDOWN_GRACE_S)
        # Resume if copying was on at last shutdown; headless runs always copy.
        autostart = bool(saved_copy.get("running")) or not cfg["web"]["enabled"]

        # Most settings are read from `cfg` per decision; these few are cached
        # on objects and need pushing when the dashboard changes them.
        def apply_settings(changed: set[str]) -> None:
            pred_portfolio.global_cap_usd = cfg["risk"]["max_open_usd_total"]
            perps_portfolio.global_cap_usd = pcfg["max_open_notional_total"]
            perps_account.cross_margin = pcfg["margin_mode"] == "cross"
            if any(k.startswith("telegram.") for k in changed):
                notifier.configure(cfg)

        settings.on_change(apply_settings)

        runtime = Runtime(
            mode=cfg["mode"], store=store, bus=bus, stats=stats, history=history, control=control,
            session=copier, settings=settings,
            venues={
                VENUE_PREDICTIONS: VenueRuntime(
                    schema=PREDICTIONS_SCHEMA, engine=predictions,
                    portfolio=pred_portfolio, balance=pred_balance,
                    feeds=lambda: [poller.feed_status()],
                    open_orders=lambda: [o.to_dict() for o in orders.open_orders()],
                    cap_field="max_open_usd",
                ),
                VENUE_PERPS: VenueRuntime(
                    schema=PERPS_SCHEMA, engine=perps,
                    portfolio=perps_portfolio, balance=perps_balance,
                    feeds=lambda: [perps.feed_status()],
                    cap_field="max_open_notional_usd",
                ),
            },
        )
        log_banner(cfg, store, copier, autostart)

        # ── Always-on services (the venue pipeline is owned by the CopySession) ──
        sources = StateSources(poller, predictions, perps, copier)
        jobs = {
            "history": history.run(shutdown),
            "state_saver": state_saver(sources, shutdown),
        }
        if cfg["web"]["enabled"]:
            server = DashboardServer(runtime, cfg["web"]["host"], cfg["web"]["port"], cfg["web"].get("token", ""))
            jobs["web"] = server.run(shutdown)
        tasks = [asyncio.create_task(coro, name=name) for name, coro in jobs.items()]

        bus.emit(events.SYSTEM, f"Bot started ({cfg['mode']}) — {copier.label}", event=events.STARTUP)
        if autostart:
            with contextlib.suppress(SessionError):      # reason already logged + emitted
                await copier.start()

        stopper = asyncio.create_task(shutdown.wait(), name="shutdown")
        done, _ = await asyncio.wait([*tasks, stopper], return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            if t is not stopper and not t.cancelled() and t.exception() is not None:
                log.error(f"task {t.get_name()} crashed", exc_info=t.exception())
                exit_code = 1
        shutdown.set()

        # Stop copying first (drains in-flight fills, cancels resting orders),
        # then the services, then persist the final state.
        await copier.shutdown()
        _, still = await asyncio.wait(tasks, timeout=SHUTDOWN_GRACE_S)
        for t in still:
            t.cancel()
        for t in still:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        await asyncio.to_thread(save_state, sources.snapshot())
        bus.emit(events.SYSTEM, "Bot stopped", event=events.SHUTDOWN)
        await history.flush()
        await notifier.flush()
    history.close()
    log.info("Shutdown complete")
    return exit_code


def main() -> int:
    try:
        return asyncio.run(amain())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
