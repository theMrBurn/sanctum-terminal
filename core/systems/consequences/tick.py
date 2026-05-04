"""Per-frame consequences engine tick.

Called once per brain main-loop iteration after `quest_tick.tick()`
and BEFORE `world.tick_events.clear()` — both engines read the same
event accumulator, and we don't want consequences to swallow events
quests need.

Three phases per tick:

  1. Trigger phase — for each registered Consequence whose trigger
     predicate matches current events/world state, spawn a new
     `ConsequenceInstance`. `one_shot=True` consequences skip spawn
     when an instance for the same config_id already exists.

  2. Resolution phase — for each pending instance, evaluate its
     resolution predicate. None means "resolve immediately"; True
     means "run effects now"; False means "stay pending".

  3. Cleanup phase — remove resolved instances from
     `world.consequences[]`.

The engine never raises on missing predicate / effect names — the
production world should not crash on a typo in consequences.json.
Tests at module-import time catch typo'd references.
"""
from __future__ import annotations

from core.systems.consequences import (
    Consequence,
    ConsequenceInstance,
    all_consequences,
    get as get_consequence,
)
from core.systems.consequences import effects as effects_module
from core.systems.consequences import predicates as predicates_module


def tick(world, events: list[dict]) -> None:
    """One-frame consequences pass. See module doc."""
    if not hasattr(world, "consequences"):
        # Brain hasn't initialized world.consequences[] yet — defensive
        # no-op so unit tests can run on bare worlds.
        return

    current_tick = int(getattr(world, "tick_count", 0))

    _trigger_phase(world, events, current_tick)
    _resolution_phase(world, events)

    # Cleanup — drop resolved instances. List comprehension preserves
    # order for the remaining pending/resolving instances.
    world.consequences = [c for c in world.consequences if c.state != "resolved"]


def _trigger_phase(world, events: list[dict], current_tick: int) -> None:
    """Spawn ConsequenceInstance for any Consequence whose trigger fires."""
    for cfg_id, consequence in all_consequences().items():
        if consequence.one_shot and any(
            inst.config_id == cfg_id for inst in world.consequences
        ):
            continue
        fn = predicates_module.get(consequence.trigger_predicate)
        if fn is None:
            continue
        # Trigger predicates use ephemeral progress (not persisted).
        if fn(world, dict(consequence.trigger_args), {}, events):
            instance = ConsequenceInstance(
                config_id=cfg_id,
                spawned_tick=current_tick,
                state="pending",
                context=_snapshot_context(world),
                progress={},
            )
            world.consequences.append(instance)


def _resolution_phase(world, events: list[dict]) -> None:
    """Advance pending instances toward resolution."""
    for instance in list(world.consequences):
        if instance.state != "pending":
            continue
        consequence = get_consequence(instance.config_id)
        if consequence is None:
            # Config row was removed but live instance lingers — mark
            # resolved so cleanup drops it. Should not happen in
            # production but defensive.
            instance.state = "resolved"
            continue
        if consequence.resolution_predicate is None:
            # Resolve immediately on the tick after spawn.
            _run_effects(world, instance, consequence)
            continue
        fn = predicates_module.get(consequence.resolution_predicate)
        if fn is None:
            continue
        if fn(
            world,
            dict(consequence.resolution_args),
            instance.progress,
            events,
        ):
            _run_effects(world, instance, consequence)


def _run_effects(
    world,
    instance: ConsequenceInstance,
    consequence: Consequence,
) -> None:
    """Dispatch resolution effects in order, then mark instance resolved."""
    instance.state = "resolving"
    for effect in consequence.resolution_effects:
        fn = effects_module.get(effect.name)
        if fn is None:
            continue
        fn(world, dict(effect.args), instance)
    instance.state = "resolved"


def _snapshot_context(world) -> dict:
    """Capture state-at-spawn for downstream branching. Kept minimal in
    PR 3; extend as new gating needs appear."""
    player = getattr(world, "player", None)
    return {
        "tick": int(getattr(world, "tick_count", 0)),
        "player_hp": getattr(player, "hp", None) if player is not None else None,
        "player_pos": _player_pos(player),
    }


def _player_pos(player) -> tuple[float, float] | None:
    if player is None:
        return None
    x = getattr(player, "x", None)
    z = getattr(player, "z", None)
    if x is None or z is None:
        return None
    return (float(x), float(z))
