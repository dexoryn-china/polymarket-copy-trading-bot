"""Copy targets — venue-agnostic model, sizing schemas, persistent store.

Each venue registers a `VenueSchema` describing its sizing fields. The same
schema validates API/config input and drives the dashboard form, so adding a
venue needs no UI change. Targets persist to `targets.yaml` (UI-editable).
"""

import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Union

import yaml

log = logging.getLogger("targets")

VENUE_PREDICTIONS = "predictions"
VENUE_PERPS = "perps"

EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

Scalar = Union[int, float, str, bool]


class TargetError(ValueError):
    """Invalid target input (maps to HTTP 400)."""


class TargetConflict(Exception):
    """Operation not allowed in the current state (maps to HTTP 409)."""


# ── Schema ──


FIELD_TYPES = {"number", "select", "boolean", "text", "secret", "list", "multiselect"}
GROUP_BASIC = "basic"
GROUP_ADVANCED = "advanced"


@dataclass(frozen=True)
class Field:
    """One user-editable value. Drives validation AND the dashboard form.

    number · select · boolean · text · secret (write-only) ·
    list (list of strings) · multiselect (subset of `options`)."""
    key: str
    label: str
    type: str
    default: Any
    options: Optional[tuple[tuple[str, str], ...]] = None   # (value, label)
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    unit: Optional[str] = None
    help: Optional[str] = None
    show_if: Optional[tuple[str, str]] = None               # (key, equals)
    group: str = GROUP_BASIC
    nullable: bool = False                                  # empty → None ("no limit")

    def __post_init__(self) -> None:
        if self.type not in FIELD_TYPES:
            raise ValueError(f"unknown field type {self.type!r} for {self.key}")

    def coerce(self, raw: Any) -> Any:
        if self.nullable and (raw is None or raw == ""):
            return None
        if self.type == "boolean":
            if isinstance(raw, bool):
                return raw
            raise TargetError(f"{self.label} must be true/false")
        if self.type == "select":
            value = str(raw)
            allowed = {v for v, _ in self.options or ()}
            if value not in allowed:
                raise TargetError(f"{self.label} must be one of {sorted(allowed)}")
            return value
        if self.type in ("text", "secret"):
            if raw is None or isinstance(raw, (dict, list)):
                raise TargetError(f"{self.label} must be text")
            return str(raw).strip()
        if self.type in ("list", "multiselect"):
            items = raw if isinstance(raw, (list, tuple)) else str(raw or "").replace("\n", ",").split(",")
            values = list(dict.fromkeys(str(i).strip() for i in items if str(i).strip()))
            if self.type == "multiselect":
                allowed = {v for v, _ in self.options or ()}
                unknown = [v for v in values if v not in allowed]
                if unknown:
                    raise TargetError(f"{self.label}: unknown option(s) {unknown}")
            return values
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise TargetError(f"{self.label} must be a number") from None
        if self.min is not None and value < self.min:
            raise TargetError(f"{self.label} must be at least {self.min:g}")
        if self.max is not None and value > self.max:
            raise TargetError(f"{self.label} must be at most {self.max:g}")
        return value

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "key": self.key, "label": self.label, "type": self.type,
            "default": None if self.type == "secret" else self.default, "group": self.group,
        }
        if self.options is not None:
            d["options"] = [{"value": v, "label": lbl} for v, lbl in self.options]
        for name in ("min", "max", "step", "unit", "help"):
            if getattr(self, name) is not None:
                d[name] = getattr(self, name)
        if self.show_if is not None:
            d["show_if"] = {"key": self.show_if[0], "equals": self.show_if[1]}
        if self.nullable:
            d["nullable"] = True
        return d


@dataclass(frozen=True)
class VenueSchema:
    id: str
    label: str
    wallet_label: str
    wallet_placeholder: str
    close_label: str
    fields: tuple[Field, ...]
    wallet_pattern: re.Pattern = EVM_ADDRESS_RE

    def validate_sizing(self, raw: Optional[dict]) -> dict[str, Scalar]:
        raw = raw or {}
        unknown = set(raw) - {f.key for f in self.fields}
        if unknown:
            raise TargetError(f"unknown sizing fields: {sorted(unknown)}")
        return {f.key: f.coerce(raw[f.key]) if f.key in raw else f.default for f in self.fields}

    def normalize_wallet(self, wallet: Any) -> str:
        value = str(wallet or "").strip()
        if not self.wallet_pattern.match(value):
            raise TargetError(f"{self.wallet_label} must match {self.wallet_pattern.pattern}")
        return value.lower()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "wallet_label": self.wallet_label,
            "wallet_placeholder": self.wallet_placeholder,
            "close_label": self.close_label,
            "sizing_fields": [f.to_dict() for f in self.fields],
        }


# ── Target ──


@dataclass
class Target:
    id: str
    name: str
    venue: str
    wallet: str
    enabled: bool = True
    copy_closes: bool = True
    sizing: dict[str, Scalar] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


ChangeListener = Callable[[str, Target], None]   # (event: "added"|"updated"|"removed", target)


class TargetStore:
    """Owns the target list; persists every change to `path`."""

    def __init__(self, path: str, schemas: dict[str, VenueSchema]) -> None:
        self.path = Path(path)
        self.schemas = schemas
        self._targets: dict[str, Target] = {}
        self._listeners: list[ChangeListener] = []

    # ── Queries ──

    def all(self, venue: Optional[str] = None) -> list[Target]:
        return [t for t in self._targets.values() if venue is None or t.venue == venue]

    def get(self, target_id: str) -> Optional[Target]:
        return self._targets.get(target_id)

    def on_change(self, fn: ChangeListener) -> None:
        self._listeners.append(fn)

    # ── Loading ──

    def load(self, seed: Optional[list[dict]] = None) -> None:
        """Load from disk; if the file doesn't exist yet, seed from config."""
        if self.path.exists():
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
            entries = raw.get("targets") or []
        else:
            entries = seed or []
        for entry in entries:
            target = self._build(entry, target_id=entry.get("id"))
            self._targets[target.id] = target
        if not self.path.exists() and self._targets:
            self._save()
            log.info(f"seeded {self.path} with {len(self._targets)} target(s) from config")

    # ── Mutations ──

    def create(self, data: dict) -> Target:
        target = self._build(data)
        self._targets[target.id] = target
        self._commit("added", target)
        return target

    def update(self, target_id: str, data: dict) -> Target:
        current = self._require(target_id)
        if data.get("venue", current.venue) != current.venue:
            raise TargetError("venue cannot be changed")
        merged = {**current.to_dict(), **data}
        if isinstance(data.get("sizing"), dict):
            merged["sizing"] = {**current.sizing, **data["sizing"]}
        target = self._build(merged, target_id=target_id)
        self._targets[target_id] = target
        self._commit("updated", target)
        return target

    def set_enabled(self, target_id: str, enabled: bool) -> Target:
        if not isinstance(enabled, bool):
            raise TargetError("enabled must be true/false")
        return self.update(target_id, {"enabled": enabled})

    def delete(self, target_id: str, has_open_positions: Callable[[Target], bool]) -> None:
        target = self._require(target_id)
        if has_open_positions(target):
            raise TargetConflict(
                f"{target.name} still has open positions — disable it instead, or wait until they close"
            )
        del self._targets[target_id]
        self._commit("removed", target)

    # ── Internals ──

    def _require(self, target_id: str) -> Target:
        target = self._targets.get(target_id)
        if target is None:
            raise KeyError(target_id)
        return target

    def _build(self, data: dict, target_id: Optional[str] = None) -> Target:
        venue = data.get("venue")
        schema = self.schemas.get(venue)
        if schema is None:
            raise TargetError(f"venue must be one of {sorted(self.schemas)}")
        wallet = schema.normalize_wallet(data.get("wallet"))
        target_id = target_id or uuid.uuid4().hex[:8]
        duplicate = next(
            (t for t in self._targets.values()
             if t.venue == venue and t.wallet == wallet and t.id != target_id),
            None,
        )
        if duplicate:
            raise TargetError(f"{schema.wallet_label} already tracked by target '{duplicate.name}'")
        name = str(data.get("name") or "").strip() or f"{wallet[:6]}…{wallet[-4:]}"
        for key in ("enabled", "copy_closes"):
            if key in data and not isinstance(data[key], bool):
                raise TargetError(f"{key} must be true/false")
        return Target(
            id=target_id,
            name=name,
            venue=venue,
            wallet=wallet,
            enabled=data.get("enabled", True),
            copy_closes=data.get("copy_closes", True),
            sizing=schema.validate_sizing(data.get("sizing")),
        )

    def _commit(self, event: str, target: Target) -> None:
        self._save()
        for fn in list(self._listeners):
            try:
                fn(event, target)
            except Exception:
                log.exception(f"target listener failed on {event} {target.id}")

    def _save(self) -> None:
        payload = {"targets": [t.to_dict() for t in self._targets.values()]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
        tmp.replace(self.path)
