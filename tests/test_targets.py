"""Target schema: Field.coerce, VenueSchema, TargetStore."""

from __future__ import annotations

import yaml

from app.core.schema import PREDICTIONS_SCHEMA
from app.perps.schema import PERPS_SCHEMA
from app.targets import (
    GROUP_ADVANCED,
    GROUP_BASIC,
    VENUE_PERPS,
    VENUE_PREDICTIONS,
    Field,
    TargetConflict,
    TargetError,
    TargetStore,
)
from tests.fakes import SCHEMAS, WALLET_A, WALLET_B, WALLET_C


def test_field_coerce_boolean_and_select_and_number():
    flag = Field(key="on", label="On", type="boolean", default=False)
    assert flag.coerce(True) is True
    try:
        flag.coerce("true")
        assert False, "expected TargetError"
    except TargetError as e:
        assert "true/false" in str(e)

    mode = Field(
        key="mode",
        label="Mode",
        type="select",
        default="fixed",
        options=(("fixed", "Fixed"), ("percent_of_target", "Percent")),
    )
    assert mode.coerce("fixed") == "fixed"
    try:
        mode.coerce("other")
        assert False
    except TargetError as e:
        assert "must be one of" in str(e)

    num = Field(key="n", label="N", type="number", default=1.0, min=0.5, max=10.0)
    assert num.coerce("3") == 3.0
    try:
        num.coerce("nope")
        assert False
    except TargetError as e:
        assert "number" in str(e)
    try:
        num.coerce(0.1)
        assert False
    except TargetError as e:
        assert str(e) == "N must be at least 0.5"
    try:
        num.coerce(11)
        assert False
    except TargetError as e:
        assert str(e) == "N must be at most 10"


def test_validate_sizing_fills_defaults_rejects_unknown():
    filled = PREDICTIONS_SCHEMA.validate_sizing({})
    assert filled["mode"] == "fixed"
    assert filled["fixed_usd_per_fill"] == 10.0
    assert filled["percent_of_target"] == 5.0
    assert filled["max_open_usd"] == 100.0
    assert filled["min_target_shares_to_copy"] == 10.0

    partial = PREDICTIONS_SCHEMA.validate_sizing({"fixed_usd_per_fill": 25})
    assert partial["fixed_usd_per_fill"] == 25.0
    assert partial["mode"] == "fixed"

    try:
        PREDICTIONS_SCHEMA.validate_sizing({"nope": 1})
        assert False
    except TargetError as e:
        assert "unknown sizing fields" in str(e)

    try:
        PREDICTIONS_SCHEMA.validate_sizing({"percent_of_target": 200})
        assert False
    except TargetError as e:
        assert str(e) == "Percent of target must be at most 100"

    try:
        PREDICTIONS_SCHEMA.validate_sizing({"fixed_usd_per_fill": 0})
        assert False
    except TargetError as e:
        assert str(e) == "Order size must be at least 0.01"


def test_normalize_wallet_lowercases_and_rejects_bad():
    assert PREDICTIONS_SCHEMA.normalize_wallet("0x" + "AB" * 20) == "0x" + "ab" * 20
    try:
        PREDICTIONS_SCHEMA.normalize_wallet("not-an-address")
        assert False
    except TargetError:
        pass
    try:
        PREDICTIONS_SCHEMA.normalize_wallet("0x123")
        assert False
    except TargetError:
        pass


def test_load_seeds_only_when_file_missing(tmp_path):
    path = tmp_path / "targets.yaml"
    seed = [{
        "name": "from-config",
        "venue": VENUE_PREDICTIONS,
        "wallet": WALLET_A,
        "sizing": {"fixed_usd_per_fill": 7},
    }]
    store = TargetStore(str(path), SCHEMAS)
    store.load(seed)
    assert path.exists()
    assert len(store.all()) == 1
    assert store.all()[0].name == "from-config"
    assert store.all()[0].sizing["fixed_usd_per_fill"] == 7.0

    other_seed = [{
        "name": "should-not-apply",
        "venue": VENUE_PREDICTIONS,
        "wallet": WALLET_B,
    }]
    store2 = TargetStore(str(path), SCHEMAS)
    store2.load(other_seed)
    names = {t.name for t in store2.all()}
    assert names == {"from-config"}
    assert "should-not-apply" not in names


def test_load_missing_file_empty_seed_does_not_write(tmp_path):
    path = tmp_path / "targets.yaml"
    store = TargetStore(str(path), SCHEMAS)
    store.load([])
    assert not path.exists()
    assert store.all() == []


def test_create_update_merge_sizing_venue_immutable(tmp_path):
    store = TargetStore(str(tmp_path / "targets.yaml"), SCHEMAS)
    store.load()
    t = store.create({
        "name": "a",
        "venue": VENUE_PREDICTIONS,
        "wallet": WALLET_A,
        "sizing": {"fixed_usd_per_fill": 10, "max_open_usd": 80},
    })
    assert t.sizing["fixed_usd_per_fill"] == 10.0
    assert t.sizing["max_open_usd"] == 80.0
    assert t.wallet == WALLET_A.lower()

    updated = store.update(t.id, {"sizing": {"fixed_usd_per_fill": 22}, "name": "renamed"})
    assert updated.name == "renamed"
    assert updated.sizing["fixed_usd_per_fill"] == 22.0
    assert updated.sizing["max_open_usd"] == 80.0  # merged, not replaced
    assert updated.venue == VENUE_PREDICTIONS

    try:
        store.update(t.id, {"venue": VENUE_PERPS})
        assert False
    except TargetError as e:
        assert "venue cannot be changed" in str(e)


def test_set_enabled_bool_only(tmp_path):
    store = TargetStore(str(tmp_path / "targets.yaml"), SCHEMAS)
    t = store.create({"name": "a", "venue": VENUE_PREDICTIONS, "wallet": WALLET_A})
    off = store.set_enabled(t.id, False)
    assert off.enabled is False
    on = store.set_enabled(t.id, True)
    assert on.enabled is True
    try:
        store.set_enabled(t.id, 1)  # type: ignore[arg-type]
        assert False
    except TargetError as e:
        assert "enabled must be true/false" in str(e)


def test_delete_conflict_when_open_positions(tmp_path):
    store = TargetStore(str(tmp_path / "targets.yaml"), SCHEMAS)
    t = store.create({"name": "a", "venue": VENUE_PREDICTIONS, "wallet": WALLET_A})
    try:
        store.delete(t.id, lambda _t: True)
        assert False
    except TargetConflict as e:
        assert "open positions" in str(e)
    assert store.get(t.id) is not None
    store.delete(t.id, lambda _t: False)
    assert store.get(t.id) is None


def test_duplicate_wallet_per_venue_rejected(tmp_path):
    store = TargetStore(str(tmp_path / "targets.yaml"), SCHEMAS)
    store.create({"name": "a", "venue": VENUE_PREDICTIONS, "wallet": WALLET_A})
    try:
        store.create({"name": "b", "venue": VENUE_PREDICTIONS, "wallet": "0x" + WALLET_A[2:].upper()})
        assert False
    except TargetError as e:
        assert "already tracked" in str(e)
    # Same wallet on a different venue is fine.
    other = store.create({"name": "perp", "venue": VENUE_PERPS, "wallet": WALLET_A})
    assert other.venue == VENUE_PERPS


def test_on_change_listeners_and_exception_isolation(tmp_path):
    store = TargetStore(str(tmp_path / "targets.yaml"), SCHEMAS)
    events: list[tuple[str, str]] = []

    def boom(event, target):
        events.append(("boom", event))
        raise RuntimeError("listener exploded")

    def ok(event, target):
        events.append((event, target.id))

    store.on_change(boom)
    store.on_change(ok)
    t = store.create({"name": "a", "venue": VENUE_PREDICTIONS, "wallet": WALLET_A})
    store.update(t.id, {"name": "b"})
    store.delete(t.id, lambda _t: False)
    kinds = [e[0] if e[0] != "boom" else e[1] for e in events]
    assert kinds.count("added") == 2  # boom + ok
    assert ("added", t.id) in events
    assert ("updated", t.id) in events
    assert ("removed", t.id) in events


def test_persisted_atomically_and_reloadable(tmp_path):
    path = tmp_path / "targets.yaml"
    store = TargetStore(str(path), SCHEMAS)
    t = store.create({
        "name": "persist-me",
        "venue": VENUE_PREDICTIONS,
        "wallet": WALLET_C,
        "copy_closes": False,
        "sizing": {"mode": "percent_of_target", "percent_of_target": 12},
    })
    assert not path.with_suffix(".yaml.tmp").exists()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["targets"][0]["id"] == t.id
    assert raw["targets"][0]["wallet"] == WALLET_C.lower()

    store2 = TargetStore(str(path), SCHEMAS)
    store2.load(seed=[{"name": "ignored", "venue": VENUE_PREDICTIONS, "wallet": WALLET_B}])
    got = store2.get(t.id)
    assert got is not None
    assert got.name == "persist-me"
    assert got.copy_closes is False
    assert got.sizing["percent_of_target"] == 12.0
    assert got.sizing["mode"] == "percent_of_target"


def test_unknown_venue_rejected(tmp_path):
    store = TargetStore(str(tmp_path / "targets.yaml"), SCHEMAS)
    try:
        store.create({"name": "x", "venue": "forex", "wallet": WALLET_A})
        assert False
    except TargetError as e:
        assert "venue must be one of" in str(e)


def test_enabled_copy_closes_must_be_bool(tmp_path):
    store = TargetStore(str(tmp_path / "targets.yaml"), SCHEMAS)
    try:
        store.create({
            "name": "x", "venue": VENUE_PREDICTIONS, "wallet": WALLET_A, "enabled": "yes",
        })
        assert False
    except TargetError:
        pass
    try:
        store.create({
            "name": "x", "venue": VENUE_PREDICTIONS, "wallet": WALLET_A, "copy_closes": 0,
        })
        assert False
    except TargetError:
        pass


def test_perps_schema_defaults():
    sizing = PERPS_SCHEMA.validate_sizing(None)
    assert sizing["mode"] == "percent_of_target"
    assert sizing["leverage"] == 3.0


def test_field_list_multiselect_text_secret_nullable():
    ids = Field(key="ids", label="IDs", type="list", default=[])
    assert ids.coerce("a, b, a\nc") == ["a", "b", "c"]
    assert ids.coerce(["x", "x", " y ", ""]) == ["x", "y"]
    assert ids.coerce("") == []
    assert ids.coerce(None) == []

    notify = Field(
        key="ev", label="Events", type="multiselect", default=[],
        options=(("a", "A"), ("b", "B")),
    )
    assert notify.coerce("a, b, a") == ["a", "b"]
    try:
        notify.coerce(["a", "z"])
        assert False
    except TargetError as e:
        assert "Events" in str(e)
        assert "z" in str(e)

    name = Field(key="name", label="Name", type="text", default="")
    assert name.coerce("  hi  ") == "hi"
    try:
        name.coerce(None)
        assert False
    except TargetError as e:
        assert str(e) == "Name must be text"
    try:
        name.coerce(["x"])
        assert False
    except TargetError as e:
        assert "must be text" in str(e)

    secret = Field(key="tok", label="Token", type="secret", default="")
    assert secret.coerce("  abc  ") == "abc"

    cap = Field(key="cap", label="Cap", type="number", default=None, min=1.0, nullable=True)
    assert cap.coerce(None) is None
    assert cap.coerce("") is None
    assert cap.coerce(5) == 5.0
    try:
        cap.coerce(0)
        assert False
    except TargetError as e:
        assert "must be at least 1" in str(e)


def test_field_unknown_type_and_to_dict():
    try:
        Field(key="x", label="X", type="dropdown", default="")
        assert False
    except ValueError as e:
        assert "unknown field type" in str(e)
        assert "dropdown" in str(e)

    basic = Field(key="n", label="N", type="number", default=1.0, min=0.5)
    d = basic.to_dict()
    assert d["group"] == GROUP_BASIC
    assert d["default"] == 1.0
    assert "nullable" not in d
    assert "restart_required" not in d

    secret = Field(key="tok", label="Token", type="secret", default="hidden")
    assert secret.to_dict()["default"] is None

    flagged = Field(
        key="p", label="P", type="boolean", default=False,
        group=GROUP_ADVANCED, nullable=True,
    )
    d2 = flagged.to_dict()
    assert d2["group"] == GROUP_ADVANCED
    assert d2["nullable"] is True
    assert "restart_required" not in d2
