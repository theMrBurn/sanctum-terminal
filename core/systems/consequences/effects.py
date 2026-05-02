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
