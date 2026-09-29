"""PerpsClient: signing, compact ops, quantize, HTTP fakes (no network)."""

from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal

from eth_account import Account
from eth_account.messages import encode_typed_data

from app.perps.client import (
    Instrument,
    PerpsClient,
    ProxyCredentials,
    create_orders_compact,
    fmt_decimal,
    op_hash,
    quantize_price,
    quantize_qty,
    sign_op,
)
from tests.fakes import FakeSession, make_instrument


def test_sign_op_matches_eth_account_encode_typed_data():
    account = Account.create()
    compact = create_orders_compact([{
        "iid": 1, "buy": True, "p": "100", "qty": "0.5",
        "tif": "ioc", "po": False, "ro": False, "c": "ab" * 16,
    }])
    salt, ts = 123456789, 1_727_540_000_000
    got = sign_op(account, compact, salt=salt, ts=ts)
    typed = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
            ],
            "Op": [
                {"name": "data", "type": "bytes32"},
                {"name": "salt", "type": "uint64"},
                {"name": "ts", "type": "uint64"},
            ],
        },
        "domain": {"name": "Polymarket", "version": "1", "chainId": 137},
        "primaryType": "Op",
        "message": {"data": op_hash(compact), "salt": salt, "ts": ts},
    }
    ref = account.sign_message(encode_typed_data(full_message=typed))
    assert got["sig"] == "0x" + bytes(ref.signature).hex()
    assert got["salt"] == salt
    assert got["ts"] == ts


def test_create_orders_compact_omits_none_keeps_order():
    compact = create_orders_compact([{
        "iid": 7, "buy": True, "p": "1.5", "qty": "2",
        "tif": "ioc", "po": False, "ro": True, "c": "dead", "tr": None,
    }])
    assert compact[0] == "createOrders"
    row = compact[1][0]
    assert row == [7, True, "1.5", "2", "ioc", False, True, "dead"]
    full = create_orders_compact([{
        "iid": 7, "buy": False, "p": "1", "qty": "1",
        "tif": "ioc", "po": True, "ro": False, "c": "cc", "tr": "taker",
    }])
    assert full[1][0] == [7, False, "1", "1", "ioc", True, False, "cc", "taker"]


def test_quantize_price_and_qty_and_fmt_decimal():
    assert fmt_decimal(quantize_price(83639.7, 2, True)) == "83639"
    assert fmt_decimal(quantize_price(7687.47, 2, False)) == "7687.5"
    assert fmt_decimal(quantize_price(0.100587, 6, True)) == "0.10058"
    assert quantize_qty(1.239, 2) == Decimal("1.23")
    assert "e" not in fmt_decimal(Decimal("1E-5")).lower()
    assert fmt_decimal(Decimal("1E-5")) == "0.00001"
    assert fmt_decimal(Decimal("100")) == "100"


def test_instrument_from_api():
    inst = Instrument.from_api({
        "instrument_id": 42,
        "symbol": "ETH",
        "quantity_decimals": 3,
        "price_decimals": 1,
        "price_bounds": 0.02,
        "min_notional": 5,
        "max_market_notional": 0,
        "max_leverage": 10,
        "isolated_only": True,
    })
    assert inst.id == 42
    assert inst.symbol == "ETH"
    assert inst.max_market_notional == float("inf")
    assert inst.isolated_only is True


def test_public_portfolio_skips_zero_and_malformed(monkeypatch):
    asyncio.run(_public_portfolio(monkeypatch))


async def _public_portfolio(monkeypatch):
    client = PerpsClient(FakeSession(), dry_run=True)

    async def fake_request(method, path, **kwargs):
        assert path == "/v1/info/portfolio"
        return {
            "positions": [
                {"instrument_id": 1, "symbol": "BTC", "size": "2.5", "entry_price": "100"},
                {"instrument_id": 2, "symbol": "ETH", "size": "0", "entry_price": "1"},
                {"instrument_id": "bad"},
                {"instrument_id": 3, "size": "1.0"},
            ]
        }

    monkeypatch.setattr(client, "_request", fake_request)
    pos = await client.public_portfolio("0xABC")
    assert set(pos) == {1, 3}
    assert pos[1].size == 2.5
    assert pos[3].symbol == "3"


def test_place_ioc_real_flow_vwap_and_err_ack(monkeypatch):
    asyncio.run(_place_ioc(monkeypatch))


async def _place_ioc(monkeypatch):
    owner, proxy = Account.create(), Account.create()
    client = PerpsClient(FakeSession(), dry_run=False, owner_private_key=owner.key.hex())
    client._use(ProxyCredentials(
        owner=owner.address, proxy=proxy.address,
        private_key="0x" + bytes(proxy.key).hex(), secret="s",
        expires_at_ms=int(time.time() * 1000) + 86_400_000 * 8,
    ))
    inst = make_instrument(iid=9, symbol="BTC", quantity_decimals=4, price_decimals=1)
    calls = []

    async def fake_request(method, path, *, params=None, body=None, auth=False):
        calls.append((method, path, params, body))
        if path == "/v1/trade/orders":
            return [{"status": "ok", "oid": 5}]
        if path == "/v1/account/orders":
            return [{"order_id": 5, "status": "ioc_expired", "filled_quantity": "0.4"}]
        if path == "/v1/account/fills":
            return {"data": [
                {"order_id": 5, "quantity": "0.25", "price": "100"},
                {"order_id": 5, "quantity": "0.15", "price": "110"},
                {"order_id": 99, "quantity": "9", "price": "1"},
            ]}
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request", fake_request)
    result = await client.place_ioc(inst, True, Decimal("1"), Decimal("101"), False)
    assert result.success is True
    assert result.order_id == 5
    assert result.filled_qty == 0.4
    assert abs(result.avg_price - 103.75) < 1e-9  # (0.25*100 + 0.15*110) / 0.4

    async def err_request(method, path, **kwargs):
        return [{"status": "err", "error": "insufficient_margin"}]

    monkeypatch.setattr(client, "_request", err_request)
    bad = await client.place_ioc(inst, True, Decimal("1"), Decimal("101"), False)
    assert bad.success is False
    assert "insufficient_margin" in (bad.error or "")


def test_place_ioc_dry_run_fills_at_mark():
    asyncio.run(_dry_ioc())


async def _dry_ioc():
    client = PerpsClient(FakeSession(), dry_run=True)
    inst = make_instrument(iid=1)
    client._marks[1] = 55.5
    result = await client.place_ioc(inst, True, Decimal("2"), Decimal("99"), False)
    assert result.success is True
    assert result.dry_run is True
    assert result.filled_qty == 2.0
    assert result.avg_price == 55.5
    assert result.status == "filled"


def test_open_session_creates_and_reuses(tmp_path, monkeypatch):
    asyncio.run(_session(tmp_path, monkeypatch))


async def _session(tmp_path, monkeypatch):
    owner = Account.create()
    session_file = tmp_path / "perps_session.json"
    client = PerpsClient(
        FakeSession(), dry_run=False,
        owner_private_key=owner.key.hex(),
        session_file=str(session_file),
    )
    created = {"n": 0}

    async def fake_request(method, path, *, body=None, **kwargs):
        created["n"] += 1
        assert path == "/v1/account/proxy"
        assert body["op"]["type"] == "createProxy"
        return {"secret": "new-secret"}

    monkeypatch.setattr(client, "_request", fake_request)
    await client.open_session()
    assert created["n"] == 1
    assert session_file.exists()
    assert client.creds is not None
    assert client.creds.secret == "new-secret"
    first_proxy = client.creds.proxy

    # Reuse a still-valid file (no _request).
    client2 = PerpsClient(
        FakeSession(), dry_run=False,
        owner_private_key=owner.key.hex(),
        session_file=str(session_file),
    )

    async def must_not_hit(*_a, **_k):
        raise AssertionError("should reuse stored creds")

    monkeypatch.setattr(client2, "_request", must_not_hit)
    await client2.open_session()
    assert client2.creds is not None
    assert client2.creds.proxy == first_proxy
    assert client2.creds.secret == "new-secret"

    # Expiring creds → create again.
    data = json.loads(session_file.read_text(encoding="utf-8"))
    data["expires_at_ms"] = int(time.time() * 1000) + 60_000  # < 24h → needs_renewal
    session_file.write_text(json.dumps(data), encoding="utf-8")
    client3 = PerpsClient(
        FakeSession(), dry_run=False,
        owner_private_key=owner.key.hex(),
        session_file=str(session_file),
    )
    monkeypatch.setattr(client3, "_request", fake_request)
    await client3.open_session()
    assert created["n"] == 2
