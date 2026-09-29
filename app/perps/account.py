"""Account-level state shared by every perps target.

Each target keeps a *virtual* book, but orders hit one exchange account, so
some decisions need the aggregate: the net size per instrument (reduce-only
eligibility, leverage changes only from flat) and margin committed to
in-flight orders (balance checks).
"""

import logging
from typing import Protocol

from app.perps.client import Instrument, PerpsClient
from app.utils.keyed_lock import KeyedLocks

log = logging.getLogger("perps")


class _Book(Protocol):
    def size(self, instrument_id: int) -> float: ...


class PerpsAccount:
    def __init__(self, client: PerpsClient, cross_margin: bool = False) -> None:
        self.client = client
        self.cross_margin = cross_margin
        self._books: dict[str, _Book] = {}
        self._leverage: dict[int, int] = {}
        self._leverage_locks = KeyedLocks()
        self._margin: dict[str, float] = {}

    # ── Books ──

    def register(self, target_id: str, book: _Book) -> None:
        self._books[target_id] = book

    def unregister(self, target_id: str) -> None:
        self._books.pop(target_id, None)

    def net_size(self, instrument_id: int) -> float:
        return sum(b.size(instrument_id) for b in self._books.values())

    # ── Margin reservations ──

    def reserve_margin(self, key: str, usd: float) -> None:
        self._margin[key] = max(0.0, usd)

    def release_margin(self, key: str) -> None:
        self._margin.pop(key, None)

    def reserved_margin(self) -> float:
        return sum(self._margin.values())

    # ── Leverage ──

    async def ensure_leverage(self, inst: Instrument, leverage: int) -> None:
        """Apply `leverage` before opening from flat. With a position already
        open the exchange keeps the existing setting (changing it would
        re-margin positions other targets opened)."""
        async with self._leverage_locks.hold(inst.id):
            if self._leverage.get(inst.id) == leverage or abs(self.net_size(inst.id)) > 0:
                return
            await self.client.update_leverage(inst, leverage, self.cross_margin)
            self._leverage[inst.id] = leverage
            log.info(f"perps leverage {inst.symbol} → {leverage}x ({'cross' if self.cross_margin else 'isolated'})")
