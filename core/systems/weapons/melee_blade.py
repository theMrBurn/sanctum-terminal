"""melee_blade — HELD mode handler for swung blade weapons (sword, axe).

Per `feat_arpg-combat.md` PR 3. Wires the 5-verb swing system to a
concrete weapon (`iron_sword`).

V1 supports four offensive verbs (PUNCH, STAB, SLASH, HACK) plus
RIPOSTE (defensive parry, V1 stub — no enemy Strikes to deflect yet).
Each verb has its own arc shape from `strike.arc_shape()` defaults.
Per-weapon overrides land via `held_arc_overrides` in vault.profiles.

The `iron_sword` profile excludes PUNCH (sword too long for tight
forward-thrust) — `held_verbs: [SLASH, STAB, HACK, RIPOSTE]` with
SLASH as default.
"""
from __future__ import annotations

from typing import Any

from core.systems import strike
from core.systems.strike import HeldVerb


WEAPON_INSTANCE_ID: str = "weapon"


# ----------------------------------------------------------------------
# V1 weapon profile — iron_sword
# ----------------------------------------------------------------------

IRON_SWORD_PROFILE: dict[str, Any] = {
    "_target":        "melee blade — V1 HELD mode proof, iron sword",
    "mode":           "held",
    "geometry":       "sphere",                # V1; V2 = "blade" capsule
    "ball_mass":      1.5,
    "ball_radius":    0.4,
    "ball_drag_coeff": 0.0,                   # held mode = no flight drag
    "ball_magnus_coeff": 0.0,
    "gravity_y":      0.0,                     # held mode = no gravity
    "wall_restitution": 1.0,
    "coupling":        0.85,
    "weapon_class":    "melee_blade",
    # Verb taxonomy. PUNCH excluded — sword too long.
    "held_verbs":      ["SLASH", "STAB", "HACK", "RIPOSTE"],
    "default_verb":    "SLASH",
}


# ----------------------------------------------------------------------
# Verb selection helpers
# ----------------------------------------------------------------------


def supported_verbs(weapon_profile: dict[str, Any]) -> list[HeldVerb]:
    """Resolve `held_verbs` (list of names) into HeldVerb enum values.
    Empty list → falls back to PUNCH (the universal default)."""
    names = weapon_profile.get("held_verbs") or []
    out: list[HeldVerb] = []
    for n in names:
        try:
            out.append(HeldVerb[str(n).upper()])
        except KeyError:
            continue          # silently skip unknown verb names
    if not out:
        out.append(HeldVerb.PUNCH)
    return out


def cycle_verb(
    weapon_profile: dict[str, Any],
    current:        HeldVerb,
    direction:      int = 1,
) -> HeldVerb:
    """Cycle to next/prev verb in weapon's supported list. direction=+1
    forward, -1 back. Wraps at list ends."""
    verbs = supported_verbs(weapon_profile)
    if current not in verbs:
        return verbs[0]
    idx = verbs.index(current)
    idx = (idx + direction) % len(verbs)
    return verbs[idx]


# ----------------------------------------------------------------------
# Dispatcher — held-mode resolution lives in strike_runtime; this is
# a placeholder that gets registered for completeness.
# ----------------------------------------------------------------------


def _held_dispatcher(active_strike, world):
    """HELD mode resolution. Per-frame swept-sphere CCD lives in
    `strike_runtime._tick_held`; this dispatcher is a placeholder for
    future mode-specific overrides (e.g. RIPOSTE's parry path)."""
    return []


# ----------------------------------------------------------------------
# Activation
# ----------------------------------------------------------------------


def activate(vault) -> None:
    """Seed iron_sword profile + register HELD dispatcher. Idempotent."""
    if vault.profile_load(WEAPON_INSTANCE_ID, "iron_sword") is None:
        vault.profile_save(
            WEAPON_INSTANCE_ID,
            "iron_sword",
            params=IRON_SWORD_PROFILE,
            notes="V1 melee_blade — feat_arpg-combat PR 3",
        )
    strike.register_dispatcher("held", _held_dispatcher)


# ----------------------------------------------------------------------
# Convenience programmatic spawn
# ----------------------------------------------------------------------


def on_use(
    weapon_profile: dict[str, Any],
    camera_state:   dict[str, Any],
    source_actor:   str = "player",
    verb:           HeldVerb | None = None,
) -> Any:
    """Construct a HELD-mode Strike with the given verb (or default)."""
    return strike.spawn(
        weapon_profile=weapon_profile,
        mode="held",
        camera_state=camera_state,
        source_actor=source_actor,
        held_verb=verb,
    )
