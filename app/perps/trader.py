"""PerpsTrader — one per perps target.

Detection is snapshot-based: the engine polls the target's public portfolio
and hands it to `observe()`, which diffs signed sizes per instrument:

    |size| grows (or opens)    → entry: open/add our own size (sizing mode)
    |size| shrinks             → exit: reduce ours by the same fraction
    goes flat / flips side     → close ours fully (then open the new side)

Orders are IOC at mark ± slippage; our book records only the quantity that
actually filled. Changes on different instruments run concurrently; changes
on the same instrument run strictly in order.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Coroutine, Optional, TYPE_CHECKING

from app import events
from app.core.portfolio import BalanceMonitor, Portfolio
from app.events import EventBus
from app.perps.account import PerpsAccount
from app.perps.client import (
    Instrument, PerpsClient, PerpsOrderResult, PublicPosition, fmt_decimal, quantize_price, quantize_qty,
)
from app.perps.schema import MODE_FIXED, MODE_PERCENT
from app.targets import VENUE_PERPS, Target
from app.utils.keyed_lock import KeyedLocks

if TYPE_CHECKING:
    from app.control import Control

log = logging.getLogger("perps")

SIZE_EPSILON = 1e-9
FULL_CLOSE_FRACTION = 0.999
DEFAULT_SLIPPAGE_BPS = 50.0


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


@dataclass
class PerpPosition:
    instrument_id: int
    symbol: str
    size: float              # signed contracts: + long, − short
    entry_price: float
    opened_at_ms: int
    leverage: int = 0

    @property
    def notional_usd(self) -> float:
        return abs(self.size) * self.entry_price


@dataclass(frozen=True)
class PositionChange:
    instrument_id: int
    symbol: str
    prev: float              # target's signed size before
    now: float               # target's signed size after
    target_entry: float
    detected_ms: int


@dataclass
class PerpsContext:
    """Dependencies shared by every PerpsTrader."""
    config: dict             # the `perps` config section
    client: PerpsClient
    account: PerpsAccount
    portfolio: Portfolio
    bus: EventBus
    control: "Control"
    balance: Optional[BalanceMonitor] = None

    @property
    def slippage_bps(self) -> float:
        return float(self.config.get("slippage_bps", DEFAULT_SLIPPAGE_BPS))


class PerpsTrader:
    def __init__(self, target: Target, ctx: PerpsContext, state: Optional[dict] = None) -> None:
        self.target = target
        self.ctx = ctx
        state = state or {}
        self.positions: dict[int, PerpPosition] = {
            int(k): PerpPosition(**v) for k, v in (state.get("positions") or {}).items()
        }
        saved_sizes = state.get("target_sizes")
        # Last-seen target sizes. None → first observation is a silent baseline.
        self.target_sizes: Optional[dict[int, float]] = (
            {int(k): float(v) for k, v in saved_sizes.items()} if saved_sizes is not None else None
        )
        self._observed_since_start = False
        # Entry size too small for the instrument minimum, carried per
        # instrument as (direction, qty) until enough accumulates.
        self._pending_entry: dict[int, tuple[int, float]] = {}
        self._dirty = False
        self._locks = KeyedLocks()
        self._bg_tasks: set[asyncio.Task] = set()

    @property
    def target_id(self) -> str:
        return self.target.id

    # ── Book ──

    def size(self, instrument_id: int) -> float:
        pos = self.positions.get(instrument_id)
        return pos.size if pos else 0.0

    def open_usd(self, now_ms: int) -> float:
        return sum(p.notional_usd for p in self.positions.values())

    def has_open_positions(self) -> bool:
        return bool(self.positions)

    def _apply_fill(self, instrument_id: int, symbol: str, delta: float, price: float,
                    leverage: int = 0) -> float:
        """Apply a signed fill to our book; returns realized P&L."""
        pos = self.positions.get(instrument_id)
        if pos is None:
            self.positions[instrument_id] = PerpPosition(instrument_id, symbol, delta, price, _now_ms(), leverage)
            self._dirty = True
            return 0.0
        realized = 0.0
        new_size = pos.size + delta
        if _sign(delta) == _sign(pos.size):
            pos.entry_price = (abs(pos.size) * pos.entry_price + abs(delta) * price) / abs(new_size)
        else:
            closed = min(abs(delta), abs(pos.size))
            realized = (price - pos.entry_price) * closed * _sign(pos.size)
            if _sign(new_size) not in (0, _sign(pos.size)):
                pos.entry_price = price
                pos.opened_at_ms = _now_ms()
        pos.size = new_size
        if abs(pos.size) <= SIZE_EPSILON:
            del self.positions[instrument_id]
        self._dirty = True
        return realized

    # ── State ──

    def export_state(self) -> dict:
        return {
            "positions": {str(k): asdict(v) for k, v in self.positions.items()},
            "target_sizes": (None if self.target_sizes is None
                             else {str(k): v for k, v in self.target_sizes.items()}),
        }

    @property
    def dirty(self) -> bool:
        return self._dirty

    def mark_clean(self) -> None:
        self._dirty = False

    # ── Detection ──

    def resume(self) -> None:
        """Copying (re)started: the next snapshot is diffed with `_offline_change`."""
        self._observed_since_start = False

    def observe(self, snapshot: dict[int, PublicPosition]) -> list[PositionChange]:
        """Diff a fresh portfolio snapshot against the last one and submit
        the resulting changes. Returns the submitted changes."""
        now_ms = _now_ms()
        prev = self.target_sizes
        self.target_sizes = {iid: p.size for iid, p in snapshot.items()}
        if prev != self.target_sizes:
            self._dirty = True

        first = not self._observed_since_start
        self._observed_since_start = True
        if prev is None:
            log.info(f"[PERPS] {self.target.name} baseline: {len(snapshot)} open position(s) — not copied")
            return []

        changes = []
        for iid in sorted(set(prev) | set(snapshot)):
            before, after = prev.get(iid, 0.0), self.target_sizes.get(iid, 0.0)
            if abs(after - before) <= SIZE_EPSILON:
                continue
            pos = snapshot.get(iid)
            symbol = pos.symbol if pos else self._symbol(iid)
            changes.append(PositionChange(iid, symbol, before, after, pos.entry_price if pos else 0.0, now_ms))

        if first:
            changes = [c for c in map(self._offline_change, changes) if c is not None]

        for change in changes:
            self._spawn(self._handle_in_order(change))
        return changes

    def _offline_change(self, c: PositionChange) -> Optional[PositionChange]:
        """A change that happened while we weren't copying (bot offline or
        stopped): mirror only the risk-reducing part — a late entry would copy
        at a stale price."""
        if c.prev != 0 and _sign(c.now) != _sign(c.prev):
            return PositionChange(c.instrument_id, c.symbol, c.prev, 0.0, c.target_entry, c.detected_ms)
        if abs(c.now) < abs(c.prev):
            return c
        log.info(f"[PERPS] {self.target.name} {c.symbol} grew while not copying — not copied")
        return None

    def _symbol(self, instrument_id: int) -> str:
        pos = self.positions.get(instrument_id)
        if pos:
            return pos.symbol
        inst = self.ctx.client.instruments.get(instrument_id)
        return inst.symbol if inst else str(instrument_id)

    # ── Handling ──

    def _spawn(self, coro: Coroutine) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    async def _handle_in_order(self, change: PositionChange) -> None:
        async with self._locks.hold(change.instrument_id):
            try:
                await self.handle_change(change)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception(f"perps change handling failed {change}: {e}")
                self.ctx.bus.emit(
                    events.ERROR, f"{self.target.name}: internal error on {change.symbol}: {e}",
                    level=events.ERROR_LEVEL, venue=VENUE_PERPS, target=self.target,
                )

    async def handle_change(self, change: PositionChange) -> None:
        self._emit_target_change(change)
        prev, now = change.prev, change.now
        if prev != 0 and _sign(now) != _sign(prev):
            await self._exit(change, fraction=1.0)
            if now != 0:
                await self._enter(change, delta=abs(now), direction=_sign(now))
        elif abs(now) < abs(prev):
            await self._exit(change, fraction=(abs(prev) - abs(now)) / abs(prev))
        else:
            await self._enter(change, delta=abs(now) - abs(prev), direction=_sign(now))

    async def _instrument(self, instrument_id: int) -> Optional[Instrument]:
        inst = self.ctx.client.instruments.get(instrument_id)
        if inst is None:
            await self.ctx.client.load_instruments()
            inst = self.ctx.client.instruments.get(instrument_id)
        return inst

    def _limit_price(self, inst: Instrument, mark: float, buy: bool):
        # Stay inside the exchange's allowed band around mark.
        bps = min(self.ctx.slippage_bps, inst.price_bounds * 10_000 * 0.9)
        raw = mark * (1 + bps / 10_000) if buy else mark * (1 - bps / 10_000)
        return quantize_price(raw, inst.price_decimals, buy)

    def _entry_block_reason(self) -> Optional[str]:
        if self.ctx.control.paused:
            return "trading paused"
        if not self.target.enabled:
            return "target disabled"
        return None

    # ── Entry ──

    async def _enter(self, change: PositionChange, delta: float, direction: int) -> None:
        blocked = self._entry_block_reason()
        if blocked:
            return self._skip(change, blocked)
        inst = await self._instrument(change.instrument_id)
        if inst is None:
            return self._skip(change, "unknown instrument")
        mark = self.ctx.client.mark(inst.id) or change.target_entry
        if not mark or mark <= 0:
            return self._skip(change, "no mark price")

        sizing = self.target.sizing
        if sizing["mode"] == MODE_PERCENT:
            qty = delta * sizing["percent_of_target"] / 100.0
        elif sizing["mode"] == MODE_FIXED:
            qty = sizing["fixed_notional_usd"] / mark
        else:
            raise ValueError(f"unknown perps sizing mode {sizing['mode']!r}")
        pending_dir, pending_qty = self._pending_entry.pop(inst.id, (direction, 0.0))
        if pending_dir == direction:
            qty += pending_qty

        headroom = self.ctx.portfolio.headroom_usd(self.target_id, sizing["max_open_notional_usd"])
        if headroom <= 0:
            return self._skip(change, f"exposure cap reached — ${max(headroom, 0):.2f} left")
        if qty * mark < inst.min_notional:
            self._pending_entry[inst.id] = (direction, qty)
            log.info(f"[PERPS] {self.target.name} {inst.symbol} accumulating ${qty * mark:.2f} "
                     f"(instrument minimum ${inst.min_notional:.2f})")
            return
        qty = min(qty, headroom / mark, inst.max_market_notional / mark)
        qty_d = quantize_qty(qty, inst.quantity_decimals)
        notional = float(qty_d) * mark
        if qty_d <= 0 or notional < inst.min_notional:
            return self._skip(change, f"exposure cap reached — ${headroom:.2f} left, "
                                      f"instrument minimum is ${inst.min_notional:.2f}")

        leverage = max(1, min(int(sizing["leverage"]), inst.max_leverage))
        margin = notional / leverage
        if self.ctx.balance is not None:
            reason = self.ctx.balance.check(margin)
            if reason:
                return self._skip(change, reason, level=events.WARNING)

        buy = direction > 0
        key = uuid.uuid4().hex
        self.ctx.portfolio.reserve(key, self.target_id, notional)
        self.ctx.account.reserve_margin(key, margin)
        try:
            try:
                await self.ctx.account.ensure_leverage(inst, leverage)
            except Exception as e:
                log.warning(f"[PERPS] leverage update {inst.symbol} failed: {e} — using account setting")
            result = await self._place(inst, buy, qty_d, self._limit_price(inst, mark, buy), False, change)
        finally:
            self.ctx.portfolio.release(key)
            self.ctx.account.release_margin(key)

        if not result.success:
            return self._fail(change, buy, float(qty_d), result.error or "order rejected")
        if result.filled_qty <= 0:
            return self._fail(change, buy, float(qty_d), f"not filled (status={result.status})")
        price = result.avg_price or mark
        self._apply_fill(inst.id, inst.symbol, direction * result.filled_qty, price, leverage)
        if self.ctx.balance:
            self.ctx.balance.debit(result.filled_qty * price / leverage)
        self._report(change, "open" if abs(change.prev) <= SIZE_EPSILON else "add", buy,
                     float(qty_d), result, price, leverage=leverage)

    # ── Exit ──

    async def _exit(self, change: PositionChange, fraction: float) -> None:
        if fraction >= FULL_CLOSE_FRACTION:
            self._pending_entry.pop(change.instrument_id, None)
        if not self.target.copy_closes:
            return self._skip(change, "close mirroring disabled for this target")
        pos = self.positions.get(change.instrument_id)
        if pos is None or _sign(pos.size) != _sign(change.prev):
            log.info(f"[PERPS] {self.target.name} {change.symbol} exit — nothing held on that side")
            return
        inst = await self._instrument(change.instrument_id)
        if inst is None:
            return self._skip(change, "unknown instrument")
        mark = self.ctx.client.mark(inst.id) or pos.entry_price

        full = fraction >= FULL_CLOSE_FRACTION
        qty = abs(pos.size) if full else abs(pos.size) * fraction
        qty_d = quantize_qty(qty, inst.quantity_decimals)
        if qty_d <= 0:
            return
        if not full and float(qty_d) * mark < inst.min_notional:
            return self._skip(change, f"partial exit ${float(qty_d) * mark:.2f} below instrument minimum")

        buy = pos.size < 0
        net = self.ctx.account.net_size(inst.id)
        # Reduce-only is only safe when the account's net position is on our
        # side and at least as large (other targets may hold the opposite side).
        reduce_only = _sign(net) == _sign(pos.size) and abs(net) + SIZE_EPSILON >= float(qty_d)
        result = await self._place(inst, buy, qty_d, self._limit_price(inst, mark, buy), reduce_only, change)
        if not result.success:
            return self._fail(change, buy, float(qty_d), result.error or "order rejected")
        if result.filled_qty <= 0:
            return self._fail(change, buy, float(qty_d), f"not filled (status={result.status})")
        price = result.avg_price or mark
        filled = min(result.filled_qty, abs(pos.size))
        realized = self._apply_fill(inst.id, inst.symbol, -_sign(pos.size) * filled, price)
        self._report(change, "close" if full else "reduce", buy, float(qty_d), result, price, realized=realized)

    # ── Order placement ──

    async def _place(self, inst: Instrument, buy: bool, qty, price, reduce_only: bool,
                     change: PositionChange) -> PerpsOrderResult:
        t0 = _now_ms()
        result = await self.ctx.client.place_ioc(inst, buy, qty, price, reduce_only)
        result.posted_at_ms = _now_ms()
        result.latency_ms = result.posted_at_ms - change.detected_ms
        log.info(
            f"[{'DRY-RUN' if result.dry_run else 'PERPS'}] {self.target.name} {'BUY' if buy else 'SELL'} "
            f"{result.filled_qty}/{fmt_decimal(qty)} {inst.symbol} @ {fmt_decimal(price)} ro={reduce_only} "
            f"status={result.status or result.error} rtt={result.posted_at_ms - t0}ms"
        )
        return result

    # ── Activity ──

    def _fields(self, change: PositionChange) -> dict:
        return {"symbol": change.symbol, "instrument_id": change.instrument_id,
                "target_prev": change.prev, "target_now": change.now}

    def _emit_target_change(self, c: PositionChange) -> None:
        delta = c.now - c.prev
        self.ctx.bus.emit(
            events.TARGET_FILL,
            f"{self.target.name} {c.symbol}: {c.prev:+g} → {c.now:+g} ({'+' if delta > 0 else ''}{delta:g})",
            venue=VENUE_PERPS, target=self.target,
            side="BUY" if delta > 0 else "SELL", size=abs(delta), price=c.target_entry or None,
            title=c.symbol, **self._fields(c),
        )

    def _skip(self, change: PositionChange, reason: str, level: str = events.INFO) -> None:
        log.info(f"[PERPS-SKIP] {self.target.name} {change.symbol}: {reason}")
        self.ctx.bus.emit(
            events.COPY_SKIPPED, f"{self.target.name}: skipped {change.symbol} — {reason}",
            level=level, venue=VENUE_PERPS, target=self.target, reason=reason, **self._fields(change),
        )

    def _fail(self, change: PositionChange, buy: bool, qty: float, error: str) -> None:
        self.ctx.bus.emit(
            events.COPY_FAILURE,
            f"{self.target.name}: {'BUY' if buy else 'SELL'} {qty:g} {change.symbol} failed — {error}",
            level=events.ERROR_LEVEL, venue=VENUE_PERPS, target=self.target,
            error=error, side="BUY" if buy else "SELL", size=qty, **self._fields(change),
        )

    def _report(self, change: PositionChange, action: str, buy: bool, qty: float,
                result: PerpsOrderResult, price: float, leverage: Optional[int] = None,
                realized: Optional[float] = None) -> None:
        dry = "[DRY RUN] " if result.dry_run else ""
        pnl = f", realized {realized:+.2f}" if realized else ""
        self.ctx.bus.emit(
            events.COPY_SUCCESS,
            f"{dry}{self.target.name}: {action} {change.symbol} {'BUY' if buy else 'SELL'} "
            f"{result.filled_qty:g}/{qty:g} @ {price:g}{pnl}",
            level=events.SUCCESS, venue=VENUE_PERPS, target=self.target,
            action=action, side="BUY" if buy else "SELL", size=qty, filled=result.filled_qty,
            price=price, usd=result.filled_qty * price, status=result.status, order_id=result.order_id,
            dry_run=result.dry_run, latency_ms=result.latency_ms, leverage=leverage,
            realized_pnl=realized, **self._fields(change),
        )

    # ── Dashboard ──

    def position_views(self) -> list[dict]:
        views = []
        for p in self.positions.values():
            mark = self.ctx.client.mark(p.instrument_id)
            views.append({
                "id": f"{self.target_id}:perp:{p.instrument_id}",
                "venue": VENUE_PERPS,
                "target_id": self.target_id,
                "target_name": self.target.name,
                "label": p.symbol,
                "sublabel": f"{p.leverage}x" if p.leverage else None,
                "side": "long" if p.size > 0 else "short",
                "size": abs(p.size),
                "entry_price": p.entry_price,
                "value_usd": abs(p.size) * (mark or p.entry_price),
                "pnl_usd": (mark - p.entry_price) * p.size if mark else None,
                "opened_at_ms": p.opened_at_ms,
                "url": None,
            })
        return views

    async def shutdown(self, grace_s: float = 5.0) -> None:
        if self._bg_tasks:
            _, pending = await asyncio.wait(set(self._bg_tasks), timeout=grace_s)
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

