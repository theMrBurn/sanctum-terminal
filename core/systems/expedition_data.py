"""Expedition recipes — pure-data definitions of game-loop expeditions.

Expeditions are the third stamp-like primitive in the system, after
kinds (gen_kind_mesh) and stamps (biome_data.CAVERN_STAMPS). One
engine, many recipes, infinite instantiations. The engine reads
recipes; Godot reads the engine's snapshot via manifest['expedition'].
No recipe-specific knowledge leaks into the renderer.

Two layers:

  EXPEDITION_CLASSES  — biome-agnostic recipe templates. Coordinates
                        become symbolic anchors (`select_by`). Kind
                        names never appear. Messages are defaults.
  BIOME_EXPEDITIONS   — per-biome bindings. Resolves anchors to
                        concrete kind+position pairs. May override
                        message text per class.

This mirrors the kind_config class-default + per-kind override
pattern already proven in the visual layer.

The contract that makes one class serve every biome:
  1. No absolute coordinates in EXPEDITION_CLASSES[*]
  2. No biome-specific kind names in EXPEDITION_CLASSES[*]
  3. Messages are class-level defaults; biome bindings may override

Schema fields are accepted by the engine even if v1 doesn't implement
all branches. Future recipes can declare new triggers, resolution
actions, and deposit grammars without schema breakage — the engine
grows the corresponding branch when the new recipe lands.

See design_hub_and_spoke, design_journal_quest_pipeline, project_hub_poc
for the architectural context. This is where the hub PoC, the tag
system, and the Wizardry-tavern-bounty framing converge.
"""

from __future__ import annotations


# ============================================================
# EXPEDITION CLASSES — biome-agnostic, symbolic anchors only
# ============================================================

ANOMALY_HUNT: dict = {
    "id": "anomaly_hunt",
    "trigger": {"on": "spawn"},
    "objective_text": "Something's off here. Mark what doesn't belong.",

    # Deposit points — symbolic anchors only. Biome binding resolves
    # `select_by` to a concrete kind+pos pair at engine construction.
    "deposit_points": [
        {
            "id": "axis_mundi",
            "select_by": "axis_mundi",
            "accepts": ["any"],
            "threshold": 3,
            "satisfied_visual": {
                "emission_boost": 2.0,
                "pipe_lock": "warm",
            },
        },
    ],

    # Exit point — also symbolic.
    "exit_point": {
        "id": "exit_arch",
        "select_by": "exit_arch",
        "trigger_radius": 2.0,
        "active_visual": {
            "emission_boost": 1.5,
            "pipe_lock": "cool",
        },
    },

    # Class-level message defaults. Biome binding may override any key.
    "messages": {
        "spawn":     "Something's off here. Mark what doesn't belong.",
        "first_tag": "The witness listens.",
        "halfway":   "Halfway. Keep marking.",
        "satisfied": "The way out is open.",
        "complete":  "You step through.",
    },

    "on_complete": {
        "write_session_log": True,
        "quit_godot": True,
    },
}


EXPEDITION_CLASSES: dict[str, dict] = {
    "anomaly_hunt": ANOMALY_HUNT,
    # future classes drop in here as pure data:
    # "pilgrimage":      PILGRIMAGE,
    # "scout_dispatch":  SCOUT_DISPATCH,
    # "witnesses":       WITNESSES,
}


# ============================================================
# BIOME BINDINGS — symbolic anchors → concrete kind + position
#                  + optional message overrides per class
# ============================================================

CAVERN_BINDING: dict = {
    "anchors": {
        # Core cavern hub anchors (authored in biome_data.ORIGIN_HUB).
        # See project_hub_poc.md for the layout; the hub PoC was
        # hub-ready for this without knowing it.
        "axis_mundi": {"kind": "mega_column", "pos": [0.0, 0.0]},
        "exit_arch":  {"kind": "doorframe",   "pos": [0.0, -14.0]},

        # Future symbols future classes can reach for:
        # "ne_witness": {"kind": "monolith", "pos": [12.0,  12.0]},
        # "se_witness": {"kind": "monolith", "pos": [12.0, -12.0]},
        # "sw_witness": {"kind": "monolith", "pos": [-12.0, -12.0]},
        # "nw_witness": {"kind": "monolith", "pos": [-12.0,  12.0]},
    },

    "active_classes": ["anomaly_hunt"],

    "message_overrides": {
        "anomaly_hunt": {
            # Cavern-specific flavor for the first-tag moment; other
            # keys fall through to class defaults above.
            "first_tag": "The column listens.",
        },
    },
}


OUTDOOR_BINDING: dict = {
    # User declares outdoor hub anchors when the outdoor biome gets
    # a hub of its own. Until then the binding is empty and
    # BIOME_EXPEDITIONS won't be able to instantiate anomaly_hunt
    # against it — the engine will raise MissingAnchorBinding, which
    # is the correct behavior (fail fast, not silently wrong).
    "anchors": {},
    "active_classes": ["anomaly_hunt"],
    "message_overrides": {
        "anomaly_hunt": {
            # "first_tag": "The canopy notices.",
        },
    },
}


BIOME_EXPEDITIONS: dict[str, dict] = {
    "cavern":  CAVERN_BINDING,
    "outdoor": OUTDOOR_BINDING,
}
