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

    def on_session_start(self, t: float) -> None:
        """Called once per Godot session. Fires the class's trigger if
        it matches 'on: spawn'. Sets state=ACTIVE, queues spawn message.

        Idempotent: calling again while already ACTIVE is a no-op
        (the second spawn toast after a brain reconnect would be
        confusing; the player already saw it)."""
        if self.state != ExpeditionState.DORMANT:
            return
        trigger_on = self.class_def.get("trigger", {}).get("on", "spawn")
        if trigger_on != "spawn":
            raise NotImplementedError(
                f"trigger 'on: {trigger_on}' lands in a later commit; "
                f"v1 only implements 'on: spawn'")
        self.state = ExpeditionState.ACTIVE
        self.started_at = t
        self._queue_message("spawn")

    def on_tag_event(self, tag: dict, t: float) -> None:
        """Receive a tag event from Godot. Append to log unconditionally
        — the tag_log is the source of truth for post-mortem regardless
        of whether the tag ever deposits. Deposit happens separately
        via on_deposit_intent when proximity is reported."""
        if self.state == ExpeditionState.DORMANT:
            return  # dropped on the floor before start
        self.tag_log.append(dict(tag))

    def on_deposit_intent(
        self,
        deposit_id: str,
        tag_id: int,
        t: float,
    ) -> dict:
        """Godot reports player is near `deposit_id` with tag `tag_id`.
        Engine matches the tag against the point's accepts rule.

        Returns:
            {"accepted": bool, "reason": str, "deposit": <dpt snapshot>}

        Idempotent: same tag_id deposited twice at the same point is a
        no-op and returns accepted=False with reason='already_deposited'.
        """
        if self.state not in (
            ExpeditionState.ACTIVE, ExpeditionState.RESOLUTION,
        ):
            return {
                "accepted": False,
                "reason": "wrong_state",
                "deposit": None,
            }

        # Find the deposit point
        dpt: DepositPointState | None = None
        for point in self.deposit_points:
            if point.id == deposit_id:
                dpt = point
                break
        if dpt is None:
            return {
                "accepted": False,
                "reason": "unknown_deposit",
                "deposit": None,
            }

        # Already deposited?
        if tag_id in dpt.deposited_tag_ids:
            return {
                "accepted": False,
                "reason": "already_deposited",
                "deposit": self._deposit_snapshot(dpt),
            }

        # Find the tag in the log
        tag: dict | None = self._find_tag_by_id(tag_id)
        if tag is None:
            return {
                "accepted": False,
                "reason": "tag_not_in_log",
                "deposit": self._deposit_snapshot(dpt),
            }

        # Match against accepts rule
        if not self._tag_matches_accepts(tag, dpt.accepts):
            return {
                "accepted": False,
                "reason": "rejected_by_accepts",
                "deposit": self._deposit_snapshot(dpt),
            }

        # Satisfied? no more deposits once satisfied
        if dpt.satisfied:
            return {
                "accepted": False,
                "reason": "already_satisfied",
                "deposit": self._deposit_snapshot(dpt),
            }

        # Accept.
        dpt.current += 1
        dpt.deposited_tag_ids.append(tag_id)

        # Milestone + satisfaction checks land in commit 4.
        self._emit_milestones_if_any(dpt)
        self._check_satisfaction(dpt)
        self._activate_exit_if_ready()

        return {
            "accepted": True,
            "reason": "accepted",
            "deposit": self._deposit_snapshot(dpt),
        }

    # -- walk-through + session log ------------------------------------------

    def on_walk_through(
        self,
        t: float,
        sessions_dir: Path,
    ) -> dict:
        """Player walked through the active exit point. Finalize,
        write the session log, return the resolution payload for
        the brain to ack to Godot.

        If the exit point is not active (player walked through the
        arch before all deposits were satisfied), no-op with a
        clear payload — the arch just doesn't do anything yet.
        """
        if self.exit_point is None:
            return {
                "resolution": "no_exit",
                "quit_godot": False,
                "log_path": None,
            }
        if not self.exit_point.active:
            return self.on_walk_through_inactive(t)

        # Finalize
        self.state = ExpeditionState.COMPLETE
        self.completed_at = t
        self._queue_message("complete")

        # Write log
        on_complete = self.class_def.get("on_complete", {})
        log_path: Path | None = None
        if on_complete.get("write_session_log", False):
            log_path = self.write_session_log(sessions_dir, t)

        # Forbidden-for-v1 resolution actions: raise loudly if a
        # future recipe set one without engine support.
        for forbidden in ("write_scout_report", "write_journal_entry"):
            if on_complete.get(forbidden, False):
                raise NotImplementedError(
                    f"on_complete.{forbidden} is declared by the recipe "
                    f"but the engine does not implement it yet")

        return {
            "resolution": "complete",
            "quit_godot": bool(on_complete.get("quit_godot", False)),
            "log_path": str(log_path) if log_path is not None else None,
        }

    def on_walk_through_inactive(self, t: float) -> dict:
        """Exit is not yet active. No state change, no log write,
        just a courtesy payload."""
        return {
            "resolution": "exit_inactive",
            "quit_godot": False,
            "log_path": None,
        }

    def write_session_log(
        self,
        sessions_dir: Path,
        t: float,
    ) -> Path:
        """Dump the full expedition record as JSON. This file is
        what I read post-mortem to correlate tags, screenshots,
        and perf telemetry."""
        sessions_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(t))
        log_path = sessions_dir / f"expedition_{ts}.json"

        payload: dict = {
            "class_id": self.class_id,
            "biome": self.biome,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_s": (
                (self.completed_at or t) - (self.started_at or t)
            ),
            "final_state": self.state.value,
            "resolved_messages": dict(self.resolved_messages),
            "deposit_points": [
                {
                    "id": d.id,
                    "kind": d.kind,
                    "pos": list(d.pos),
                    "accepts": list(d.accepts),
                    "current": d.current,
                    "threshold": d.threshold,
                    "satisfied": d.satisfied,
                    "deposited_tag_ids": list(d.deposited_tag_ids),
                }
                for d in self.deposit_points
            ],
            "exit_point": (
                {
                    "id": self.exit_point.id,
                    "kind": self.exit_point.kind,
                    "pos": list(self.exit_point.pos),
                    "trigger_radius": self.exit_point.trigger_radius,
                    "active": self.exit_point.active,
                }
                if self.exit_point is not None else None
            ),
            "tag_log": list(self.tag_log),
            "messages_emitted": list(self.messages_emitted),
        }

        with log_path.open("w") as f:
            json.dump(payload, f, indent=2)
        return log_path

    # -- snapshot for manifest -----------------------------------------------

    def snapshot(self) -> dict:
        """Pure read. Produces the manifest['expedition'] dict that
        Godot renders generically. Godot has no recipe-specific
        knowledge; it draws exactly what this dict declares.

        The `last_message` field carries any pending message key;
        Godot toasts once per key change and brain calls
        consume_message() after each manifest send so the same
        key is not reported twice."""
        return {
            "id": self.class_id,
            "biome": self.biome,
            "state": self.state.value,
            "objective_text": self.class_def.get("objective_text", ""),
            "deposit_points": [
                {
                    "id": d.id,
                    "kind": d.kind,
                    "pos": list(d.pos),
                    "current": d.current,
                    "threshold": d.threshold,
                    "satisfied": d.satisfied,
                    "visual": dict(d.visual),
                }
                for d in self.deposit_points
            ],
            "exit_point": (
                {
                    "id": self.exit_point.id,
                    "kind": self.exit_point.kind,
                    "pos": list(self.exit_point.pos),
                    "active": self.exit_point.active,
                    "trigger_radius": self.exit_point.trigger_radius,
                    "visual": dict(self.exit_point.visual),
                }
                if self.exit_point is not None else None
            ),
            "last_message": self.pending_message_key,
            "last_message_text": (
                self.resolved_messages.get(self.pending_message_key, "")
                if self.pending_message_key is not None else ""
            ),
        }

    def consume_message(self) -> None:
        """Called by brain after each frame's manifest has shipped.
        Clears pending_message_key so the same key isn't toasted twice."""
        self.pending_message_key = None

    # -- internal helpers -----------------------------------------------------

    def _queue_message(self, key: str) -> None:
        """Mark a message key as pending. Brain attaches it to the
        snapshot on the next frame; Godot toasts once; brain calls
        consume_message() to clear. Milestones that would duplicate
        an already-emitted message are skipped."""
        if key in self.messages_emitted:
            return
        self.pending_message_key = key
        self.messages_emitted.append(key)

    def _find_tag_by_id(self, tag_id: int) -> dict | None:
        for t in self.tag_log:
            if t.get("tag_id") == tag_id or t.get("tag") == tag_id:
                return t
        return None

    def _tag_matches_accepts(
        self,
        tag: dict,
        accepts: list[str],
    ) -> bool:
        """Tag is accepted if:
          - the point accepts 'any' (wildcard), OR
          - the tag's reason is in the accepts list."""
        if "any" in accepts:
            return True
        reason = tag.get("tag_reason", "neutral")
        return reason in accepts

    def _deposit_snapshot(self, dpt: DepositPointState) -> dict:
        return {
            "id": dpt.id,
            "kind": dpt.kind,
            "pos": list(dpt.pos),
            "current": dpt.current,
            "threshold": dpt.threshold,
            "satisfied": dpt.satisfied,
        }

    def _emit_milestones_if_any(self, dpt: DepositPointState) -> None:
        """After each accepted deposit, decide whether to emit a
        milestone message.

        v1 rules (single deposit point):
          - first accepted deposit anywhere → 'first_tag'
          - total progress crosses 50% of total threshold → 'halfway'
          - all deposits satisfied → 'satisfied'

        Multi-deposit recipes (WITNESSES, PILGRIMAGE) will grow this
        into per-point milestones in later commits.
        """
        # first_tag: any deposit on an engine that had zero progress
        # before now. Emitted once per session.
        if dpt.current == 1 and "first_tag" not in self.messages_emitted:
            self._queue_message("first_tag")

        # halfway: total progress crosses 50% of total threshold.
        total_current = sum(d.current for d in self.deposit_points)
        total_threshold = sum(d.threshold for d in self.deposit_points)
        if total_threshold > 0:
            pct = total_current / total_threshold
            if pct >= 0.5 and "halfway" not in self.messages_emitted:
                # Don't emit halfway if we're already at 100% — jump
                # straight to 'satisfied' below.
                if pct < 1.0:
                    self._queue_message("halfway")

    def _check_satisfaction(self, dpt: DepositPointState) -> None:
        """Mark the deposit point satisfied if current >= threshold.
        Cap current at threshold to keep snapshot clean."""
        if dpt.current >= dpt.threshold:
            dpt.current = dpt.threshold
            dpt.satisfied = True

    def _activate_exit_if_ready(self) -> None:
        """If every deposit point is satisfied, activate the exit
        point, transition to RESOLUTION, and emit the 'satisfied'
        message."""
        if not self.deposit_points:
            return
        if not all(d.satisfied for d in self.deposit_points):
            return
        if self.exit_point is not None and not self.exit_point.active:
            self.exit_point.active = True
            self.state = ExpeditionState.RESOLUTION
            self._queue_message("satisfied")
