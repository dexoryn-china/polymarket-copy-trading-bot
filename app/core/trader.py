"""CopyTrader — one per prediction-market target.

Decision pipeline per target fill:
  submit → (Gamma meta prefetch) → per-asset ordered task:
  stage chunk → size (per-target cap + global cap) → translate → balance check
  → clob.place_order → record ACTUAL fill → track resting remainder

Fills on different assets are handled concurrently; fills on the same asset
run strictly in arrival order so the per-asset accumulators stay consistent.
Entries are blocked while the target is disabled or trading is paused; exits
keep mirroring so existing positions are never stranded.
"""

import asyncio
import logging
import math
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Coroutine, Optional, TYPE_CHECKING

from app import events
from app.core.orders import OrderTracker, TrackedOrder
from app.core.portfolio import BalanceMonitor, Portfolio
from app.core.schema import MODE_FIXED, MODE_PERCENT
from app.events import EventBus
from app.pm.clob import MarketMeta, OrderResult, OrderSpec
from app.targets import VENUE_PREDICTIONS, Target
from app.utils.keyed_lock import KeyedLocks

if TYPE_CHECKING:
    from app.control import Control
    from app.pm.clob import ClobClient


DEFAULT_TICK = 0.01   # fallback when target fill price gives no info ("0.5")
CLOB_MIN_SHARES = 5.0   # default floor for order_minimum.mode=shares (overridable via config)

# PM binary outcome: price ∈ (0, 1) exclusive of $1. The highest valid limit is
# (1 - tick). Hardcoded exact values avoid float-imprecision from `1.0 - tick`.
TICK_MAX_PRICE = {
    0.01:   0.99,
    0.001:  0.999,
    0.0001: 0.9999,
}

log = logging.getLogger("trader")


# ──────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class TargetFill:
    """Normalized target fill from PM activity/trades WS event."""
    tx_hash: str
    asset: str             # token_id
    market_slug: str
    side: str              # "BUY" or "SELL"
    size: float
    price: float
    price_str: str         # original string for tick inference
    timestamp_ms: int
    outcome: str = ""      # human-readable outcome token: "Yes"/"No"/"Up"/"Down"
    title: str = ""        # human-readable market/event title
    wallet: str = ""       # lowercase proxy wallet of the trader


@dataclass
class PositionEntry:
    asset_id: str
    market_slug: str
    cost_basis_usd: float
    opened_at_ms: int
    end_date_ms: Optional[int] = None    # populated async via Gamma
    order_id: Optional[str] = None       # CLOB orderID (None in dry_run sim)
    size_shares: float = 0.0             # shares actually held
    title: str = ""
    outcome: str = ""


@dataclass
class TradingContext:
    """Dependencies shared by every prediction-market CopyTrader."""
    config: dict
    clob: "ClobClient"
    portfolio: Portfolio
    orders: OrderTracker
    bus: EventBus
    control: "Control"
    balance: Optional[BalanceMonitor] = None


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def infer_tick_from_price(price_str: str) -> float:
    """
    "0.42"   → 0.01
    "0.435"  → 0.001
    "0.4321" → 0.0001
    "0.5"    → DEFAULT_TICK (no info, fallback)
    "0.50"   → DEFAULT_TICK (trailing zero stripped)
    """
    s = str(price_str)
    if "." not in s:
        return DEFAULT_TICK
    decimals = s.split(".")[1].rstrip("0")
    n = len(decimals)
    if n <= 1:
        return DEFAULT_TICK
    if n == 2:
        return 0.01
    if n == 3:
        return 0.001
    return 0.0001


def round_to_tick(price: float, tick: float) -> float:
    """Round price to nearest tick multiple."""
    return round(price / tick) * tick


def max_price_for_tick(tick: float) -> float:
    """Highest valid limit price for a binary outcome at this tick = (1 - tick),
    snapped to the tick grid. PM rejects price >= 1, so this is the ceiling."""
    exact = TICK_MAX_PRICE.get(tick)
    if exact is not None:
        return exact
    return round(round_to_tick(1.0 - tick, tick), 6)


def floor_2dec(x: float) -> float:
    return int(x * 100) / 100.0


def ceil_2dec(x: float) -> float:
    """Round up to 2 decimals (used so dollar-mode minimums never land a hair
    under the target value due to truncation)."""
    return math.ceil(x * 100) / 100.0


def _now_ms() -> int:
    return int(time.time() * 1000)


# ──────────────────────────────────────────────────────────────────────────
# CopyTrader
# ──────────────────────────────────────────────────────────────────────────


class CopyTrader:
    """
    Owns one target's accumulators and positions.
    Pipeline: submit() → handle_fill() → stage chunk → translate → place_order → track.
    """

    BUFFER_CAP_MULTIPLIER = 3   # max buffer size = threshold × this (protects against runaway accumulation on repeated POST failures)
    HOLDINGS_EPSILON = 0.01     # below this many shares is treated as "flat" (float dust tolerance)

    def __init__(self, target: Target, ctx: TradingContext, state: Optional[dict] = None):
        self.target = target
        self.ctx = ctx
        state = state or {}
        # Per-asset buffer of target's BUY shares; reset to 0 after each copy
        self.target_buy_accumulator: dict[str, float] = dict(state.get("target_buy_accumulator", {}))
        # Per-asset net shares the target is tracked to hold (BUY adds, SELL subtracts).
        # Drives the sell fraction so partial exits are mirrored proportionally.
        self.target_holdings: dict[str, float] = dict(state.get("target_holdings", {}))
        # Per-asset buffer of shares we intend to sell; reset after each exit.
        self.target_sell_accumulator: dict[str, float] = dict(state.get("target_sell_accumulator", {}))
        self.positions: list[PositionEntry] = [
            PositionEntry(**p) for p in state.get("positions", [])
        ]
        self._state_dirty = False
        self._asset_locks = KeyedLocks()
        # Background tasks (fill handlers, Gamma fetches) — held to prevent GC
        # and drained/cancelled on shutdown.
        self._bg_tasks: set[asyncio.Task] = set()

    @property
    def target_id(self) -> str:
        return self.target.id

    @property
    def config(self) -> dict:
        return self.ctx.config

    # ── State serialization ──

    def export_state(self) -> dict:
        return {
            "target_buy_accumulator": self.target_buy_accumulator,
            "target_holdings": self.target_holdings,
            "target_sell_accumulator": self.target_sell_accumulator,
            "positions": [asdict(p) for p in self.positions],
        }

    @property
    def dirty(self) -> bool:
        return self._state_dirty

    def mark_clean(self) -> None:
        self._state_dirty = False

    # ── Exposure + expiry ──

    def open_usd(self, now_ms: int) -> float:
        """Cost basis of non-expired held positions (reservations live in Portfolio)."""
        return sum(p.cost_basis_usd for p in self.positions if not self._is_expired(p, now_ms))

    def has_open_positions(self) -> bool:
        return any(p.size_shares >= self.HOLDINGS_EPSILON for p in self.positions)

    def _is_expired(self, p: PositionEntry, now_ms: int) -> bool:
        if p.end_date_ms is not None:
            return now_ms > p.end_date_ms + self.config["position_expiry"]["buffer_s"] * 1000
        return (now_ms - p.opened_at_ms) > self.config["position_expiry"]["fallback_ttl_min"] * 60_000

    def gc_expired(self, now_ms: int) -> int:
        """Drop expired positions from tracker; return count dropped."""
        before = len(self.positions)
        kept = []
        for p in self.positions:
            if self._is_expired(p, now_ms):
                end_info = f"endDate+{self.config['position_expiry']['buffer_s']}s passed" \
                    if p.end_date_ms is not None else "fallback_ttl_min reached"
                log.info(
                    f"[EXPIRE] {self.target.name} asset={p.asset_id[:12]}… "
                    f"cost=${p.cost_basis_usd:.2f} → drop ({end_info})"
                )
                # Also clear accumulator for this asset (rebuild from scratch if it returns)
                self.target_buy_accumulator.pop(p.asset_id, None)
                self._state_dirty = True
            else:
                kept.append(p)
        self.positions = kept
        return before - len(kept)

    # ── Batching accumulator ──

    def stage_chunk_if_ready(self, target_fill: TargetFill) -> Optional[float]:
        """
        Always commits the new fill into the buffer (bounded by BUFFER_CAP).
        Returns chunk_shares if buffer has crossed threshold — but does NOT
        reset. Caller must call commit_copied_chunk() after the copy is placed;
        if it fails, the buffer stays so the next fill keeps building.
        """
        asset = target_fill.asset
        threshold = self.target.sizing["min_target_shares_to_copy"]
        # Never truncate a single fill: the cap only bounds carry-over from failed copies.
        max_buffer = max(threshold * self.BUFFER_CAP_MULTIPLIER, target_fill.size)
        new_acc = self.target_buy_accumulator.get(asset, 0.0) + target_fill.size
        if new_acc > max_buffer:
            log.info(
                f"[BUFFER-CAP] {self.target.name} asset={asset[:12]}… buffer would be {new_acc:.2f}, "
                f"capping at {max_buffer:.2f} (threshold×{self.BUFFER_CAP_MULTIPLIER})"
            )
            new_acc = max_buffer
        self.target_buy_accumulator[asset] = new_acc
        self._state_dirty = True

        if new_acc < threshold:
            log.info(
                f"[SKIP] {self.target.name} accumulating_below_threshold asset={asset[:12]}… "
                f"buffer={new_acc:.2f} threshold={threshold}"
            )
            return None

        log.info(
            f"[CHUNK] {self.target.name} asset={asset[:12]}… chunk={new_acc:.2f} shares "
            f"(threshold {threshold} crossed — pending POST result)"
        )
        return new_acc

    def commit_copied_chunk(self, asset: str) -> None:
        if asset in self.target_buy_accumulator:
            self.target_buy_accumulator[asset] = 0.0
            self._state_dirty = True

    # ── Holdings ──

    def _bot_shares_held(self, asset: str) -> float:
        return sum(p.size_shares for p in self.positions if p.asset_id == asset)

    def _reduce_holdings(self, asset: str, shares_sold: float) -> None:
        """
        Remove `shares_sold` shares from our tracked holdings (FIFO, oldest
        first), reducing each entry's cost_basis proportionally so headroom
        frees up correctly. Entries that reach ~0 shares are dropped.
        """
        remaining = shares_sold
        kept: list[PositionEntry] = []
        for p in self.positions:
            if p.asset_id != asset or remaining <= 0:
                kept.append(p)
                continue
            if p.size_shares <= remaining + 1e-9:
                remaining -= p.size_shares
                continue
            frac_left = (p.size_shares - remaining) / p.size_shares
            p.cost_basis_usd *= frac_left
            p.size_shares -= remaining
            remaining = 0.0
            if p.size_shares >= self.HOLDINGS_EPSILON:
                kept.append(p)
        self.positions = kept
        self._state_dirty = True

    def _record_buy(self, spec: OrderSpec, fill: TargetFill, shares: float, usd: float,
                    order_id: Optional[str]) -> None:
        """Add ACTUALLY filled shares (merged per order for incremental maker fills)."""
        entry = next((p for p in self.positions if order_id and p.order_id == order_id), None)
        if entry is None:
            entry = PositionEntry(
                asset_id=spec.asset_id,
                market_slug=spec.market_slug,
                cost_basis_usd=0.0,
                opened_at_ms=_now_ms(),
                order_id=order_id,
                title=fill.title,
                outcome=fill.outcome,
            )
            self.positions.append(entry)
            self._spawn(self._enrich_with_end_date(entry))
        entry.size_shares += shares
        entry.cost_basis_usd += usd
        self._state_dirty = True
        if self.ctx.balance:
            self.ctx.balance.debit(usd)

    def _record_sell(self, asset: str, shares: float, usd: float) -> None:
        self._reduce_holdings(asset, shares)
        if self.ctx.balance:
            self.ctx.balance.credit(usd)

    def _exit_bps(self) -> float:
        """Exit slippage; falls back to entry slippage when unset."""
        slip = self.config.get("slippage", {})
        return slip.get("exit_bps_max", slip["entry_bps_max"])

    def _min_shares_for_price(self, price: float) -> float:
        """Minimum shares an order must have to clear the configured floor.

        dollar mode → min_usd / price (rounded UP to 2 decimals so the order
                      value never lands a hair under min_usd). Price-dependent.
        shares mode → flat min_shares, independent of price.
        """
        cfg = self.config.get("order_minimum", {})
        mode = cfg.get("mode", "shares")
        if mode == "dollar":
            if price <= 0:
                return float("inf")
            min_usd = cfg.get("min_usd", 1.0)
            return ceil_2dec(min_usd / price)
        if mode == "shares":
            return cfg.get("min_shares", CLOB_MIN_SHARES)
        raise ValueError(f"unknown order_minimum mode: {mode!r}")

    # ── Sizing ──

    def _compute_size_usd(self, target_fill: TargetFill, chunk_shares: float, headroom: float) -> Optional[float]:
        if headroom <= 0:
            return None
        sizing = self.target.sizing
        mode = sizing["mode"]
        if mode == MODE_FIXED:
            usd = sizing["fixed_usd_per_fill"]
        elif mode == MODE_PERCENT:
            usd = chunk_shares * target_fill.price * sizing["percent_of_target"] / 100.0
        else:
            raise ValueError(f"unknown sizing mode: {mode}")
        return min(usd, headroom)

    # ── Translator ──

    def _translate(self, target_fill: TargetFill, chunk_shares: float, headroom: float,
                   meta: Optional[MarketMeta] = None) -> Optional[OrderSpec]:
        if target_fill.side != "BUY":
            return None

        usd = self._compute_size_usd(target_fill, chunk_shares, headroom)
        if usd is None:
            self._skip(target_fill, f"exposure cap reached — ${max(headroom, 0):.2f} left")
            return None

        meta = meta or MarketMeta()
        # Taker: limit = target_price * (1 + slippage_bps/10000)
        # Maker: limit = target_price + offset_ticks * tick (no book check)
        order_type_cfg = self.config["execution"]["order_type"]
        tick = meta.tick or infer_tick_from_price(target_fill.price_str)

        if order_type_cfg == "taker":
            slippage_bps = self.config["slippage"]["entry_bps_max"]
            limit_price = target_fill.price * (1 + slippage_bps / 10000)
            order_type = "FAK"
        elif order_type_cfg == "maker":
            offset_ticks = self.config["maker_settings"]["price_offset_ticks"]
            limit_price = target_fill.price + offset_ticks * tick
            order_type = "GTC"
        else:
            raise ValueError(f"unknown order_type: {order_type_cfg}")

        my_limit_price = round_to_tick(limit_price, tick)
        if my_limit_price <= 0:
            self._skip(target_fill, f"non-positive limit price {my_limit_price}")
            return None
        max_price = max_price_for_tick(tick)
        if my_limit_price > max_price:
            log.info(
                f"[CAP] limit_price {my_limit_price:.4f} > {max_price:.4f} "
                f"(max for tick={tick}) → capped"
            )
            my_limit_price = max_price

        shares = floor_2dec(usd / my_limit_price)

        min_shares = self._min_shares_for_price(my_limit_price)
        if shares < min_shares:
            min_cost = min_shares * my_limit_price
            if min_cost > headroom:
                self._skip(
                    target_fill,
                    f"exposure cap reached — ${headroom:.2f} left, order minimum is ${min_cost:.2f}",
                )
                return None
            log.info(
                f"[BUMP] desired={shares:.2f} < min {min_shares:.2f} → "
                f"using {min_shares:.2f} shares (cost ${min_cost:.2f})"
            )
            shares = min_shares

        return OrderSpec(
            asset_id=target_fill.asset,
            side="BUY",
            size=shares,
            price=my_limit_price,
            order_type=order_type,
            market_slug=target_fill.market_slug,
            target_price=target_fill.price,
            neg_risk=meta.neg_risk,
        )

    def _translate_sell(self, target_fill: TargetFill, shares: float, allow_below_min: bool = False,
                        meta: Optional[MarketMeta] = None) -> Optional[OrderSpec]:
        """
        Build a SELL OrderSpec for `shares` shares, priced to accept selling
        slightly BELOW the target's fill. `allow_below_min` bypasses the
        CLOB-minimum skip — used for full exits so dust gets liquidated.
        """
        meta = meta or MarketMeta()
        tick = meta.tick or infer_tick_from_price(target_fill.price_str)
        order_type_cfg = self.config["execution"]["order_type"]

        if order_type_cfg == "taker":
            limit_price = target_fill.price * (1 - self._exit_bps() / 10000)
            order_type = "FAK"
        elif order_type_cfg == "maker":
            offset_ticks = self.config["maker_settings"]["price_offset_ticks"]
            limit_price = target_fill.price - offset_ticks * tick
            order_type = "GTC"
        else:
            raise ValueError(f"unknown order_type: {order_type_cfg}")

        my_limit_price = round_to_tick(limit_price, tick)
        max_price = max_price_for_tick(tick)
        my_limit_price = min(max(my_limit_price, tick), max_price)

        shares = floor_2dec(shares)
        if shares <= 0:
            return None
        min_shares = self._min_shares_for_price(my_limit_price)
        if shares < min_shares and not allow_below_min:
            self._skip(target_fill, f"exit {shares:.2f} shares below order minimum {min_shares:.2f}")
            return None

        return OrderSpec(
            asset_id=target_fill.asset,
            side="SELL",
            size=shares,
            price=my_limit_price,
            order_type=order_type,
            market_slug=target_fill.market_slug,
            target_price=target_fill.price,
            neg_risk=meta.neg_risk,
        )

    # ── Entry point ──

    def submit(self, target_fill: TargetFill) -> None:
        """Non-blocking entry point for the WS receive loop.

        Kicks off the Gamma metadata lookup immediately (so it overlaps any wait
        behind an earlier fill on the same asset, and is cached by the time a
        batched BUY crosses its threshold), then schedules the fill handler.
        """
        self.ctx.bus.emit(
            events.TARGET_FILL,
            f"{self.target.name} {target_fill.side} {target_fill.outcome or '?'} "
            f"{target_fill.size:.2f} @ {target_fill.price * 100:.1f}¢ — {target_fill.title or target_fill.market_slug}",
            venue=VENUE_PREDICTIONS,
            target=self.target,
            side=target_fill.side,
            size=target_fill.size,
            price=target_fill.price,
            outcome=target_fill.outcome,
            title=target_fill.title,
            slug=target_fill.market_slug,
            asset=target_fill.asset,
            tx_hash=target_fill.tx_hash,
            lag_ms=(_now_ms() - target_fill.timestamp_ms) if target_fill.timestamp_ms > 0 else None,
        )
        slug = target_fill.market_slug
        if slug and not self.ctx.clob.has_market_meta(slug):
            self._spawn(self.ctx.clob.get_market_meta(slug))
        self._spawn(self._handle_fill_in_order(target_fill))

    async def _handle_fill_in_order(self, target_fill: TargetFill) -> None:
        async with self._asset_locks.hold(target_fill.asset):
            try:
                await self.handle_fill(target_fill)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception(f"handle_fill raised tx={target_fill.tx_hash[:10]}…: {e}")
                self.ctx.bus.emit(
                    events.ERROR, f"{self.target.name}: internal error handling fill: {e}",
                    level=events.ERROR_LEVEL, venue=VENUE_PREDICTIONS, target=self.target,
                )

    def _spawn(self, coro: Coroutine) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    async def handle_fill(self, target_fill: TargetFill) -> None:
        """Dispatch a target fill to the BUY (entry) or SELL (mirror exit) path.

        Callers other than tests should use submit(), which guarantees per-asset
        ordering; this method assumes it holds the asset's lock.
        """
        side = target_fill.side
        if side == "BUY":
            await self._handle_buy(target_fill)
        elif side == "SELL":
            await self._handle_sell(target_fill)
        else:
            log.info(f"[SKIP] unknown_side={side!r} asset={target_fill.asset[:12]}…")

    def _entry_block_reason(self) -> Optional[str]:
        if self.ctx.control.paused:
            return "trading paused"
        if not self.target.enabled:
            return "target disabled"
        return None

    # ── BUY ──

    async def _handle_buy(self, target_fill: TargetFill) -> None:
        asset = target_fill.asset
        # Track the target's net holdings (independent of our copy batching) so
        # later SELLs can be mirrored proportionally.
        self.target_holdings[asset] = self.target_holdings.get(asset, 0.0) + target_fill.size
        self._state_dirty = True

        blocked = self._entry_block_reason()
        if blocked:
            self._skip(target_fill, blocked)
            return

        chunk_shares = self.stage_chunk_if_ready(target_fill)
        if chunk_shares is None:
            return

        # Market metadata (neg_risk + real tick) is needed before signing. It is
        # cached per market and usually already prefetched by submit().
        meta = await self.ctx.clob.get_market_meta(target_fill.market_slug)

        # Headroom is read AFTER the await and reserved before the next one, so
        # concurrent BUYs always see each other's commitments.
        now_ms = _now_ms()
        self.gc_expired(now_ms)
        headroom = self.ctx.portfolio.headroom_usd(self.target_id, self.target.sizing["max_open_usd"], now_ms)
        spec = self._translate(target_fill, chunk_shares, headroom, meta)
        if spec is None:
            return

        cost = spec.size * spec.price
        if self.ctx.balance is not None:
            reason = self.ctx.balance.check(cost)
            if reason:
                self._skip(target_fill, reason, level=events.WARNING)
                return

        reservation = uuid.uuid4().hex
        self.ctx.portfolio.reserve(reservation, self.target_id, cost)
        try:
            result = await self._place(spec, target_fill)
        except BaseException:
            self.ctx.portfolio.release(reservation)
            raise
        if not result.success:
            self.ctx.portfolio.release(reservation)
            self._fail(spec, target_fill, result.error or "order rejected")
            return

        if result.filled_shares > 0:
            self._record_buy(spec, target_fill, result.filled_shares, result.filled_usd, result.order_id)

        if result.is_resting and result.order_id:
            self.ctx.portfolio.reserve(reservation, self.target_id, max(0.0, cost - result.filled_usd))
            self._track_resting(spec, target_fill, result, reservation)
        else:
            self.ctx.portfolio.release(reservation)

        if result.filled_shares <= 0 and not result.is_resting:
            # FAK killed without matching — the chunk was not copied; keep the
            # buffer so the next target fill retries.
            self._fail(spec, target_fill, f"not filled (status={result.status})")
            return

        self.commit_copied_chunk(asset)
        self._report(spec, target_fill, result)

    # ── SELL ──

    async def _handle_sell(self, target_fill: TargetFill) -> None:
        """
        Mirror a target SELL by exiting a proportional slice of our holdings.

        Sizing: fraction = target_sell_size / target_position_before_sell.
        We sell that fraction of OUR holdings, batching tiny exits up to the
        CLOB minimum. We liquidate the WHOLE position in one shot (bypassing the
        minimum) when the target goes flat OR when our entire holding is already
        below the CLOB minimum (dust we could never mirror partially).
        """
        asset = target_fill.asset
        sell_size = target_fill.size

        target_prev = self.target_holdings.get(asset, 0.0)
        target_now = max(0.0, target_prev - sell_size)
        self.target_holdings[asset] = target_now
        self._state_dirty = True

        if not self.target.copy_closes:
            self._skip(target_fill, "sell mirroring disabled for this target")
            return

        now_ms = _now_ms()
        self.gc_expired(now_ms)
        resting_sells = self.ctx.orders.pending_size(self.target_id, asset, "SELL")
        bot_held = self._bot_shares_held(asset) - resting_sells
        if bot_held < self.HOLDINGS_EPSILON:
            log.info(f"[SELL-SKIP] {self.target.name} no_holdings asset={asset[:12]}… (target_sell={sell_size:.2f})")
            self.target_sell_accumulator.pop(asset, None)
            return

        full_exit = target_now < self.HOLDINGS_EPSILON
        min_shares = self._min_shares_for_price(target_fill.price)
        # Dump the WHOLE position when the target went flat, or when our entire
        # holding is below the CLOB minimum (trapped dust).
        dump_all = full_exit or bot_held < min_shares

        if dump_all:
            desired = bot_held
            reason = "target flat" if full_exit else f"position {bot_held:.2f} < min {min_shares:.2f} (dust)"
            log.info(f"[EXIT] {reason} → selling all held asset={asset[:12]}… held={bot_held:.2f} shares")
        else:
            frac = 1.0 if target_prev <= 0 else min(1.0, sell_size / target_prev)
            new_acc = min(bot_held, self.target_sell_accumulator.get(asset, 0.0) + frac * bot_held)
            self.target_sell_accumulator[asset] = new_acc
            self._state_dirty = True
            if new_acc < min_shares:
                log.info(
                    f"[SELL-SKIP] accumulating_below_min asset={asset[:12]}… "
                    f"pending={new_acc:.2f} min={min_shares:.2f} (target {frac*100:.0f}% exit)"
                )
                return
            desired = new_acc

        shares = floor_2dec(min(desired, bot_held))
        if shares <= 0:
            return
        if shares < min_shares and not dump_all:
            return

        meta = await self.ctx.clob.get_market_meta(target_fill.market_slug)
        spec = self._translate_sell(target_fill, shares, allow_below_min=dump_all, meta=meta)
        if spec is None:
            return

        result = await self._place(spec, target_fill)
        if not result.success:
            # Keep the accumulator so the next SELL retries.
            self._fail(spec, target_fill, result.error or "order rejected")
            return

        if result.filled_shares > 0:
            self._record_sell(asset, result.filled_shares, result.filled_usd)
        if result.is_resting and result.order_id:
            self._track_resting(spec, target_fill, result, reservation=None)

        if result.filled_shares <= 0 and not result.is_resting:
            self._fail(spec, target_fill, f"not filled (status={result.status})")
            return

        self.target_sell_accumulator[asset] = 0.0
        self._report(spec, target_fill, result)

    # ── Order placement + resting orders ──

    async def _place(self, spec: OrderSpec, target_fill: TargetFill) -> OrderResult:
        t_pre_post = _now_ms()
        result = await self.ctx.clob.place_order(spec)
        result.posted_at_ms = _now_ms()
        if result.success and target_fill.timestamp_ms > 0:
            detect = t_pre_post - target_fill.timestamp_ms
            rtt = result.posted_at_ms - t_pre_post
            result.latency_ms = result.posted_at_ms - target_fill.timestamp_ms
            log.info(
                f"[{'DRY-RUN' if result.dry_run else 'COPY'}] {self.target.name} {spec.side} "
                f"{result.filled_shares:.2f}/{spec.size:.2f}@{spec.price:.4f} type={spec.order_type} "
                f"status={result.status} asset={spec.asset_id[:12]}… "
                f"lat={result.latency_ms}ms(pre={detect} rtt={rtt})"
            )
        return result

    def _track_resting(self, spec: OrderSpec, target_fill: TargetFill, result: OrderResult,
                       reservation: Optional[str]) -> None:
        price = spec.price
        rest_timeout_s = self.config["maker_settings"].get("rest_timeout_s")

        def on_fill(delta_shares: float) -> None:
            usd = delta_shares * price
            if spec.side == "BUY":
                self._record_buy(spec, target_fill, delta_shares, usd, result.order_id)
                if reservation:
                    remaining = max(0.0, (spec.size - order.filled) * price)
                    self.ctx.portfolio.reserve(reservation, self.target_id, remaining)
            else:
                self._record_sell(spec.asset_id, delta_shares, usd)

        def on_done() -> None:
            if reservation:
                self.ctx.portfolio.release(reservation)

        order = TrackedOrder(
            order_id=result.order_id,
            venue=VENUE_PREDICTIONS,
            target=self.target,
            asset=spec.asset_id,
            label=target_fill.title or target_fill.market_slug or spec.asset_id[:12],
            side=spec.side,
            price=price,
            size=spec.size,
            filled=result.filled_shares,
            placed_at_ms=result.posted_at_ms or _now_ms(),
            expires_at_ms=(_now_ms() + int(rest_timeout_s * 1000)) if rest_timeout_s else None,
            on_fill=on_fill,
            on_done=on_done,
        )
        self.ctx.orders.track(order)

    # ── Activity reporting ──

    def _market_fields(self, target_fill: TargetFill) -> dict:
        return {
            "title": target_fill.title,
            "outcome": target_fill.outcome,
            "slug": target_fill.market_slug,
            "asset": target_fill.asset,
        }

    def _skip(self, target_fill: TargetFill, reason: str, level: str = events.INFO) -> None:
        log.info(f"[SKIP] {self.target.name} {target_fill.side} asset={target_fill.asset[:12]}…: {reason}")
        self.ctx.bus.emit(
            events.COPY_SKIPPED,
            f"{self.target.name}: skipped {target_fill.side} — {reason}",
            level=level, venue=VENUE_PREDICTIONS, target=self.target,
            reason=reason, side=target_fill.side, **self._market_fields(target_fill),
        )

    def _fail(self, spec: OrderSpec, target_fill: TargetFill, error: str) -> None:
        self.ctx.bus.emit(
            events.COPY_FAILURE,
            f"{self.target.name}: {spec.side} {spec.size:.2f} @ {spec.price * 100:.1f}¢ failed — {error}",
            level=events.ERROR_LEVEL, venue=VENUE_PREDICTIONS, target=self.target,
            error=error, side=spec.side, size=spec.size, price=spec.price,
            order_type=spec.order_type, **self._market_fields(target_fill),
        )

    def _report(self, spec: OrderSpec, target_fill: TargetFill, result: OrderResult) -> None:
        filled = result.filled_shares
        resting = " (resting)" if result.is_resting else ""
        dry = "[DRY RUN] " if result.dry_run else ""
        self.ctx.bus.emit(
            events.COPY_SUCCESS,
            f"{dry}{self.target.name}: {spec.side} {filled:.2f}/{spec.size:.2f} "
            f"{target_fill.outcome or ''} @ {spec.price * 100:.1f}¢{resting} — "
            f"{target_fill.title or target_fill.market_slug}",
            level=events.SUCCESS, venue=VENUE_PREDICTIONS, target=self.target,
            side=spec.side, size=spec.size, filled=filled, price=spec.price,
            usd=result.filled_usd, order_type=spec.order_type, status=result.status,
            order_id=result.order_id, dry_run=result.dry_run, latency_ms=result.latency_ms,
            **self._market_fields(target_fill),
        )

    # ── Dashboard views ──

    def position_views(self) -> list[dict]:
        views = []
        for p in self.positions:
            if p.size_shares < self.HOLDINGS_EPSILON:
                continue
            views.append({
                "id": f"{self.target_id}:{p.asset_id}:{p.order_id or p.opened_at_ms}",
                "venue": VENUE_PREDICTIONS,
                "target_id": self.target_id,
                "target_name": self.target.name,
                "label": p.title or p.market_slug or p.asset_id[:12],
                "sublabel": p.outcome or None,
                "side": (p.outcome or "long").lower(),
                "size": p.size_shares,
                "entry_price": (p.cost_basis_usd / p.size_shares) if p.size_shares else None,
                "value_usd": p.cost_basis_usd,
                "pnl_usd": None,
                "opened_at_ms": p.opened_at_ms,
                "url": f"https://polymarket.com/market/{p.market_slug}" if p.market_slug else None,
            })
        return views

    # ── Background ──

    async def _enrich_with_end_date(self, entry: PositionEntry) -> None:
        try:
            end_ms = await self.ctx.clob.fetch_market_end_date(entry.market_slug)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"[EXPIRY-FALLBACK] slug={entry.market_slug} Gamma error: {e}")
            return
        if end_ms is None:
            log.warning(
                f"[EXPIRY-FALLBACK] slug={entry.market_slug} Gamma failed → "
                f"using fallback_ttl_min={self.config['position_expiry']['fallback_ttl_min']}min"
            )
            return
        entry.end_date_ms = end_ms
        self._state_dirty = True

    async def shutdown(self, grace_s: float = 5.0) -> None:
        """Let in-flight fills finish (so a POSTed order's position is recorded),
        then cancel whatever is left."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + grace_s
        # Loop: a finishing fill may spawn a follow-up task (endDate enrichment).
        while self._bg_tasks and (remaining := deadline - loop.time()) > 0:
            await asyncio.wait(set(self._bg_tasks), timeout=remaining)
        leftover = list(self._bg_tasks)
        for t in leftover:
            t.cancel()
        if leftover:
            await asyncio.gather(*leftover, return_exceptions=True)
