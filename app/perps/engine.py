"""PerpsEngine — polls each perps target's public portfolio and routes the
snapshots to its PerpsTrader. Targets added / edited / removed from the
dashboard take effect on the next poll."""

import asyncio
import logging
import time
from typing import Optional

from app import events
from app.perps.trader import PerpsContext, PerpsTrader
from app.targets import VENUE_PERPS, Target, TargetStore

log = logging.getLogger("perps")

DEFAULT_POLL_INTERVAL_S = 1.0
ERROR_ALERT_AFTER = 5      # consecutive failed polls before an ERROR activity


class PerpsEngine:
    def __init__(self, ctx: PerpsContext, store: TargetStore, state: Optional[dict] = None) -> None:
        self.ctx = ctx
        self.store = store
        self.traders: dict[str, PerpsTrader] = {}
        self._saved_state: dict[str, dict] = dict((state or {}).get("targets", {}))
        self._errors: dict[str, int] = {}
        self.last_poll_ms: Optional[int] = None
        self.poll_failures = 0

        for target in store.all(VENUE_PERPS):
            self._add(target)
        store.on_change(self._on_target_change)

    @property
    def poll_interval_s(self) -> float:
        # Read live: editable from the dashboard settings.
        return float(self.ctx.config.get("poll_interval_s", DEFAULT_POLL_INTERVAL_S))

    # ── Target lifecycle ──

    def _on_target_change(self, event: str, target: Target) -> None:
        if target.venue != VENUE_PERPS:
            return
        if event == "added":
            self._add(target)
        elif event == "updated":
            trader = self.traders[target.id]
            if trader.target.wallet != target.wallet:
                # Different account: start from a fresh baseline.
                trader.target_sizes = None
            trader.target = target
        elif event == "removed":
            self.traders.pop(target.id, None)
            self.ctx.portfolio.unregister(target.id)
            self.ctx.account.unregister(target.id)

    def _add(self, target: Target) -> None:
        trader = PerpsTrader(target, self.ctx, self._saved_state.pop(target.id, None))
        self.traders[target.id] = trader
        self.ctx.portfolio.register(trader)
        self.ctx.account.register(target.id, trader)

    # ── Polling ──

    async def run(self, shutdown: asyncio.Event) -> None:
        if not self.ctx.client.instruments:
            try:
                await self.ctx.client.load_instruments()
            except Exception as e:
                log.warning(f"perps instruments load failed: {e}")
        for trader in self.traders.values():
            trader.resume()
        loop = asyncio.get_running_loop()
        while not shutdown.is_set():
            started = loop.time()
            traders = list(self.traders.values())
            if traders:
                await asyncio.gather(*(self._poll(t) for t in traders))
            wait = max(0.0, self.poll_interval_s - (loop.time() - started))
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass

    async def _poll(self, trader: PerpsTrader) -> None:
        target = trader.target
        try:
            snapshot = await self.ctx.client.public_portfolio(target.wallet)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.poll_failures += 1
            n = self._errors[target.id] = self._errors.get(target.id, 0) + 1
            log.warning(f"[PERPS] portfolio poll {target.name} failed ({n}): {e}")
            if n == ERROR_ALERT_AFTER:
                self.ctx.bus.emit(
                    events.ERROR, f"Perps: can't read {target.name}'s portfolio ({n} failures): {e}",
                    level=events.ERROR_LEVEL, venue=VENUE_PERPS, target=target,
                )
            return
        self._errors[target.id] = 0
        self.last_poll_ms = int(time.time() * 1000)
        # The target may have been removed while the request was in flight.
        if self.traders.get(target.id) is trader:
            trader.observe(snapshot)

    def feed_status(self) -> dict:
        now = int(time.time() * 1000)
        healthy = self.last_poll_ms is not None and now - self.last_poll_ms < self.poll_interval_s * 5000
        return {
            "id": "perps-poll",
            "label": "Perps portfolio poll" if self.traders else "Perps portfolio poll (no targets)",
            "connected": healthy or not self.traders,
            "last_event_ms": self.last_poll_ms,
            "reconnects": self.poll_failures,
        }

    # ── State ──

    def export_state(self) -> dict:
        return {"targets": {tid: t.export_state() for tid, t in self.traders.items()}}

    @property
    def dirty(self) -> bool:
        return any(t.dirty for t in self.traders.values())

    def mark_clean(self) -> None:
        for t in self.traders.values():
            t.mark_clean()

    # ── Views ──

    def positions(self, target_id: Optional[str] = None) -> list[dict]:
        return [
            view for tid, trader in self.traders.items()
            if target_id in (None, tid)
            for view in trader.position_views()
        ]

    def has_open_positions(self, target: Target) -> bool:
        trader = self.traders.get(target.id)
        return trader is not None and trader.has_open_positions()

    async def shutdown(self, grace_s: float = 5.0) -> None:
        await asyncio.gather(*(t.shutdown(grace_s) for t in self.traders.values()))
