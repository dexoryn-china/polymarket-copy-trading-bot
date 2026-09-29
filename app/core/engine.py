"""PredictionsEngine — routes detected fills to the per-target CopyTrader.

Keeps `wallets` (the set the poller filters on) in sync with the TargetStore
so targets added / removed / edited from the dashboard take effect live.
"""

import asyncio
import logging
import time
from typing import Optional

from app.core.trader import CopyTrader, TargetFill, TradingContext
from app.targets import VENUE_PREDICTIONS, Target, TargetStore

log = logging.getLogger("engine")

GC_INTERVAL_S = 30


class PredictionsEngine:
    def __init__(self, ctx: TradingContext, store: TargetStore, state: Optional[dict] = None) -> None:
        self.ctx = ctx
        self.store = store
        self.traders: dict[str, CopyTrader] = {}
        # Shared, mutated in place — the poller holds a reference to this set.
        self.wallets: set[str] = set()
        self._by_wallet: dict[str, CopyTrader] = {}
        self._saved_state: dict[str, dict] = dict((state or {}).get("targets", {}))

        for target in store.all(VENUE_PREDICTIONS):
            self._add(target)
        store.on_change(self._on_target_change)

    # ── Routing ──

    def submit(self, fill: TargetFill) -> None:
        trader = self._by_wallet.get(fill.wallet)
        if trader is not None:
            trader.submit(fill)

    # ── Target lifecycle ──

    def _on_target_change(self, event: str, target: Target) -> None:
        if target.venue != VENUE_PREDICTIONS:
            return
        if event == "added":
            self._add(target)
        elif event == "updated":
            trader = self.traders[target.id]
            self._unindex(trader)
            trader.target = target
            self._index(trader)
        elif event == "removed":
            trader = self.traders.pop(target.id)
            self._unindex(trader)
            self.ctx.portfolio.unregister(target.id)

    def _add(self, target: Target) -> None:
        trader = CopyTrader(target, self.ctx, self._saved_state.pop(target.id, None))
        self.traders[target.id] = trader
        self.ctx.portfolio.register(trader)
        self._index(trader)

    def _index(self, trader: CopyTrader) -> None:
        self._by_wallet[trader.target.wallet] = trader
        self.wallets.add(trader.target.wallet)

    def _unindex(self, trader: CopyTrader) -> None:
        self._by_wallet.pop(trader.target.wallet, None)
        self.wallets.discard(trader.target.wallet)

    # ── State ──

    @staticmethod
    def migrate_legacy_state(state: dict, store: TargetStore) -> dict:
        """Pre-multi-target state.json kept one trader's fields at top level;
        hand them to the first predictions target."""
        if "positions" not in state:
            return state.get("predictions", {})
        first = next(iter(store.all(VENUE_PREDICTIONS)), None)
        if first is None:
            return {}
        legacy = {k: state.get(k, {}) for k in (
            "target_buy_accumulator", "target_holdings", "target_sell_accumulator", "positions",
        )}
        log.info(f"migrated legacy state into target '{first.name}'")
        return {"targets": {first.id: legacy}}

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

    # ── Background ──

    async def gc_loop(self, shutdown: asyncio.Event) -> None:
        while not shutdown.is_set():
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=GC_INTERVAL_S)
                return
            except asyncio.TimeoutError:
                pass
            now_ms = int(time.time() * 1000)
            for trader in self.traders.values():
                trader.gc_expired(now_ms)

    async def shutdown(self, grace_s: float = 5.0) -> None:
        await asyncio.gather(*(t.shutdown(grace_s) for t in self.traders.values()))
