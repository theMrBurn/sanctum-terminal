"""Consequences engine — cause/effect substrate for non-quest causation.

Per `design_reflective_loop` and `design_virtual_hallucination`:
consequences are first-class objects that spawn on a trigger predicate
and resolve via a resolution predicate + effect list. Same shape as
quests, separate registry, different lifecycle: a quest is authored
intent; a consequence is reactive causation.

This is the substrate the HP=0 respawn flow runs through. The same
engine will later host reflective-mode entry/exit, tension cycle
resolution, atom_skin_destruction cause/effect, and elemental_wire
pulse handlers. PR 3 ships the substrate plus one consumer
(hp_zero_respawn) wired in subsequent steps.

A `Consequence` is the registered shape (config row, frozen).
A `ConsequenceInstance` is a live object on `world.consequences[]` that
spawns when a trigger fires, advances per tick, and is removed on
resolution. The instance carries a `context` snapshot taken at spawn
so the resolution path can branch on state-at-spawn without re-querying
world — see `feedback_iterate_then_formalize` and the dynamic-gating
discussion in `design_reflective_loop`.

Definitions live in `config/consequences.json` and load via
`core.systems.consequences.definitions`. Predicate evaluation, instance
lifecycle, and effect dispatch live in `tick.py`. Brain-loop wiring
calls `consequences.tick(world, events)` per frame after `quest_tick`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Effect:
    """A single named action with config args. Effect handlers live in
    `effects.py`, keyed by `name`."""
    name: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Consequence:
    """Registered shape of a consequence — one row in consequences.json.

    `trigger_predicate` fires the spawn. `resolution_predicate` gates
    the effects (None means resolve on the next tick after spawn).
    `resolution_effects` run when resolution fires.

    `one_shot=True` prevents double-spawn while an instance for this
    config_id already exists on the world — useful for held trigger
    conditions (e.g. HP stays at 0 across multiple ticks before regen).
    """
    id: str
    trigger_predicate: str
    trigger_args: dict = field(default_factory=dict)
    resolution_predicate: str | None = None
    resolution_args: dict = field(default_factory=dict)
    resolution_effects: list[Effect] = field(default_factory=list)
    one_shot: bool = False


InstanceState = Literal["pending", "resolving", "resolved"]


@dataclass
class ConsequenceInstance:
    """Live object on `world.consequences[]`. Spawned when a Consequence's
    trigger fires; lives until resolved.

    `context` is a snapshot of state-at-spawn (tick, HP, position, …)
    so resolution can branch on it without re-querying world. Per
    `feedback_iterate_then_formalize` — the snapshot is what makes
    dynamic gating work without freezing the resolution shape early.

    `progress` is mutable per-instance state predicates may write into
    (analogous to `QuestState.progress`).
    """
    config_id: str
    spawned_tick: int
    state: InstanceState = "pending"
    context: dict = field(default_factory=dict)
    progress: dict = field(default_factory=dict)


_REGISTRY: dict[str, Consequence] = {}


def register(consequence: Consequence) -> None:
    if consequence.id in _REGISTRY:
        raise ValueError(f"consequence already registered: {consequence.id!r}")
    _REGISTRY[consequence.id] = consequence


def get(consequence_id: str) -> Consequence | None:
    return _REGISTRY.get(consequence_id)


def all_consequences() -> dict[str, Consequence]:
    """Snapshot of the registry. Tests + brain manifest both consume this."""
    return dict(_REGISTRY)


def clear() -> None:
    """Test-only — reset the registry."""
    _REGISTRY.clear()


# Import definition modules to trigger registration. Same pattern as
# `core.systems.quests.__init__`.
from core.systems.consequences import definitions as _definitions  # noqa: E402, F401
