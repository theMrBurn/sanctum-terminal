"""Reflective-mode JSON loaders — rules + magnet pools.

Auto-loads on import (same pattern as `core.systems.quests.definitions`
and `core.systems.consequences.definitions`).

Two configs:
  - `config/reflective/rules.json` — rule registry rows
  - `config/reflective/magnets.json` — magnet pool sources (connectives,
    thematic, wildcards)

Tests that need a clean state call `rules.clear()` (and/or set the
magnet pool config explicitly) first, then `load_rules_from_json()`
or `load_magnets_from_json()` against a tmp file.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.systems.reflective import magnets, rules


_REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_PATH = _REPO_ROOT / "config" / "reflective" / "rules.json"
MAGNETS_PATH = _REPO_ROOT / "config" / "reflective" / "magnets.json"


# ── Rules loader ──────────────────────────────────────────────────


def load_rules_from_json(path: Path = RULES_PATH) -> None:
    """Read the rules JSON config and register each row.

    Idempotent only if `rules.clear()` was called first; duplicate
    ids raise per the registry's strict-once semantics.

    Missing file is a no-op — early-bringup safety.
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


# ── Magnets loader ────────────────────────────────────────────────


def load_magnets_from_json(path: Path = MAGNETS_PATH) -> None:
    """Read the magnets JSON config and install it as the active pool
    config. Idempotent — replaces whatever was set previously.

    Missing file leaves the existing pool config in place (which
    starts empty on first import). Tests can pass a tmp_path to
    install custom pools.
    """
    if not path.exists():
        return
    data = json.loads(path.read_text())
    config = magnets.PoolConfig(
        connectives=tuple(data.get("connectives", [])),
        thematic=tuple(data.get("thematic", [])),
        wildcards=tuple(data.get("wildcards", [])),
    )
    magnets.set_pool_config(config)


# Auto-load on import.
load_rules_from_json()
load_magnets_from_json()
