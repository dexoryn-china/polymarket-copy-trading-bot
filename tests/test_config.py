"""legacy_seed + load_config / validate_config / target_seed."""

from __future__ import annotations

import yaml

from app.config import ConfigError, load_config, target_seed, validate_config, DEFAULTS
from app.core.schema import legacy_seed
from app.targets import VENUE_PREDICTIONS
from tests.fakes import WALLET_A, WALLET_B, valid_config_dict


def test_legacy_seed_none_without_wallet():
    assert legacy_seed({}) is None
    assert legacy_seed({"sizing": {"mode": "fixed"}}) is None
    assert legacy_seed({"target_wallet": ""}) is None


def test_legacy_seed_converts_fraction_and_keys():
    seed = legacy_seed({
        "target_wallet": WALLET_A,
        "sizing": {
            "mode": "percent_of_target",
            "fixed_usd_per_fill": 8.0,
            "percent_of_target": 0.05,
            "max_usd_total_in_positions": 250.0,
            "min_target_shares_to_copy": 3.0,
        },
        "execution": {"copy_sells": False, "order_type": "taker"},
    })
    assert seed is not None
    assert seed["name"] == "default"
    assert seed["venue"] == VENUE_PREDICTIONS
    assert seed["wallet"] == WALLET_A
    assert seed["enabled"] is True
    assert seed["copy_closes"] is False
    assert seed["sizing"]["percent_of_target"] == 5.0
    assert seed["sizing"]["max_open_usd"] == 250.0
    assert seed["sizing"]["min_target_shares_to_copy"] == 3.0
    assert seed["sizing"]["fixed_usd_per_fill"] == 8.0


def test_legacy_seed_copy_sells_defaults_true():
    seed = legacy_seed({"target_wallet": WALLET_A})
    assert seed["copy_closes"] is True
    assert seed["sizing"]["percent_of_target"] == 5.0  # 0.05 * 100


def _write_cfg(tmp_path, mapping: dict) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
    return str(path)


def test_load_config_applies_defaults(tmp_path):
    path = _write_cfg(tmp_path, valid_config_dict())
    cfg = load_config(path)
    assert cfg["execution"]["order_type"] == DEFAULTS["execution"]["order_type"]
    assert cfg["order_minimum"]["mode"] == "shares"
    assert cfg["web"]["port"] == 8787
    assert cfg["copy"]["venue"] == "predictions"
    assert "enabled" not in cfg["perps"]
    assert cfg["perps"]["margin_mode"] == "isolated"
    assert cfg["maker_settings"]["rest_timeout_s"] == 30
    # File values win over defaults.
    path2 = _write_cfg(tmp_path, valid_config_dict(web={"port": 9999}, execution={"order_type": "maker"}))
    cfg2 = load_config(path2)
    assert cfg2["web"]["port"] == 9999
    assert cfg2["web"]["host"] == "127.0.0.1"
    assert cfg2["execution"]["order_type"] == "maker"


def test_load_config_missing_file(tmp_path):
    try:
        load_config(str(tmp_path / "nope.yaml"))
        assert False
    except ConfigError as e:
        assert "not found" in str(e)


def test_validate_config_mode_and_perps_and_web():
    cfg = valid_config_dict()
    # Merge defaults as load_config would.
    from app.config import DEFAULTS as D
    for section, defaults in D.items():
        cfg[section] = {**defaults, **(cfg.get(section) or {})}

    validate_config(cfg)

    bad = {**cfg, "mode": "paper"}
    try:
        validate_config(bad)
        assert False
    except ConfigError as e:
        assert "dry_run|real" in str(e)

    bad = {**cfg, "perps": {**cfg["perps"], "poll_interval_s": 0.1}}
    try:
        validate_config(bad)
        assert False
    except ConfigError as e:
        assert "poll_interval_s" in str(e)

    bad = {**cfg, "perps": {**cfg["perps"], "margin_mode": "isolated-cross"}}
    try:
        validate_config(bad)
        assert False
    except ConfigError as e:
        assert "margin_mode" in str(e)

    bad = {**cfg, "web": {**cfg["web"], "port": 70000}}
    try:
        validate_config(bad)
        assert False
    except ConfigError as e:
        assert "web.port" in str(e)

    bad = {**cfg, "web": {**cfg["web"], "port": 80.5}}
    try:
        validate_config(bad)
        assert False
    except ConfigError as e:
        assert "web.port" in str(e)


def test_validate_config_real_mode_requires_secrets():
    from app.config import DEFAULTS as D
    cfg = valid_config_dict(mode="real")
    for section, defaults in D.items():
        cfg[section] = {**defaults, **(cfg.get(section) or {})}
    try:
        validate_config(cfg)
        assert False
    except ConfigError as e:
        assert "polymarket" in str(e)

    cfg["polymarket"] = {
        "private_key": "0x1",
        "wallet_address": "0x2",
        "api_key": "k",
        "api_secret": "s",
        "passphrase": "p",
    }
    validate_config(cfg)

    cfg["polymarket"]["api_secret"] = ""
    try:
        validate_config(cfg)
        assert False
    except ConfigError as e:
        assert "api_secret" in str(e)

    cfg["polymarket"]["api_secret"] = "s"
    cfg["polymarket"]["signature_type"] = "9"
    try:
        validate_config(cfg)
        assert False
    except ConfigError as e:
        assert "signature_type" in str(e)


def test_validate_config_telegram_and_misc():
    from app.config import DEFAULTS as D
    cfg = valid_config_dict()
    for section, defaults in D.items():
        cfg[section] = {**defaults, **(cfg.get(section) or {})}

    cfg["telegram"] = {"enabled": True, "bot_token": "", "chat_id": "1"}
    try:
        validate_config(cfg)
        assert False
    except ConfigError as e:
        assert "bot_token" in str(e)

    cfg["telegram"] = {"enabled": True, "bot_token": "tok", "chat_id": ""}
    try:
        validate_config(cfg)
        assert False
    except ConfigError as e:
        assert "chat_id" in str(e)

    cfg["telegram"] = {
        "enabled": True, "bot_token": "tok", "chat_id": "1",
        "notify_on": ["copy_success", "not_a_real_event"],
    }
    try:
        validate_config(cfg)
        assert False
    except ConfigError as e:
        assert "notify_on" in str(e)

    cfg["telegram"] = {"enabled": True, "bot_token": "tok", "chat_id": ["1", "2"]}
    validate_config(cfg)

    cfg["targets"] = "not-a-list"
    try:
        validate_config(cfg)
        assert False
    except ConfigError as e:
        assert "targets must be a list" in str(e)


def test_target_seed_prefers_list_over_legacy():
    cfg = {
        "targets": [{"name": "listed", "venue": "predictions", "wallet": WALLET_A}],
        "target_wallet": WALLET_B,
    }
    seed = target_seed(cfg)
    assert len(seed) == 1
    assert seed[0]["name"] == "listed"

    legacy_only = {"target_wallet": WALLET_A, "sizing": {"percent_of_target": 0.1}}
    seed2 = target_seed(legacy_only)
    assert len(seed2) == 1
    assert seed2[0]["wallet"] == WALLET_A
    assert seed2[0]["sizing"]["percent_of_target"] == 10.0

    assert target_seed({}) == []


def test_copy_venue_default_and_validation(tmp_path):
    cfg = load_config(_write_cfg(tmp_path, valid_config_dict()))
    assert cfg["copy"]["venue"] == "predictions"

    cfg = load_config(_write_cfg(tmp_path, valid_config_dict(copy={"venue": "perps"})))
    assert cfg["copy"]["venue"] == "perps"

    try:
        load_config(_write_cfg(tmp_path, valid_config_dict(copy={"venue": "spot"})))
        assert False
    except ConfigError as e:
        assert "copy.venue" in str(e)


def test_legacy_perps_enabled_maps_to_copy_venue(tmp_path):
    cfg = load_config(_write_cfg(tmp_path, valid_config_dict(perps={"enabled": True})))
    assert cfg["copy"]["venue"] == "perps"

    cfg = load_config(_write_cfg(tmp_path, valid_config_dict(perps={"enabled": False})))
    assert cfg["copy"]["venue"] == "predictions"


def test_explicit_copy_wins_over_legacy_perps_enabled(tmp_path):
    cfg = load_config(_write_cfg(tmp_path, valid_config_dict(
        copy={"venue": "predictions"},
        perps={"enabled": True},
    )))
    assert cfg["copy"]["venue"] == "predictions"

    cfg = load_config(_write_cfg(tmp_path, valid_config_dict(
        copy={"venue": "perps"},
        perps={"enabled": False},
    )))
    assert cfg["copy"]["venue"] == "perps"
