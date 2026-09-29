"""ClobClient.keep_warm and real-mode credential caching."""

from __future__ import annotations

import asyncio
import base64
import time

from eth_account import Account

from app.pm.clob import (
    CLOB_WARM_URL,
    GAMMA_WARM_URL,
    ClobClient,
    OrderResult,
    OrderSpec,
    decode_secret,
    load_account,
    _parse_fill_amount,
)


class _FakeResp:
    async def read(self) -> bytes:
        return b"ok"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None


class _JsonResp:
    def __init__(self, status: int, text: str):
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text

    async def read(self) -> bytes:
        return self._text.encode()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None


class FakeSession:
    """aiohttp-like session: `.get(url)` returns an async CM and records URLs."""

    def __init__(self, error: BaseException | None = None):
        self.urls: list[str] = []
        self.error = error
        self.post_responses: list[tuple[int, str]] = []
        self.posts: list[str] = []

    def get(self, url: str, **_kwargs):
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        return _FakeResp()

    def post(self, url: str, **_kwargs):
        self.posts.append(url)
        if self.post_responses:
            status, text = self.post_responses.pop(0)
            return _JsonResp(status, text)
        return _JsonResp(200, '{"success": true}')


async def _wait_until(pred, timeout: float = 2.0, interval: float = 0.01) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s")


def _real_secrets() -> tuple[dict, object]:
    acct = Account.create()
    secret = base64.b64encode(b"clob-api-secret-bytes").decode()
    secrets = {
        "private_key": acct.key.hex(),
        "wallet_address": "0x" + "33" * 20,
        "api_key": "api-key",
        "api_secret": secret,
        "passphrase": "phrase",
    }
    return secrets, acct


def test_keep_warm_dry_run_only_hits_gamma():
    asyncio.run(_keep_warm_dry_run())


async def _keep_warm_dry_run():
    session = FakeSession()
    clob = ClobClient(None, True, session)
    shutdown = asyncio.Event()
    task = asyncio.create_task(clob.keep_warm(shutdown, interval_s=30.0))
    await _wait_until(lambda: GAMMA_WARM_URL in session.urls)
    shutdown.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert CLOB_WARM_URL not in session.urls
    assert set(session.urls) == {GAMMA_WARM_URL}


def test_keep_warm_real_mode_hits_clob_and_gamma():
    asyncio.run(_keep_warm_real())


async def _keep_warm_real():
    secrets, _acct = _real_secrets()
    session = FakeSession()
    clob = ClobClient(secrets, False, session)
    shutdown = asyncio.Event()
    task = asyncio.create_task(clob.keep_warm(shutdown, interval_s=30.0))
    await _wait_until(
        lambda: CLOB_WARM_URL in session.urls and GAMMA_WARM_URL in session.urls
    )
    shutdown.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert set(session.urls) == {CLOB_WARM_URL, GAMMA_WARM_URL}


def test_keep_warm_swallows_get_exceptions():
    asyncio.run(_keep_warm_swallows())


async def _keep_warm_swallows():
    session = FakeSession(error=ConnectionError("boom"))
    clob = ClobClient(None, True, session)
    shutdown = asyncio.Event()
    task = asyncio.create_task(clob.keep_warm(shutdown, interval_s=30.0))
    await asyncio.sleep(0.05)
    assert not task.done()
    shutdown.set()
    await asyncio.wait_for(task, timeout=1.0)


def test_keep_warm_returns_promptly_when_shutdown_set():
    asyncio.run(_keep_warm_prompt())


async def _keep_warm_prompt():
    session = FakeSession()
    clob = ClobClient(None, True, session)
    shutdown = asyncio.Event()
    shutdown.set()
    t0 = time.perf_counter()
    await asyncio.wait_for(clob.keep_warm(shutdown, interval_s=30.0), timeout=1.0)
    assert time.perf_counter() - t0 < 1.0

    # Set during the interval wait after the first warm.
    session2 = FakeSession()
    clob2 = ClobClient(None, True, session2)
    shutdown2 = asyncio.Event()
    task = asyncio.create_task(clob2.keep_warm(shutdown2, interval_s=30.0))
    await _wait_until(lambda: bool(session2.urls))
    t1 = time.perf_counter()
    shutdown2.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert time.perf_counter() - t1 < 1.0


def test_real_mode_caches_account_signer_and_secret():
    secrets, acct = _real_secrets()
    clob = ClobClient(secrets, False, FakeSession())
    assert clob.account is not None
    assert clob.account.address == load_account(secrets["private_key"]).address
    assert clob.account.address == acct.address
    assert clob.signer_address == acct.address
    assert clob.api_secret_bytes == decode_secret(secrets["api_secret"])
    assert clob.funder == secrets["wallet_address"]
    assert clob.api_key == secrets["api_key"]
    assert clob.passphrase == secrets["passphrase"]


def _spec(side="BUY", size=10.0, price=0.4) -> OrderSpec:
    return OrderSpec(
        asset_id="123456789",
        side=side,
        size=size,
        price=price,
        order_type="FAK",
        market_slug="m",
        target_price=price,
    )


def test_order_result_is_resting():
    assert OrderResult(success=True, status="live").is_resting is True
    assert OrderResult(success=True, status="delayed").is_resting is True
    assert OrderResult(success=True, status="matched").is_resting is False
    assert OrderResult(success=False, status="live").is_resting is False
    assert OrderResult(success=True, status=None).is_resting is False


def test_parse_fill_amount_decimal_and_fixed_point():
    assert _parse_fill_amount("1.655735", 10) == 1.655735
    assert _parse_fill_amount(1.5, 10) == 1.5
    # Integer string far above the order size is micro-units.
    assert abs(_parse_fill_amount("1655735", 2.0) - 1.655735) < 1e-9
    # Small integer string is already in token units.
    assert _parse_fill_amount("1", 10) == 1.0
    assert _parse_fill_amount("", 10) == 0.0
    assert _parse_fill_amount(None, 10) == 0.0


def test_order_result_buy_sell_mapping_and_unmatched():
    buy = ClobClient._order_result(
        _spec("BUY", size=10, price=0.4),
        {"orderID": "oid-b", "status": "matched", "makingAmount": "2.00", "takingAmount": "5.0"},
    )
    assert buy.success is True
    assert buy.order_id == "oid-b"
    assert buy.filled_shares == 5.0
    assert buy.filled_usd == 2.0

    sell = ClobClient._order_result(
        _spec("SELL", size=10, price=0.4),
        {"order_id": "oid-s", "status": "MATCHED", "makingAmount": "4.0", "takingAmount": "1.60"},
    )
    assert sell.filled_shares == 4.0
    assert sell.filled_usd == 1.60
    assert sell.status == "matched"

    # 6-dec fixed-point integers
    buy_fp = ClobClient._order_result(
        _spec("BUY", size=2, price=0.5),
        {"makingAmount": "825000", "takingAmount": "1655735", "status": "matched", "orderID": "fp"},
    )
    assert abs(buy_fp.filled_shares - 1.655735) < 1e-9
    assert abs(buy_fp.filled_usd - 0.825) < 1e-9

    unmatched = ClobClient._order_result(
        _spec("BUY"),
        {"success": True, "status": "unmatched", "orderID": "u"},
    )
    assert unmatched.status == "unmatched"
    assert unmatched.filled_shares == 0.0
    assert unmatched.filled_usd == 0.0


def test_place_order_dry_run_full_fill():
    asyncio.run(_dry_run_fill())


async def _dry_run_fill():
    clob = ClobClient(None, True, FakeSession())
    spec = _spec(size=7.5, price=0.2)
    result = await clob.place_order(spec)
    assert result.success is True
    assert result.dry_run is True
    assert result.status == "matched"
    assert result.filled_shares == 7.5
    assert abs(result.filled_usd - 1.5) < 1e-9
    assert result.order_id and result.order_id.startswith("dry_")


def test_place_order_success_false_uses_error_msg():
    asyncio.run(_success_false())


async def _success_false():
    secrets, _ = _real_secrets()
    session = FakeSession()
    session.post_responses = [(200, '{"success": false, "errorMsg": "not enough balance"}')]
    clob = ClobClient(secrets, False, session)
    result = await clob.place_order(_spec())
    assert result.success is False
    assert result.error == "not enough balance"


def test_get_collateral_parses_micro_units(monkeypatch):
    asyncio.run(_collateral(monkeypatch))


async def _collateral(monkeypatch):
    secrets, _ = _real_secrets()
    clob = ClobClient(secrets, False, FakeSession())

    async def fake_l2(method, path, body=None, params=None):
        assert path == "/balance-allowance"
        return 200, {
            "balance": "123000000",
            "allowances": {"0xaaa": "5000000", "0xbbb": "9000000"},
        }

    monkeypatch.setattr(clob, "_l2_request", fake_l2)
    col = await clob.get_collateral()
    assert col is not None
    assert abs(col.balance_usd - 123.0) < 1e-9
    assert abs(col.allowance_usd - 9.0) < 1e-9


def test_get_and_cancel_order_dry_run():
    asyncio.run(_dry_order_ops())


async def _dry_order_ops():
    clob = ClobClient(None, True, FakeSession())
    assert await clob.get_order("abc") is None
    assert await clob.cancel_order("abc") is True


def test_get_and_cancel_order_real(monkeypatch):
    asyncio.run(_real_order_ops(monkeypatch))


async def _real_order_ops(monkeypatch):
    secrets, _ = _real_secrets()
    clob = ClobClient(secrets, False, FakeSession())
    calls = []

    async def fake_l2(method, path, body=None, params=None):
        calls.append((method, path, body))
        if method == "GET":
            return 200, {"status": "ORDER_STATUS_LIVE", "size_matched": "1.5"}
        return 200, {"canceled": ["oid-1"], "not_canceled": {}}

    monkeypatch.setattr(clob, "_l2_request", fake_l2)
    st = await clob.get_order("oid-1")
    assert st is not None
    assert st.status == "live"
    assert st.size_matched == 1.5
    assert await clob.cancel_order("oid-1") is True
    assert calls[1][0] == "DELETE"
    assert calls[1][2] == {"orderID": "oid-1"}
