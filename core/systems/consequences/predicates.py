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
