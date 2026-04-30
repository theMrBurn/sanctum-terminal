"""Quest definitions — the active quest catalog.

Pure data. Each entry is a `Quest` registered at import time. Adding a
quest = appending one Quest(...) call below; no other code changes.

Migration target per `design_crud_substrate`: this module becomes
`config/quests.json` once predicate references stabilize and we have a
schema validator. Until then, Python module + import-time registration
matches the pillars pattern (`core.systems.pillars.*`).

Predicate references must match a name registered in
`core.systems.quests.predicates`. The brain validates on world boot —
unknown predicate id = startup error.

Reward shape mirrors the legacy `mission_loot` table on kind_config so
the migration path stays simple: each entry is `{name, weight}` where
weight ≤1.0 is roll-chance (1.0 = guaranteed). No `name`-only string
form — every entry must be a dict so the schema is uniform.
"""
from __future__ import annotations

from core.systems.quests import Quest, register


# ── anomaly_hunt_01 ────────────────────────────────────────────────
# Migration of the existing clay_pot mission. Predicate fires on a
# single clay_pot destruction event from Godot. Rewards match the
# legacy `kind_config.clay_pot.mission_loot`.

register(Quest(
    id="anomaly_hunt_01",
    name="The Anomaly Hunt",
    description="Something's off here. Mark what doesn't belong.",
    predicate="destroy_kind",
    predicate_args={"kind": "clay_pot", "count": 1},
    rewards=[
        {"name": "pot_shard", "weight": 1.0},
        {"name": "ember", "weight": 0.4},
        {"name": "healing_potion", "weight": 0.6},
    ],
    register="loop",
))


# ── cast_trial_01 ──────────────────────────────────────────────────
# Pinned for v1; predicate plumbing on cast events (cast_landed) lands
# alongside brain wiring in the next slice.

register(Quest(
    id="cast_trial_01",
    name="The Four-Element Trial",
    description="Cast each element at the standing column.",
    predicate="cast_at_kind",
    predicate_args={
        "kind": "mega_column",
        "elements": ["fire", "ice", "electric", "light"],
    },
    rewards=[
        {"name": "elemental_focus", "weight": 1.0},
    ],
    register="loop",
))
