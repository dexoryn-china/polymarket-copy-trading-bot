"""Poller._handle_text: wallet filter, parse, dedup, dispatch."""

from __future__ import annotations

import asyncio
import json
import logging
import types

from eth_utils import to_checksum_address

from app.core.poller import Poller, _full_row_key
from app.core.trader import TargetFill


TARGET = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"
OTHER = "0x1111111111111111111111111111111111111111"
CHECKSUM = to_checksum_address(TARGET)


def _poller_config() -> dict:
    return {
        "dedup": {"seen_cap": 1000},
        "watchdog": {"max_consecutive_errors": 5, "silent_timeout_s": 30},
    }


def _make_poller(wallets=None):
    fills: list[TargetFill] = []

    def on_fill(fill: TargetFill) -> None:
        fills.append(fill)

    wallets = wallets if wallets is not None else {TARGET.lower()}
    poller = Poller(_poller_config(), None, wallets, on_fill, {}, bus=None)
    return poller, fills


def _envelope(proxy_wallet: str, **payload_over) -> str:
    payload = {
        "proxyWallet": proxy_wallet,
        "transactionHash": "0xabc",
        "asset": "123",
        "side": "BUY",
        "size": 10,
        "price": 0.42,
        "slug": "some-market",
        "outcome": "Yes",
        "title": "T",
    }
    payload.update(payload_over)
    return json.dumps(
        {
            "topic": "activity",
            "type": "trades",
            "timestamp": 1727540000000,
            "payload": payload,
        }
    )


def test_checksum_proxy_wallet_is_dispatched():
    poller, fills = _make_poller()
    poller._handle_text(_envelope(CHECKSUM))
    assert len(fills) == 1
    fill = fills[0]
    assert fill.tx_hash == "0xabc"
    assert fill.asset == "123"
    assert fill.side == "BUY"
    assert fill.size == 10.0
    assert fill.price == 0.42
    assert fill.market_slug == "some-market"
    assert fill.outcome == "Yes"
    assert fill.title == "T"
    assert fill.timestamp_ms == 1727540000000
    assert fill.wallet == TARGET.lower()


def test_mixed_case_wallet_still_matches():
    poller, fills = _make_poller({TARGET.lower()})
    poller._handle_text(_envelope("0x" + TARGET[2:].upper()))
    assert len(fills) == 1
    assert fills[0].wallet == TARGET.lower()


def test_non_target_trade_ignored():
    poller, fills = _make_poller()
    poller._handle_text(_envelope(OTHER))
    assert fills == []


def test_ping_pong_empty_ignored():
    poller, fills = _make_poller()
    for raw in ("PING", "PONG", ""):
        poller.last_event_ms = 0
        poller._handle_text(raw)
        assert poller.last_event_ms > 0
        assert fills == []


def test_malformed_json_ignored():
    poller, fills = _make_poller()
    poller.last_event_ms = 0
    poller._handle_text('{"payload": {"proxyWallet": "' + CHECKSUM + '"')
    assert poller.last_event_ms > 0
    assert fills == []


def test_non_dict_json_containing_address_ignored():
    poller, fills = _make_poller()
    poller._handle_text(json.dumps([CHECKSUM, "activity", "trades"]))
    poller._handle_text(json.dumps(CHECKSUM))
    assert fills == []


def test_non_dict_payload_ignored_without_raising():
    poller, fills = _make_poller()
    envelopes = [
        json.dumps(
            {
                "topic": "activity",
                "type": "trades",
                "timestamp": 1727540000000,
                "payload": [CHECKSUM],
            }
        ),
        json.dumps(
            {
                "topic": "activity",
                "type": "trades",
                "timestamp": 1727540000000,
                "payload": CHECKSUM,
            }
        ),
    ]
    for raw in envelopes:
        poller._handle_text(raw)
    assert fills == []
    assert len(poller.seen) == 0


def test_non_numeric_size_ignored_and_not_added_to_seen():
    poller, fills = _make_poller()
    bad_payload = {
        "proxyWallet": CHECKSUM,
        "transactionHash": "0xabc",
        "asset": "123",
        "side": "BUY",
        "size": "nope",
        "price": 0.42,
        "slug": "some-market",
        "outcome": "Yes",
        "title": "T",
    }
    poller._handle_text(
        json.dumps(
            {
                "topic": "activity",
                "type": "trades",
                "timestamp": 1727540000000,
                "payload": bad_payload,
            }
        )
    )
    key = _full_row_key(bad_payload)
    assert key not in poller.seen
    assert fills == []
    poller._handle_text(_envelope(CHECKSUM))
    assert len(fills) == 1
    assert _full_row_key(bad_payload) not in poller.seen


def test_duplicate_row_dispatched_once():
    poller, fills = _make_poller()
    raw = _envelope(CHECKSUM)
    poller._handle_text(raw)
    poller._handle_text(raw)
    assert len(fills) == 1


def test_on_fill_exception_is_logged_not_raised(caplog):
    fills: list[TargetFill] = []

    def boom(fill: TargetFill) -> None:
        fills.append(fill)
        raise RuntimeError("handler exploded")

    poller = Poller(_poller_config(), None, {TARGET.lower()}, boom, {})
    with caplog.at_level(logging.ERROR, logger="poller"):
        poller._handle_text(_envelope(CHECKSUM))
    assert len(fills) == 1
    assert "on_fill dispatch raised" in caplog.text


def test_last_event_ms_updated_for_every_message():
    poller, _fills = _make_poller()
    messages = [
        "PING",
        "",
        _envelope(OTHER),
        "{not-json " + TARGET,
        json.dumps([TARGET]),
        _envelope(CHECKSUM, transactionHash="0x1"),
        json.dumps(
            {
                "topic": "comments",
                "type": "trades",
                "timestamp": 1,
                "payload": {"proxyWallet": CHECKSUM},
            }
        ),
    ]
    for raw in messages:
        poller.last_event_ms = 0
        poller._handle_text(raw)
        assert poller.last_event_ms > 0, repr(raw)


def test_wrong_topic_ignored():
    poller, fills = _make_poller()
    raw = json.dumps(
        {
            "topic": "activity",
            "type": "orders",
            "timestamp": 1727540000000,
            "payload": {
                "proxyWallet": CHECKSUM,
                "transactionHash": "0xabc",
                "asset": "123",
                "side": "BUY",
                "size": 10,
                "price": 0.42,
                "slug": "some-market",
            },
        }
    )
    poller._handle_text(raw)
    raw2 = json.dumps(
        {
            "topic": "comments",
            "type": "trades",
            "timestamp": 1727540000000,
            "payload": {
                "proxyWallet": CHECKSUM,
                "transactionHash": "0xdef",
                "asset": "123",
                "side": "BUY",
                "size": 10,
                "price": 0.42,
                "slug": "some-market",
            },
        }
    )
    poller._handle_text(raw2)
    assert fills == []


def test_feed_status_shape():
    poller, _ = _make_poller()
    status = poller.feed_status()
    assert status["id"] == "predictions-ws"
    assert status["label"] == "Predictions feed"
    assert status["connected"] is False
    assert "last_event_ms" in status
    assert status["reconnects"] == 0


def test_silent_watchdog_does_not_trip_on_stale_last_event_ms(monkeypatch):
    asyncio.run(_watchdog_stale(monkeypatch))


async def _watchdog_stale(monkeypatch):
    poller, _ = _make_poller()
    poller.last_event_ms = 0
    poller.config["watchdog"]["silent_timeout_s"] = 10
    stop = asyncio.Event()
    calls = {"n": 0}

    async def wait_for(aw, timeout=None):
        if asyncio.iscoroutine(aw):
            aw.close()
        calls["n"] += 1
        if calls["n"] == 1:
            raise asyncio.TimeoutError
        stop.set()
        return True

    monkeypatch.setattr(
        "app.core.poller.asyncio",
        types.SimpleNamespace(TimeoutError=asyncio.TimeoutError, wait_for=wait_for),
    )
    await poller.silent_watchdog(stop)
    assert poller.last_event_ms != 0
