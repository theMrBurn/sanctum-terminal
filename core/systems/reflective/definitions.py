"""Reflective-mode JSON loaders — rules + (later) magnet pools.

Auto-loads on import (same pattern as `core.systems.quests.definitions`
and `core.systems.consequences.definitions`).

Step 2 of PR 3.5 ships rule loading via `config/reflective/rules.json`.
Step 3 will add magnet pool loading via `config/reflective/magnets.json`
into the same module.

Tests that need a clean registry call `rules.clear()` first, then
`load_rules_from_json(custom_path)` against a tmp file.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.systems.reflective import rules


_REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_PATH = _REPO_ROOT / "config" / "reflective" / "rules.json"


def load_rules_from_json(path: Path = RULES_PATH) -> None:
    """Read the rules JSON config and register each row.

    Idempotent only if `rules.clear()` was called first; duplicate
    ids raise per the registry's strict-once semantics.

    Missing file is a no-op — early-bringup safety so tests / scripts
    that import the package before the config exists don't blow up.
    """
    if not path.exists():
        return
    data = json.loads(path.read_text())
    rows = data.get("rules", [])
    for row in rows:
        rule = _row_to_rule(row)
        rules.register(rule)


def _row_to_rule(row: dict) -> rules.Rule:
    return rules.Rule(
        id=row["id"],
        name=row.get("name", row["id"]),
        instructions=row.get("instructions", ""),
        ac_predicates=list(row.get("ac_predicates", [])),
        ac_args=dict(row.get("ac_args", {})),
    )


# Auto-load on import.
load_rules_from_json()
