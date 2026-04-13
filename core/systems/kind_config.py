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
from pathlib import Path
from typing import Any


# Resolve config/kind_config.json relative to repo root. core/systems/ is
# 2 levels deep from repo root; kind_config lives at config/.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / "config" / "kind_config.json"


_cache: dict[str, Any] | None = None


def load() -> dict[str, Any]:
    """Return the parsed kind_config dict, loaded once and cached."""
    global _cache
    if _cache is None:
        with _CONFIG_PATH.open() as f:
            _cache = json.load(f)
    return _cache


def kind(name: str) -> dict[str, Any]:
    """Return the per-kind config dict, or empty dict if unknown."""
    cfg = load()
    return cfg.get("kinds", {}).get(name, {})


def all_kinds() -> dict[str, dict[str, Any]]:
    """Return the full kinds map."""
    cfg = load()
    return cfg.get("kinds", {})


def reset_cache() -> None:
    """Force reload on next access. For tests that mutate the file."""
    global _cache
    _cache = None
