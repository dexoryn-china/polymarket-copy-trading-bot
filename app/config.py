"""config.yaml loading + validation.

Targets live in `targets.yaml` (edited from the dashboard). `config.yaml`
only seeds it on first run — from a `targets:` list, or from the legacy
single `target_wallet` + `sizing` block, so existing configs keep working.
"""

from pathlib import Path
from typing import Any, Optional

import yaml

from app.core.schema import legacy_seed
from app.notifications.telegram import ALL_EVENTS
from app.targets import VENUE_PERPS, VENUE_PREDICTIONS

VENUES = (VENUE_PREDICTIONS, VENUE_PERPS)

DEFAULTS: dict[str, Any] = {
    "copy": {"venue": VENUE_PREDICTIONS},
    "execution": {"order_type": "taker"},
    "order_minimum": {"mode": "shares", "min_usd": 1.0, "min_shares": 5.0},
    "maker_settings": {"rest_timeout_s": 30, "price_offset_ticks": 0},
    "risk": {"max_open_usd_total": None},
    "perps": {
        "poll_interval_s": 1.0,
        "slippage_bps": 50,
        "margin_mode": "isolated",
        "max_open_notional_total": None,
    },
    "web": {"enabled": True, "host": "127.0.0.1", "port": 8787, "token": ""},
}


class ConfigError(Exception):
    pass


def load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"{path} not found — copy config.yaml.example and edit")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(cfg, dict):
        raise ConfigError(f"{path} must be a mapping")
    if "copy" not in cfg and (cfg.get("perps") or {}).get("enabled") is True:
        cfg["copy"] = {"venue": VENUE_PERPS}       # legacy `perps.enabled: true`
    for section, defaults in DEFAULTS.items():
        cfg[section] = {**defaults, **(cfg.get(section) or {})}
    validate_config(cfg)
    return cfg


def target_seed(cfg: dict) -> list[dict]:
    """Targets used to create targets.yaml when it doesn't exist yet."""
    if cfg.get("targets"):
        return list(cfg["targets"])
    legacy = legacy_seed(cfg)
    return [legacy] if legacy else []


def _require(d: dict, path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise ConfigError(f"missing required config: {path}")
        cur = cur[part]
    return cur


def _positive_or_none(value: Optional[float], name: str) -> None:
    if value is not None and (not isinstance(value, (int, float)) or value <= 0):
        raise ConfigError(f"{name} must be a positive number or null")


def validate_config(cfg: dict) -> None:
    mode = _require(cfg, "mode")
    if mode not in ("dry_run", "real"):
        raise ConfigError(f"mode must be dry_run|real, got {mode!r}")

    targets = cfg.get("targets")
    if targets is not None and not isinstance(targets, list):
        raise ConfigError("targets must be a list")

    ot = cfg["execution"]["order_type"]
    if ot not in ("taker", "maker"):
        raise ConfigError(f"execution.order_type must be taker|maker, got {ot!r}")

    om = cfg["order_minimum"]
    if om["mode"] not in ("dollar", "shares"):
        raise ConfigError(f"order_minimum.mode must be dollar|shares, got {om['mode']!r}")
    if om["mode"] == "dollar" and om["min_usd"] <= 0:
        raise ConfigError("order_minimum.min_usd must be > 0")
    if om["mode"] == "shares" and om["min_shares"] <= 0:
        raise ConfigError("order_minimum.min_shares must be > 0")

    rest = cfg["maker_settings"].get("rest_timeout_s")
    _positive_or_none(rest, "maker_settings.rest_timeout_s")

    bps = _require(cfg, "slippage.entry_bps_max")
    if not (0 < bps < 10000):
        raise ConfigError("slippage.entry_bps_max must be in (0, 10000)")
    if "exit_bps_max" in cfg["slippage"] and not (0 < cfg["slippage"]["exit_bps_max"] < 10000):
        raise ConfigError("slippage.exit_bps_max must be in (0, 10000)")

    _require(cfg, "position_expiry.buffer_s")
    if _require(cfg, "position_expiry.fallback_ttl_min") < 5:
        raise ConfigError("position_expiry.fallback_ttl_min must be >= 5")
    if _require(cfg, "dedup.seen_cap") < 1000:
        raise ConfigError("dedup.seen_cap must be >= 1000")
    if _require(cfg, "watchdog.max_consecutive_errors") < 1:
        raise ConfigError("watchdog.max_consecutive_errors must be >= 1")
    if _require(cfg, "watchdog.silent_timeout_s") < 10:
        raise ConfigError("watchdog.silent_timeout_s must be >= 10")

    _positive_or_none(cfg["risk"]["max_open_usd_total"], "risk.max_open_usd_total")

    venue = cfg["copy"]["venue"]
    if venue not in VENUES:
        raise ConfigError(f"copy.venue must be {'|'.join(VENUES)}, got {venue!r}")

    perps = cfg["perps"]
    if perps["poll_interval_s"] < 0.25:
        raise ConfigError("perps.poll_interval_s must be >= 0.25")
    if not (0 < perps["slippage_bps"] < 10000):
        raise ConfigError("perps.slippage_bps must be in (0, 10000)")
    if perps["margin_mode"] not in ("isolated", "cross"):
        raise ConfigError("perps.margin_mode must be isolated|cross")
    _positive_or_none(perps["max_open_notional_total"], "perps.max_open_notional_total")

    web = cfg["web"]
    if not isinstance(web["port"], int) or not (0 < web["port"] < 65536):
        raise ConfigError("web.port must be 1-65535")

    if mode == "real":
        secrets = cfg.get("polymarket")
        if not secrets:
            raise ConfigError("mode=real requires polymarket: section")
        missing = [k for k in ("private_key", "wallet_address", "api_key", "api_secret", "passphrase")
                   if not secrets.get(k)]
        if missing:
            raise ConfigError(f"mode=real missing polymarket fields: {missing}")
        st = str(secrets.get("signature_type", "auto")).lower()
        if st not in ("auto", "0", "2", "3"):
            raise ConfigError(f"polymarket.signature_type must be auto|0|2|3, got {st!r}")

    tg = cfg.get("telegram") or {}
    if tg.get("enabled"):
        if not (tg.get("bot_token") or "").strip():
            raise ConfigError("telegram.enabled requires bot_token")
        chat_id = tg.get("chat_id")
        chat_list = chat_id if isinstance(chat_id, (list, tuple)) else [chat_id]
        if not any(str(c or "").strip() for c in chat_list):
            raise ConfigError("telegram.enabled requires at least one chat_id")
        notify_on = tg.get("notify_on")
        if notify_on is not None:
            unknown = set(notify_on) - ALL_EVENTS
            if unknown:
                raise ConfigError(f"telegram.notify_on unknown events: {sorted(unknown)}")
