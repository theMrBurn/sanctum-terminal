"""Loads consequences from `config/consequences.json` into the registry.

JSON-driven from day 1 — consequences are CRUD authoring per
`design_kind_config_pattern` and `feedback_brain_owns_config`. Adding
a new consequence is a config row, not a code change.

Auto-loads on import (same pattern as `core.systems.quests.definitions`).
Tests that need a clean registry call `clear()` first, then call
`load_from_json(custom_path)` with a tmp file.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.systems.consequences import Consequence, Effect, register


CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "consequences.json"
)


def load_from_json(path: Path = CONFIG_PATH) -> None:
    """Read the JSON config and register each row.

    Idempotent only if the registry was cleared first; duplicate ids
    raise ValueError per the registry's strict-once semantics.
    """
    if not path.exists():
        return
    data = json.loads(path.read_text())
    rows = data.get("consequences", [])
    for row in rows:
        consequence = _row_to_consequence(row)
        register(consequence)


def _row_to_consequence(row: dict) -> Consequence:
    trigger = row.get("trigger", {})
    resolution = row.get("resolution", {})
    effects_raw = resolution.get("effects", [])
    effects = [
        Effect(name=e["name"], args=dict(e.get("args", {})))
        for e in effects_raw
    ]
    return Consequence(
        id=row["id"],
        trigger_predicate=trigger.get("predicate", ""),
        trigger_args=dict(trigger.get("args", {})),
        resolution_predicate=resolution.get("predicate"),
        resolution_args=dict(resolution.get("args", {})),
        resolution_effects=effects,
        one_shot=bool(row.get("one_shot", False)),
    )


# Auto-load on import.
load_from_json()
