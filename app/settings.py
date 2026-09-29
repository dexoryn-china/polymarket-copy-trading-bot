"""Dashboard-editable bot settings.

`SETTINGS_SECTIONS` declares every editable setting once (dotted config path,
type, bounds, help, basic/advanced group); the same declaration validates API
input and renders the dashboard form. Changes are applied to the live config
dict in place — components read it per decision (the few cached values are
pushed by `on_change` listeners), so they take effect immediately — and
persisted to `settings.yaml`, which overrides config.yaml.
"""

import copy
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from app.config import ConfigError, validate_config
from app.notifications.telegram import DEFAULT_EVENTS, EVENT_LABELS
from app.targets import GROUP_ADVANCED, VENUE_PERPS, VENUE_PREDICTIONS, Field, TargetError

log = logging.getLogger("settings")

SECRET_MASK = "••••••••"


class SettingsError(TargetError):
    """Invalid settings input (maps to HTTP 400)."""


@dataclass(frozen=True)
class Section:
    id: str
    label: str
    description: str
    fields: tuple[Field, ...]
    venue: Optional[str] = None        # None = applies to every venue

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "description": self.description,
                "venue": self.venue, "fields": [f.to_dict() for f in self.fields]}


ORDER_TYPE = "execution.order_type"
ORDER_MIN_MODE = "order_minimum.mode"

SETTINGS_SECTIONS: tuple[Section, ...] = (
    Section(
        id="trading",
        label="Prediction markets",
        description="How copies are executed on the Polymarket CLOB. Per-wallet order size lives on each target.",
        venue=VENUE_PREDICTIONS,
        fields=(
            Field(
                key=ORDER_TYPE, label="Order type", type="select", default="taker",
                options=(("taker", "Taker — fill now (FAK)"), ("maker", "Maker — rest on the book (GTC)")),
                help="Taker fills immediately against the book; maker posts a limit order and waits.",
            ),
            Field(
                key="risk.max_open_usd_total", label="Total exposure cap", type="number", default=None,
                min=1.0, step=10.0, unit="USD", nullable=True,
                help="Across ALL prediction targets (each target also has its own cap). Empty = no total cap.",
            ),
            Field(
                key="maker_settings.rest_timeout_s", label="Cancel unfilled after", type="number", default=30,
                min=1.0, step=5.0, unit="s", nullable=True, show_if=(ORDER_TYPE, "maker"),
                help="Resting maker orders still open after this are cancelled. Empty = never.",
            ),
            Field(
                key="slippage.entry_bps_max", label="Max entry slippage", type="number", default=1000,
                min=1.0, max=9999.0, step=50.0, unit="bps", group=GROUP_ADVANCED, show_if=(ORDER_TYPE, "taker"),
                help="Buy limit = target price × (1 + bps/10000). 100 bps = 1%. Wider fills more often.",
            ),
            Field(
                key="slippage.exit_bps_max", label="Max exit slippage", type="number", default=1000,
                min=1.0, max=9999.0, step=50.0, unit="bps", group=GROUP_ADVANCED, show_if=(ORDER_TYPE, "taker"),
                help="Sell limit = target price × (1 − bps/10000).",
            ),
            Field(
                key="maker_settings.price_offset_ticks", label="Maker price offset", type="number", default=0,
                min=-10.0, max=10.0, step=1.0, unit="ticks", group=GROUP_ADVANCED, show_if=(ORDER_TYPE, "maker"),
                help="0 = the target's price; positive = more aggressive for buys.",
            ),
            Field(
                key=ORDER_MIN_MODE, label="Order minimum rule", type="select", default="shares",
                options=(("dollar", "Minimum order value (USD)"), ("shares", "Minimum share count")),
                group=GROUP_ADVANCED,
                help="Copies smaller than the market minimum are bumped up (entries) or batched (exits).",
            ),
            Field(
                key="order_minimum.min_usd", label="Minimum order value", type="number", default=1.0,
                min=0.01, step=0.5, unit="USD", group=GROUP_ADVANCED, show_if=(ORDER_MIN_MODE, "dollar"),
            ),
            Field(
                key="order_minimum.min_shares", label="Minimum shares", type="number", default=5.0,
                min=0.01, step=1.0, unit="shares", group=GROUP_ADVANCED, show_if=(ORDER_MIN_MODE, "shares"),
            ),
            Field(
                key="position_expiry.buffer_s", label="Release exposure after market end", type="number",
                default=60, min=0.0, step=30.0, unit="s", group=GROUP_ADVANCED,
                help="A resolved market stops counting toward caps this long after its end date.",
            ),
            Field(
                key="position_expiry.fallback_ttl_min", label="Fallback position lifetime", type="number",
                default=1440, min=5.0, step=60.0, unit="min", group=GROUP_ADVANCED,
                help="Used when a market's end date is unknown.",
            ),
        ),
    ),
    Section(
        id="perps",
        label="Perps",
        description="Polymarket Perps copying. Per-wallet size and leverage live on each target. "
                    "Real mode needs polymarket.private_key and a funded Perps account.",
        venue=VENUE_PERPS,
        fields=(
            Field(
                key="perps.max_open_notional_total", label="Total notional cap", type="number", default=None,
                min=1.0, step=50.0, unit="USD", nullable=True,
                help="Across ALL perps targets. Empty = no total cap.",
            ),
            Field(
                key="perps.slippage_bps", label="Max slippage", type="number", default=50,
                min=1.0, max=9999.0, step=5.0, unit="bps", group=GROUP_ADVANCED,
                help="IOC limit = mark × (1 ± bps/10000), kept inside the instrument's price band.",
            ),
            Field(
                key="perps.poll_interval_s", label="Poll interval", type="number", default=1.0,
                min=0.25, max=60.0, step=0.25, unit="s", group=GROUP_ADVANCED,
                help="How often each target's portfolio is checked. Lower = faster copies, more requests.",
            ),
            Field(
                key="perps.margin_mode", label="Margin mode", type="select", default="isolated",
                options=(("isolated", "Isolated"), ("cross", "Cross")), group=GROUP_ADVANCED,
                help="Applied when opening an instrument from flat.",
            ),
        ),
    ),
    Section(
        id="notifications",
        label="Telegram",
        description="Push notifications to one or more Telegram chats.",
        fields=(
            Field(key="telegram.enabled", label="Send notifications", type="boolean", default=False),
            Field(
                key="telegram.bot_token", label="Bot token", type="secret", default="",
                help="From @BotFather. Stored on the bot machine only.",
            ),
            Field(
                key="telegram.chat_id", label="Chat IDs", type="list", default=[],
                help="Comma-separated. Group / channel ids are negative.",
            ),
            Field(
                key="telegram.notify_on", label="Notify on", type="multiselect",
                default=sorted(DEFAULT_EVENTS), options=tuple(EVENT_LABELS.items()), group=GROUP_ADVANCED,
            ),
        ),
    ),
)


def _get(cfg: dict, path: str) -> Any:
    cur: Any = cfg
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _set(cfg: dict, path: str, value: Any) -> None:
    *parents, leaf = path.split(".")
    cur = cfg
    for part in parents:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = cur[part] = {}
        cur = nxt
    cur[leaf] = value


class SettingsStore:
    def __init__(self, config: dict, path: str,
                 sections: tuple[Section, ...] = SETTINGS_SECTIONS) -> None:
        self.config = config
        self.path = Path(path)
        self.sections = sections
        self.fields: dict[str, Field] = {f.key: f for s in sections for f in s.fields}
        self._overrides: dict[str, Any] = {}
        self._listeners: list[Callable[[set[str]], None]] = []

    def on_change(self, fn: Callable[[set[str]], None]) -> None:
        self._listeners.append(fn)

    # ── Loading ──

    def load(self) -> None:
        """Apply settings.yaml overrides on top of config.yaml (raises ConfigError)."""
        if not self.path.exists():
            return
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ConfigError(f"{self.path} must be a mapping")
        overrides = {k: v for k, v in raw.items() if k in self.fields}
        ignored = set(raw) - set(overrides)
        if ignored:
            log.warning(f"ignoring unknown settings in {self.path}: {sorted(ignored)}")
        try:
            self._validated(overrides)
        except TargetError as e:
            raise ConfigError(f"{self.path}: {e}") from None
        for key, value in overrides.items():
            _set(self.config, key, value)
        self._overrides = overrides

    # ── Reads ──

    def value(self, key: str) -> Any:
        field = self.fields[key]
        value = _get(self.config, key)
        if field.type == "list" and not isinstance(value, list):
            value = [str(value)] if value not in (None, "") else []
        if field.type == "multiselect" and value is None:
            value = list(field.default)
        return field.default if value is None and not field.nullable else value

    def values(self) -> dict[str, Any]:
        out = {}
        for key, field in self.fields.items():
            value = self.value(key)
            out[key] = (SECRET_MASK if value else "") if field.type == "secret" else value
        return out

    def to_dict(self) -> dict:
        return {"sections": [s.to_dict() for s in self.sections], "values": self.values()}

    # ── Writes ──

    def update(self, changes: dict) -> set[str]:
        """Validate + apply + persist; returns the keys whose value actually changed."""
        if not isinstance(changes, dict) or not changes:
            raise SettingsError("send at least one setting")
        coerced = self._validated(changes)
        changed = {k for k, v in coerced.items() if v != _get(self.config, k)}
        for key in changed:
            _set(self.config, key, coerced[key])
        if changed:
            self._overrides.update({k: coerced[k] for k in changed})
            self._save()
            for fn in list(self._listeners):
                try:
                    fn(changed)
                except Exception:
                    log.exception("settings listener failed")
        return changed

    def _validated(self, changes: dict) -> dict[str, Any]:
        unknown = set(changes) - set(self.fields)
        if unknown:
            raise SettingsError(f"unknown settings: {sorted(unknown)}")
        coerced: dict[str, Any] = {}
        for key, raw in changes.items():
            field = self.fields[key]
            if field.type == "secret" and raw == SECRET_MASK:
                continue                        # unchanged (UI echoes the mask)
            coerced[key] = field.coerce(raw)
        candidate = copy.deepcopy(self.config)
        for key, value in coerced.items():
            _set(candidate, key, value)
        try:
            validate_config(candidate)
        except ConfigError as e:
            raise SettingsError(str(e)) from None
        return coerced

    def _save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(self._overrides, sort_keys=True, allow_unicode=True), encoding="utf-8")
        tmp.replace(self.path)
