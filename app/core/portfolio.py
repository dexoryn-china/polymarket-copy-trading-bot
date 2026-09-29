"""Exposure accounting shared by all targets of one venue.

- Per-target cap and optional venue-wide cap both count open exposure PLUS USD
  reserved by in-flight / resting orders, so concurrent copies can't overshoot.
- Collateral balance is refreshed in the background (never on the order hot
  path) and debited optimistically as entries fill.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Protocol

log = logging.getLogger("portfolio")

BALANCE_REFRESH_S = 15.0


class _HoldsPositions(Protocol):
    target_id: str

    def open_usd(self, now_ms: int) -> float: ...


class Portfolio:
    def __init__(self, global_cap_usd: Optional[float] = None) -> None:
        self.global_cap_usd = global_cap_usd
        self._books: dict[str, _HoldsPositions] = {}
        self._reserved: dict[str, tuple[str, float]] = {}   # key -> (target_id, usd)

    # ── Registration ──

    def register(self, book: _HoldsPositions) -> None:
        self._books[book.target_id] = book

    def unregister(self, target_id: str) -> None:
        self._books.pop(target_id, None)

    # ── Reservations ──

    def reserve(self, key: str, target_id: str, usd: float) -> None:
        self._reserved[key] = (target_id, max(0.0, usd))

    def release(self, key: str) -> None:
        self._reserved.pop(key, None)

    def reserved_usd(self, target_id: Optional[str] = None) -> float:
        return sum(usd for tid, usd in self._reserved.values() if target_id is None or tid == target_id)

    # ── Exposure ──

    def open_usd(self, target_id: Optional[str] = None, now_ms: Optional[int] = None) -> float:
        """Held cost basis + reservations, for one target or all."""
        now_ms = now_ms or int(time.time() * 1000)
        books: Iterable[_HoldsPositions] = (
            self._books.values() if target_id is None
            else [b for b in (self._books.get(target_id),) if b is not None]
        )
        return sum(b.open_usd(now_ms) for b in books) + self.reserved_usd(target_id)

    def headroom_usd(self, target_id: str, target_cap_usd: float, now_ms: Optional[int] = None) -> float:
        headroom = target_cap_usd - self.open_usd(target_id, now_ms)
        if self.global_cap_usd is not None:
            headroom = min(headroom, self.global_cap_usd - self.open_usd(None, now_ms))
        return headroom


@dataclass(frozen=True, slots=True)
class Collateral:
    balance_usd: float
    allowance_usd: Optional[float]


class CollateralSource(Protocol):
    async def get_collateral(self) -> Optional[Collateral]: ...


class BalanceMonitor:
    """Cached collateral balance/allowance. `check(usd)` is synchronous.

    `reserved_usd` returns collateral already committed to in-flight orders,
    which is not yet reflected in the fetched balance."""

    def __init__(self, source: CollateralSource, reserved_usd: Callable[[], float],
                 refresh_s: float = BALANCE_REFRESH_S) -> None:
        self.source = source
        self.reserved_usd = reserved_usd
        self.refresh_s = refresh_s
        self.balance_usd: Optional[float] = None
        self.allowance_usd: Optional[float] = None

    async def refresh(self) -> None:
        try:
            snapshot = await self.source.get_collateral()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"balance refresh failed: {e}")
            return
        if snapshot is None:
            return
        self.balance_usd = snapshot.balance_usd
        self.allowance_usd = snapshot.allowance_usd

    async def run(self, shutdown: asyncio.Event) -> None:
        while not shutdown.is_set():
            await self.refresh()
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=self.refresh_s)
            except asyncio.TimeoutError:
                pass

    def check(self, usd: float) -> Optional[str]:
        """None when `usd` can be spent now, else a human-readable reason.
        Unknown balance (not fetched yet / API down) never blocks trading —
        the CLOB remains the source of truth."""
        if self.balance_usd is None:
            return None
        available = self.balance_usd - self.reserved_usd()
        if usd > available + 1e-9:
            return f"insufficient balance: need ${usd:.2f}, available ${max(available, 0):.2f}"
        if self.allowance_usd is not None and usd > self.allowance_usd + 1e-9:
            return f"insufficient allowance: need ${usd:.2f}, approved ${self.allowance_usd:.2f}"
        return None

    def debit(self, usd: float) -> None:
        if self.balance_usd is not None:
            self.balance_usd = max(0.0, self.balance_usd - usd)

    def credit(self, usd: float) -> None:
        if self.balance_usd is not None:
            self.balance_usd += usd
