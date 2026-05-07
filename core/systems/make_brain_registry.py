"""
core/systems/make_brain_registry.py

Make-brain instance registry. Each make-brain (ping_pong, future archery,
future puzzle modules) registers its identity, entry point, default
profile, the set of StateEvent types it emits, and a handler object.

The brain dispatches commands by instance_id -> handler. Future instances
plug in here without surgery on brain_server.py dispatch.

See .claude/feature/feat_make-brain-ping-pong.md PR 1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class MakeBrainSpec:
    """Immutable record describing one make-brain instance."""
    instance_id:       str
    entry_point:       str                    # "biome:volley_chamber" / "object:fridge" / etc.
    default_profile:   str
    state_event_types: tuple[str, ...]
    handler:           Any                    # instance with .on_command(...) etc.


# Module-level registry. Populated via register(); read via dispatch() / get().
_REGISTRY: dict[str, MakeBrainSpec] = {}


def register(
    instance_id: str,
    entry_point: str,
    default_profile: str,
    state_event_types: list[str] | tuple[str, ...],
    handler: Any,
) -> MakeBrainSpec:
    """Register a make-brain instance. Returns the MakeBrainSpec.

    Raises:
      - ValueError on empty/blank instance_id, entry_point, default_profile
      - ValueError if state_event_types is empty (every make-brain must
        declare at least one event type — universal lifecycle ones at
        minimum: make_brain_started/_ended/profile_loaded/peak_recorded)
      - ValueError on duplicate instance_id (use unregister() first if
        intentional re-registration is needed)
    """
    iid = (instance_id or "").strip()
    if not iid:
        raise ValueError("register: instance_id must be non-empty")
    if not (entry_point or "").strip():
        raise ValueError(f"register({iid!r}): entry_point must be non-empty")
    if not (default_profile or "").strip():
        raise ValueError(f"register({iid!r}): default_profile must be non-empty")
    if not state_event_types:
        raise ValueError(
            f"register({iid!r}): state_event_types must be non-empty — "
            "every make-brain emits at least the universal lifecycle events"
        )
    types_tuple = tuple(str(t) for t in state_event_types)
    if any(not t.strip() for t in types_tuple):
        raise ValueError(
            f"register({iid!r}): state_event_types contains a blank entry"
        )
    if iid in _REGISTRY:
        raise ValueError(
            f"register({iid!r}): instance_id already registered "
            "(call unregister first if this is intentional)"
        )
    spec = MakeBrainSpec(
        instance_id       = iid,
        entry_point       = entry_point.strip(),
        default_profile   = default_profile.strip(),
        state_event_types = types_tuple,
        handler           = handler,
    )
    _REGISTRY[iid] = spec
    return spec


def unregister(instance_id: str) -> bool:
    """Remove an instance from the registry. Returns True if removed."""
    return _REGISTRY.pop(str(instance_id), None) is not None


def get(instance_id: str) -> MakeBrainSpec:
    """Return the spec for an instance. Raises LookupError if unknown."""
    spec = _REGISTRY.get(str(instance_id))
    if spec is None:
        raise LookupError(
            f"make_brain_registry.get({instance_id!r}): instance not registered"
        )
    return spec


def list_instances() -> list[str]:
    """Sorted list of registered instance ids."""
    return sorted(_REGISTRY.keys())


def dispatch(instance_id: str, method: str, *args, **kwargs) -> Any:
    """Invoke `handler.<method>(*args, **kwargs)` for the given instance.

    Raises:
      - LookupError if instance_id is not registered
      - AttributeError if the handler does not implement the method
    """
    spec = get(instance_id)
    fn = getattr(spec.handler, method, None)
    if fn is None or not callable(fn):
        raise AttributeError(
            f"dispatch({instance_id!r}, {method!r}): "
            f"handler {type(spec.handler).__name__} has no callable {method!r}"
        )
    return fn(*args, **kwargs)


def _reset_for_tests() -> None:
    """Test-only: clear the registry so each test starts clean."""
    _REGISTRY.clear()
