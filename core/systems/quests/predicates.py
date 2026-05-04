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


# ── Target-position registry (HUD bearing) ───────────────────────────
#
# PR 4: each predicate may optionally register a companion that returns
# the spatial target the player should move toward to make progress on
# the predicate's win condition. Brain calls this at manifest build
# time and feeds the result through `core.systems.bearing` to produce
# a compass string for the HUD.
#
# Predicates that have no spatial target (journal_followup completes
# by re-journaling, not by walking somewhere) simply omit registration.
# Brain treats a missing registration the same as a None return value.


TargetFn = Callable[
    ["WorldLike", dict, float, float], "tuple[float, float] | None"
]
"""Signature: (world, static_args, player_x, player_y) -> (tx, ty) | None.

Returns the world position the player should head toward, or None if
the quest currently has no spatial target (e.g. all entities of a
target kind have been destroyed; player has no progress hook).

`player_x`, `player_y` are passed in so resolvers can pick the NEAREST
matching entity rather than a fixed one — relevant for kinds that
appear scattered across the world (clay_pots, etc.).
"""


_TARGETS: dict[str, TargetFn] = {}


def register_target(name: str) -> Callable[[TargetFn], TargetFn]:
    """Decorator: register a target-position resolver alongside a
    same-named predicate. Idempotent — re-registration overwrites
    (avoids `clean` fixture pain at the cost of strict-once semantics
    for resolvers; predicates remain strict-once)."""
    def decorator(fn: TargetFn) -> TargetFn:
        _TARGETS[name] = fn
        return fn
    return decorator


def get_target(name: str) -> TargetFn | None:
    return _TARGETS.get(name)


def all_targets() -> dict[str, TargetFn]:
    return dict(_TARGETS)


def clear_targets() -> None:
    """Test-only — reset the target registry."""
    _TARGETS.clear()


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


@register("journal_followup")
def _journal_followup(
    world: WorldLike,
    args: dict,
    progress: dict,
    events: list[dict],
) -> bool:
    """True when the player logs a new journal entry mentioning `term`.

    The planner-native predicate: a quest born from a journal entry
    completes when she journals about it again. No game-kind binding
    required — the act of journaling closes the loop. Match is
    case-insensitive substring on raw_note (lemma matching is the
    lexicon module's job; this predicate stays small).

    The bridge skips registration of the entry that BIRTHED the quest
    (entry_id passed in args) so a quest cannot complete on its own
    creation event.

    args:
      term:           str — substring to match (already lowercased)
      birth_entry_id: int — entry id that created this quest; ignored
    """
    term = str(args.get("term", "")).strip().lower()
    if not term:
        return False
    birth = args.get("birth_entry_id")
    for evt in events:
        if evt.get("type") != "journal_entry":
            continue
        if birth is not None and evt.get("entry_id") == birth:
            continue
        raw = str(evt.get("raw_note", "")).lower()
        if term in raw:
            return True
    return False


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


# ── Target-position resolvers (HUD bearing companions) ─────────────


def _nearest_entity_of_kind(
    world: WorldLike,
    kind: str,
    player_x: float,
    player_y: float,
) -> "tuple[float, float] | None":
    """Iterate world entities, return (x, y) of the closest one whose
    `kind` matches. Used by both destroy_kind and cast_at_kind targets.

    `world.entities` is duck-typed: a sequence of dicts with `kind`,
    `x`, `y`. Brain's BrainWorld satisfies this; tests can pass a
    minimal fake.
    """
    if not kind:
        return None
    nearest: tuple[float, float] | None = None
    nearest_d2 = float("inf")
    entities = getattr(world, "entities", None) or []
    # BrainWorld.entities is sometimes a dict {id: dict}; iterate values
    # if so, items if list-of-dicts.
    iterable = entities.values() if hasattr(entities, "values") else entities
    for ent in iterable:
        if not isinstance(ent, dict):
            continue
        if ent.get("kind") != kind:
            continue
        try:
            ex = float(ent.get("x", 0.0))
            ey = float(ent.get("y", 0.0))
        except (TypeError, ValueError):
            continue
        d2 = (ex - player_x) ** 2 + (ey - player_y) ** 2
        if d2 < nearest_d2:
            nearest_d2 = d2
            nearest = (ex, ey)
    return nearest


@register_target("destroy_kind")
def _destroy_kind_target(world, args, player_x, player_y):
    """Nearest entity of the target kind to the player. None if no
    entities of that kind exist (e.g. all destroyed already)."""
    return _nearest_entity_of_kind(world, str(args.get("kind", "")), player_x, player_y)


@register_target("cast_at_kind")
def _cast_at_kind_target(world, args, player_x, player_y):
    """Same as destroy_kind: point at the nearest matching entity.
    The player still has to walk to it before casting."""
    return _nearest_entity_of_kind(world, str(args.get("kind", "")), player_x, player_y)


# `journal_followup` deliberately has NO target resolver — completion
# happens by re-journaling, not by walking somewhere. HUD shows the
# quest name without a bearing prefix in that case.
