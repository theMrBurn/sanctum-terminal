"""Loader for config/encounters.json — the encounter primitive's data pool.

Encounters compose from pools (actors, intents, environments, objects, scouts).
This module is the only place that reads the JSON; the rest of the codebase
calls typed accessors.

Cache once per process (config is read-only at runtime). Use reload() in tests
if you need a fresh state.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "encounters.json"
_cache: Dict[str, Any] | None = None


def load() -> Dict[str, Any]:
    """Return the full config dict. Cached."""
    global _cache
    if _cache is None:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def reload() -> Dict[str, Any]:
    """Force a fresh read — useful in tests that mutate config on disk."""
    global _cache
    _cache = None
    return load()


# -- Pool accessors ----------------------------------------------------------

def get_intent(name: str) -> Dict[str, Any]:
    intents = load()["intents"]
    if name not in intents:
        raise KeyError(f"unknown intent {name!r}")
    return intents[name]


def get_dialog_intent(name: str) -> Dict[str, Any]:
    intents = load().get("dialog_intents", {})
    if name not in intents:
        raise KeyError(f"unknown dialog_intent {name!r}")
    return intents[name]


def get_posture(name: str) -> Dict[str, Any]:
    postures = load().get("postures", {})
    if name not in postures or name.startswith("_"):
        raise KeyError(f"unknown posture {name!r}")
    return postures[name]


def get_dialog_verb(name: str) -> Dict[str, Any]:
    verbs = load().get("dialog_verbs", {})
    if name not in verbs or name.startswith("_"):
        raise KeyError(f"unknown dialog_verb {name!r}")
    return verbs[name]


def dialog_verb_names() -> list[str]:
    """All declared dialog verbs (no doc keys)."""
    return [k for k in load().get("dialog_verbs", {}).keys()
            if not k.startswith("_")]


def get_actor(name: str) -> Dict[str, Any]:
    actors = load()["actors"]
    if name not in actors:
        raise KeyError(f"unknown actor {name!r}")
    return actors[name]


def get_environment(name: str) -> Dict[str, Any]:
    envs = load()["environments"]
    if name not in envs:
        raise KeyError(f"unknown environment {name!r}")
    return envs[name]


def get_object(name: str) -> Dict[str, Any]:
    objs = load()["objects"]
    if name not in objs:
        raise KeyError(f"unknown object {name!r}")
    return objs[name]


def get_scout(name: str) -> Dict[str, Any]:
    scouts = load()["scouts"]
    if name not in scouts:
        raise KeyError(f"unknown scout {name!r}")
    return scouts[name]


# -- Phase resolution --------------------------------------------------------

def phase_for_hp_fraction(frac: float) -> str:
    """Map a 0.0-1.0 HP fraction to a phase name.

    Thresholds come from config.phases.<name>.hp_min_frac. Highest threshold
    wins; "desperate" (hp_min_frac=0.0) is always the fallback.
    """
    phases = load()["phases"]
    # Sort by descending threshold; first match wins.
    ordered = sorted(
        phases.items(),
        key=lambda kv: kv[1]["hp_min_frac"],
        reverse=True,
    )
    for name, spec in ordered:
        if frac >= spec["hp_min_frac"]:
            return name
    # Unreachable if "desperate" is at 0.0, but stay safe
    return ordered[-1][0]
