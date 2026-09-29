"""Portfolio + BalanceMonitor."""

from __future__ import annotations

import asyncio
import logging

from app.core.portfolio import BalanceMonitor, Collateral, Portfolio


class _Book:
    def __init__(self, target_id: str, usd: float) -> None:
        self.target_id = target_id
        self._usd = usd

    def open_usd(self, now_ms: int) -> float:
        return self._usd


class _Source:
    def __init__(self, snap: Collateral | None = None, error: Exception | None = None) -> None:
        self.snap = snap
        self.error = error
        self.calls = 0

    async def get_collateral(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.snap


def test_portfolio_headroom_min_of_target_and_global():
    p = Portfolio(global_cap_usd=30.0)
    a = _Book("ta", 10.0)
    b = _Book("tb", 5.0)
    p.register(a)
    p.register(b)
    now = 1_000
    # Target A open 10, cap 20 → 10; global open 15, cap 30 → 15; min = 10
    assert p.headroom_usd("ta", 20.0, now) == 10.0
    p.reserve("r1", "ta", 4.0)
    # A open+res 14, target headroom 6; global 19, global headroom 11; min = 6
    assert p.headroom_usd("ta", 20.0, now) == 6.0
    p.release("r1")
    assert p.headroom_usd("ta", 20.0, now) == 10.0
    p.unregister("tb")
    assert p.open_usd("tb", now) == 0.0
    assert p.open_usd("ta", now) == 10.0


def test_portfolio_no_global_cap():
    p = Portfolio(None)
    p.register(_Book("t", 8.0))
    assert p.headroom_usd("t", 10.0, 1) == 2.0


def test_balance_unknown_never_blocks():
    mon = BalanceMonitor(_Source(None), lambda: 0.0)
    assert mon.check(100.0) is None


def test_balance_insufficient_and_allowance():
    asyncio.run(_balance_checks())


async def _balance_checks():
    src = _Source(Collateral(balance_usd=10.0, allowance_usd=8.0))
    reserved = {"v": 1.0}
    mon = BalanceMonitor(src, lambda: reserved["v"])
    await mon.refresh()
    # available = 10 - 1 = 9, allowance = 8 → spendable is min of both
    assert mon.check(8.0) is None
    reason = mon.check(9.5)
    assert reason is not None and "insufficient balance" in reason
    src.snap = Collateral(balance_usd=100.0, allowance_usd=8.0)
    await mon.refresh()
    reason = mon.check(8.5)
    assert reason is not None and "insufficient allowance" in reason
    assert mon.check(8.0) is None

    mon.debit(3.0)
    assert mon.balance_usd == 97.0
    mon.credit(2.0)
    assert mon.balance_usd == 99.0


def test_balance_refresh_swallows_source_exceptions(caplog):
    asyncio.run(_refresh_swallows(caplog))


async def _refresh_swallows(caplog):
    src = _Source(error=RuntimeError("api down"))
    mon = BalanceMonitor(src, lambda: 0.0)
    with caplog.at_level(logging.WARNING, logger="portfolio"):
        await mon.refresh()
    assert mon.balance_usd is None
    assert "balance refresh failed" in caplog.text
    assert mon.check(50) is None
