"""SettingsStore: load, values, update, persistence."""

from __future__ import annotations

import copy
import logging

import yaml

from app import events
from app.config import ConfigError, load_config, validate_config
from app.notifications.telegram import DEFAULT_EVENTS
from app.settings import SECRET_MASK, SETTINGS_SECTIONS, SettingsError, SettingsStore, _get, _set
from app.targets import TargetError
from tests.fakes import load_example_config, make_runtime, make_settings_store


def _all_fields():
    return [f for s in SETTINGS_SECTIONS for f in s.fields]


def test_defaults_and_values_view(tmp_path):
    cfg = load_example_config(tmp_path)
    cfg["telegram"]["chat_id"] = "12345"
    cfg["telegram"]["bot_token"] = "live-token"
    store = make_settings_store(tmp_path, cfg)

    values = store.values()
    assert values["telegram.bot_token"] == SECRET_MASK
    assert values["telegram.chat_id"] == ["12345"]
    assert values["telegram.notify_on"] == sorted(DEFAULT_EVENTS)
    assert values["telegram.enabled"] is False
    assert "perps.enabled" not in values
    assert store.value("telegram.bot_token") == "live-token"

    by_id = {s.id: s for s in SETTINGS_SECTIONS}
    assert by_id["trading"].venue == "predictions"
    assert by_id["perps"].venue == "perps"
    assert by_id["notifications"].venue is None
    payload = store.to_dict()
    assert set(payload) == {"sections", "values"}
    sections = {s["id"]: s for s in payload["sections"]}
    assert sections["trading"]["venue"] == "predictions"
    assert sections["perps"]["venue"] == "perps"
    assert sections["notifications"]["venue"] is None


def test_update_mutates_nested_dicts_in_place(tmp_path):
    cfg = load_example_config(tmp_path)
    perps = cfg["perps"]
    telegram = cfg["telegram"]
    store = make_settings_store(tmp_path, cfg)

    changed = store.update({"perps.poll_interval_s": 2.5, "perps.slippage_bps": 80})
    assert changed == {"perps.poll_interval_s", "perps.slippage_bps"}
    assert cfg["perps"] is perps
    assert cfg["telegram"] is telegram
    assert perps["poll_interval_s"] == 2.5
    assert perps["slippage_bps"] == 80.0


def test_update_notifies_only_changed_keys_noop_is_silent(tmp_path):
    cfg = load_example_config(tmp_path)
    store = make_settings_store(tmp_path, cfg)
    seen: list[set[str]] = []
    store.on_change(lambda keys: seen.append(set(keys)))

    both = store.update({"perps.poll_interval_s": 3.0, "perps.slippage_bps": 90})
    assert both == {"perps.poll_interval_s", "perps.slippage_bps"}
    assert seen == [both]
    written = (tmp_path / "settings.yaml").read_text(encoding="utf-8")

    seen.clear()
    noop = store.update({"perps.poll_interval_s": 3.0, "perps.slippage_bps": 90})
    assert noop == set()
    assert seen == []
    assert (tmp_path / "settings.yaml").read_text(encoding="utf-8") == written

    store2 = SettingsStore(load_example_config(tmp_path), str(tmp_path / "other.yaml"))
    store2.load()
    store2.on_change(lambda keys: seen.append(set(keys)))
    none = store2.update({"perps.poll_interval_s": store2.value("perps.poll_interval_s")})
    assert none == set()
    assert seen == []
    assert not (tmp_path / "other.yaml").exists()


def test_update_validation_errors(tmp_path):
    store = make_settings_store(tmp_path)

    try:
        store.update({"perps.poll_interval_s": 0.1})
        assert False
    except TargetError as e:
        assert "Poll interval" in str(e)
        assert "at least" in str(e)

    try:
        store.update({"execution.order_type": "market"})
        assert False
    except TargetError as e:
        assert "Order type" in str(e)
        assert "must be one of" in str(e)

    try:
        store.update({"not.a.setting": 1})
        assert False
    except SettingsError as e:
        assert "unknown settings" in str(e)

    try:
        store.update({})
        assert False
    except SettingsError as e:
        assert "at least one setting" in str(e)

    try:
        store.update({"telegram.enabled": True})
        assert False
    except SettingsError as e:
        assert "bot_token" in str(e)


def test_secret_mask_is_kept(tmp_path):
    cfg = load_example_config(tmp_path)
    cfg["telegram"]["bot_token"] = "real-secret"
    store = make_settings_store(tmp_path, cfg)
    seen: list[set[str]] = []
    store.on_change(lambda keys: seen.append(set(keys)))

    changed = store.update({
        "telegram.bot_token": SECRET_MASK,
        "perps.poll_interval_s": 2.0,
    })
    assert changed == {"perps.poll_interval_s"}
    assert store.value("telegram.bot_token") == "real-secret"
    assert store.values()["telegram.bot_token"] == SECRET_MASK
    assert seen == [{"perps.poll_interval_s"}]

    seen.clear()
    only_mask = store.update({"telegram.bot_token": SECRET_MASK})
    assert only_mask == set()
    assert seen == []
    assert store.value("telegram.bot_token") == "real-secret"


def test_persistence_round_trip(tmp_path):
    cfg = load_example_config(tmp_path)
    path = tmp_path / "settings.yaml"
    store = make_settings_store(tmp_path, cfg)
    store.update({
        "perps.poll_interval_s": 2.5,
        "telegram.bot_token": "abc",
        "telegram.chat_id": "1, 2, 1",
    })
    assert cfg["telegram"]["chat_id"] == ["1", "2"]
    assert not path.with_suffix(".yaml.tmp").exists()

    fresh = load_config(str(tmp_path / "config.yaml"))
    assert fresh["perps"]["poll_interval_s"] == 1.0
    store2 = SettingsStore(fresh, str(path))
    store2.load()
    assert fresh["perps"]["poll_interval_s"] == 2.5
    assert store2.value("telegram.bot_token") == "abc"
    assert store2.values()["telegram.bot_token"] == SECRET_MASK
    assert store2.value("telegram.chat_id") == ["1", "2"]


def test_invalid_settings_yaml_raises_config_error(tmp_path):
    cfg = load_example_config(tmp_path)
    path = tmp_path / "settings.yaml"
    path.write_text("execution.order_type: nope\n", encoding="utf-8")
    store = SettingsStore(cfg, str(path))
    try:
        store.load()
        assert False
    except ConfigError as e:
        assert "Order type" in str(e) or "order_type" in str(e)


def test_unknown_keys_in_file_are_ignored(tmp_path, caplog):
    cfg = load_example_config(tmp_path)
    path = tmp_path / "settings.yaml"
    path.write_text(
        yaml.safe_dump({"bogus.thing": 1, "perps.slippage_bps": 80}),
        encoding="utf-8",
    )
    store = SettingsStore(cfg, str(path))
    with caplog.at_level(logging.WARNING, logger="settings"):
        store.load()
    assert cfg["perps"]["slippage_bps"] == 80.0
    assert "bogus.thing" not in store._overrides
    assert "bogus.thing" in caplog.text


def test_every_section_field_default_validates(tmp_path):
    cfg = load_example_config(tmp_path)
    store = make_settings_store(tmp_path, cfg)
    fields = _all_fields()
    keys = [f.key for f in fields]
    assert len(keys) == len(set(keys))

    candidate = copy.deepcopy(cfg)
    for field in fields:
        _set(candidate, field.key, copy.deepcopy(field.default))
    validate_config(candidate)

    for field in fields:
        resolved = store.value(field.key)
        present = _get(cfg, field.key)
        assert present is not None or resolved == field.default or field.nullable
        if not field.nullable:
            # Missing keys (e.g. telegram.notify_on) still resolve via the field default.
            assert resolved is not None or field.type in ("text", "secret", "list")


def test_runtime_update_settings_emits_only_when_changed(tmp_path):
    settings = make_settings_store(tmp_path)
    runtime, _, _ = make_runtime(tmp_path, settings=settings)
    acts: list = []
    runtime.bus.subscribe(acts.append)

    current = settings.value("perps.poll_interval_s")
    runtime.update_settings({"perps.poll_interval_s": current})
    assert not any(a.data.get("event") == "settings" for a in acts)

    out = runtime.update_settings({"perps.poll_interval_s": 2.5})
    settings_acts = [a for a in acts if a.kind == events.SYSTEM and a.data.get("event") == "settings"]
    assert len(settings_acts) == 1
    assert "Poll interval" in settings_acts[0].summary
    assert settings_acts[0].summary.startswith("Settings updated:")
    assert out["values"]["perps.poll_interval_s"] == 2.5
    runtime.history.close()
