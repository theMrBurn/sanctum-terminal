"""Expedition engine — resolves recipes, runs state machine, emits
snapshot for manifest consumption by Godot.

One engine, many recipes. Recipes live in expedition_data.py as pure
data and declare symbolic anchors (select_by). Biome bindings resolve
symbols to concrete kind+pos pairs at engine construction time.

Runtime is a small state machine:

    DORMANT ──on_session_start──▶ ACTIVE
       ACTIVE ──deposit to satisfy all points──▶ RESOLUTION
       RESOLUTION ──on_walk_through──▶ COMPLETE

`snapshot()` produces manifest['expedition'] — a pure-read dict that
Godot renders generically. Godot has no recipe-specific knowledge;
it draws whatever the snapshot declares.

Per the plan-before-code discipline, the engine accepts the full
schema (select_by, accepts, threshold, visual, messages, triggers,
resolution actions) even if v1 only implements a subset. Features
beyond v1 raise NotImplementedError so they fail loud when a future
recipe reaches for them before the engine has grown that branch.

See design_render_manifest, design_hub_and_spoke, project_hub_poc
for the architectural context. See expedition_data.py for recipes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import json
import time


# -- Exceptions ---------------------------------------------------------------


class ClassNotBiomeAgnostic(ValueError):
    """Raised when an expedition class contains absolute coordinates,
    kind names, or `select_at` — all three are forbidden at the class
    level. Only `select_by` symbolic anchors are allowed."""


class ClassNotInBiome(ValueError):
    """Raised when a class is instantiated against a biome whose
    binding does not list it in `active_classes`."""


class MissingAnchorBinding(KeyError):
    """Raised when a recipe's `select_by` symbol has no entry in the
    biome binding's `anchors` dict."""


class UnknownExpeditionClass(KeyError):
    """Raised when `from_class_id` is called with an id not present
    in EXPEDITION_CLASSES."""


class UnknownBiome(KeyError):
    """Raised when `from_class_id` is called with a biome not present
    in BIOME_EXPEDITIONS."""


# -- Dataclasses --------------------------------------------------------------


class ExpeditionState(str, Enum):
    DORMANT = "dormant"          # engine built, trigger not fired
    ACTIVE = "active"            # accepting tags, deposits open
    RESOLUTION = "resolution"    # all deposits satisfied, exit active
    COMPLETE = "complete"        # walk-through happened, log written


@dataclass
class DepositPointState:
    id: str
    kind: str
    pos: tuple[float, float, float]
    accepts: list[str]
    threshold: int
    current: int = 0
    satisfied: bool = False
    visual: dict = field(default_factory=dict)
    deposited_tag_ids: list[int] = field(default_factory=list)


@dataclass
class ExitPointState:
    id: str
    kind: str
    pos: tuple[float, float, float]
    trigger_radius: float
    active: bool = False
    visual: dict = field(default_factory=dict)


# -- Engine -------------------------------------------------------------------


# Keys that are forbidden at the class level. `pos`, `kind`, and
# `select_at` are all signals that a class has leaked biome-specific
# state. Only `select_by` is allowed.
_FORBIDDEN_CLASS_KEYS: frozenset[str] = frozenset(["pos", "kind", "select_at"])

# Message keys the engine knows how to emit as milestones.
_MESSAGE_KEYS: frozenset[str] = frozenset([
    "spawn", "first_tag", "halfway", "satisfied", "complete",
])


class ExpeditionEngine:
    """State machine + symbol resolver + snapshot emitter.

    Construction:
        engine = ExpeditionEngine(class_def, biome, binding)
        engine = ExpeditionEngine.from_class_id(class_id, biome)

    Lifetime:
        engine.on_session_start(t)
        # ... loop:
        engine.on_tag_event(tag, t)
        engine.on_deposit_intent(deposit_id, tag_id, t)
        engine.snapshot()               # attach to manifest
        engine.consume_message()        # after each manifest send
        # ...
        engine.on_walk_through(t, sessions_dir)
    """

    def __init__(
        self,
        class_def: dict,
        biome: str,
        binding: dict,
    ) -> None:
        self._validate_class_is_biome_agnostic(class_def)
        self._validate_class_active_in_biome(class_def, binding)

        self.class_def: dict = class_def
        self.biome: str = biome
        self.binding: dict = binding
        self.class_id: str = class_def["id"]

        # Resolve symbols + merge messages now. After construction the
        # engine never touches class_def or binding directly — runtime
        # state is the source of truth.
        self.resolved_messages: dict[str, str] = self._merge_messages(
            class_def, binding)
        self.deposit_points: list[DepositPointState] = \
            self._resolve_deposit_points(class_def, binding)
        self.exit_point: ExitPointState | None = \
            self._resolve_exit_point(class_def, binding)

        # Runtime state
        self.state: ExpeditionState = ExpeditionState.DORMANT
        self.tag_log: list[dict] = []
        self.pending_message_key: str | None = None
        self.messages_emitted: list[str] = []
        self.started_at: float | None = None
        self.completed_at: float | None = None

    # -- class method construction --------------------------------------------

    @classmethod
    def from_class_id(
        cls,
        class_id: str,
        biome: str,
    ) -> "ExpeditionEngine":
        """Look up class in EXPEDITION_CLASSES, binding in
        BIOME_EXPEDITIONS, instantiate.

        Lazy-imports expedition_data so tests can inject synthetic
        classes/bindings via the direct constructor without loading
        the real module.
        """
        from core.systems.expedition_data import (
            EXPEDITION_CLASSES,
            BIOME_EXPEDITIONS,
        )
        if class_id not in EXPEDITION_CLASSES:
            raise UnknownExpeditionClass(
                f"unknown expedition class {class_id!r}; "
                f"known: {sorted(EXPEDITION_CLASSES)}")
        if biome not in BIOME_EXPEDITIONS:
            raise UnknownBiome(
                f"unknown biome {biome!r}; "
                f"known: {sorted(BIOME_EXPEDITIONS)}")
        return cls(
            class_def=EXPEDITION_CLASSES[class_id],
            biome=biome,
            binding=BIOME_EXPEDITIONS[biome],
        )

    # -- validation -----------------------------------------------------------

    def _validate_class_is_biome_agnostic(self, class_def: dict) -> None:
        """Walk class_def recursively; raise if any forbidden key appears."""
        self._assert_no_forbidden_keys(class_def, path="<root>")

    def _assert_no_forbidden_keys(self, node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _FORBIDDEN_CLASS_KEYS:
                    raise ClassNotBiomeAgnostic(
                        f"class contains forbidden key {k!r} at {path}; "
                        f"classes must use `select_by` instead of {k!r}")
                self._assert_no_forbidden_keys(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                self._assert_no_forbidden_keys(item, f"{path}[{i}]")

    def _validate_class_active_in_biome(
        self,
        class_def: dict,
        binding: dict,
    ) -> None:
        class_id = class_def.get("id", "<unknown>")
        active = binding.get("active_classes", [])
        if class_id not in active:
            raise ClassNotInBiome(
                f"class {class_id!r} is not in active_classes {active!r}")

    # -- resolution -----------------------------------------------------------

    def _merge_messages(
        self,
        class_def: dict,
        binding: dict,
    ) -> dict[str, str]:
        """Class defaults under; biome overrides for this class on top."""
        merged: dict[str, str] = {}
        class_messages: dict = class_def.get("messages", {})
        for k, v in class_messages.items():
            merged[k] = v
        overrides: dict = binding.get("message_overrides", {}).get(
            class_def["id"], {})
        for k, v in overrides.items():
            merged[k] = v
        return merged

    def _lookup_anchor(self, symbol: str, binding: dict) -> dict:
        anchors: dict = binding.get("anchors", {})
        if symbol not in anchors:
            raise MissingAnchorBinding(
                f"anchor {symbol!r} not declared in biome binding; "
                f"known anchors: {sorted(anchors)}")
        return anchors[symbol]

    def _resolve_deposit_points(
        self,
        class_def: dict,
        binding: dict,
    ) -> list[DepositPointState]:
        points: list[DepositPointState] = []
        raw_points: list = class_def.get("deposit_points", [])
        for raw in raw_points:
            symbol: str = raw["select_by"]
            anchor = self._lookup_anchor(symbol, binding)
            kind: str = anchor["kind"]
            pos_xy: list[float] = anchor["pos"]
            # Anchors are 2D (world x, y); engine stores 3D with z=0.
            # Godot reads pos as [x, y, z] from the snapshot.
            pos3: tuple[float, float, float] = (
                float(pos_xy[0]), float(pos_xy[1]), 0.0)
            points.append(DepositPointState(
                id=raw["id"],
                kind=kind,
                pos=pos3,
                accepts=list(raw.get("accepts", ["any"])),
                threshold=int(raw.get("threshold", 1)),
                visual=dict(raw.get("satisfied_visual", {})),
            ))
        return points

    def _resolve_exit_point(
        self,
        class_def: dict,
        binding: dict,
    ) -> ExitPointState | None:
        raw: dict | None = class_def.get("exit_point")
        if raw is None:
            return None
        symbol: str = raw["select_by"]
        anchor = self._lookup_anchor(symbol, binding)
        kind: str = anchor["kind"]
        pos_xy: list[float] = anchor["pos"]
        pos3: tuple[float, float, float] = (
            float(pos_xy[0]), float(pos_xy[1]), 0.0)
        return ExitPointState(
            id=raw["id"],
            kind=kind,
            pos=pos3,
            trigger_radius=float(raw.get("trigger_radius", 2.0)),
            visual=dict(raw.get("active_visual", {})),
        )

    # -- lifecycle -------------------------------------------------------------
    # (filled in by later commits)

    def on_session_start(self, t: float) -> None:
        raise NotImplementedError("lifecycle lands in commit 3")

    def on_tag_event(self, tag: dict, t: float) -> None:
        raise NotImplementedError("lifecycle lands in commit 3")

    def on_deposit_intent(
        self,
        deposit_id: str,
        tag_id: int,
        t: float,
    ) -> dict:
        raise NotImplementedError("lifecycle lands in commit 3")

    def on_walk_through(
        self,
        t: float,
        sessions_dir: Path,
    ) -> dict:
        raise NotImplementedError("walk-through lands in commit 5")

    def on_walk_through_inactive(self, t: float) -> dict:
        raise NotImplementedError("walk-through lands in commit 5")

    def snapshot(self) -> dict:
        raise NotImplementedError("snapshot lands in commit 6")

    def consume_message(self) -> None:
        raise NotImplementedError("snapshot lands in commit 6")

    def write_session_log(
        self,
        sessions_dir: Path,
        t: float,
    ) -> Path:
        raise NotImplementedError("log writer lands in commit 5")
