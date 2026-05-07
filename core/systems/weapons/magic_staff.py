"""magic_staff — combo weapon (HELD primary + SHOT secondary).

Per `feat_arpg-combat.md` PR 5. Proves the architecture supports
multi-mode-per-weapon: a single weapon profile carries both a primary
swing (held) and a secondary cast (shot) shape, dispatched by the
input the player pressed.

Combo profile uses a `modes` sub-dict keyed by mode name. Each
sub-dict is a normal mode profile (mass, radius, coupling, etc.).
Brain dispatch resolves combo profiles by extracting the sub-profile
matching the input's mode arg.

V1 ships `fire_staff` — primary STAB swing for melee + secondary
fireball cast. Activity-loop integration (PR 7): primary swing emits
HUNT (kinetic combat); secondary cast emits SOLVE (constrained-aim
problem-solving). Wizard-heavy player gets puzzle-shaped tension via
the SOLVE → activity_loop chain.
"""
from __future__ import annotations

from typing import Any

from core.systems import strike


WEAPON_INSTANCE_ID: str = "weapon"


# ----------------------------------------------------------------------
# V1 combo weapon — fire_staff
#
# Shape: top-level fields are common (weapon_class, etc.); per-mode
# fields live under `modes[<mode_name>]`. Brain dispatch unpacks the
# right sub-dict before calling strike.spawn().
# ----------------------------------------------------------------------

FIRE_STAFF_PROFILE: dict[str, Any] = {
    "_target":        "magic combo — V1 PR 5 proof, fire staff",
    "weapon_class":   "magic_staff",
    # No top-level mode — combo weapons declare per-mode sub-profiles.
    # The presence of `modes` is the signal to the brain dispatch.
    "modes": {
        # Primary — close-range thrust. Narrow set (STAB + RIPOSTE).
        # Staves traditionally parry; PUNCH/SLASH/HACK don't fit.
        "held": {
            "mode":             "held",
            "geometry":         "sphere",
            "ball_mass":        1.0,
            "ball_radius":      0.3,
            "ball_drag_coeff":  0.0,
            "ball_magnus_coeff": 0.0,
            "gravity_y":        0.0,
            "wall_restitution": 1.0,
            "coupling":         0.6,
            "held_verbs":       ["STAB", "RIPOSTE"],
            "default_verb":     "STAB",
        },
        # Secondary — fire bolt. Spin-curve via magnus for arcing
        # trajectory; minimal drag (fire doesn't drag).
        "shot": {
            "mode":             "shot",
            "geometry":         "sphere",
            "ball_mass":        1.0,
            "ball_radius":      0.3,
            "ball_drag_coeff":  0.0,
            "ball_magnus_coeff": 0.15,            # spin-curve
            "gravity_y":        -3.0,             # mild arc, not freefall
            "wall_restitution": 0.5,
            "coupling":         0.95,
            "shot_initial_v":   24.0,
        },
    },
}


def is_combo(profile: dict[str, Any]) -> bool:
    """A profile is a combo weapon if it ships per-mode sub-profiles
    under the `modes` key."""
    return isinstance(profile.get("modes"), dict) and bool(profile.get("modes"))


def sub_profile(combo_profile: dict[str, Any], mode: str) -> dict[str, Any] | None:
    """Extract the sub-profile for a given mode from a combo weapon
    profile. Returns None if the mode isn't supported.

    The returned dict is a flat mode profile suitable for passing to
    `strike.spawn(weapon_profile=..., mode=...)`. Carries the parent
    profile's `weapon_class` + `profile_name` for telemetry."""
    modes = combo_profile.get("modes") or {}
    sub = modes.get(mode)
    if not isinstance(sub, dict):
        return None
    out = dict(sub)         # shallow copy — caller can mutate without polluting
    # Carry parent metadata down so strike.spawn populates weapon_kind correctly.
    if "weapon_class" not in out:
        out["weapon_class"] = combo_profile.get("weapon_class")
    if "profile_name" not in out:
        out["profile_name"] = combo_profile.get("profile_name", "fire_staff")
    return out


# ----------------------------------------------------------------------
# Activation
# ----------------------------------------------------------------------


def activate(vault) -> None:
    """Seed fire_staff combo profile. Idempotent. Dispatchers for
    held + shot were already registered by melee_blade + ranged_thrown
    activations — combo weapons reuse those existing dispatchers."""
    if vault.profile_load(WEAPON_INSTANCE_ID, "fire_staff") is None:
        vault.profile_save(
            WEAPON_INSTANCE_ID,
            "fire_staff",
            params=FIRE_STAFF_PROFILE,
            notes="V1 magic_staff combo — feat_arpg-combat PR 5",
        )


# ----------------------------------------------------------------------
# Convenience programmatic spawn for combo weapons
# ----------------------------------------------------------------------


def on_primary(
    weapon_profile: dict[str, Any],
    camera_state:   dict[str, Any],
    source_actor:   str = "player",
) -> Any:
    """Construct a HELD-mode Strike from the combo weapon's primary
    sub-profile. Raises ValueError if the profile has no `held` sub.
    """
    sub = sub_profile(weapon_profile, "held")
    if sub is None:
        raise ValueError("magic_staff.on_primary: profile has no `held` sub-mode")
    return strike.spawn(
        weapon_profile=sub,
        mode="held",
        camera_state=camera_state,
        source_actor=source_actor,
    )


def on_secondary(
    weapon_profile: dict[str, Any],
    camera_state:   dict[str, Any],
    source_actor:   str = "player",
) -> Any:
    """Construct a SHOT-mode Strike from the combo weapon's secondary
    sub-profile. Raises ValueError if the profile has no `shot` sub.
    """
    sub = sub_profile(weapon_profile, "shot")
    if sub is None:
        raise ValueError("magic_staff.on_secondary: profile has no `shot` sub-mode")
    return strike.spawn(
        weapon_profile=sub,
        mode="shot",
        camera_state=camera_state,
        source_actor=source_actor,
    )
