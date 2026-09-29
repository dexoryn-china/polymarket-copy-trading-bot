"""Venue pipeline factories from app.main (no live network)."""

from __future__ import annotations

import asyncio

from app.main import perps_pipeline


class _StubClient:
    async def open_session(self):
        return None

    async def run(self, stop):
        await stop.wait()

    async def keep_session(self, stop):
        await stop.wait()


class _StubEngine:
    async def run(self, stop):
        await stop.wait()

    async def shutdown(self, grace_s):
        return None


def test_perps_pipeline_dry_run_omits_session_job():
    client = _StubClient()
    pipe = perps_pipeline(client, _StubEngine(), None, dry_run=True)
    assert pipe.prepare.__self__ is client
    assert pipe.prepare.__func__ is _StubClient.open_session
    stop = asyncio.Event()
    jobs = pipe.jobs(stop)
    try:
        assert "session" not in jobs
        assert "poll" in jobs
        assert "market" in jobs
    finally:
        for coro in jobs.values():
            coro.close()
