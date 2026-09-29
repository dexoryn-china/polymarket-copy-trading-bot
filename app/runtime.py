"""Runtime — read/write facade over the running bot for the dashboard.

Venues plug in through `VenueRuntime`, so the web layer never touches
venue-specific trading code.
"""

import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from app import events
from app.control import Control
from app.core.portfolio import BalanceMonitor, Portfolio
from app.events import EventBus
from app.session import CopySession
from app.settings import SettingsStore
from app.stats import Stats
from app.storage.history import HistoryStore
from app.targets import Target, TargetStore, VenueSchema

APP_NAME = "Polymarket Copy Bot"
VERSION = "2.2.0"


class VenueEngine(Protocol):
    def positions(self, target_id: Optional[str] = None) -> list[dict]: ...
    def has_open_positions(self, target: Target) -> bool: ...


@dataclass
class VenueRuntime:
    schema: VenueSchema
    engine: VenueEngine
    portfolio: Portfolio
    balance: Optional[BalanceMonitor] = None
    feeds: Callable[[], list[dict]] = lambda: []
    open_orders: Callable[[], list[dict]] = lambda: []
    cap_field: Optional[str] = None           # sizing key holding the per-target cap

    def cap_usd(self, targets: list[Target]) -> Optional[float]:
        if self.portfolio.global_cap_usd is not None:
            return self.portfolio.global_cap_usd
        if self.cap_field is None:
            return None
        caps = [float(t.sizing.get(self.cap_field, 0)) for t in targets if t.enabled]
        return sum(caps) if caps else None


@dataclass
class Runtime:
    mode: str
    store: TargetStore
    bus: EventBus
    stats: Stats
    history: HistoryStore
    control: Control
    session: CopySession
    settings: SettingsStore
    venues: dict[str, VenueRuntime] = field(default_factory=dict)
    started_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    # ── Meta / status ──

    def meta(self) -> dict:
        return {
            "name": APP_NAME,
            "mode": self.mode,
            "version": VERSION,
            "venues": [v.schema.to_dict() for v in self.venues.values()],
        }

    def status(self) -> dict:
        now = int(time.time() * 1000)
        venues = []
        feeds: list[dict] = []
        for vid, v in self.venues.items():
            targets = self.store.all(vid)
            active = self.session.is_active(vid)
            balance = v.balance.balance_usd if v.balance is not None else None
            venues.append({
                "id": vid,
                "label": v.schema.label,
                "active": active,
                "balance_usd": balance,
                "open_usd": round(v.portfolio.open_usd(), 2),
                "cap_usd": v.cap_usd(targets),
                "positions": len(v.engine.positions()),
            })
            if active and self.session.running:
                feeds.extend(v.feeds())
        return {
            "mode": self.mode,
            "copy": self.session.to_dict(),
            "paused": self.control.paused,
            "started_at_ms": self.started_at_ms,
            "uptime_s": (now - self.started_at_ms) // 1000,
            "feeds": feeds,
            "venues": venues,
            "counts": self.stats.total.as_dict(),
            "latency": self.stats.latency(),
        }

    # ── Copy session ──

    def select_venue(self, venue: str) -> dict:
        self.session.select(venue)
        return self.status()

    async def start_copy(self, venue: Optional[str] = None) -> dict:
        await self.session.start(venue)
        return self.status()

    async def stop_copy(self) -> dict:
        await self.session.stop()
        return self.status()

    def set_paused(self, paused: bool) -> dict:
        if paused != self.control.paused:
            self.control.paused = paused
            self.bus.emit(
                events.SYSTEM,
                "Trading paused — new entries blocked, exits still mirrored" if paused else "Trading resumed",
                level=events.WARNING if paused else events.INFO,
                event="pause" if paused else "resume",
            )
        return self.status()

    # ── Targets ──

    def target_view(self, target: Target) -> dict:
        venue = self.venues.get(target.venue)
        counts = self.stats.for_target(target.id).as_dict()
        open_usd = venue.portfolio.open_usd(target.id) if venue else 0.0
        positions = len(venue.engine.positions(target.id)) if venue else 0
        return {**target.to_dict(), "stats": {**counts, "open_usd": round(open_usd, 2), "positions": positions}}

    def targets(self) -> list[dict]:
        return [self.target_view(t) for t in self.store.all()]

    def create_target(self, data: dict) -> dict:
        target = self.store.create(data)
        self._announce(f"Target added: {target.name}", target)
        return self.target_view(target)

    def update_target(self, target_id: str, data: dict) -> dict:
        target = self.store.update(target_id, data)
        self._announce(f"Target updated: {target.name}", target)
        return self.target_view(target)

    def set_target_enabled(self, target_id: str, enabled: bool) -> dict:
        target = self.store.set_enabled(target_id, enabled)
        self._announce(f"Target {'enabled' if enabled else 'disabled'}: {target.name}", target)
        return self.target_view(target)

    def delete_target(self, target_id: str) -> None:
        target = self.store.get(target_id)
        self.store.delete(target_id, self.has_open_positions)
        if target is not None:
            self._announce(f"Target removed: {target.name}", target)

    def has_open_positions(self, target: Target) -> bool:
        venue = self.venues.get(target.venue)
        return venue is not None and venue.engine.has_open_positions(target)

    def _announce(self, summary: str, target: Target) -> None:
        self.bus.emit(events.SYSTEM, summary, venue=target.venue, target=target, event="target")

    # ── Settings ──

    def get_settings(self) -> dict:
        return self.settings.to_dict()

    def update_settings(self, values: dict) -> dict:
        changed = self.settings.update(values)
        if changed:
            labels = ", ".join(self.settings.fields[k].label for k in sorted(changed))
            self.bus.emit(events.SYSTEM, f"Settings updated: {labels}", event="settings")
        return self.settings.to_dict()

    # ── Positions / orders ──

    def positions(self, venue: Optional[str] = None, target_id: Optional[str] = None) -> list[dict]:
        out: list[dict] = []
        for vid, v in self.venues.items():
            if venue in (None, vid):
                out.extend(v.engine.positions(target_id))
        return sorted(out, key=lambda p: p.get("opened_at_ms") or 0, reverse=True)

    def orders(self) -> list[dict]:
        return [o for v in self.venues.values() for o in v.open_orders()]
