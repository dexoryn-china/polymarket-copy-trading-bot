"""CopySession — runs exactly one venue's copy pipeline at a time.

The operator picks a venue (prediction markets or perps) and starts / stops
copying from the dashboard. Each venue plugs in a `VenuePipeline`: its
background jobs plus optional prepare (before start) and drain (after stop)
steps, so adding a venue never touches this class.

The selected venue and whether copying was on are persisted, so a restarted
bot resumes where it left off.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Coroutine, Optional

from app import events
from app.events import EventBus
from app.targets import TargetConflict, TargetError

log = logging.getLogger("session")

STOPPED = "stopped"
STARTING = "starting"
RUNNING = "running"
STOPPING = "stopping"

Jobs = Callable[[asyncio.Event], dict[str, Coroutine]]


class SessionError(TargetError):
    """Copying couldn't start (maps to HTTP 400 with the reason)."""


@dataclass
class VenuePipeline:
    label: str
    jobs: Jobs                                               # stop event → {name: coroutine}
    prepare: Optional[Callable[[], Awaitable[None]]] = None  # raising aborts the start
    drain: Optional[Callable[[float], Awaitable[None]]] = None  # finish in-flight work after jobs stop


class CopySession:
    def __init__(
        self,
        pipelines: dict[str, VenuePipeline],
        bus: EventBus,
        venue: str,
        on_fatal: Callable[[str, BaseException], None],
        grace_s: float = 5.0,
    ) -> None:
        if venue not in pipelines:
            raise ValueError(f"unknown venue {venue!r}")
        self.pipelines = pipelines
        self.bus = bus
        self.venue = venue
        self.on_fatal = on_fatal
        self.grace_s = grace_s
        self.state = STOPPED
        self.started_at_ms: Optional[int] = None
        self.wanted = False            # persisted "copying on" — survives a bot shutdown
        self._stop: Optional[asyncio.Event] = None
        self._tasks: list[asyncio.Task] = []
        self._lock = asyncio.Lock()
        self._dirty = False

    @property
    def running(self) -> bool:
        return self.state == RUNNING

    @property
    def label(self) -> str:
        return self.pipelines[self.venue].label

    def is_active(self, venue: str) -> bool:
        """The venue whose pipeline is (or would be) running."""
        return venue == self.venue

    # ── Control ──

    def select(self, venue: str) -> None:
        if venue not in self.pipelines:
            raise TargetError(f"venue must be one of {sorted(self.pipelines)}")
        if venue == self.venue:
            return
        if self.state != STOPPED:
            raise TargetConflict("stop copying before switching venue")
        self.venue = venue
        self._dirty = True
        self.bus.emit(events.SYSTEM, f"Copy venue: {self.label}", event="venue")

    async def start(self, venue: Optional[str] = None) -> None:
        async with self._lock:
            if self.state != STOPPED:
                raise TargetConflict(f"already copying {self.label}")
            if venue is not None:
                self.select(venue)
            pipeline = self.pipelines[self.venue]
            self.state = STARTING
            try:
                if pipeline.prepare is not None:
                    await pipeline.prepare()
            except Exception as e:
                self.state = STOPPED
                log.error(f"couldn't start {pipeline.label}: {e}")
                self.bus.emit(events.ERROR, f"Couldn't start {pipeline.label} copying: {e}",
                              level=events.ERROR_LEVEL)
                raise SessionError(f"couldn't start {pipeline.label} copying: {e}") from None
            self._stop = asyncio.Event()
            self._tasks = [asyncio.create_task(coro, name=f"{self.venue}:{name}")
                           for name, coro in pipeline.jobs(self._stop).items()]
            for task in self._tasks:
                task.add_done_callback(self._on_job_done)
            self.state = RUNNING
            self.started_at_ms = int(time.time() * 1000)
            self.wanted = True
            self._dirty = True
            log.info(f"copying started — {pipeline.label}")
            self.bus.emit(events.SYSTEM, f"Copying started — {pipeline.label}", event=events.COPY_START)

    async def stop(self) -> None:
        """Operator stop: copying stays off after a restart."""
        await self._halt(keep_wanted=False)

    async def shutdown(self) -> None:
        """Bot shutdown: stop the pipeline but remember it was on."""
        await self._halt(keep_wanted=True)

    async def _halt(self, keep_wanted: bool) -> None:
        async with self._lock:
            if not keep_wanted and self.wanted:
                self.wanted = False
                self._dirty = True
            if self.state != RUNNING:
                return
            pipeline = self.pipelines[self.venue]
            self.state = STOPPING
            assert self._stop is not None
            self._stop.set()
            _, pending = await asyncio.wait(self._tasks, timeout=self.grace_s)
            for task in pending:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            # Feed is down, so no new fills: finish in-flight ones, pull resting orders.
            if pipeline.drain is not None:
                try:
                    await pipeline.drain(self.grace_s)
                except Exception:
                    log.exception(f"{pipeline.label} drain failed")
            self._tasks, self._stop = [], None
            self.state = STOPPED
            self.started_at_ms = None
            log.info(f"copying stopped — {pipeline.label}")
            self.bus.emit(events.SYSTEM, f"Copying stopped — {pipeline.label}", event=events.COPY_STOP)

    def _on_job_done(self, task: asyncio.Task) -> None:
        if task.cancelled() or self._stop is None or self._stop.is_set():
            return
        exc = task.exception()
        if exc is not None:
            self.on_fatal(task.get_name(), exc)

    # ── Views / state ──

    def to_dict(self) -> dict:
        return {
            "venue": self.venue,
            "venue_label": self.label,
            "state": self.state,
            "running": self.running,
            "started_at_ms": self.started_at_ms,
        }

    def export_state(self) -> dict:
        return {"venue": self.venue, "running": self.wanted}

    @property
    def dirty(self) -> bool:
        return self._dirty

    def mark_clean(self) -> None:
        self._dirty = False
