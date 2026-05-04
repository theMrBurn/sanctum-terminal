"""Consequence predicates — named yes/no functions evaluated per tick.

Same shape as `core.systems.quests.predicates`, separate registry.
Quest predicates evaluate per-quest progress against per-tick events;
consequence predicates evaluate per-instance progress against per-tick
events too, but the trigger-vs-resolution split gives them two
distinct invocation moments per consequence.

The two registries don't share namespace deliberately:
- Quest predicates have a single role (completion check).
- Consequence predicates serve two roles (trigger spawn + resolution
  gate) and may want different built-ins per role.

Decorator pattern is copied verbatim from quests for consistency. The
30-line duplication earns its keep via clean semantic separation per
`design_render_reuse_mandate`.

Built-in predicates land in step 2 of PR 3 (`hp_zero`) and beyond.
This module ships in step 1 with no built-ins; the substrate is
testable on its own with locally-registered fixtures.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol


class WorldLike(Protocol):
    """Structural type for what predicates may read off `world`. Loose
    so this module avoids importing BrainWorld directly (circular)."""
    player: Any
    entities: Any


PredicateFn = Callable[[WorldLike, dict, dict, list[dict]], bool]
"""Signature: (world, static_args, progress, events) -> match?

Same shape as quest predicates. See `core.systems.quests.predicates`
for full doc.
"""


_REGISTRY: dict[str, PredicateFn] = {}


def register(name: str) -> Callable[[PredicateFn], PredicateFn]:
    """Decorator: `@register("hp_zero")` adds a predicate by name."""
    def decorator(fn: PredicateFn) -> PredicateFn:
        if name in _REGISTRY:
            raise ValueError(f"predicate already registered: {name!r}")
        _REGISTRY[name] = fn
        return fn
    return decorator


def get(name: str) -> PredicateFn | None:
    return _REGISTRY.get(name)


def all_predicates() -> dict[str, PredicateFn]:
    return dict(_REGISTRY)


def clear() -> None:
    """Test-only — reset the registry."""
    _REGISTRY.clear()


# ── Built-in predicates ──────────────────────────────────────────────


def _hp_zero(
    world: WorldLike,
    args: dict,
    progress: dict,
    events: list[dict],
) -> bool:
    """True when a `hp_zero` event was pushed onto tick_events this frame.

    The brain pushes the event from `signals.push_hp_zero(world)`
    whenever `world.player.hp <= 0` after a damage mutator. One
    detection site per damage path; the predicate just reads the event
    accumulator.

    Per `design_virtual_hallucination`: this is JUST a respawn
    condition — no perma-death framing in the code identifier or path.

    args: none.
    """
    for evt in events:
        if evt.get("type") == "hp_zero":
            return True
    return False


def _reflective_committed_from_hp_zero(
    world: WorldLike,
    args: dict,
    progress: dict,
    events: list[dict],
) -> bool:
    """True when the player committed a successful poem AFTER the
    HP=0 forced entry path. Brain's commit_reflective cmd handler
    emits this event on AC success when world.reflective.trigger ==
    'hp_zero'.

    Drives the second-half of the HP=0 chain: exit reflective + regen
    world + restore HP + emit RESPAWN. See `reflective_commit_resume`
    in config/consequences.json.

    args: none.
    """
    for evt in events:
        if evt.get("type") == "reflective_committed_from_hp_zero":
            return True
    return False


def _reflective_committed_voluntary(
    world: WorldLike,
    args: dict,
    progress: dict,
    events: list[dict],
) -> bool:
    """True when the player committed a successful poem from a
    voluntary entry (walked up to the fridge in hub). Brain's
    commit_reflective cmd handler emits this event when
    world.reflective.trigger == 'voluntary'.

    Drives the voluntary commit chain: exit reflective + emit
    REFLECTIVE_COMPLETE. No regen, no HP restore — voluntary entry
    doesn't have a respawn payload. See `reflective_commit_voluntary`
    in config/consequences.json.

    args: none.
    """
    for evt in events:
        if evt.get("type") == "reflective_committed_voluntary":
            return True
    return False


def register_builtins() -> None:
    """(Re)-register built-in predicates. Idempotent. Module import
    auto-calls this. Tests with a `clean` fixture call this in teardown
    so subsequent tests see the built-ins."""
    if "hp_zero" not in _REGISTRY:
        _REGISTRY["hp_zero"] = _hp_zero
    if "reflective_committed_from_hp_zero" not in _REGISTRY:
        _REGISTRY["reflective_committed_from_hp_zero"] = _reflective_committed_from_hp_zero
    if "reflective_committed_voluntary" not in _REGISTRY:
        _REGISTRY["reflective_committed_voluntary"] = _reflective_committed_voluntary


# Auto-register on import.
register_builtins()
