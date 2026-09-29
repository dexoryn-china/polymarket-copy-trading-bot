"""Rolling counters + latency window, fed from the EventBus."""

from collections import deque
from dataclasses import asdict, dataclass
from typing import Optional

from app import events
from app.events import Activity

LATENCY_WINDOW = 200

_COUNTED = {
    events.TARGET_FILL: "detected",
    events.COPY_SUCCESS: "copied",
    events.COPY_FAILURE: "failed",
    events.COPY_SKIPPED: "skipped",
}


@dataclass
class Counts:
    detected: int = 0
    copied: int = 0
    failed: int = 0
    skipped: int = 0
    last_activity_ms: Optional[int] = None

    def as_dict(self) -> dict:
        return asdict(self)


class Stats:
    def __init__(self) -> None:
        self.total = Counts()
        self.by_target: dict[str, Counts] = {}
        self._latency: deque[tuple[int, int]] = deque(maxlen=LATENCY_WINDOW)

    def record(self, a: Activity) -> None:
        """EventBus subscriber."""
        field_name = _COUNTED.get(a.kind)
        if field_name is None:
            return
        for counts in self._targets_for(a):
            setattr(counts, field_name, getattr(counts, field_name) + 1)
            counts.last_activity_ms = a.ts_ms
        latency = a.data.get("latency_ms")
        if a.kind == events.COPY_SUCCESS and isinstance(latency, (int, float)) and latency >= 0:
            self._latency.append((a.ts_ms, int(latency)))

    def _targets_for(self, a: Activity) -> list[Counts]:
        out = [self.total]
        if a.target_id:
            out.append(self.by_target.setdefault(a.target_id, Counts()))
        return out

    def for_target(self, target_id: str) -> Counts:
        return self.by_target.get(target_id, Counts())

    def latency(self) -> dict:
        values = [v for _, v in self._latency]
        if not values:
            return {"last_ms": None, "avg_ms": None, "p95_ms": None, "recent": []}
        ordered = sorted(values)
        p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
        return {
            "last_ms": values[-1],
            "avg_ms": round(sum(values) / len(values)),
            "p95_ms": p95,
            "recent": [{"ts_ms": ts, "total_ms": v} for ts, v in list(self._latency)[-60:]],
        }
