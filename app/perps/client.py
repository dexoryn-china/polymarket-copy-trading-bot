"""Polymarket Perps REST client (https://api.perpetuals.polymarket.com).

Public reads (instruments, tickers, any account's portfolio) need no auth.
Trading uses a delegated *proxy* signer: the Polymarket account key signs an
EIP-712 `CreateProxy` once (≈ weekly), after which every operation is signed
by the proxy key:

    op_hash = keccak256(msgpack(compact_op))
    sig     = EIP-712 Op{data: op_hash, salt, ts}  (domain Polymarket / 1 / 137)

Private reads authenticate with `polymarket-proxy` / `polymarket-secret`
headers. The proxy credentials are created and renewed automatically and kept
in `perps_session.json`.
"""

import asyncio
import json
import logging
import secrets as _secrets
import time
from dataclasses import asdict, dataclass
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from pathlib import Path
from typing import Any, Optional

import aiohttp
import msgpack
import orjson
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_account.signers.local import LocalAccount
from eth_utils import keccak

from app.core.portfolio import Collateral

log = logging.getLogger("perps")

PERPS_API = "https://api.perpetuals.polymarket.com"
CHAIN_ID = 137
DOMAIN = {"name": "Polymarket", "version": "1", "chainId": CHAIN_ID}

SESSION_FILE = "perps_session.json"
SESSION_TTL_MS = 7 * 24 * 3600 * 1000
SESSION_RENEW_BEFORE_MS = 24 * 3600 * 1000
SESSION_CHECK_INTERVAL_S = 3600.0

TICKER_REFRESH_S = 1.0
INSTRUMENT_REFRESH_S = 600.0
IOC_RESOLVE_TIMEOUT_S = 5.0
MAX_SIG_FIGS = 5   # non-integer prices are limited to 5 significant figures

IOC_FINAL_STATUSES = {
    "filled", "ioc_no_fill", "ioc_expired", "stp_cancelled",
    "cancelled", "canceled", "rejected", "expired",
}


class PerpsError(Exception):
    pass


# ── Signing ──

_DOMAIN_TYPEHASH = keccak(b"EIP712Domain(string name,string version,uint256 chainId)")
_OP_TYPEHASH = keccak(b"Op(bytes32 data,uint64 salt,uint64 ts)")
DOMAIN_SEPARATOR = keccak(
    _DOMAIN_TYPEHASH + keccak(b"Polymarket") + keccak(b"1") + CHAIN_ID.to_bytes(32, "big")
)


def op_hash(compact: list) -> bytes:
    """keccak256 of the MessagePack-encoded compact operation."""
    return keccak(msgpack.packb(compact, use_bin_type=True))


def op_digest(data: bytes, salt: int, ts: int) -> bytes:
    struct_hash = keccak(_OP_TYPEHASH + data + salt.to_bytes(32, "big") + ts.to_bytes(32, "big"))
    return keccak(b"\x19\x01" + DOMAIN_SEPARATOR + struct_hash)


def new_salt() -> int:
    # Kept under 2**53 so JSON consumers never lose precision.
    return _secrets.randbelow(2**53)


def sign_op(account: LocalAccount, compact: list, salt: Optional[int] = None,
            ts: Optional[int] = None) -> dict:
    """Return the `{sig, salt, ts}` envelope fields for a signed operation."""
    salt = new_salt() if salt is None else salt
    ts = int(time.time() * 1000) if ts is None else ts
    signed = account.unsafe_sign_hash(op_digest(op_hash(compact), salt, ts))
    return {"sig": "0x" + bytes(signed.signature).hex(), "salt": salt, "ts": ts}


def create_orders_compact(orders: list[dict]) -> list:
    """["createOrders", [[iid, buy, p, qty, tif, po, ro, c, tr], ...]] with
    absent entries omitted — must mirror exactly the JSON args sent."""
    keys = ("iid", "buy", "p", "qty", "tif", "po", "ro", "c", "tr")
    return ["createOrders", [[o[k] for k in keys if o.get(k) is not None] for o in orders]]


def update_leverage_compact(iid: int, lev: int, cross: bool) -> list:
    return ["updateLeverage", [iid, lev, cross]]


# ── Number formatting ──

def fmt_decimal(d: Decimal) -> str:
    s = format(d.normalize(), "f")
    return s if s not in ("-0", "") else "0"


def quantize_qty(qty: float, decimals: int) -> Decimal:
    return Decimal(repr(qty)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN)


def quantize_price(price: float, decimals: int, buy: bool) -> Decimal:
    """Round to the instrument's price decimals and the 5-significant-figure
    rule, rounding toward the mark (buys down, sells up) so the slippage cap
    is never exceeded."""
    d = Decimal(repr(price))
    # d.adjusted() is the exponent of the leading digit: 123.4 → 2, 0.0123 → -2.
    places = max(0, min(decimals, MAX_SIG_FIGS - d.adjusted() - 1))
    return d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN if buy else ROUND_UP)


# ── Models ──

@dataclass(frozen=True)
class Instrument:
    id: int
    symbol: str
    quantity_decimals: int
    price_decimals: int
    price_bounds: float
    min_notional: float
    max_market_notional: float
    max_leverage: int
    isolated_only: bool

    @classmethod
    def from_api(cls, d: dict) -> "Instrument":
        return cls(
            id=int(d["instrument_id"]),
            symbol=str(d.get("symbol") or d["instrument_id"]),
            quantity_decimals=int(d.get("quantity_decimals", 4)),
            price_decimals=int(d.get("price_decimals", 2)),
            price_bounds=float(d.get("price_bounds") or 0.05),
            min_notional=float(d.get("min_notional") or 0),
            max_market_notional=float(d.get("max_market_notional") or 0) or float("inf"),
            max_leverage=int(d.get("max_leverage") or 1),
            isolated_only=bool(d.get("isolated_only", False)),
        )


@dataclass(frozen=True)
class PublicPosition:
    instrument_id: int
    symbol: str
    size: float           # signed: + long, − short
    entry_price: float


@dataclass
class PerpsOrderResult:
    success: bool
    order_id: Optional[int] = None
    status: str = ""
    filled_qty: float = 0.0
    avg_price: Optional[float] = None
    error: Optional[str] = None
    dry_run: bool = False
    posted_at_ms: Optional[int] = None
    latency_ms: Optional[int] = None


@dataclass
class ProxyCredentials:
    owner: str
    proxy: str
    private_key: str
    secret: str
    expires_at_ms: int

    @property
    def needs_renewal(self) -> bool:
        return self.expires_at_ms - int(time.time() * 1000) < SESSION_RENEW_BEFORE_MS


# ── Client ──

class PerpsClient:
    def __init__(self, session: aiohttp.ClientSession, dry_run: bool,
                 owner_private_key: Optional[str] = None, session_file: str = SESSION_FILE) -> None:
        self.session = session
        self.dry_run = dry_run
        self.owner: Optional[LocalAccount] = Account.from_key(owner_private_key) if owner_private_key else None
        self.session_file = Path(session_file)
        self.creds: Optional[ProxyCredentials] = None
        self._proxy: Optional[LocalAccount] = None
        self.instruments: dict[int, Instrument] = {}
        self._marks: dict[int, float] = {}

    # ── HTTP ──

    def _auth_headers(self) -> dict:
        if self.creds is None:
            raise PerpsError("perps trading session not open")
        return {"polymarket-proxy": self.creds.proxy, "polymarket-secret": self.creds.secret}

    async def _request(self, method: str, path: str, *, params: Optional[dict] = None,
                       body: Optional[dict] = None, auth: bool = False) -> Any:
        headers = {"content-type": "application/json"} if body is not None else {}
        if auth:
            headers.update(self._auth_headers())
        data = orjson.dumps(body) if body is not None else None
        async with self.session.request(method, PERPS_API + path, params=params,
                                        data=data, headers=headers) as resp:
            raw = await resp.read()
            try:
                payload = orjson.loads(raw) if raw else None
            except orjson.JSONDecodeError:
                payload = raw.decode(errors="replace")
            if resp.status >= 400:
                err = payload.get("error") if isinstance(payload, dict) else payload
                raise PerpsError(f"{method} {path} → {resp.status}: {err}")
            return payload

    # ── Public data ──

    async def load_instruments(self) -> dict[int, Instrument]:
        data = await self._request("GET", "/v1/info/instruments")
        items = data if isinstance(data, list) else (data or {}).get("data", [])
        instruments = {}
        for item in items:
            try:
                inst = Instrument.from_api(item)
            except (KeyError, TypeError, ValueError):
                continue
            instruments[inst.id] = inst
        if instruments:
            self.instruments = instruments
        return self.instruments

    async def refresh_marks(self) -> None:
        data = await self._request("GET", "/v1/info/tickers")
        items = data if isinstance(data, list) else (data or {}).get("data", [])
        for t in items:
            try:
                self._marks[int(t["instrument_id"])] = float(t["mark_price"])
            except (KeyError, TypeError, ValueError):
                continue

    def mark(self, instrument_id: int) -> Optional[float]:
        return self._marks.get(instrument_id)

    async def public_portfolio(self, address: str) -> dict[int, PublicPosition]:
        data = await self._request("GET", "/v1/info/portfolio", params={"address": address})
        positions: dict[int, PublicPosition] = {}
        for p in (data or {}).get("positions") or []:
            try:
                pos = PublicPosition(
                    instrument_id=int(p["instrument_id"]),
                    symbol=str(p.get("symbol") or p["instrument_id"]),
                    size=float(p["size"]),
                    entry_price=float(p.get("entry_price") or 0),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if pos.size != 0:
                positions[pos.instrument_id] = pos
        return positions

    # ── Session (proxy credentials) ──

    async def open_session(self) -> None:
        """Load stored proxy credentials, creating / renewing them as needed."""
        if self.dry_run:
            return
        if self.owner is None:
            raise PerpsError("perps trading needs polymarket.private_key (the account signer)")
        creds = self._load_creds()
        if creds is None or creds.needs_renewal or creds.owner.lower() != self.owner.address.lower():
            creds = await self._create_proxy()
            self._save_creds(creds)
        self._use(creds)

    async def keep_session(self, shutdown: asyncio.Event) -> None:
        while not shutdown.is_set():
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=SESSION_CHECK_INTERVAL_S)
                return
            except asyncio.TimeoutError:
                pass
            if self.creds is not None and self.creds.needs_renewal:
                try:
                    creds = await self._create_proxy()
                except Exception as e:
                    log.warning(f"perps session renewal failed: {e}")
                    continue
                self._save_creds(creds)
                self._use(creds)

    def _use(self, creds: ProxyCredentials) -> None:
        self.creds = creds
        self._proxy = Account.from_key(creds.private_key)
        left_h = (creds.expires_at_ms - int(time.time() * 1000)) / 3_600_000
        log.info(f"perps session ready — proxy {creds.proxy[:10]}… valid {left_h:.0f}h")

    def _load_creds(self) -> Optional[ProxyCredentials]:
        if not self.session_file.exists():
            return None
        try:
            return ProxyCredentials(**json.loads(self.session_file.read_text(encoding="utf-8")))
        except Exception as e:
            log.warning(f"ignoring unreadable {self.session_file}: {e}")
            return None

    def _save_creds(self, creds: ProxyCredentials) -> None:
        tmp = self.session_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(creds), indent=2), encoding="utf-8")
        tmp.replace(self.session_file)

    async def _create_proxy(self) -> ProxyCredentials:
        assert self.owner is not None
        proxy = Account.create()
        now = int(time.time() * 1000)
        expiry = now + SESSION_TTL_MS
        salt = new_salt()
        typed = {
            "domain": DOMAIN,
            "primaryType": "CreateProxy",
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                ],
                "CreateProxy": [
                    {"name": "addr", "type": "address"},
                    {"name": "exp", "type": "uint64"},
                    {"name": "salt", "type": "uint64"},
                    {"name": "ts", "type": "uint64"},
                ],
            },
            "message": {"addr": proxy.address, "exp": expiry, "salt": salt, "ts": now},
        }
        signed = self.owner.sign_message(encode_typed_data(full_message=typed))
        body = {
            "op": {"type": "createProxy",
                   "args": {"owner": self.owner.address, "proxy": proxy.address, "expiry": expiry}},
            "sig": "0x" + bytes(signed.signature).hex(),
            "salt": salt,
            "ts": now,
            "label": "polymarket-copy-bot",
        }
        data = await self._request("POST", "/v1/account/proxy", body=body)
        secret = (data or {}).get("secret")
        if not secret:
            raise PerpsError(f"createProxy returned no secret: {data}")
        log.info(f"perps proxy created {proxy.address[:10]}… (expires in 7d)")
        return ProxyCredentials(
            owner=self.owner.address, proxy=proxy.address,
            private_key="0x" + bytes(proxy.key).hex(), secret=secret, expires_at_ms=expiry,
        )

    # ── Trading ──

    def _signed(self, op_type: str, args: Any, compact: list) -> dict:
        if self._proxy is None:
            raise PerpsError("perps trading session not open")
        return {"op": {"type": op_type, "args": args}, **sign_op(self._proxy, compact)}

    async def place_ioc(self, inst: Instrument, buy: bool, qty: Decimal, price: Decimal,
                        reduce_only: bool) -> PerpsOrderResult:
        """Immediate-or-cancel order; returns the quantity that actually filled."""
        if self.dry_run:
            return PerpsOrderResult(success=True, status="filled", filled_qty=float(qty),
                                    avg_price=self.mark(inst.id) or float(price), dry_run=True)
        order = {
            "iid": inst.id, "buy": buy, "p": fmt_decimal(price), "qty": fmt_decimal(qty),
            "tif": "ioc", "po": False, "ro": reduce_only, "c": _secrets.token_hex(16),
        }
        body = self._signed("createOrders", [order], create_orders_compact([order]))
        try:
            data = await self._request("POST", "/v1/trade/orders", body=body, auth=True)
        except PerpsError as e:
            return PerpsOrderResult(success=False, error=str(e))
        ack = data[0] if isinstance(data, list) and data else (data or {})
        if ack.get("status") != "ok" or ack.get("oid") is None:
            return PerpsOrderResult(success=False, error=str(ack.get("error") or ack))
        oid = int(ack["oid"])
        status, filled = await self._resolve_ioc(oid)
        avg = await self._avg_fill_price(inst.id, oid) if filled > 0 else None
        return PerpsOrderResult(success=True, order_id=oid, status=status,
                                filled_qty=filled, avg_price=avg or float(price))

    async def _resolve_ioc(self, oid: int) -> tuple[str, float]:
        """Poll the order snapshot until the IOC reaches a final status."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + IOC_RESOLVE_TIMEOUT_S
        delay = 0.05
        status, filled = "unknown", 0.0
        while True:
            try:
                data = await self._request("GET", "/v1/account/orders", params={"order_id": oid}, auth=True)
                rows = data if isinstance(data, list) else (data or {}).get("data", [])
                row = next((r for r in rows if int(r.get("order_id", -1)) == oid), None)
                if row is not None:
                    status = str(row.get("status", "unknown")).lower()
                    filled = float(row.get("filled_quantity") or 0)
                    if status in IOC_FINAL_STATUSES:
                        return status, filled
            except PerpsError as e:
                log.debug(f"order {oid} status read failed: {e}")
            if loop.time() + delay > deadline:
                log.warning(f"order {oid} not final after {IOC_RESOLVE_TIMEOUT_S}s (status={status})")
                return status, filled
            await asyncio.sleep(delay)
            delay = min(delay * 2, 0.5)

    async def _avg_fill_price(self, instrument_id: int, oid: int) -> Optional[float]:
        try:
            data = await self._request("GET", "/v1/account/fills",
                                       params={"instrument_id": instrument_id, "sort": "desc"}, auth=True)
        except PerpsError:
            return None
        rows = data.get("data", []) if isinstance(data, dict) else (data or [])
        qty = notional = 0.0
        for r in rows:
            if int(r.get("order_id", -1)) != oid:
                continue
            q = float(r.get("quantity") or 0)
            qty += q
            notional += q * float(r.get("price") or 0)
        return notional / qty if qty > 0 else None

    async def update_leverage(self, inst: Instrument, leverage: int, cross: bool) -> None:
        if self.dry_run:
            return
        cross = cross and not inst.isolated_only
        args = {"iid": inst.id, "lev": leverage, "cross": cross}
        body = self._signed("updateLeverage", args, update_leverage_compact(inst.id, leverage, cross))
        await self._request("PATCH", "/v1/trade/leverage", body=body, auth=True)

    async def get_collateral(self) -> Optional[Collateral]:
        """Margin available for new orders (pUSD)."""
        if self.dry_run or self.creds is None:
            return None
        data = await self._request("GET", "/v1/account/portfolio", auth=True)
        margin = (data or {}).get("margin") or {}
        available = margin.get("available_order_margin")
        return Collateral(float(available), None) if available is not None else None

    # ── Background ──

    async def run(self, shutdown: asyncio.Event) -> None:
        """Keep marks fresh (sizing + P&L) and instruments current."""
        last_instruments = time.monotonic()
        while not shutdown.is_set():
            try:
                await self.refresh_marks()
                if time.monotonic() - last_instruments > INSTRUMENT_REFRESH_S:
                    await self.load_instruments()
                    last_instruments = time.monotonic()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning(f"perps market data refresh failed: {e}")
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=TICKER_REFRESH_S)
            except asyncio.TimeoutError:
                pass
