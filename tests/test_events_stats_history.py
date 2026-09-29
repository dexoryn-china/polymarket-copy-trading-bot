"""EventBus, Stats, HistoryStore."""

from __future__ import annotations

import asyncio
import logging

from app import events
from app.events import Activity, EventBus
from app.stats import Stats
from app.storage.history import HistoryStore


def test_event_bus_ids_increment_from_start_id():
    bus = EventBus(start_id=10)
    a = bus.emit(events.SYSTEM, "one")
    b = bus.emit(events.SYSTEM, "two")
    assert a.id == 10
    assert b.id == 11


def test_event_bus_subscriber_exceptions_isolated(caplog):
    bus = EventBus()
    seen: list[int] = []

    def boom(_a):
        raise RuntimeError("sub exploded")

    def ok(a):
        seen.append(a.id)

    bus.subscribe(boom)
    bus.subscribe(ok)
    with caplog.at_level(logging.ERROR, logger="events"):
        act = bus.emit(events.SYSTEM, "hi")
    assert seen == [act.id]
    assert "subscriber" in caplog.text


def test_event_bus_unsubscribe():
    bus = EventBus()
    seen: list[str] = []
    unsub = bus.subscribe(lambda a: seen.append(a.summary))
    bus.emit(events.SYSTEM, "a")
    unsub()
    bus.emit(events.SYSTEM, "b")
    assert seen == ["a"]
    # Unsubscribing twice is a no-op.
    unsub()


def test_stats_counts_overall_and_per_target_and_p95():
    stats = Stats()
    t1 = Activity(kind=events.TARGET_FILL, summary="f", target_id="t1", ts_ms=1)
    t2 = Activity(kind=events.COPY_SUCCESS, summary="c", target_id="t1", ts_ms=2,
                  data={"latency_ms": 40})
    t3 = Activity(kind=events.COPY_FAILURE, summary="x", target_id="t2", ts_ms=3)
    t4 = Activity(kind=events.COPY_SKIPPED, summary="s", target_id="t1", ts_ms=4)
    t5 = Activity(kind=events.COPY_SUCCESS, summary="c2", target_id="t1", ts_ms=5,
                  data={"latency_ms": 100})
    t6 = Activity(kind=events.ORDER_UPDATE, summary="ignored")
    for a in (t1, t2, t3, t4, t5, t6):
        stats.record(a)

    assert stats.total.detected == 1
    assert stats.total.copied == 2
    assert stats.total.failed == 1
    assert stats.total.skipped == 1
    assert stats.for_target("t1").copied == 2
    assert stats.for_target("t1").skipped == 1
    assert stats.for_target("t1").failed == 0
    assert stats.for_target("t2").failed == 1
    assert stats.for_target("unknown").copied == 0

    lat = stats.latency()
    assert lat["last_ms"] == 100
    assert lat["avg_ms"] == 70
    assert lat["p95_ms"] == 100
    assert len(lat["recent"]) == 2

    empty = Stats().latency()
    assert empty["last_ms"] is None
    assert empty["p95_ms"] is None
    assert empty["recent"] == []


def test_stats_ignores_negative_latency():
    stats = Stats()
    stats.record(Activity(kind=events.COPY_SUCCESS, summary="c", data={"latency_ms": -1}))
    assert stats.latency()["last_ms"] is None


def test_history_store_record_flush_query(tmp_path):
    asyncio.run(_history(tmp_path))


async def _history(tmp_path):
    path = str(tmp_path / "history.db")
    store = HistoryStore(path)
    bus = EventBus(start_id=1)
    bus.subscribe(store.record)
    a1 = bus.emit(events.TARGET_FILL, "fill a", venue="predictions", target=_T("t1", "A"))
    a2 = bus.emit(events.COPY_SUCCESS, "copy a", venue="predictions", target=_T("t1", "A"))
    a3 = bus.emit(events.COPY_FAILURE, "fail b", venue="perps", target=_T("t2", "B"))
    a4 = bus.emit(events.SYSTEM, "sys", venue="system")

    await store.flush()
    assert store.max_id() == a4.id

    all_items = await store.query(limit=10)
    assert [i["id"] for i in all_items] == [a4.id, a3.id, a2.id, a1.id]
    assert all_items[0]["summary"] == "sys"

    only_t1 = await store.query(target_id="t1")
    assert {i["id"] for i in only_t1} == {a1.id, a2.id}

    only_perps = await store.query(venue="perps")
    assert [i["id"] for i in only_perps] == [a3.id]

    only_kind = await store.query(kind=events.COPY_SUCCESS)
    assert [i["id"] for i in only_kind] == [a2.id]

    page = await store.query(limit=2)
    assert [i["id"] for i in page] == [4, 3]
    older = await store.query(limit=2, before_id=page[-1]["id"])
    assert [i["id"] for i in older] == [2, 1]

    store.close()


class _T:
    def __init__(self, id, name):
        self.id = id
        self.name = name
