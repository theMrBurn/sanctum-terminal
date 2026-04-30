"""Quest completion predicates — named functions evaluated per tick.

A predicate answers a single yes/no question about world state: "has
the player satisfied this quest's win condition?" Predicates are pure
reads of `world` + per-tick events; they never mutate. The brain's
quest tick (lands in PR 1.5) calls each active quest's predicate every
frame; on a true return, the quest moves from active → completed and
rewards drop.

Predicates are registered by name so quest definitions can reference
them as plain strings — keeps `core.systems.quests.definitions` JSON-
migratable later (per `design_crud_substrate`). Adding a new predicate
type = adding one row here, then referencing it from a quest definition.

The `events` arg is a list of dicts the brain populates per tick from
incoming Godot commands (e.g., `kind_destroyed`). Predicates that watch
state (entity counts, player position) read `world` directly. Event-
driven and state-driven predicates compose cleanly: a quest can require
both ("destroy 3 clay_pots while at the axis_mundi anchor").
"""
from __future__ import annotations

from typing import Any, Callable, Protocol


class WorldLike(Protocol):
    """Structural type for what predicates may read off `world`. Kept
    loose so this module doesn't import BrainWorld directly (avoids the
    circular import that would force quests to depend on brain_server)."""
    player: Any
    entities: Any


PredicateFn = Callable[[WorldLike, dict, dict, list[dict]], bool]
"""Signature: (world, static_args, progress, events) -> done?

  world         : the brain world (read-only)
  static_args   : read-only config from the Quest (e.g., kind="clay_pot")
  progress      : mutable per-active-quest state owned by the brain. The
                  predicate may write into it (e.g., a running count). The
                  brain persists progress alongside active_quests.
  events        : list of per-tick event dicts the brain accumulates from
                  Godot commands (e.g., {"type": "kind_destroyed", "kind": ...}).

  Returns True when the quest's win condition is satisfied. Brain
  observes the True return, fires completion + reward drop, moves the
  quest from active → completed.
"""


_REGISTRY: dict[str, PredicateFn] = {}


def register(name: str) -> Callable[[PredicateFn], PredicateFn]:
    """Decorator: `@register("destroy_kind")` adds a predicate by name."""
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


@register("destroy_kind")
def _destroy_kind(
    world: WorldLike,
    args: dict,
    progress: dict,
    events: list[dict],
) -> bool:
    """True when the player has destroyed N entities of the given kind.
    Reads `kind_destroyed` events; counts accumulate in `progress["count"]`.

    args:
      kind: str  — the entity kind to watch (e.g., "clay_pot")
      count: int — how many destructions complete the quest (default 1)
    """
    kind = str(args.get("kind", ""))
    target = int(args.get("count", 1))
    if not kind:
        return False
    count = int(progress.get("count", 0))
    for evt in events:
        if evt.get("type") == "kind_destroyed" and evt.get("kind") == kind:
            count += 1
    progress["count"] = count
    return count >= target


@register("cast_at_kind")
def _cast_at_kind(
    world: WorldLike,
    args: dict,
    progress: dict,
    events: list[dict],
) -> bool:
    """True when the player has cast each listed element at the given kind.
    Reads `cast_landed` events; observed elements accumulate as a set in
    `progress["seen"]`.

    args:
      kind: str            — target entity kind
      elements: list[str]  — required elements (set semantics)
    """
    kind = str(args.get("kind", ""))
    required = set(args.get("elements", []))
    if not kind or not required:
        return False
    seen = set(progress.get("seen", []))
    for evt in events:
        if evt.get("type") == "cast_landed" and evt.get("kind") == kind:
            element = evt.get("element")
            if element:
                seen.add(str(element))
    progress["seen"] = sorted(seen)
    return required.issubset(seen)
