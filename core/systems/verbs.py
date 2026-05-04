"""Verb taxonomy reader.

Loads config/verbs.json. Four pools:

- cast_trajectories: how a cast reaches its target (straight/fast/arc/...)
- cast_effects: what the cast delivers (fire/ice/light/...)
- contact_verbs: avatar-initiated contact (touch/hit/kick/...)
- held_object_verbs: contact with a held weapon (stabbing/slashing/...)

Scaffolded from design_thoughts.txt:598-600. Identifiers-only until the
renderer and resolver are ready to consume tuning values (damage, force,
palette). Brain-authoritative config per design_kind_config_single_source.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / "config" / "verbs.json"

_POOLS = (
    "cast_trajectories",
    "cast_effects",
    "contact_verbs",
    "held_object_verbs",
)

_cache: dict[str, Any] | None = None


def load() -> dict[str, Any]:
    """Return the parsed verbs dict, loaded once and cached."""
    global _cache
    if _cache is None:
        with _CONFIG_PATH.open() as f:
            _cache = json.load(f)
    return _cache


def _pool(name: str) -> dict[str, dict[str, Any]]:
    raw = load().get(name, {})
    # Strip _doc sentinels so callers iterate only real entries.
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def cast_trajectories() -> dict[str, dict[str, Any]]:
    return _pool("cast_trajectories")


def cast_effects() -> dict[str, dict[str, Any]]:
    return _pool("cast_effects")


def contact_verbs() -> dict[str, dict[str, Any]]:
    return _pool("contact_verbs")


def held_object_verbs() -> dict[str, dict[str, Any]]:
    return _pool("held_object_verbs")


def validate_cast(trajectory: str, effect: str) -> bool:
    """True if the (trajectory, effect) pair exists in the taxonomy.

    Plugs into the existing CAST_TRIAL filter: the brain already routes
    cast_events by `element`; trajectory is a future extension of the
    payload. Accept either pool member by identifier.
    """
    return trajectory in cast_trajectories() and effect in cast_effects()


def validate_contact(verb: str, held: str | None = None) -> bool:
    """True if the contact verb (and optional held-object verb) are known."""
    if held is None:
        return verb in contact_verbs()
    return verb in contact_verbs() and held in held_object_verbs()


def reset_cache() -> None:
    """Force reload on next access. For tests that mutate the file."""
    global _cache
    _cache = None
