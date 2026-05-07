"""Nethack make-brain — classic NetHack as a side-project comparator.

Spec: `.claude/feature/feat_make-brain-nethack.md`.

Public surface mirrors `core/systems/make_brains/ping_pong.py`:
  - identity constants (INSTANCE_ID, ENTRY_POINT, DEFAULT_PROFILE,
    STATE_EVENT_TYPES)
  - activate(vault) -> MakeBrainSpec — idempotent registration
"""
from __future__ import annotations

from core.systems import make_brain_registry

from .handler import (
    DEFAULT_PROFILE,
    ENTRY_POINT,
    INSTANCE_ID,
    NetHackHandler,
    STATE_EVENT_TYPES,
)

__all__ = [
    "INSTANCE_ID", "ENTRY_POINT", "DEFAULT_PROFILE", "STATE_EVENT_TYPES",
    "NetHackHandler", "activate",
]


def activate(vault) -> "make_brain_registry.MakeBrainSpec":
    """Register NetHackHandler with make_brain_registry. Idempotent.

    Called once at terminal boot. Returns the existing spec if already
    registered (tolerates re-import in long-running test processes).
    """
    try:
        return make_brain_registry.get(INSTANCE_ID)
    except LookupError:
        pass
    handler = NetHackHandler(vault)
    return make_brain_registry.register(
        instance_id       = INSTANCE_ID,
        entry_point       = ENTRY_POINT,
        default_profile   = DEFAULT_PROFILE,
        state_event_types = STATE_EVENT_TYPES,
        handler           = handler,
    )
