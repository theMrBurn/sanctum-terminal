"""Consequence effect handlers — named side effects fired when a
resolution predicate returns True.

Effect handlers run brain-side. They mutate world state, push events,
emit StateEvents, etc. Per `feedback_brain_owns_config`, effect
implementation lives here, not on the consequence dataclass.

The `instance` argument gives handlers read access to the spawn-time
context (`instance.context`) and read/write access to per-instance
progress (`instance.progress`). Removal is automatic — the engine
removes resolved instances at end of tick — so handlers never need a
`remove_self` call. Per `design_reflective_loop`, this keeps the
substrate's lifecycle pure: predicates gate, effects mutate world,
engine handles bookkeeping.

Built-in handlers (regen_world, restore_hp, emit_state_event) land in
step 3 of PR 3. This module ships in step 1 with no built-ins; the
substrate is testable on its own with locally-registered fixtures.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol


class WorldLike(Protocol):
    player: Any


# `instance` is typed Any to avoid circular import on
# ConsequenceInstance. Handlers may read instance.context and
# read/write instance.progress.
EffectFn = Callable[[WorldLike, dict, Any], None]
"""Signature: (world, args, instance) -> None

  world    : the brain world (mutable)
  args     : effect config from the resolution_effects entry
  instance : the live ConsequenceInstance — handlers may read
             instance.context and read/write instance.progress
"""


_REGISTRY: dict[str, EffectFn] = {}


def register(name: str) -> Callable[[EffectFn], EffectFn]:
    """Decorator: `@register("regen_world")` adds an effect handler by name."""
    def decorator(fn: EffectFn) -> EffectFn:
        if name in _REGISTRY:
            raise ValueError(f"effect already registered: {name!r}")
        _REGISTRY[name] = fn
        return fn
    return decorator


def get(name: str) -> EffectFn | None:
    return _REGISTRY.get(name)


def all_effects() -> dict[str, EffectFn]:
    return dict(_REGISTRY)


def clear() -> None:
    """Test-only — reset the registry."""
    _REGISTRY.clear()


# ── Built-in effect handlers ────────────────────────────────────────


def _regen_world(world, args: dict, instance) -> None:
    """Reseed and wipe cached world state.

    args:
      reseed: "random" — pick a fresh int seed via random.randint
              <int>    — use this seed exactly

    Per `design_death_only_regen` and `design_virtual_hallucination`:
    the procedural expedition regenerates; the hub stays authored;
    quests, character, and vault persist (handled elsewhere — this
    effect only mutates world tiles/entities/spawns).
    """
    import random as _random

    reseed = args.get("reseed", "random")
    if reseed == "random":
        new_seed = _random.randint(0, 2**31 - 1)
    else:
        new_seed = int(reseed)
    world.regen_world(new_seed)


def _restore_hp(world, args: dict, instance) -> None:
    """Reset player HP after respawn.

    args:
      to: "full" — set hp to max_hp
          <int>  — set hp to this exact value (clamped to max_hp)

    Mutates world.player via PlayerState._replace — PlayerState is a
    NamedTuple, so we never edit fields in place.
    """
    target = args.get("to", "full")
    player = world.player
    if target == "full":
        new_hp = player.max_hp
    else:
        new_hp = min(int(target), player.max_hp)
    world.player = player._replace(hp=new_hp)


def _emit_state_event(world, args: dict, instance) -> None:
    """Push a StateEvent through `world.state_events` for client toast.

    args:
      kind:     str — routing key (e.g. "respawn")
      label:    str — short ALL-CAPS top line
      detail:   str | None — optional second line
      register: str — pacing hint (loop / system / tense / ritual / discovery)

    No-op if world has no state_events buffer (defensive — tests can
    pass minimal world fakes that don't bother with the buffer).
    """
    buffer = getattr(world, "state_events", None)
    if buffer is None:
        return
    buffer.emit(
        kind=str(args.get("kind", "consequence")),
        label=str(args.get("label", "")),
        detail=args.get("detail"),
        register=str(args.get("register", "system")),
    )


def register_builtins() -> None:
    """(Re)-register built-in effect handlers. Idempotent. Module
    import auto-calls this. Tests with a `clean` fixture call this in
    teardown so subsequent tests see the built-ins."""
    if "regen_world" not in _REGISTRY:
        _REGISTRY["regen_world"] = _regen_world
    if "restore_hp" not in _REGISTRY:
        _REGISTRY["restore_hp"] = _restore_hp
    if "emit_state_event" not in _REGISTRY:
        _REGISTRY["emit_state_event"] = _emit_state_event


# Auto-register on import.
register_builtins()
