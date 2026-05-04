"""Acceptance-criteria predicates — gate return-to-active on commit.

Mirrors quest/consequence predicate registry shape but evaluates
against commit-time composition data instead of per-tick events.
Separate registry kept clean: AC predicates have a different
lifecycle (called on commit attempts, not every frame) and a
different read surface (the ReflectiveState's composed list, not
world.tick_events).

Per `design_render_reuse_mandate`: same decorator pattern as
quest/consequence predicates, separate state registry. The 30-LOC
duplication earns its keep via clean semantic separation —
quest predicates accumulate state across ticks via events; AC
predicates read commit-time state once.

Built-in: `min_magnet_count`. Production rules (acrostic, theme
matching, rhyme, spatial) layer on as new built-ins without
engine changes.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol


class WorldLike(Protocol):
    """Loose duck type — AC predicates rarely need world but the arg
    stays in the signature for parity with quest/consequence predicates
    and future predicates that might (e.g. biome-aware AC)."""
    pass


class ReflectiveStateLike(Protocol):
    """What AC predicates may read off the reflective state.
    Decoupled from concrete dataclass to avoid circular imports."""
    composed: list[str]
    magnet_pool: list[str]
    attempt_count: int
    current_rule_id: str


PredicateFn = Callable[[WorldLike, dict, ReflectiveStateLike], bool]
"""Signature: (world, args, state) -> ac_satisfied?

  world : the brain world (read-only). Often unused; kept in signature
          for parity with quest/consequence predicates.
  args  : the rule's `ac_args[predicate_name]` dict (e.g. {"count": 3})
  state : ReflectiveState — predicates read state.composed,
          state.magnet_pool, state.attempt_count, state.current_rule_id.

Returns True when the commit attempt should succeed and the player
should return to active play. Per-attempt evaluation; no cross-attempt
accumulation (that's what state.attempt_count records, for predicates
that want progressive difficulty hints).
"""


_REGISTRY: dict[str, PredicateFn] = {}


def register(name: str) -> Callable[[PredicateFn], PredicateFn]:
    """Decorator: `@register("min_magnet_count")` adds a predicate by name."""
    def decorator(fn: PredicateFn) -> PredicateFn:
        if name in _REGISTRY:
            raise ValueError(f"AC predicate already registered: {name!r}")
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


# ── Built-in AC predicates ───────────────────────────────────────────


def _min_magnet_count(world, args: dict, state) -> bool:
    """True when the composition has at least N magnets placed.

    Smallest possible AC — proves the engine works end-to-end without
    requiring grammar, theme, rhyme, or spatial constraint. Step 1 of
    PR 3.5; production rules layer on as new built-ins.

    args:
      count: int — minimum magnets required (default 3)
    """
    target = int(args.get("count", 3))
    return len(state.composed) >= target


def register_builtins() -> None:
    """(Re)-register built-in AC predicates. Idempotent. Module
    import auto-calls this. Tests with a `clean` fixture call this
    in teardown so subsequent tests see the built-ins."""
    if "min_magnet_count" not in _REGISTRY:
        _REGISTRY["min_magnet_count"] = _min_magnet_count


# Auto-register on import.
register_builtins()
