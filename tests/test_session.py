"""CopySession: one venue at a time, start/stop/shutdown, jobs, drain."""

from __future__ import annotations

import asyncio
import logging

from app import events
from app.events import EventBus
from app.session import RUNNING, STOPPED, SessionError, VenuePipeline
from app.targets import TargetConflict, TargetError, VENUE_PERPS, VENUE_PREDICTIONS
from tests.fakes import make_copy_session, make_pipeline


def _session(**kwargs):
    bus = EventBus()
    acts = []
    bus.subscribe(acts.append)
    kwargs.setdefault("grace_s", 0.05)
    return make_copy_session(bus, **kwargs), acts


def _events(acts) -> list:
    return [a.data.get("event") for a in acts if a.data.get("event") is not None]


def test_start_running_stop_stopped_and_restart():
    asyncio.run(_start_stop_restart())


async def _start_stop_restart():
    session, acts = _session()
    assert session.state == STOPPED
    assert session.to_dict()["running"] is False
    assert session.export_state() == {"venue": VENUE_PREDICTIONS, "running": False}

    await session.start()
    assert session.state == RUNNING
    assert session.running is True
    assert session.wanted is True
    d = session.to_dict()
    assert d["state"] == RUNNING
    assert d["running"] is True
    assert d["venue"] == VENUE_PREDICTIONS
    assert d["venue_label"] == "Prediction markets"
    assert d["started_at_ms"] is not None
    stop1 = session._stop
    assert stop1 is not None and not stop1.is_set()
    assert "copy_start" in _events(acts)

    await session.stop()
    assert session.state == STOPPED
    assert session.running is False
    assert session.wanted is False
    assert session.to_dict()["started_at_ms"] is None
    assert session._stop is None
    assert session._tasks == []
    assert "copy_stop" in _events(acts)
    assert stop1.is_set()

    await session.start()
    assert session.state == RUNNING
    stop2 = session._stop
    assert stop2 is not None and stop2 is not stop1
    assert not stop2.is_set()
    await session.stop()
    assert session.state == STOPPED


def test_second_start_conflicts():
    asyncio.run(_second_start())


async def _second_start():
    session, _ = _session()
    await session.start()
    try:
        await session.start()
        assert False
    except TargetConflict as e:
        assert "already copying" in str(e)
    assert session.state == RUNNING
    await session.stop()


def test_select_while_running():
    asyncio.run(_select_running())


async def _select_running():
    session, acts = _session()
    await session.start()
    acts.clear()
    session.select(VENUE_PREDICTIONS)
    assert session.venue == VENUE_PREDICTIONS
    assert session.state == RUNNING
    assert acts == []
    try:
        session.select(VENUE_PERPS)
        assert False
    except TargetConflict as e:
        assert "stop copying" in str(e)
    assert session.venue == VENUE_PREDICTIONS
    await session.stop()


def test_select_unknown_raises_target_error():
    session, _ = _session()
    try:
        session.select("spot")
        assert False
    except TargetConflict:
        assert False
    except TargetError as e:
        assert "venue" in str(e)
    assert session.venue == VENUE_PREDICTIONS


def test_select_change_emits_and_dirties():
    session, acts = _session()
    session.mark_clean()
    session.select(VENUE_PREDICTIONS)
    assert not session.dirty
    session.select(VENUE_PERPS)
    assert session.venue == VENUE_PERPS
    assert session.dirty
    assert "venue" in _events(acts)
    assert any(a.kind == events.SYSTEM for a in acts)


def test_failing_prepare_rolls_back():
    asyncio.run(_failing_prepare())


async def _failing_prepare():
    async def boom():
        raise RuntimeError("no creds")

    session, acts = _session(pipelines={
        VENUE_PREDICTIONS: make_pipeline(prepare=boom),
        VENUE_PERPS: make_pipeline("Perps"),
    })
    try:
        await session.start()
        assert False
    except SessionError as e:
        assert isinstance(e, TargetError)
        assert "couldn't start" in str(e).lower()
        assert "no creds" in str(e)
    assert session.state == STOPPED
    assert session.wanted is False
    assert session._tasks == []
    errors = [a for a in acts if a.kind == events.ERROR]
    assert len(errors) == 1
    assert "Couldn't start" in errors[0].summary


def test_drain_called_with_grace_after_jobs_stop():
    asyncio.run(_drain_order())


async def _drain_order():
    order = []

    async def job(stop):
        await stop.wait()
        order.append("job")

    async def drain(grace_s):
        order.append(("drain", grace_s))

    grace = 0.07
    session, _ = _session(
        grace_s=grace,
        pipelines={
            VENUE_PREDICTIONS: VenuePipeline(
                "Prediction markets", lambda stop: {"j": job(stop)}, drain=drain,
            ),
            VENUE_PERPS: make_pipeline("Perps"),
        },
    )
    await session.start()
    await session.stop()
    assert order == ["job", ("drain", grace)]
    assert session.state == STOPPED


def test_drain_exception_is_swallowed(caplog):
    asyncio.run(_drain_boom(caplog))


async def _drain_boom(caplog):
    async def drain(_grace_s):
        raise RuntimeError("drain failed")

    session, _ = _session(pipelines={
        VENUE_PREDICTIONS: make_pipeline(drain=drain),
        VENUE_PERPS: make_pipeline("Perps"),
    })
    await session.start()
    with caplog.at_level(logging.ERROR, logger="session"):
        await session.stop()
    assert session.state == STOPPED
    assert "drain failed" in caplog.text


def test_stubborn_job_is_cancelled_after_grace():
    asyncio.run(_stubborn())


async def _stubborn():
    async def stubborn(_stop):
        await asyncio.sleep(30)

    session, _ = _session(
        grace_s=0.05,
        pipelines={
            VENUE_PREDICTIONS: make_pipeline(jobs=lambda stop: {"stuck": stubborn(stop)}),
            VENUE_PERPS: make_pipeline("Perps"),
        },
    )
    await session.start()
    await asyncio.wait_for(session.stop(), timeout=2)
    assert session.state == STOPPED
    assert session._tasks == []


def test_crashing_job_calls_on_fatal():
    asyncio.run(_crash_fatal())


async def _crash_fatal():
    fatal: list[tuple[str, BaseException]] = []

    async def boom(_stop):
        raise RuntimeError("crash")

    session, _ = _session(
        on_fatal=lambda name, exc: fatal.append((name, exc)),
        pipelines={
            VENUE_PREDICTIONS: make_pipeline(jobs=lambda stop: {"boom": boom(stop)}),
            VENUE_PERPS: make_pipeline("Perps"),
        },
    )
    await session.start()
    for _ in range(50):
        if fatal:
            break
        await asyncio.sleep(0.01)
    assert fatal
    assert fatal[0][0] == f"{VENUE_PREDICTIONS}:boom"
    assert isinstance(fatal[0][1], RuntimeError)
    await session.stop()


def test_job_exit_during_stop_does_not_call_on_fatal():
    asyncio.run(_exit_during_stop())


async def _exit_during_stop():
    fatal: list = []

    async def die_on_stop(stop):
        await stop.wait()
        raise RuntimeError("while stopping")

    session, _ = _session(
        on_fatal=lambda name, exc: fatal.append((name, exc)),
        pipelines={
            VENUE_PREDICTIONS: make_pipeline(jobs=lambda stop: {"x": die_on_stop(stop)}),
            VENUE_PERPS: make_pipeline("Perps"),
        },
    )
    await session.start()
    await session.stop()
    assert fatal == []
    assert session.state == STOPPED


def test_stop_clears_wanted_shutdown_keeps_it():
    asyncio.run(_wanted())


async def _wanted():
    session, _ = _session()
    await session.start()
    assert session.export_state()["running"] is True
    await session.shutdown()
    assert session.state == STOPPED
    assert session.export_state() == {"venue": VENUE_PREDICTIONS, "running": True}
    assert session.wanted is True

    await session.start()
    await session.stop()
    assert session.state == STOPPED
    assert session.export_state() == {"venue": VENUE_PREDICTIONS, "running": False}
    assert session.wanted is False


def test_dirty_flag():
    asyncio.run(_dirty())


async def _dirty():
    session, _ = _session()
    assert not session.dirty
    session.select(VENUE_PERPS)
    assert session.dirty
    session.mark_clean()
    assert not session.dirty
    session.select(VENUE_PERPS)
    assert not session.dirty

    await session.start()
    assert session.dirty
    session.mark_clean()
    await session.stop()
    assert session.dirty
    session.mark_clean()
    await session.start()
    session.mark_clean()
    await session.shutdown()
    # shutdown does not flip wanted, so it does not mark dirty
    assert not session.dirty
    await session.stop()
    assert session.dirty
    assert session.wanted is False


def test_activity_events():
    asyncio.run(_activity())


async def _activity():
    session, acts = _session()
    session.select(VENUE_PERPS)
    await session.start()
    await session.stop()
    assert _events(acts) == ["venue", "copy_start", "copy_stop"]
    for a, event in zip(
        [a for a in acts if a.data.get("event")],
        ["venue", "copy_start", "copy_stop"],
    ):
        assert a.kind == events.SYSTEM
        assert a.data["event"] == event


def test_stop_when_not_running_is_noop():
    asyncio.run(_noop_stop())


async def _noop_stop():
    session, acts = _session()
    await session.stop()
    await session.shutdown()
    assert session.state == STOPPED
    assert _events(acts) == []


def test_start_with_venue_selects_first():
    asyncio.run(_start_venue())


async def _start_venue():
    session, acts = _session()
    await session.start(VENUE_PERPS)
    assert session.venue == VENUE_PERPS
    assert session.state == RUNNING
    assert "venue" in _events(acts)
    assert "copy_start" in _events(acts)
    await session.stop()
