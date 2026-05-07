"""Strike primitive — universal ARPG combat substrate.

Every weapon use spawns a Strike: a moving sphere with ContactProfile
properties that traverses space via the existing BallisticsSolver
(carved out of `feat/make-brain-ping-pong`) and resolves on contact.

Three modes per the locked V1 spec at `~/.claude/projects/.../memory/
design_arpg_combat_v1.md` + `.claude/feature/feat_arpg-combat.md`:

- WHIP   — tethered ball, swing-arc travel, deterministic retract
- SHOT   — direct projectile, point-and-launch, fades at visible distance
- HELD   — wielded weapon, persistent at hand, FIVE swing verbs
           (PUNCH / STAB / SLASH / HACK / RIPOSTE)

PR 1 (this file) ships the dataclass + IntEnum + factory + dispatch
stubs. Real per-mode resolution lands in PR 2 (SHOT), PR 3 (HELD), PR 4
(WHIP), PR 5 (combo).

Cross-references
----------------
- `design_arpg_combat_v1` — locked spec
- `design_creature_engagement_v1` — Strike-on-creature triggers engagement
- `design_wont_tolerate` #5 — no extractive mechanics on creatures;
  Strike triggers engagement, not damage
- `core/systems/ballistics.py` — the physics floor this primitive rides on
- `core/systems/make_brain_registry.py` — weapons register here per
  `instance_id="weapon"` with profile_name = weapon kind
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Literal

from core.systems.ballistics import BallisticsParams, MotionVector


# ---------------------------------------------------------------------------
# HeldVerb — five swing arcs. IntEnum so ordering is pinned and indexing
# is O(1). Adding a 6th verb is a real migration (verb tables, weapon
# profile lists, animation bindings) — not a content change.
# ---------------------------------------------------------------------------

class HeldVerb(IntEnum):
    PUNCH   = 0   # forward thrust, narrow capsule, fast (1.0m reach)
    STAB    = 1   # forward thrust extended, tip-cone (1.8m reach)
    SLASH   = 2   # horizontal sweep, wide arc (1.5m reach)
    HACK    = 3   # vertical chop, tall arc, heavy wind-up (1.5m reach)
    RIPOSTE = 4   # parry zone (defensive). NOT an offensive arc — see
                  # design_arpg_combat_v1 §"RIPOSTE — defensive verb"


# ---------------------------------------------------------------------------
# Default arc tuning per HeldVerb. V1 ships these as the default;
# per-weapon overrides land via vault.profiles row's `held_arc_overrides`
# dict (PR 3+). Numbers are first-pass dialed via UAT.
# ---------------------------------------------------------------------------

# (wind_up_s, active_s, cooldown_s, reach_m, hitbox_radius_m)
_DEFAULT_ARC_SHAPES: dict[HeldVerb, dict[str, float]] = {
    HeldVerb.PUNCH: {
        "wind_up_s":      0.05,
        "active_s":       0.10,
        "cooldown_s":     0.15,
        "reach_m":        1.0,
        "hitbox_radius":  0.30,    # narrow capsule
    },
    HeldVerb.STAB: {
        "wind_up_s":      0.10,
        "active_s":       0.15,
        "cooldown_s":     0.20,
        "reach_m":        1.8,
        "hitbox_radius":  0.20,    # tip-cone
    },
    HeldVerb.SLASH: {
        "wind_up_s":      0.08,
        "active_s":       0.20,
        "cooldown_s":     0.25,
        "reach_m":        1.5,
        "hitbox_radius":  0.40,    # wide arc-segment height
    },
    HeldVerb.HACK: {
        "wind_up_s":      0.20,    # heavier wind-up
        "active_s":       0.20,
        "cooldown_s":     0.30,
        "reach_m":        1.5,
        "hitbox_radius":  0.50,    # tall arc-segment width
    },
    HeldVerb.RIPOSTE: {
        "wind_up_s":      0.03,    # tight — don't broadcast a parry
        "active_s":       0.18,    # short timing window
        "cooldown_s":     0.35,    # punishes a failed parry
        "reach_m":        1.5,
        "hitbox_radius":  0.40,    # absorb-zone in front of player
    },
}


def arc_shape(verb: HeldVerb) -> dict[str, float]:
    """Per-verb arc geometry + timing. Returned dict is a copy so
    callers can mutate (e.g., per-weapon overrides) without polluting
    the defaults."""
    return dict(_DEFAULT_ARC_SHAPES[verb])


# ---------------------------------------------------------------------------
# Strike — the primitive every weapon use produces.
# ---------------------------------------------------------------------------

# Resolution kinds — what happens when the Strike contacts something.
# Per design_arpg_combat_v1:
#   damage_env             — hit env entity → damage per kinetic_energy × coupling × (1/hardness)
#   trigger_engagement     — hit creature → open creature's engagement_type from kind_config
#   apply_effect           — schema-only V1; full impl in V2 (status effects)
#   parry_incoming_strike  — RIPOSTE special-case; deflects an enemy Strike that crosses the parry zone
OnContactKind = Literal[
    "damage_env",
    "trigger_engagement",
    "apply_effect",
    "parry_incoming_strike",
]

StrikeMode = Literal["whip", "shot", "held"]

GeometryKind = Literal["sphere", "capsule", "blade"]


@dataclass(frozen=True)
class Strike:
    """One swing / shot / lash. Physics body + dispatch metadata.

    Constructed by `spawn()`; resolved by the per-mode dispatch function.
    Frozen so the brain can pass these around safely; new state lives in
    a fresh Strike (matching MotionVector / ContactProfile convention).
    """
    mode:              StrikeMode
    profile:           BallisticsParams       # ping-pong's substrate — mass, drag, magnus, etc.
    geometry:          GeometryKind           # V1 sphere only; V2 adds capsule + blade
    on_contact:        OnContactKind          # how to resolve a hit
    weapon_kind:       str                    # vault.profiles profile_name (e.g. "iron_sword")
    source_actor:      str                    # "player" or creature id

    # Initial physics state — mode-specific spawn position + velocity.
    initial_state:     MotionVector

    # Mode-specific knobs. Fields not used per mode are harmless / ignored
    # (e.g., a SHOT Strike has tether_length=0; nothing reads it).
    tether_length:     float = 0.0            # mode=whip
    shot_initial_v:    float = 0.0            # mode=shot
    held_verb:         HeldVerb | None = None  # mode=held
    held_arc:          dict[str, float] = field(default_factory=dict)
                                                # mode=held — per-verb timing + geometry


# ---------------------------------------------------------------------------
# Spawn factory — translates (weapon_profile, mode, camera_state) into a
# Strike instance. Each mode populates the right initial_state + knobs.
#
# camera_state is a dict carrying the input vectors needed to compute
# spawn position + initial velocity:
#   - "pos"      : (x, y, z) — player/source position
#   - "forward"  : (x, y, z) — unit forward direction (where player faces)
#   - "ang_vel"  : float     — camera angular velocity (rad/s) used for
#                              swing-strike paddle_velocity
# ---------------------------------------------------------------------------

def spawn(
    weapon_profile:  dict[str, Any],
    mode:            StrikeMode,
    camera_state:    dict[str, Any],
    source_actor:    str,
    *,
    held_verb:       HeldVerb | None = None,
    on_contact:      OnContactKind | None = None,
) -> Strike:
    """Construct a Strike from a vault.profiles weapon row + camera state.

    Raises ValueError on unknown mode or missing required camera fields.

    `held_verb` is required for mode=held; ignored otherwise. If None and
    mode=held, falls back to weapon_profile['default_verb'] or PUNCH.

    `on_contact` defaults are inferred from mode — most weapons land on
    `damage_env` (which the resolver routes per target kind: env →
    damage, creature with engagement slot → trigger_engagement). RIPOSTE
    overrides to `parry_incoming_strike`.
    """
    if mode not in ("whip", "shot", "held"):
        raise ValueError(f"strike.spawn: unknown mode {mode!r}")

    # Required camera fields ----------------------------------------------
    pos = tuple(camera_state["pos"])
    fwd = tuple(camera_state["forward"])

    # Profile + ballistics params -----------------------------------------
    profile = BallisticsParams.from_profile(weapon_profile)
    geometry = str(weapon_profile.get("geometry", "sphere"))
    weapon_kind = str(weapon_profile.get("profile_name") or
                      weapon_profile.get("weapon_kind") or
                      "unknown_weapon")

    # Initial state per mode ----------------------------------------------
    if mode == "shot":
        v0 = float(weapon_profile.get("shot_initial_v",
                                      weapon_profile.get("secondary_v", 12.0)))
        initial_vel = (fwd[0] * v0, fwd[1] * v0, fwd[2] * v0)
        initial_state = MotionVector(
            pos=pos, vel=initial_vel, spin=(0.0, 0.0, 0.0),
            timestamp=float(camera_state.get("now", 0.0)),
        )
        oc: OnContactKind = on_contact or "damage_env"
        return Strike(
            mode="shot",
            profile=profile,
            geometry=geometry,
            on_contact=oc,
            weapon_kind=weapon_kind,
            source_actor=source_actor,
            initial_state=initial_state,
            shot_initial_v=v0,
        )

    if mode == "whip":
        tether = float(weapon_profile.get("tether_length", 2.0))
        ang_vel = float(camera_state.get("ang_vel", 0.0))
        # Swing arc velocity = camera_angular_velocity × tether_length
        # (per ping-pong V1 paddle_velocity math).
        swing_speed = abs(ang_vel) * tether
        # Initial direction is forward + perpendicular swing — V1
        # simplification: launch tangent to forward in the swing plane.
        initial_vel = (fwd[0] * swing_speed, fwd[1] * swing_speed, fwd[2] * swing_speed)
        # Ball spawns at end of tether, forward of player.
        spawn_pos = (
            pos[0] + fwd[0] * tether,
            pos[1] + fwd[1] * tether,
            pos[2] + fwd[2] * tether,
        )
        initial_state = MotionVector(
            pos=spawn_pos, vel=initial_vel, spin=(0.0, 0.0, 0.0),
            timestamp=float(camera_state.get("now", 0.0)),
        )
        oc = on_contact or "damage_env"
        return Strike(
            mode="whip",
            profile=profile,
            geometry=geometry,
            on_contact=oc,
            weapon_kind=weapon_kind,
            source_actor=source_actor,
            initial_state=initial_state,
            tether_length=tether,
        )

    # mode == "held"
    if held_verb is None:
        default_verb_name = weapon_profile.get("default_verb")
        if default_verb_name is not None:
            held_verb = HeldVerb[str(default_verb_name).upper()]
        else:
            held_verb = HeldVerb.PUNCH
    arc = arc_shape(held_verb)
    # Capture forward direction at swing-start so the runtime can place
    # the swept hitbox at player_pos + forward × reach during the active
    # phase. Camera rotation during swing doesn't follow — held swings
    # are locked to start-of-swing direction (standard ARPG melee feel).
    arc["spawn_forward"] = [float(fwd[0]), float(fwd[1]), float(fwd[2])]
    # Held-mode "ball" stays at hand; initial velocity zero (the swing
    # arc itself drives the per-frame hitbox sweep, computed during
    # resolution rather than as initial_state.vel).
    initial_state = MotionVector(
        pos=pos, vel=(0.0, 0.0, 0.0), spin=(0.0, 0.0, 0.0),
        timestamp=float(camera_state.get("now", 0.0)),
    )
    # RIPOSTE overrides on_contact to its parry resolution kind unless
    # caller explicitly provides one.
    if on_contact is None:
        oc = "parry_incoming_strike" if held_verb == HeldVerb.RIPOSTE else "damage_env"
    else:
        oc = on_contact
    return Strike(
        mode="held",
        profile=profile,
        geometry=geometry,
        on_contact=oc,
        weapon_kind=weapon_kind,
        source_actor=source_actor,
        initial_state=initial_state,
        held_verb=held_verb,
        held_arc=arc,
    )


# ---------------------------------------------------------------------------
# Per-mode dispatch stubs. PR 1 ships placeholders that raise
# NotImplementedError when called; PR 2-4 land real implementations.
#
# The brain calls `resolve(strike, world)` and the right dispatcher is
# selected by mode. Future per-mode files (`weapons/ranged_thrown.py`,
# etc.) register handlers here as part of their PRs.
# ---------------------------------------------------------------------------

_DISPATCHERS: dict[StrikeMode, Any] = {}


def register_dispatcher(mode: StrikeMode, handler: Any) -> None:
    """Register a per-mode dispatcher. Idempotent overwrite — each
    mode's PR replaces the stub when its real handler is ready."""
    _DISPATCHERS[mode] = handler


def get_dispatcher(mode: StrikeMode) -> Any:
    """Return the registered dispatcher for a mode, or None if not yet
    wired. Callers should NotImplementedError on None."""
    return _DISPATCHERS.get(mode)


def resolve(strike: Strike, world: Any) -> list:
    """Top-level dispatch. Routes to the per-mode handler. Returns a
    list of ContactProfile records (the contacts produced during this
    Strike's resolution) for telemetry / state-event emission.

    PR 1 stub: raises NotImplementedError if the mode isn't registered
    yet. PR 2 (SHOT), PR 3 (HELD), PR 4 (WHIP), PR 5 (combo) register
    handlers as they land.
    """
    fn = get_dispatcher(strike.mode)
    if fn is None:
        raise NotImplementedError(
            f"strike.resolve: no dispatcher for mode {strike.mode!r} "
            f"(PR 1 ships stubs only — PR 2+ wire real handlers)"
        )
    return fn(strike, world)


def _reset_dispatchers_for_tests() -> None:
    """Test-only: clear dispatcher registry between cases."""
    _DISPATCHERS.clear()
