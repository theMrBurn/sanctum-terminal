"""Quest reward roll — same shape as the legacy `kind_config.mission_loot`.

Each reward entry is `{name, weight}` where weight ≤1.0 is the chance
the item drops (1.0 = guaranteed). Matches the legacy semantic at
brain_server.py's mission_complete_trigger handler — `random.random() >
weight` skips, so weight 1.0 always drops and weight 0.4 drops 40%.

Pure function: takes a reward table, returns a list of item names that
rolled. Brain owns inventory mutation (`add_item`); this module never
touches player state.
"""
from __future__ import annotations

import random


def roll(rewards: list[dict]) -> list[str]:
    """Roll the reward table. Returns the names that dropped, in
    table order. Skips entries without a `name` field."""
    out: list[str] = []
    for entry in rewards:
        if not isinstance(entry, dict):
            continue
        weight = float(entry.get("weight", 1.0))
        if random.random() > weight:
            continue
        name = str(entry.get("name", ""))
        if not name:
            continue
        out.append(name)
    return out
