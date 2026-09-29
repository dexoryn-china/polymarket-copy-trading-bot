"""KeyedLocks: FIFO per key, concurrency across keys, no leftover entries."""

from __future__ import annotations

import asyncio

from app.utils.keyed_lock import KeyedLocks


def test_same_key_serialized_fifo():
    asyncio.run(_same_key_fifo())


async def _same_key_fifo():
    locks = KeyedLocks()
    order: list[str] = []
    first_inside = asyncio.Event()
    release_first = asyncio.Event()

    async def first():
        async with locks.hold("asset"):
            order.append("1-in")
            first_inside.set()
            await release_first.wait()
            order.append("1-out")

    async def later(name: str):
        async with locks.hold("asset"):
            order.append(f"{name}-in")
            order.append(f"{name}-out")

    t1 = asyncio.create_task(first())
    await first_inside.wait()
    t2 = asyncio.create_task(later("2"))
    await asyncio.sleep(0.02)
    t3 = asyncio.create_task(later("3"))
    await asyncio.sleep(0.02)
    assert len(locks) == 1
    release_first.set()
    await asyncio.gather(t1, t2, t3)
    assert order == ["1-in", "1-out", "2-in", "2-out", "3-in", "3-out"]
    assert len(locks) == 0


def test_different_keys_run_concurrently():
    asyncio.run(_different_keys_concurrent())


async def _different_keys_concurrent():
    locks = KeyedLocks()
    a_in = asyncio.Event()
    b_in = asyncio.Event()

    async def a():
        async with locks.hold("a"):
            a_in.set()
            await b_in.wait()

    async def b():
        async with locks.hold("b"):
            b_in.set()
            await a_in.wait()

    await asyncio.wait_for(asyncio.gather(a(), b()), timeout=1.0)
    assert len(locks) == 0


def test_len_zero_after_body_raises():
    asyncio.run(_len_zero_after_raise())


async def _len_zero_after_raise():
    locks = KeyedLocks()

    async def boom():
        async with locks.hold("k"):
            raise RuntimeError("body failed")

    result = await asyncio.gather(boom(), return_exceptions=True)
    assert isinstance(result[0], RuntimeError)
    assert len(locks) == 0


def test_len_zero_after_waiter_cancelled():
    asyncio.run(_len_zero_after_cancel())


async def _len_zero_after_cancel():
    locks = KeyedLocks()
    inside = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with locks.hold("k"):
            inside.set()
            await release.wait()

    async def waiter():
        async with locks.hold("k"):
            pass

    ht = asyncio.create_task(holder())
    await inside.wait()
    wt = asyncio.create_task(waiter())
    await asyncio.sleep(0.02)
    assert not wt.done()
    assert len(locks) == 1

    wt.cancel()
    cancelled = await asyncio.gather(wt, return_exceptions=True)
    assert isinstance(cancelled[0], asyncio.CancelledError)
    assert len(locks) == 1  # holder still in

    release.set()
    await ht
    assert len(locks) == 0
