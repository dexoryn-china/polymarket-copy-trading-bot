"""Independent EIP-712 / ERC-7739 checks against eth_account.encode_typed_data."""

from __future__ import annotations

import base64
import hashlib
import hmac
import random

from eth_abi import encode
from eth_account import Account
from eth_account.messages import _hash_eip191_message, encode_typed_data
from eth_utils import keccak, to_checksum_address

from app.pm import clob as clob_mod
from app.pm.clob import (
    CTF_EXCHANGE_V2,
    DOMAIN_SEPARATORS,
    NEG_RISK_CTF_EXCHANGE_V2,
    _order_struct_hash,
    decode_secret,
    l2_headers,
    load_account,
    sign_order,
)


# Spec copy of the V2 Order type (independent of app.pm.clob.ORDER_TYPE_STRING).
SPEC_ORDER_TYPE = (
    "Order(uint256 salt,address maker,address signer,uint256 tokenId,"
    "uint256 makerAmount,uint256 takerAmount,uint8 side,uint8 signatureType,"
    "uint256 timestamp,bytes32 metadata,bytes32 builder)"
)
TYPED_DATA_SIGN_PREFIX = (
    "TypedDataSign(Order contents,string name,string version,uint256 chainId,"
    "address verifyingContract,bytes32 salt)"
)

ORDER_TYPES = {
    "Order": [
        {"name": "salt", "type": "uint256"},
        {"name": "maker", "type": "address"},
        {"name": "signer", "type": "address"},
        {"name": "tokenId", "type": "uint256"},
        {"name": "makerAmount", "type": "uint256"},
        {"name": "takerAmount", "type": "uint256"},
        {"name": "side", "type": "uint8"},
        {"name": "signatureType", "type": "uint8"},
        {"name": "timestamp", "type": "uint256"},
        {"name": "metadata", "type": "bytes32"},
        {"name": "builder", "type": "bytes32"},
    ]
}

SIDE = {"BUY": 0, "SELL": 1}


def _exchange_domain(neg_risk: bool) -> dict:
    return {
        "name": "Polymarket CTF Exchange",
        "version": "2",
        "chainId": 137,
        "verifyingContract": NEG_RISK_CTF_EXCHANGE_V2 if neg_risk else CTF_EXCHANGE_V2,
    }


def _message_from_order(order: dict) -> dict:
    return {
        "salt": int(order["salt"]),
        "maker": order["maker"],
        "signer": order["signer"],
        "tokenId": int(order["tokenId"]),
        "makerAmount": int(order["makerAmount"]),
        "takerAmount": int(order["takerAmount"]),
        "side": SIDE[order["side"]],
        "signatureType": int(order["signatureType"]),
        "timestamp": int(order["timestamp"]),
        "metadata": bytes(32),
        "builder": bytes(32),
    }


def _reference_signable(neg_risk: bool, order: dict):
    return encode_typed_data(
        _exchange_domain(neg_risk),
        ORDER_TYPES,
        _message_from_order(order),
    )


def _erc7739_final_hash(header: bytes, body: bytes, deposit_wallet: str) -> bytes:
    """Independent TypedDataSign hash: keccak(abi.encode(typehash, fields))."""
    typehash = keccak((TYPED_DATA_SIGN_PREFIX + SPEC_ORDER_TYPE).encode())
    packed = encode(
        ["bytes32", "bytes32", "bytes32", "bytes32", "uint256", "address", "bytes32"],
        [
            typehash,
            body,
            keccak(b"DepositWallet"),
            keccak(b"1"),
            137,
            deposit_wallet,
            bytes(32),
        ],
    )
    typed_data_struct_hash = keccak(packed)
    return keccak(b"\x19\x01" + header + typed_data_struct_hash)


def _rand_address(rng: random.Random) -> str:
    raw = "0x" + rng.randbytes(20).hex()
    return to_checksum_address(raw) if rng.choice((True, False)) else raw


def test_sign_order_matches_encode_typed_data(monkeypatch):
    rng = random.Random(20260928)
    account = load_account(Account.create().key.hex())

    cases = 0
    for neg_risk in (False, True):
        for is_buy in (True, False):
            for order_type in ("FAK", "GTC"):
                for signature_type in ("auto", 0, 2, 3):
                    for _extra in range(2):
                        salt = rng.randrange(2**32)
                        ts_s = rng.randrange(1_700_000_000, 1_800_000_000)
                        monkeypatch.setattr(
                            clob_mod._secrets, "randbelow", lambda n, s=salt: s
                        )
                        monkeypatch.setattr(
                            clob_mod.time, "time", lambda t=float(ts_s): t
                        )

                        if signature_type == "auto" and rng.random() < 0.5:
                            funder = account.address
                        else:
                            funder = _rand_address(rng)

                        if rng.random() < 0.3:
                            token_id = str(rng.randrange(2**200, 2**255))
                        else:
                            token_id = str(rng.randrange(1, 10**12))

                        price = rng.uniform(0.05, 0.95)
                        size = rng.uniform(1.0, 80.0)

                        body = sign_order(
                            account,
                            funder,
                            token_id,
                            price,
                            size,
                            is_buy,
                            api_key="test-api-key",
                            order_type=order_type,
                            signature_type=signature_type,
                            neg_risk=neg_risk,
                        )
                        order = body["order"]
                        assert order["salt"] == salt
                        assert int(order["timestamp"]) == ts_s * 1000

                        signable = _reference_signable(neg_risk, order)
                        msg = _message_from_order(order)

                        assert DOMAIN_SEPARATORS[neg_risk] == bytes(signable.header)
                        struct_hash = _order_struct_hash(
                            msg["salt"],
                            msg["maker"],
                            msg["signer"],
                            msg["tokenId"],
                            msg["makerAmount"],
                            msg["takerAmount"],
                            msg["side"],
                            msg["signatureType"],
                            msg["timestamp"],
                        )
                        assert struct_hash == bytes(signable.body)

                        sig_hex = order["signature"]
                        sig_type = int(order["signatureType"])
                        if sig_type == 3:
                            _assert_poly1271_wrap(
                                sig_hex, signable, order["maker"], account.address
                            )
                        else:
                            expected = (
                                "0x"
                                + bytes(account.sign_message(signable).signature).hex()
                            )
                            assert sig_hex == expected
                            digest = _hash_eip191_message(signable)
                            recovered = Account._recover_hash(
                                digest, signature=bytes.fromhex(sig_hex[2:])
                            )
                            assert recovered == account.address

                        cases += 1

    assert cases == 64


def _assert_poly1271_wrap(sig_hex: str, signable, deposit_wallet: str, eoa: str) -> None:
    wrapped = bytes.fromhex(sig_hex[2:])
    ecdsa, header, contents, rest = (
        wrapped[:65],
        wrapped[65:97],
        wrapped[97:129],
        wrapped[129:],
    )
    desc, length = rest[:-2], int.from_bytes(rest[-2:], "big")
    assert header == bytes(signable.header)
    assert contents == bytes(signable.body)
    assert desc == SPEC_ORDER_TYPE.encode()
    assert length == len(desc)
    assert len(wrapped) == 65 + 32 + 32 + len(desc) + 2

    final = _erc7739_final_hash(header, contents, deposit_wallet)
    recovered = Account._recover_hash(final, signature=ecdsa)
    assert recovered == eoa


def test_l2_headers_known_hmac(monkeypatch):
    monkeypatch.setattr(clob_mod.time, "time", lambda: 1_727_540_000)
    secret = b"supersecret-bytes"
    body = '{"hello":"world"}'
    headers = l2_headers(
        "api-key-1",
        secret,
        "passphrase-1",
        "0xabc",
        "POST",
        "/order",
        body,
    )
    ts = "1727540000"
    msg = f"{ts}POST/order{body}".encode()
    expected = base64.urlsafe_b64encode(
        hmac.new(secret, msg, hashlib.sha256).digest()
    ).decode()
    assert headers == {
        "POLY_API_KEY": "api-key-1",
        "POLY_SIGNATURE": expected,
        "POLY_TIMESTAMP": ts,
        "POLY_PASSPHRASE": "passphrase-1",
        "POLY_ADDRESS": "0xabc",
    }


def test_decode_secret_urlsafe_and_missing_padding():
    raw = bytes.fromhex("deadbeefcafebabe0123456789ff")
    padded = base64.urlsafe_b64encode(raw).decode()
    unpadded = padded.rstrip("=")
    assert unpadded != padded
    assert decode_secret(unpadded) == raw
    assert decode_secret(padded) == raw

    # Force the url-safe alphabet (- / _).
    urlsafe_raw = b"\xfb\xef\xff\x00\x11"
    urlsafe = base64.urlsafe_b64encode(urlsafe_raw).decode()
    assert "-" in urlsafe or "_" in urlsafe
    assert decode_secret(urlsafe.rstrip("=")) == urlsafe_raw

    std_raw = b"\xfb\xef>"
    std = base64.b64encode(std_raw).decode()
    assert decode_secret(std.rstrip("=")) == std_raw
