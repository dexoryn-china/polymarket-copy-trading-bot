"""In-process activity bus.

Trading code publishes `Activity` records; subscribers (history store, stats,
Telegram, dashboard websocket) consume them. Publishing is synchronous and
cheap — subscribers must not block (schedule I/O as tasks / buffers).
"""

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger("events")

# Activity kinds
TARGET_FILL = "target_fill"
COPY_SUCCESS = "copy_success"
COPY_FAILURE = "copy_failure"
COPY_SKIPPED = "copy_skipped"
ORDER_UPDATE = "order_update"
SYSTEM = "system"
ERROR = "error"

# SYSTEM activities carry a sub-event in `data["event"]`; these are the ones
# worth notifying on (the rest — pause, target, settings… — are UI-only).
STARTUP = "startup"
SHUTDOWN = "shutdown"
COPY_START = "copy_start"
COPY_STOP = "copy_stop"

# Levels
INFO = "info"
SUCCESS = "success"
WARNING = "warning"
ERROR_LEVEL = "error"

VENUE_SYSTEM = "system"


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Activity:
    kind: str
    summary: str
    level: str = INFO
    venue: str = VENUE_SYSTEM
    target_id: Optional[str] = None
    target_name: Optional[str] = None
    data: dict[str, Any] = field(default_factory=dict)
    ts_ms: int = field(default_factory=now_ms)
    id: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Subscriber = Callable[[Activity], None]


class EventBus:
    def __init__(self, start_id: int = 1) -> None:
        self._subs: list[Subscriber] = []
        self._next_id = start_id

    def subscribe(self, fn: Subscriber) -> Callable[[], None]:
        self._subs.append(fn)
        return lambda: self._subs.remove(fn) if fn in self._subs else None

    def publish(self, activity: Activity) -> Activity:
        activity.id = self._next_id
        self._next_id += 1
        for fn in list(self._subs):
            try:
                fn(activity)
            except Exception:
                log.exception(f"activity subscriber {fn!r} failed")
        return activity

    def emit(
        self,
        kind: str,
        summary: str,
        *,
        level: str = INFO,
        venue: str = VENUE_SYSTEM,
        target: Optional[Any] = None,
        **data: Any,
    ) -> Activity:
        """Publish an activity. `target` is any object with `id` / `name`."""
        return self.publish(Activity(
            kind=kind,
            summary=summary,
            level=level,
            venue=venue,
            target_id=getattr(target, "id", None),
            target_name=getattr(target, "name", None),
            data=data,
        ))
