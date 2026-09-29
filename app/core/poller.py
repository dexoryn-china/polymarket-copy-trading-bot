"""Poller — WebSocket subscription to PM activity/trades, dedup, watchdog.

Subscribes once to the global activity/trades stream and filters incoming
events by `proxyWallet` against the live set of watched wallets (one per
prediction target). App-level `Text("PING")` heartbeat every 5s (matches PM
convention). Matched fills are handed to a synchronous, non-blocking `on_fill`
callback (PredictionsEngine.submit) that schedules execution as its own task,
so the WS receive loop never waits on POST /order. PM WS connections become
zombie after ~20 minutes of silence — the silent watchdog raises to force a
supervisor restart.
"""

import asyncio
import contextlib
import json
import logging
import re
import time
from collections import OrderedDict
from typing import Callable, Collection, Optional

import aiohttp
import orjson

from app import events
from app.core.trader import TargetFill
from app.events import EventBus
from app.targets import VENUE_PREDICTIONS


WS_URL = "wss://ws-live-data.polymarket.com"
PING_INTERVAL_S = 5             # app-level Text("PING") cadence
RECONNECT_MIN_SLEEP_S = 1.0     # minimum delay between reconnects even on clean close

# Pulls the trader's wallet straight out of the raw frame, so the (global)
# firehose is filtered with one regex scan + set lookup — independent of how
# many wallets are watched — and only matching rows reach the JSON decoder.
_PROXY_WALLET_RE = re.compile(r'"proxyWallet"\s*:\s*"(0x[0-9a-fA-F]{40})"')

log = logging.getLogger("poller")


def _full_row_key(p: dict) -> str:
    """Dedup key: tx_hash + asset + side + size + price (full row, not just tx_hash —
    one taker × N makers produces N rows sharing tx_hash but with different size/price)."""
    return f"{p.get('transactionHash','')}|{p.get('asset','')}|{p.get('side','')}|{p.get('size','')}|{p.get('price','')}"


class LRU:
    """Tiny LRU set with capacity. add() / __contains__, no value storage."""

    def __init__(self, cap: int):
        self.cap = cap
        self._d: OrderedDict[str, bool] = OrderedDict()

    def __contains__(self, key: str) -> bool:
        return key in self._d

    def add(self, key: str) -> None:
        if key in self._d:
            self._d.move_to_end(key)
            return
        self._d[key] = True
        if len(self._d) > self.cap:
            self._d.popitem(last=False)

    def __len__(self) -> int:
        return len(self._d)

    def to_list(self) -> list[str]:
        return list(self._d.keys())

    @classmethod
    def from_list(cls, keys: list[str], cap: int) -> "LRU":
        lru = cls(cap)
        for k in keys:
            lru.add(k)
        return lru


class Poller:
    """WebSocket poller for PM activity/trades stream."""

    feed_id = "predictions-ws"
    feed_label = "Predictions feed"

    def __init__(
        self,
        config: dict,
        session: aiohttp.ClientSession,
        wallets: Collection[str],
        on_fill: Callable[[TargetFill], None],
        state: dict,
        bus: Optional[EventBus] = None,
    ):
        self.config = config
        self.session = session
        # Live view of watched lowercase wallets (owned by PredictionsEngine).
        self.wallets = wallets
        self.on_fill = on_fill
        self.bus = bus

        self.seen = LRU.from_list(state.get("seen_tx_keys", []), config["dedup"]["seen_cap"])

        # Watchdog state — updated on every WS event (any message type), so we
        # detect zombie connections even when no target is trading.
        self.last_event_ms = int(time.time() * 1000)
        self.consecutive_reconnect_errors = 0
        self.connected = False
        self.reconnects = 0
        self._state_dirty = False

    # ── State ──

    def export_state(self) -> dict:
        return {"seen_tx_keys": self.seen.to_list()}

    @property
    def dirty(self) -> bool:
        return self._state_dirty

    def mark_clean(self) -> None:
        self._state_dirty = False

    def feed_status(self) -> dict:
        return {
            "id": self.feed_id,
            "label": self.feed_label,
            "connected": self.connected,
            "last_event_ms": self.last_event_ms,
            "reconnects": self.reconnects,
        }

    # ── Main run loop with reconnect ──

    async def run(self, shutdown: asyncio.Event) -> None:
        max_errs = self.config["watchdog"]["max_consecutive_errors"]
        while not shutdown.is_set():
            try:
                await self._run_connection(shutdown)
                self.consecutive_reconnect_errors = 0
                # Even on clean close, pause briefly to avoid tight-loop
                # reconnects if the server flaps.
                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=RECONNECT_MIN_SLEEP_S)
                    return
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.consecutive_reconnect_errors += 1
                backoff_s = min(2 ** min(self.consecutive_reconnect_errors, 5), 30)
                log.warning(
                    f"[WS-ERROR] {type(e).__name__}: {e} "
                    f"(consecutive={self.consecutive_reconnect_errors}, "
                    f"backoff={backoff_s}s)"
                )
                if self.consecutive_reconnect_errors == max_errs:
                    log.error(
                        f"[WS] {self.consecutive_reconnect_errors} consecutive "
                        f"failures (>= {max_errs}) — still retrying"
                    )
                    self._emit_error(f"Predictions feed: {self.consecutive_reconnect_errors} consecutive failures: {e}")
                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=backoff_s)
                    return
                except asyncio.TimeoutError:
                    pass
            finally:
                self.connected = False
            self.reconnects += 1

    async def _run_connection(self, shutdown: asyncio.Event) -> None:
        log.info("Data stream connecting…")
        # Reset watchdog at connect-start so slow handshake doesn't trip it.
        self.last_event_ms = int(time.time() * 1000)

        async with self.session.ws_connect(WS_URL, timeout=10) as ws:
            sub = {
                "action": "subscribe",
                "subscriptions": [{"topic": "activity", "type": "trades"}],
            }
            await ws.send_str(json.dumps(sub))
            self.connected = True
            log.info(f"Subscribed — watching {len(self.wallets)} wallet(s)")
            self.last_event_ms = int(time.time() * 1000)

            # App-level heartbeat: PM expects Text("PING"), not WS frame ping.
            ping_task = asyncio.create_task(self._ping_loop(ws), name="ws-ping")
            try:
                async for msg in ws:
                    if shutdown.is_set():
                        return
                    mt = msg.type
                    if mt == aiohttp.WSMsgType.TEXT:
                        self._handle_text(msg.data)
                    elif mt in (
                        aiohttp.WSMsgType.PING,
                        aiohttp.WSMsgType.PONG,
                        aiohttp.WSMsgType.BINARY,
                    ):
                        # Any inbound traffic = alive
                        self.last_event_ms = int(time.time() * 1000)
                    elif mt in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.CLOSE,
                    ):
                        log.warning("[WS] connection closed by remote")
                        return
                    elif mt == aiohttp.WSMsgType.ERROR:
                        log.warning(f"[WS] error: {ws.exception()}")
                        return
            finally:
                ping_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ping_task

    async def _ping_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """App-level heartbeat — PM convention: send Text("PING") every 5s,
        server replies Text("PONG"). Loop exits when connection breaks."""
        while True:
            await asyncio.sleep(PING_INTERVAL_S)
            try:
                await ws.send_str("PING")
            except (aiohttp.ClientError, ConnectionResetError):
                return

    # ── Message handling (WS receive side) ──

    def _handle_text(self, raw: str) -> None:
        # Any TEXT message counts as alive for watchdog.
        self.last_event_ms = int(time.time() * 1000)

        match = _PROXY_WALLET_RE.search(raw)
        if match is None or match.group(1).lower() not in self.wallets:
            return

        try:
            data = orjson.loads(raw)
        except orjson.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return

        if data.get("topic") != "activity" or data.get("type") != "trades":
            return

        # Envelope timestamp (ms, 13-digit) = when PM pushed the event.
        # More accurate for lag measurement than payload.timestamp (sec).
        envelope_ts_ms = data.get("timestamp", 0)

        payload = data.get("payload")
        if not isinstance(payload, dict):
            return
        wallet = str(payload.get("proxyWallet") or "").lower()
        if wallet not in self.wallets:
            return

        key = _full_row_key(payload)
        if key in self.seen:
            return    # already processed

        try:
            fill = self._parse_fill(payload, envelope_ts_ms)
        except (TypeError, ValueError) as e:
            log.warning(f"[WS] unparseable target row {key[:40]}…: {e}")
            return

        self.seen.add(key)
        self._state_dirty = True
        self._dispatch(fill)

        lag_ms = (int(time.time() * 1000) - fill.timestamp_ms) if fill.timestamp_ms > 0 else -1
        # ASCII-only on purpose: the Windows console is cp1252 and non-ASCII
        # glyphs raise UnicodeEncodeError inside logging (a traceback per line).
        log.info(
            f"[NEW] {wallet[:10]}... {fill.side} {fill.outcome or '?'} {fill.size:.2f}sh @ {fill.price:.4f} "
            f"({int(round(fill.price * 100))}c) val=${fill.size * fill.price:.2f} lag={lag_ms}ms "
            f'slug={fill.market_slug} title="{fill.title or fill.market_slug}" '
            f"asset={fill.asset[:12]}... tx={fill.tx_hash[:10]}..."
        )

    def _dispatch(self, fill: TargetFill) -> None:
        # A handler bug must never tear down the WS connection.
        try:
            self.on_fill(fill)
        except Exception as e:
            log.exception(f"on_fill dispatch raised tx={fill.tx_hash[:10]}…: {e}")

    @staticmethod
    def _parse_fill(p: dict, envelope_ts_ms: int) -> TargetFill:
        """
        Normalize a PM activity/trades payload into a TargetFill.

        We use the ENVELOPE timestamp (ms, when PM pushed) for `timestamp_ms`
        because it gives accurate "PM publish → bot recv" latency. The
        payload.timestamp is unix SECONDS (1s quantization, 0-999ms noise)
        and unsuitable for lag measurement. Fall back to payload.timestamp
        if envelope ts is missing/zero.
        """
        try:
            ts_ms = int(envelope_ts_ms or 0)
        except (TypeError, ValueError):
            ts_ms = 0
        if ts_ms < 10**11:    # envelope absent or in seconds — fall back to payload
            ts_raw = p.get("timestamp", 0) or 0
            try:
                ts_num = float(ts_raw)
            except (TypeError, ValueError):
                ts_num = 0.0
            ts_ms = int(ts_num if ts_num >= 1e11 else ts_num * 1000)

        return TargetFill(
            tx_hash=p.get("transactionHash", ""),
            asset=str(p.get("asset", "")),
            market_slug=p.get("slug", "") or p.get("eventSlug", ""),
            side=str(p.get("side") or "").upper(),
            size=float(p.get("size", 0) or 0),
            price=float(p.get("price", 0) or 0),
            price_str=str(p.get("price", "")),
            timestamp_ms=ts_ms,
            outcome=str(p.get("outcome", "") or ""),
            title=str(p.get("title", "") or ""),
            wallet=str(p.get("proxyWallet") or "").lower(),
        )

    # ── Silent-freeze watchdog ──

    async def silent_watchdog(self, shutdown: asyncio.Event) -> None:
        """
        If no WS event arrives in N seconds, abort the bot. PM activity is a
        global firehose — events flow continuously regardless of targets' trading.
        Silence = zombie connection; raise to trigger graceful shutdown so a
        supervisor (systemd / operator) can restart with a fresh socket.
        """
        timeout_ms = self.config["watchdog"]["silent_timeout_s"] * 1000
        # Copying may be (re)started long after the last event.
        self.last_event_ms = int(time.time() * 1000)
        while not shutdown.is_set():
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=5)
                return
            except asyncio.TimeoutError:
                pass
            silent_ms = int(time.time() * 1000) - self.last_event_ms
            if silent_ms > timeout_ms:
                msg = (
                    f"[WATCHDOG] No WS event in {silent_ms / 1000:.1f}s "
                    f"(threshold {timeout_ms / 1000:.0f}s) — exiting for supervisor restart"
                )
                log.error(msg)
                self._emit_error(msg)
                raise RuntimeError(msg)

    def _emit_error(self, message: str) -> None:
        if self.bus is not None:
            self.bus.emit(events.ERROR, message, level=events.ERROR_LEVEL, venue=VENUE_PREDICTIONS)
