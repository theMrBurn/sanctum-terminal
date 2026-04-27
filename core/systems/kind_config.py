"""Single-source kind configuration reader.

Both brain (Python) and Godot (GDScript via res://kind_config.json symlink)
load the SAME file at config/kind_config.json. This module is the brain-side
reader — Godot has its own _load_kind_config() in main.gd reading the same
underlying file.

Phase 1 of the kind-config consolidation: file moved to shared location,
both readers point at it. No schema change yet; brain just gains the
ability to read the same dict Godot already does. Future phases add
fields (collision_radius, render.scale, behavior block) and migrate
duplicate sources (KIND_PROPS, HARD_OBJECTS, CREATURE_KINDS).

Cached at module load — kind_config is large (37 kinds, ~30KB) and
read-only at runtime.
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any

from core.systems import kind_config_schema


# Resolve config/kind_config.json relative to repo root. core/systems/ is
# 2 levels deep from repo root; kind_config lives at config/.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / "config" / "kind_config.json"


_cache: dict[str, Any] | None = None

# Config-lock (design_thoughts.txt:864-888) — brain validates the schema on
# first load. Set SANCTUM_SKIP_CONFIG_VALIDATION=1 to bypass (dev only; the
# point of the lock is to fail loudly, so only skip while iterating on the
# schema itself).
_SKIP_VALIDATION_ENV = "SANCTUM_SKIP_CONFIG_VALIDATION"


def load() -> dict[str, Any]:
    """Return the parsed kind_config dict, loaded once and cached.

    Raises kind_config_schema.ConfigError if the file fails validation.
    """
    global _cache
    if _cache is None:
        with _CONFIG_PATH.open() as f:
            data = json.load(f)
        if not os.environ.get(_SKIP_VALIDATION_ENV):
            kind_config_schema.assert_valid(data)
        _cache = data
    return _cache


def kind(name: str) -> dict[str, Any]:
    """Return the per-kind config dict, or empty dict if unknown."""
    cfg = load()
    return cfg.get("kinds", {}).get(name, {})


def all_kinds() -> dict[str, dict[str, Any]]:
    """Return the full kinds map."""
    cfg = load()
    return cfg.get("kinds", {})


def z_offset(name: str, rng: random.Random) -> float:
    """Sample the z-offset for a kind from its render.z_offset [min, max] range.
    Returns 0.0 if the kind doesn't declare one. Constant ranges (min == max)
    skip the rng draw — preserves the original code path's rng state for kinds
    with fixed z (e.g., leaf at 3.0).
    """
    z_range = kind(name).get("render", {}).get("z_offset")
    if not z_range:
        return 0.0
    lo, hi = float(z_range[0]), float(z_range[1])
    if lo == hi:
        return lo
    return rng.uniform(lo, hi)


def reset_cache() -> None:
    """Force reload on next access. For tests that mutate the file."""
    global _cache
    _cache = None
