"""CLOB v2 client — EIP-712 signing, L2 HMAC auth, REST endpoints.

In dry_run mode, place_order() short-circuits and logs [DRY-RUN] WOULD-PLACE
without signing or POSTing.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets as _secrets
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import aiohttp
from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_utils import keccak

from app.core.orders import OrderState
from app.core.portfolio import Collateral
from app.utils.keyed_lock import KeyedLocks


CTF_EXCHANGE_V2 = "0xE111180000d2663C0091e4f400237545B87B996B"
# Neg-risk markets (multi-outcome events) settle through a SEPARATE exchange
# contract. Orders for them MUST be EIP-712 signed with this address as the
# domain verifyingContract — the domain name/version stay identical ("Polymarket
# CTF Exchange" / "2"). Signing a neg-risk order against the standard exchange
# above yields a valid-but-wrong-domain signature → CLOB "invalid signature".
NEG_RISK_CTF_EXCHANGE_V2 = "0xe2222d279d744050d28e00520010520000310F59"
CHAIN_ID = 137
USDC_DECIMALS = 1_000_000

# Signature types
SIG_TYPE_EOA = 0
SIG_TYPE_POLY_PROXY = 1
SIG_TYPE_POLY_GNOSIS_SAFE = 2
SIG_TYPE_POLY_1271 = 3            # deposit wallet (ERC-1271 + ERC-7739)

# Canonical EIP-712 type string for the V2 Order struct. Field order MUST match
# the encoding in _order_struct_hash exactly — it is also reused verbatim inside
# the ERC-7739 TypedDataSign wrapper as the "contents" type description.
ORDER_TYPE_STRING = (
    "Order(uint256 salt,address maker,address signer,uint256 tokenId,"
    "uint256 makerAmount,uint256 takerAmount,uint8 side,uint8 signatureType,"
    "uint256 timestamp,bytes32 metadata,bytes32 builder)"
)

# Side encoding in EIP-712 struct
SIDE_BUY = 0
SIDE_SELL = 1

CLOB_API = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

# Cheap endpoints hit periodically so the pooled TLS connections to each host
# stay open and POST /order / Gamma lookups never pay a fresh handshake.
CLOB_WARM_URL = f"{CLOB_API}/time"
GAMMA_WARM_URL = f"{GAMMA_API}/markets?limit=1"
KEEP_WARM_INTERVAL_S = 10.0

log = logging.getLogger("clob")


@dataclass
class OrderSpec:
    """Sized, priced order ready for CLOB submission."""
    asset_id: str            # token_id (numeric string)
    side: str                # "BUY" (entry) or "SELL" (mirror exit)
    size: float              # shares (float, will be floored to 2 dec)
    price: float             # limit price (rounded to tick already)
    order_type: str          # "FAK" (taker) or "GTC" (maker)
    market_slug: str         # for Gamma endDate lookup post-place
    target_price: float      # original target fill price (for tick inference if needed)
    neg_risk: bool = False   # neg-risk market → sign against NegRisk CTF Exchange domain


RESTING_STATUSES = {"live", "delayed"}


@dataclass
class OrderResult:
    """Result of place_order — fields available in dry_run + real.

    `filled_shares` / `filled_usd` are what ACTUALLY executed at placement
    (a FAK may fill partially or not at all; a GTC may rest unfilled).
    """
    success: bool
    order_id: Optional[str] = None
    status: Optional[str] = None          # "matched", "live", "unmatched", "delayed"
    filled_shares: float = 0.0
    filled_usd: float = 0.0
    error: Optional[str] = None
    dry_run: bool = False
    posted_at_ms: Optional[int] = None    # set by the caller around the POST
    latency_ms: Optional[int] = None      # target fill → our POST done

    @property
    def is_resting(self) -> bool:
        """Accepted but not final: remainder may still fill (track + cancel)."""
        return self.success and (self.status or "").lower() in RESTING_STATUSES


@dataclass
class MarketMeta:
    """Per-market CLOB parameters needed before signing/pricing an order.

    Sourced once from Gamma (/markets?slug=) and cached for the bot's lifetime —
    these never change for a given market.
    """
    neg_risk: bool = False            # → which exchange domain to sign against
    tick: Optional[float] = None      # real price increment (e.g. 0.01); None = unknown
    end_date_ms: Optional[int] = None # market close (for position expiry)


# ──────────────────────────────────────────────────────────────────────────
# Math helpers (ported from Rust eip712.rs:50-70)
# ──────────────────────────────────────────────────────────────────────────


def to_usdc_units(x: float) -> int:
    """Convert USD float to mikro-USDC (×1e6) integer."""
    return int(round(x * USDC_DECIMALS))


def _parse_amount(v: object) -> float:
    """Parse a CLOB response amount (decimal string/number) to float; 0.0 if absent/invalid."""
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_fill_amount(v: object, upper_bound: float) -> float:
    """Filled amount from POST /order. Live responses use decimal token units
    ("1.655735"); the spec also documents 6-decimal fixed-math integers
    ("1655735"). An integer string far above what the order could possibly
    fill is therefore micro-units. Result is clamped to `upper_bound`."""
    amount = _parse_amount(v)
    if amount > 0 and isinstance(v, str) and "." not in v and upper_bound > 0 and amount > upper_bound * 100:
        amount /= USDC_DECIMALS
    return min(amount, upper_bound) if upper_bound > 0 else amount


FAK_NO_MATCH_MARKER = "no orders found to match"


def _reject_reason(http_status: int, raw: str) -> str:
    """Human-readable rejection: the `error` field of a JSON body when present;
    a FAK that matched nothing is reported as such (not as an API error)."""
    message = raw
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            message = str(parsed.get("error") or parsed.get("errorMsg") or raw)
    except (TypeError, ValueError):
        pass
    if FAK_NO_MATCH_MARKER in message.lower():
        return "not filled — no liquidity within the limit price"
    return message[:200] if http_status == 200 else f"{http_status}: {message[:200]}"


def _order_status_key(status: object) -> str:
    """Normalize CLOB order statuses: "LIVE" / "ORDER_STATUS_LIVE" / "live" → "live"."""
    return str(status or "").lower().removeprefix("order_status_")


def round_to(x: float, decimals: int) -> float:
    factor = 10 ** decimals
    return round(x * factor) / factor


def floor_to(x: float, decimals: int) -> float:
    factor = 10 ** decimals
    return int(x * factor) / factor


def get_order_amounts(side: int, size: float, price: float, is_market: bool = False) -> tuple[int, int]:
    """
    Returns (maker_amount, taker_amount) in mikro-USDC units.

    Polymarket CLOB V2 decimal-accuracy rules differ by order kind:
      Market BUY (FAK):  maker=USDC max 2 dec, taker=shares max 4 dec
      Limit  BUY (GTC):  taker=shares max 2 dec, maker=USDC max 4 dec
      SELL (either):     maker=shares max 2 dec, taker=USDC max 4 dec

    Violating these yields HTTP 400 "invalid amounts ... max accuracy of N decimals".
    """
    if side == SIDE_BUY:
        if is_market:
            # Market buy: USDC (maker) must be ≤2 dec, shares (taker) ≤4 dec.
            taker = round_to(size, 4)
            maker = round_to(taker * price, 2)
        else:
            # Limit buy: shares (taker) ≤2 dec, USDC (maker) ≤4 dec.
            taker = floor_to(size, 2)
            maker = round_to(taker * price, 4)
        maker_u, taker_u = to_usdc_units(maker), to_usdc_units(taker)
        # Implied price = maker/taker must be strictly < 1 (PM rejects price ≥ 1
        # with "invalid price"). At prices near 1, USDC rounding (2-dec for market,
        # 4-dec for limit) can push maker up to == taker → implied 1.0. Nudge maker
        # down one valid unit so the order stays valid (we bid a hair less).
        if price < 1.0 and taker_u > 0 and maker_u >= taker_u:
            step = 10000 if is_market else 100  # 0.01 vs 0.0001 USDC in micro-units
            maker_u = max(0, taker_u - step)
        return maker_u, taker_u
    else:
        # SELL: shares (maker) ≤2 dec, USDC (taker) ≤4 dec.
        maker = floor_to(size, 2)
        taker = round_to(maker * price, 4)
        return to_usdc_units(maker), to_usdc_units(taker)


# ──────────────────────────────────────────────────────────────────────────
# EIP-712 v2 hashing + signature
#
# Everything except the Order struct is constant, so type hashes and domain
# separators are computed once at import. Per order we only abi-encode the
# 11 fixed-width Order fields and keccak them — equivalent to
# eth_account.messages.encode_typed_data, without its per-call schema parsing.
# ──────────────────────────────────────────────────────────────────────────

EXCHANGE_DOMAIN_NAME = "Polymarket CTF Exchange"
EXCHANGE_DOMAIN_VERSION = "2"
ZERO_BYTES32 = bytes(32)
ORDER_METADATA = "0x" + ZERO_BYTES32.hex()
ORDER_BUILDER = "0x" + ZERO_BYTES32.hex()

EIP712_DOMAIN_TYPEHASH = keccak(
    b"EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
)
ORDER_TYPEHASH = keccak(ORDER_TYPE_STRING.encode())


def _u256(x: int) -> bytes:
    return x.to_bytes(32, "big")


def _address_word(address: str) -> bytes:
    """ABI-encode an address as a left-zero-padded 32-byte word."""
    return bytes(12) + bytes.fromhex(address.lower().removeprefix("0x"))


def _domain_separator(verifying_contract: str) -> bytes:
    return keccak(
        EIP712_DOMAIN_TYPEHASH
        + keccak(EXCHANGE_DOMAIN_NAME.encode())
        + keccak(EXCHANGE_DOMAIN_VERSION.encode())
        + _u256(CHAIN_ID)
        + _address_word(verifying_contract)
    )


# Keyed by neg_risk: neg-risk markets sign against the NegRisk exchange domain.
DOMAIN_SEPARATORS = {
    False: _domain_separator(CTF_EXCHANGE_V2),
    True: _domain_separator(NEG_RISK_CTF_EXCHANGE_V2),
}


def _order_struct_hash(
    salt: int,
    maker: str,
    signer: str,
    token_id: int,
    maker_amount: int,
    taker_amount: int,
    side: int,
    signature_type: int,
    timestamp_ms: int,
) -> bytes:
    """hashStruct(Order). Field order MUST match ORDER_TYPE_STRING."""
    return keccak(b"".join((
        ORDER_TYPEHASH,
        _u256(salt),
        _address_word(maker),
        _address_word(signer),
        _u256(token_id),
        _u256(maker_amount),
        _u256(taker_amount),
        _u256(side),
        _u256(signature_type),
        _u256(timestamp_ms),
        ZERO_BYTES32,   # metadata
        ZERO_BYTES32,   # builder
    )))


def _eip712_digest(domain_separator: bytes, struct_hash: bytes) -> bytes:
    return keccak(b"\x19\x01" + domain_separator + struct_hash)


# ERC-7739 TypedDataSign constants (deposit-wallet domain is fixed per wallet
# except for its address, which is the only per-order input below).
ERC7739_TYPEHASH = keccak(
    (
        "TypedDataSign(Order contents,string name,string version,uint256 chainId,"
        "address verifyingContract,bytes32 salt)" + ORDER_TYPE_STRING
    ).encode()
)
DEPOSIT_WALLET_NAME_HASH = keccak(b"DepositWallet")
DEPOSIT_WALLET_VERSION_HASH = keccak(b"1")


def _erc7739_signing_hash(
    order_struct_hash: bytes,
    deposit_wallet: str,
    app_domain_sep: bytes,
) -> bytes:
    """
    ERC-7739 final hash that the owner EOA signs with plain ECDSA.

      finalHash = keccak256(0x1901
                    ‖ APP_DOMAIN_SEPARATOR              (CTF Exchange V2 domain)
                    ‖ hashStruct(TypedDataSign{
                          contents          = hashStruct(Order),
                          name              = "DepositWallet",
                          version           = "1",
                          chainId           = 137,
                          verifyingContract = depositWallet,
                          salt              = bytes32(0),
                      }))

    `order_struct_hash` is hashStruct(Order) (the "contents"); `app_domain_sep`
    is the CTF Exchange V2 domain separator.
    """
    typed_data_struct_hash = keccak(b"".join((
        ERC7739_TYPEHASH,
        order_struct_hash,
        DEPOSIT_WALLET_NAME_HASH,
        DEPOSIT_WALLET_VERSION_HASH,
        _u256(CHAIN_ID),
        _address_word(deposit_wallet),
        ZERO_BYTES32,   # salt
    )))
    return _eip712_digest(app_domain_sep, typed_data_struct_hash)


def _wrap_erc7739_signature(
    ecdsa_sig: bytes,
    app_domain_sep: bytes,
    order_struct_hash: bytes,
) -> bytes:
    """
    ERC-7739 TypedDataSign wire signature (implicit mode):

      originalSignature (65) ‖ APP_DOMAIN_SEPARATOR (32) ‖ contents (32)
        ‖ contentsDescription (variable) ‖ uint16(len(contentsDescription)) BE

    For Polymarket's Order type this is 65+32+32+186+2 = 317 bytes → 636-char hex.
    """
    desc = ORDER_TYPE_STRING.encode()
    return ecdsa_sig + app_domain_sep + order_struct_hash + desc + len(desc).to_bytes(2, "big")


def sign_order(
    account: LocalAccount,
    funder: str,
    token_id: str,
    price: float,
    size: float,
    is_buy: bool,
    api_key: str,
    order_type: str,
    signature_type: object = "auto",
    neg_risk: bool = False,
) -> dict:
    """
    Build EIP-712 v2 typed data, sign, return full body for POST /order.

    `funder` = wallet address that holds funds / is the maker on PM
    `account` = owner EOA that signs orders (see load_account)
    `signature_type` selects how the CLOB validates the signature:
      "auto" → EOA if funder == signer EOA, else POLY_GNOSIS_SAFE (legacy default)
      2      → force POLY_GNOSIS_SAFE (funder = Safe, key = owner EOA)
      3      → POLY_1271 deposit wallet (funder = deposit wallet = maker = signer;
               key = owner EOA; signature is ERC-7739 wrapped)
    `neg_risk` picks the EIP-712 domain verifyingContract: the NegRisk CTF
      Exchange for neg-risk markets, else the standard CTF Exchange. The ERC-7739
      path wraps the same domain separator as its APP_DOMAIN_SEPARATOR.
    """
    signer_address = account.address
    maker_address = funder

    side = SIDE_BUY if is_buy else SIDE_SELL
    # FAK = marketable/immediate (Polymarket treats it as a market order, which
    # has different decimal-accuracy rules than a resting GTC limit order).
    is_market = order_type == "FAK"
    maker_amount, taker_amount = get_order_amounts(side, size, price, is_market)

    salt = _secrets.randbelow(2**32)
    ts_ms = int(time.time() * 1000)

    # Resolve sig type and which addresses fill the maker/signer struct fields.
    #   POLY_1271:   maker = signer = funder (deposit wallet); EOA only signs off-chain.
    #   GNOSIS_SAFE: maker = funder (Safe), signer = owner EOA.
    #   auto:        EOA when funder == signer EOA, else GNOSIS_SAFE (legacy behaviour).
    sig_sel = str(signature_type).lower()
    if sig_sel == "3" or signature_type == 3:
        sig_type = SIG_TYPE_POLY_1271
        order_signer = maker_address
    elif sig_sel == "2" or signature_type == 2:
        sig_type = SIG_TYPE_POLY_GNOSIS_SAFE
        order_signer = signer_address
    elif sig_sel == "0" or signature_type == 0:
        sig_type = SIG_TYPE_EOA
        order_signer = signer_address
    else:  # "auto"
        sig_type = (
            SIG_TYPE_EOA if maker_address.lower() == signer_address.lower()
            else SIG_TYPE_POLY_GNOSIS_SAFE
        )
        order_signer = signer_address

    order_struct_hash = _order_struct_hash(
        salt=salt,
        maker=maker_address,
        signer=order_signer,
        token_id=int(token_id),
        maker_amount=maker_amount,
        taker_amount=taker_amount,
        side=side,
        signature_type=sig_type,
        timestamp_ms=ts_ms,
    )
    domain_sep = DOMAIN_SEPARATORS[bool(neg_risk)]

    # Sign the raw 32-byte hash (NOT a wrapped message). v is 27/28 as OZ expects.
    if sig_type == SIG_TYPE_POLY_1271:
        final_hash = _erc7739_signing_hash(order_struct_hash, maker_address, domain_sep)
        raw_sig = bytes(account.unsafe_sign_hash(final_hash).signature)
        signature = "0x" + _wrap_erc7739_signature(raw_sig, domain_sep, order_struct_hash).hex()
    else:
        # Plain EIP-712 ECDSA over the order digest (EOA / POLY_GNOSIS_SAFE).
        digest = _eip712_digest(domain_sep, order_struct_hash)
        signature = "0x" + bytes(account.unsafe_sign_hash(digest).signature).hex()

    side_label = "BUY" if is_buy else "SELL"

    return {
        "order": {
            "salt": salt,
            "maker": maker_address,
            "signer": order_signer,
            "tokenId": token_id,
            "makerAmount": str(maker_amount),
            "takerAmount": str(taker_amount),
            "side": side_label,
            "expiration": "0",
            "signatureType": sig_type,
            "timestamp": str(ts_ms),
            "metadata": ORDER_METADATA,
            "builder": ORDER_BUILDER,
            "signature": signature,
        },
        "owner": api_key,
        "orderType": order_type,
    }


# ──────────────────────────────────────────────────────────────────────────
# L2 HMAC auth headers
# ──────────────────────────────────────────────────────────────────────────


def load_account(private_key: str) -> LocalAccount:
    """Build the signing account once; accepts "0x…", "0X…" or bare hex."""
    return Account.from_key("0x" + private_key.lower().removeprefix("0x"))


def decode_secret(secret: str) -> bytes:
    """API secret is URL-safe base64; try URL-safe first, fall back to std."""
    pad = "=" * ((4 - len(secret) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(secret + pad)
    except Exception:
        return base64.b64decode(secret + pad)


def l2_headers(
    api_key: str,
    secret_bytes: bytes,
    passphrase: str,
    address: str,
    method: str,
    path: str,
    body: str,
) -> dict:
    """L2 auth — HMAC-SHA256 of (ts + METHOD + path + body) with the decoded
    API secret (see decode_secret)."""
    ts = str(int(time.time()))
    msg = f"{ts}{method.upper()}{path}{body}".encode()
    sig = hmac.new(secret_bytes, msg, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode()
    return {
        "POLY_API_KEY": api_key,
        "POLY_SIGNATURE": sig_b64,
        "POLY_TIMESTAMP": ts,
        "POLY_PASSPHRASE": passphrase,
        "POLY_ADDRESS": address,
    }


# ──────────────────────────────────────────────────────────────────────────
# Latency tracing (measurement only)
# ──────────────────────────────────────────────────────────────────────────


def make_trace_config() -> aiohttp.TraceConfig:
    """aiohttp TraceConfig that splits a request into:

      conn_setup — request_start → connection ready (DNS+TCP+TLS for a NEW
                   connection; ~0 if the keep-alive connection was reused)
      ttfb       — connection ready → first response byte (outbound transit +
                   server matching + first byte back) — network/infra bound
      req_total  — request_start → response complete

    Only requests passing trace_request_ctx={"trace": True} are recorded; the
    hooks write timings back into that same dict so the caller can read them.
    Attach via aiohttp.ClientSession(trace_configs=[make_trace_config()]).
    """
    def _rc(ctx):
        rc = getattr(ctx, "trace_request_ctx", None)
        return rc if isinstance(rc, dict) and rc.get("trace") else None

    async def on_request_start(session, ctx, params):
        rc = _rc(ctx)
        if rc is not None:
            rc["t0"] = time.perf_counter()
            rc["reused"] = False

    async def on_connection_reuseconn(session, ctx, params):
        rc = _rc(ctx)
        if rc is not None:
            rc["reused"] = True
            rc["conn_ready"] = time.perf_counter()

    async def on_connection_create_end(session, ctx, params):
        rc = _rc(ctx)
        if rc is not None:
            rc["conn_ready"] = time.perf_counter()

    async def on_response_chunk_received(session, ctx, params):
        rc = _rc(ctx)
        if rc is not None and "ttfb" not in rc:
            rc["ttfb"] = time.perf_counter()

    async def on_request_end(session, ctx, params):
        rc = _rc(ctx)
        if rc is not None:
            rc["end"] = time.perf_counter()

    tc = aiohttp.TraceConfig()
    tc.on_request_start.append(on_request_start)
    tc.on_connection_reuseconn.append(on_connection_reuseconn)
    tc.on_connection_create_end.append(on_connection_create_end)
    tc.on_response_chunk_received.append(on_response_chunk_received)
    tc.on_request_end.append(on_request_end)
    return tc


# ──────────────────────────────────────────────────────────────────────────
# Client
# ──────────────────────────────────────────────────────────────────────────


class ClobClient:
    """
    REST client for CLOB v2 + Gamma API.

    In dry_run mode, place_order() returns simulated success without signing
    or making network calls (except Gamma for endDate, which is always real).
    """

    def __init__(self, secrets: Optional[dict], dry_run: bool, session: aiohttp.ClientSession):
        self.dry_run = dry_run
        self.session = session
        # Per-market metadata cache (neg_risk / tick / endDate), keyed by slug.
        # Populated lazily before the first order in a market; reused thereafter.
        self._meta_cache: dict[str, MarketMeta] = {}
        self._meta_locks = KeyedLocks()

        if dry_run:
            self.account: Optional[LocalAccount] = None
            self.funder = None
            self.signer_address = None
            self.api_key = None
            self.api_secret_bytes: Optional[bytes] = None
            self.passphrase = None
            self.signature_type = "auto"
            log.info("ClobClient init: DRY-RUN — no signing")
            return

        if not secrets:
            raise RuntimeError("real mode requires polymarket: section in config")
        self.account = load_account(secrets["private_key"])
        self.funder = secrets["wallet_address"]
        self.api_key = secrets["api_key"]
        self.api_secret_bytes = decode_secret(secrets["api_secret"])
        self.passphrase = secrets["passphrase"]
        # How the CLOB validates order signatures. "auto" preserves legacy
        # behaviour (EOA / Gnosis Safe); 3 = POLY_1271 deposit wallet.
        self.signature_type = secrets.get("signature_type", "auto")
        # The signer EOA OWNS the API key (key creation always signs L1 with the
        # EOA), so it must be sent as POLY_ADDRESS in L2 auth — NOT the
        # funder/deposit wallet.
        self.signer_address = self.account.address
        log.info(
            f"ClobClient init: REAL — signer={self.signer_address[:10]}… "
            f"funder={self.funder[:10]}… sig_type={self.signature_type}"
        )

    async def place_order(self, spec: OrderSpec) -> OrderResult:
        # NOTE: success path is intentionally silent — trader.py emits a single
        # consolidated [COPY] line that combines order spec + latencies.
        # We log only on failure ([REJECT] / [ERROR]).
        if self.dry_run:
            return OrderResult(
                success=True,
                order_id=f"dry_{spec.asset_id[:8]}_{int(time.time() * 1000)}",
                status="matched",
                filled_shares=spec.size,
                filled_usd=spec.size * spec.price,
                dry_run=True,
            )

        is_buy = (spec.side == "BUY")
        # ECDSA signing is CPU-bound. Run it in a thread so it never blocks the
        # event loop / WS receive loop (keeps detect latency low).
        _t_sign0 = time.perf_counter()
        body_dict = await asyncio.to_thread(
            sign_order,
            account=self.account,
            funder=self.funder,
            token_id=spec.asset_id,
            price=spec.price,
            size=spec.size,
            is_buy=is_buy,
            api_key=self.api_key,
            order_type=spec.order_type,
            signature_type=self.signature_type,
            neg_risk=spec.neg_risk,
        )
        sign_ms = (time.perf_counter() - _t_sign0) * 1000
        body_str = json.dumps(body_dict)
        path = "/order"
        # POLY_ADDRESS must be the API key owner (the signer EOA), not the proxy
        # funder — otherwise PM rejects with "the order signer address has to be
        # the address of the API KEY".
        headers = l2_headers(
            self.api_key, self.api_secret_bytes, self.passphrase,
            self.signer_address, "POST", path, body_str,
        )
        headers["Content-Type"] = "application/json"

        trace_ctx: dict = {"trace": True}
        try:
            async with self.session.post(
                CLOB_API + path, data=body_str, headers=headers,
                trace_request_ctx=trace_ctx,
            ) as resp:
                text = await resp.text()
                self._log_latency(sign_ms, trace_ctx)
                if resp.status >= 400:
                    log.error(f"[REJECT] POST /order {resp.status}: {text[:200]}")
                    return OrderResult(success=False, error=_reject_reason(resp.status, text))
                data = json.loads(text)

            if data.get("success") is False:
                error = _reject_reason(200, data.get("errorMsg") or "order rejected")
                log.error(f"[REJECT] POST /order: {error}")
                return OrderResult(success=False, status="unmatched", error=error)
            return self._order_result(spec, data)
        except asyncio.TimeoutError:
            log.error("[ERROR] POST /order timeout")
            return OrderResult(success=False, error="timeout")
        except Exception as e:
            log.error(f"[ERROR] POST /order exception: {e}")
            return OrderResult(success=False, error=str(e))

    @staticmethod
    def _order_result(spec: OrderSpec, data: dict) -> OrderResult:
        """makingAmount is what we gave, takingAmount what we got:
        BUY → making = USDC paid, taking = shares; SELL → making = shares, taking = USDC."""
        max_shares = spec.size
        max_usd = spec.size * max(spec.price, spec.target_price, 1e-9) * 1.5
        making, taking = data.get("makingAmount"), data.get("takingAmount")
        if spec.side == "BUY":
            shares, usd = _parse_fill_amount(taking, max_shares), _parse_fill_amount(making, max_usd)
        else:
            shares, usd = _parse_fill_amount(making, max_shares), _parse_fill_amount(taking, max_usd)
        return OrderResult(
            success=True,
            order_id=data.get("orderID") or data.get("order_id"),
            status=_order_status_key(data.get("status") or "unknown"),
            filled_shares=shares,
            filled_usd=usd,
        )

    # ── Authenticated reads / cancels (L2) ──

    async def _l2_request(self, method: str, path: str, body: Optional[object] = None,
                          params: Optional[dict] = None) -> tuple[int, object]:
        """Signed CLOB request. The HMAC covers the path WITHOUT query string
        plus the exact serialized body."""
        body_str = json.dumps(body, separators=(",", ":")) if body is not None else ""
        headers = l2_headers(
            self.api_key, self.api_secret_bytes, self.passphrase,
            self.signer_address, method, path, body_str,
        )
        if body is not None:
            headers["Content-Type"] = "application/json"
        async with self.session.request(
            method, CLOB_API + path, params=params, data=body_str or None, headers=headers,
        ) as resp:
            text = await resp.text()
            try:
                payload = json.loads(text) if text else None
            except json.JSONDecodeError:
                payload = text
            return resp.status, payload

    async def get_order(self, order_id: str) -> Optional[OrderState]:
        if self.dry_run:
            return None
        status, data = await self._l2_request("GET", f"/data/order/{order_id}")
        if status >= 400 or not isinstance(data, dict):
            log.warning(f"GET /data/order {order_id[:10]}… → {status}: {str(data)[:120]}")
            return None
        return OrderState(
            status=_order_status_key(data.get("status")),
            size_matched=_parse_amount(data.get("size_matched")),
        )

    async def cancel_order(self, order_id: str) -> bool:
        if self.dry_run:
            return True
        status, data = await self._l2_request("DELETE", "/order", body={"orderID": order_id})
        if status >= 400 or not isinstance(data, dict):
            log.warning(f"DELETE /order {order_id[:10]}… → {status}: {str(data)[:120]}")
            return False
        not_canceled = data.get("not_canceled") or {}
        if order_id in not_canceled:
            log.info(f"cancel {order_id[:10]}… refused: {not_canceled[order_id]}")
            return False
        return order_id in (data.get("canceled") or [])

    async def get_collateral(self) -> Optional[Collateral]:
        """pUSD collateral balance + best allowance to the exchange contracts."""
        if self.dry_run:
            return None
        params = {"asset_type": "COLLATERAL"}
        sig_type = self._balance_signature_type()
        if sig_type is not None:
            params["signature_type"] = str(sig_type)
        status, data = await self._l2_request("GET", "/balance-allowance", params=params)
        if status >= 400 or not isinstance(data, dict):
            log.warning(f"GET /balance-allowance → {status}: {str(data)[:120]}")
            return None
        balance = _parse_amount(data.get("balance")) / USDC_DECIMALS
        allowances = data.get("allowances") or {}
        allowance = max((_parse_amount(v) for v in allowances.values()), default=None)
        return Collateral(
            balance_usd=balance,
            allowance_usd=allowance / USDC_DECIMALS if allowance is not None else None,
        )

    def _balance_signature_type(self) -> Optional[int]:
        sel = str(self.signature_type).lower()
        if sel in ("0", "1", "2", "3"):
            return int(sel)
        if self.funder and self.signer_address:
            return SIG_TYPE_EOA if self.funder.lower() == self.signer_address.lower() else SIG_TYPE_POLY_GNOSIS_SAFE
        return None

    @staticmethod
    def _log_latency(sign_ms: float, trace_ctx: dict) -> None:
        """Emit the per-order latency breakdown gathered by make_trace_config().

        conn_setup is the keep-alive/TLS cost (should be ~0 and reused=True once
        warm); ttfb is the network-distance + server-matching cost (infra-bound).
        """
        t0 = trace_ctx.get("t0")
        if t0 is None:
            return
        conn_ready = trace_ctx.get("conn_ready", t0)
        ttfb = trace_ctx.get("ttfb")
        end = trace_ctx.get("end")
        conn_ms = (conn_ready - t0) * 1000
        ttfb_ms = (ttfb - conn_ready) * 1000 if ttfb is not None else -1.0
        total_ms = (end - t0) * 1000 if end is not None else -1.0
        log.info(
            f"[LATENCY] sign={sign_ms:.1f}ms conn_setup={conn_ms:.1f}ms "
            f"(reused={trace_ctx.get('reused', False)}) ttfb={ttfb_ms:.1f}ms "
            f"req_total={total_ms:.1f}ms"
        )

    def has_market_meta(self, slug: str) -> bool:
        return slug in self._meta_cache

    async def get_market_meta(self, slug: str) -> MarketMeta:
        """
        Return cached per-market metadata (neg_risk / tick / endDate), fetching
        from Gamma on first use. Result is cached for the bot's lifetime so the
        latency cost is paid once per market, not per order. A failed fetch
        returns a transient default (NOT cached) so the next order retries.

        Concurrency: a per-slug lock collapses simultaneous first-fills for the
        same market into a single fetch.
        """
        if not slug:
            return MarketMeta()
        cached = self._meta_cache.get(slug)
        if cached is not None:
            return cached
        async with self._meta_locks.hold(slug):
            cached = self._meta_cache.get(slug)
            if cached is not None:
                return cached
            meta = await self._fetch_market_meta(slug)
            if meta is not None:
                self._meta_cache[slug] = meta
                return meta
            return MarketMeta()

    async def _fetch_market_meta(self, slug: str) -> Optional[MarketMeta]:
        """Fetch neg_risk + tick + endDate from Gamma in one call. Returns None on failure (caller substitutes a transient default).
        Gamma is public (no auth), separate rate-limit bucket from CLOB/Data."""
        url = f"{GAMMA_API}/markets?slug={slug}"
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status >= 400:
                    log.warning(f"Gamma /markets {resp.status} for slug={slug}")
                    return None
                data = await resp.json()
        except Exception as e:
            log.warning(f"Gamma fetch failed for {slug}: {e}")
            return None
        markets = data if isinstance(data, list) else []
        if not markets:
            return None
        # Find exact slug match; fall back to first entry
        market = next((m for m in markets if m.get("slug") == slug), markets[0])
        neg_risk = bool(market.get("negRisk", False))
        tick = _parse_amount(market.get("orderPriceMinTickSize")) or None
        end_ms: Optional[int] = None
        end_date_str = market.get("endDate") or market.get("end_date_iso")
        if end_date_str:
            try:
                dt = datetime.fromisoformat(str(end_date_str).replace("Z", "+00:00"))
                end_ms = int(dt.timestamp() * 1000)
            except ValueError:
                end_ms = None
        return MarketMeta(neg_risk=neg_risk, tick=tick, end_date_ms=end_ms)

    async def fetch_market_end_date(self, slug: str) -> Optional[int]:
        """endDate as unix ms (or None) — thin wrapper over the cached meta so the
        post-place expiry enrichment reuses the pre-place fetch (no extra call)."""
        meta = await self.get_market_meta(slug)
        return meta.end_date_ms

    # ── Connection warming ──

    async def keep_warm(self, shutdown: asyncio.Event, interval_s: float = KEEP_WARM_INTERVAL_S) -> None:
        """Keep pooled keep-alive connections to CLOB (real mode) and Gamma open
        so order POSTs and first-in-market lookups skip DNS + TCP + TLS setup.
        Runs immediately at startup, then every `interval_s`."""
        urls = [GAMMA_WARM_URL] if self.dry_run else [CLOB_WARM_URL, GAMMA_WARM_URL]
        while not shutdown.is_set():
            await asyncio.gather(*(self._warm(url) for url in urls))
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=interval_s)
                return
            except asyncio.TimeoutError:
                pass

    async def _warm(self, url: str) -> None:
        try:
            async with self.session.get(url) as resp:
                await resp.read()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.debug(f"keep-warm {url} failed: {e}")
