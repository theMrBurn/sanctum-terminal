"""melee_tether — WHIP mode handler for tethered swing weapons.

Per `feat_arpg-combat.md` PR 4. The third Strike mode wired through
the substrate. WHIP is the user's "Castlevania morningstar / chain
whip / tethered flail" feel:

- STRIKE input INITIATES the swing (not passive orbit — player commits)
- Ball travels arc through three pinned positions (start → end-of-reach
  → at-rest)
- Contact during arc = "SNAP" / "Knock" feedback; multi-hit allowed
  (ball continues along arc on contact)
- Ball ALWAYS returns to player (deterministic retract — even on miss)

V1 ships the chain_whip weapon. Per the locked spec, the ball orbits
under BallisticsSolver during the swing phase, then enters a retract
phase where it animates back to player along the tether.
"""
from __future__ import annotations

from typing import Any

from core.systems import strike


WEAPON_INSTANCE_ID: str = "weapon"


# ----------------------------------------------------------------------
# V1 weapon profile — chain_whip
# ----------------------------------------------------------------------

CHAIN_WHIP_PROFILE: dict[str, Any] = {
    "_target":        "melee tether — V1 WHIP mode proof, chain whip",
    "mode":           "whip",
    "geometry":       "sphere",
    "ball_mass":      2.5,
    "ball_radius":    0.35,
    "ball_drag_coeff": 0.02,
    "ball_magnus_coeff": 0.0,
    "gravity_y":      -2.0,                     # mild arc; not full freefall
    "wall_restitution": 1.0,
    "coupling":        0.7,
    "tether_length":   3.0,
    # Phase timing — swing then retract. Total max_age determines when
    # the runtime resolves the strike. Ball ALWAYS returns to player at
    # end of retract.
    "whip_swing_s":    0.45,                     # active swing — multi-hit possible
    "whip_retract_s":  0.30,                     # animation reel-in (no collisions)
    "weapon_class":    "melee_tether",
    "default_verb":    None,                     # WHIP has no verb taxonomy
}


# ----------------------------------------------------------------------
# Dispatcher placeholder. Real WHIP runtime lives in strike_runtime._tick_whip.
# ----------------------------------------------------------------------


def _whip_dispatcher(active_strike, world):
    """WHIP mode placeholder. Per-frame swing + retract animation
    lives in `strike_runtime._tick_whip`."""
    return []


# ----------------------------------------------------------------------
# Activation
# ----------------------------------------------------------------------


def activate(vault) -> None:
    """Seed chain_whip profile + register WHIP dispatcher. Idempotent."""
    if vault.profile_load(WEAPON_INSTANCE_ID, "chain_whip") is None:
        vault.profile_save(
            WEAPON_INSTANCE_ID,
            "chain_whip",
            params=CHAIN_WHIP_PROFILE,
            notes="V1 melee_tether — feat_arpg-combat PR 4",
        )
    strike.register_dispatcher("whip", _whip_dispatcher)


# ----------------------------------------------------------------------
# Convenience programmatic spawn
# ----------------------------------------------------------------------


def on_use(
    weapon_profile: dict[str, Any],
    camera_state:   dict[str, Any],
    source_actor:   str = "player",
) -> Any:
    """Construct a WHIP-mode Strike from a weapon profile + camera state."""
    return strike.spawn(
        weapon_profile=weapon_profile,
        mode="whip",
        camera_state=camera_state,
        source_actor=source_actor,
    )
