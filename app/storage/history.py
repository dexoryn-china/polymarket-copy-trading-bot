"""SQLite-backed activity history.

Writes are buffered in memory and flushed from a worker thread so publishing an
activity never touches disk on the event loop. Reads also run in a thread.
"""

import asyncio
import json
import logging
import sqlite3
import threading
from typing import Any, Optional

from app.events import Activity

log = logging.getLogger("history")

FLUSH_INTERVAL_S = 0.5
DEFAULT_RETENTION = 200_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS activity (
    id          INTEGER PRIMARY KEY,
    ts_ms       INTEGER NOT NULL,
    venue       TEXT NOT NULL,
    target_id   TEXT,
    target_name TEXT,
    kind        TEXT NOT NULL,
    level       TEXT NOT NULL,
    summary     TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS activity_target ON activity (target_id, id);
CREATE INDEX IF NOT EXISTS activity_kind ON activity (kind, id);
"""

_COLUMNS = ("id", "ts_ms", "venue", "target_id", "target_name", "kind", "level", "summary", "data")


class HistoryStore:
    def __init__(self, path: str, retention: int = DEFAULT_RETENTION) -> None:
        self.retention = retention
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._db_lock = threading.Lock()
        self._buffer: list[Activity] = []

    def max_id(self) -> int:
        with self._db_lock:
            row = self._conn.execute("SELECT MAX(id) FROM activity").fetchone()
        return int(row[0] or 0)

    # ── Write side ──

    def record(self, activity: Activity) -> None:
        """EventBus subscriber — O(1), no I/O."""
        self._buffer.append(activity)

    async def run(self, shutdown: asyncio.Event) -> None:
        while not shutdown.is_set():
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=FLUSH_INTERVAL_S)
            except asyncio.TimeoutError:
                pass
            await self.flush()

    async def flush(self) -> None:
        if not self._buffer:
            return
        batch, self._buffer = self._buffer, []
        try:
            await asyncio.to_thread(self._write, batch)
        except Exception:
            log.exception(f"failed to persist {len(batch)} activity rows")

    def _write(self, batch: list[Activity]) -> None:
        rows = [
            (a.id, a.ts_ms, a.venue, a.target_id, a.target_name, a.kind, a.level,
             a.summary, json.dumps(a.data, default=str))
            for a in batch
        ]
        with self._db_lock:
            self._conn.executemany(
                f"INSERT OR REPLACE INTO activity ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))})",
                rows,
            )
            self._conn.execute(
                "DELETE FROM activity WHERE id <= (SELECT MAX(id) FROM activity) - ?",
                (self.retention,),
            )
            self._conn.commit()

    # ── Read side ──

    async def query(
        self,
        *,
        limit: int = 100,
        before_id: Optional[int] = None,
        target_id: Optional[str] = None,
        venue: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        await self.flush()
        return await asyncio.to_thread(self._query, limit, before_id, target_id, venue, kind)

    def _query(self, limit, before_id, target_id, venue, kind) -> list[dict[str, Any]]:
        clauses, params = [], []
        for col, val in (("target_id", target_id), ("venue", venue), ("kind", kind)):
            if val:
                clauses.append(f"{col} = ?")
                params.append(val)
        if before_id is not None:
            clauses.append("id < ?")
            params.append(before_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT {', '.join(_COLUMNS)} FROM activity {where} ORDER BY id DESC LIMIT ?"
        with self._db_lock:
            rows = self._conn.execute(sql, (*params, limit)).fetchall()
        items = []
        for row in rows:
            item = dict(zip(_COLUMNS, row))
            item["data"] = json.loads(item["data"])
            items.append(item)
        return items

    def close(self) -> None:
        with self._db_lock:
            self._conn.close()
