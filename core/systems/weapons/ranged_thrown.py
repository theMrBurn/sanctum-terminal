"""ranged_thrown — SHOT mode handler for thrown weapons (axe, knife, dart).

The first SHOT-mode weapon class wired through the Strike substrate.
Per `feat_arpg-combat.md` PR 2.

Architecture:
- `activate(vault)` seeds `vault.profiles` with the V1 throwing_axe
  profile and registers the SHOT dispatcher with `strike.register_dispatcher`.
- `on_use(weapon_profile, camera_state, source_actor)` returns a fully-
  populated Strike via `strike.spawn(...)`.
- Brain calls `strike.spawn` directly via the cmd_dispatch path for
  weapon_use commands; this module's `on_use` is convenience for
  programmatic spawn (e.g., NPC AI in V2).

The dispatcher itself is a thin runtime helper — most SHOT mode work
lives in `strike_runtime.tick_active_strikes`, which advances every
active SHOT/WHIP strike under BallisticsSolver, checks per-frame
entity collisions, and resolves on hit. The dispatcher slot exists for
mode-specific resolution overrides (e.g., RIPOSTE's parry path on
HELD), which SHOT doesn't need.
"""
from __future__ import annotations

from typing import Any

from core.systems import strike


# ----------------------------------------------------------------------
# V1 weapon profile — throwing_axe (per spec example)
# ----------------------------------------------------------------------

WEAPON_INSTANCE_ID:  str = "weapon"
THROWING_AXE_PROFILE: dict[str, Any] = {
    "_target":        "ranged thrown — V1 SHOT mode proof, throwing axe",
    "mode":           "shot",
    "geometry":       "sphere",
    "ball_mass":      2.0,
    "ball_radius":    0.3,
    "ball_drag_coeff": 0.05,
    "ball_magnus_coeff": 0.0,             # axe doesn't curve
    "gravity_y":      -9.81,
    "wall_restitution": 0.5,              # not relevant for outdoor flight
    "shot_initial_v":  18.0,
    "coupling":        0.95,
    "weapon_class":    "ranged_thrown",
    "default_verb":    None,              # SHOT has no verb; HELD does
}


# ----------------------------------------------------------------------
# Dispatcher — placeholder for SHOT-mode-specific resolution.
# ----------------------------------------------------------------------


def _shot_dispatcher(active_strike, world):
    """SHOT mode resolution. PR 2 V1 uses the runtime tick path
    (`strike_runtime.tick_active_strikes`) for the actual
    physics + collision + resolution flow — the dispatcher exists for
    completeness so the registry is non-empty for SHOT mode.

    Returns an empty list since the runtime tick is what produces
    contact events for SHOT.
    """
    return []


# ----------------------------------------------------------------------
# Activation — call once on brain boot.
# ----------------------------------------------------------------------


def activate(vault) -> None:
    """Seed throwing_axe profile + register SHOT dispatcher. Idempotent."""
    if vault.profile_load(WEAPON_INSTANCE_ID, "throwing_axe") is None:
        vault.profile_save(
            WEAPON_INSTANCE_ID,
            "throwing_axe",
            params=THROWING_AXE_PROFILE,
            notes="V1 ranged_thrown — feat_arpg-combat PR 2",
        )
    strike.register_dispatcher("shot", _shot_dispatcher)


# ----------------------------------------------------------------------
# Convenience programmatic spawn (for NPC AI / scripted scenarios).
# Brain's cmd_dispatch path calls strike.spawn directly.
# ----------------------------------------------------------------------


def on_use(
    weapon_profile: dict[str, Any],
    camera_state:   dict[str, Any],
    source_actor:   str = "player",
) -> Any:
    """Construct a SHOT-mode Strike from a weapon profile + camera state."""
    return strike.spawn(
        weapon_profile=weapon_profile,
        mode="shot",
        camera_state=camera_state,
        source_actor=source_actor,
    )
