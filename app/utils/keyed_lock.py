"""Per-key asyncio locks that are released from memory once unused.

Short-lived markets (e.g. 5-minute up/down) produce a new key every few
minutes; a plain dict of locks would grow for the life of the process.
"""

import asyncio
import contextlib
from typing import AsyncIterator, Hashable


class KeyedLocks:
    """`async with locks.hold(key):` serializes tasks sharing `key` (FIFO) while
    tasks on different keys run concurrently."""

    def __init__(self) -> None:
        self._locks: dict[Hashable, asyncio.Lock] = {}
        self._refs: dict[Hashable, int] = {}

    @contextlib.asynccontextmanager
    async def hold(self, key: Hashable) -> AsyncIterator[None]:
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        self._refs[key] = self._refs.get(key, 0) + 1
        try:
            async with lock:
                yield
        finally:
            self._refs[key] -= 1
            if self._refs[key] == 0:
                del self._refs[key]
                del self._locks[key]

    def __len__(self) -> int:
        return len(self._locks)
