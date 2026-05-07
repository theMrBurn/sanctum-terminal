"""Strike runtime — active in-flight strikes + per-tick advance + contact resolution.

Companion to `core/systems/strike.py` (frozen primitive) — this module
owns the MUTABLE state that lives between frames: ball position evolving
under physics, age, target tracking. The brain holds an
`active_strikes: list[ActiveStrike]` and ticks it each frame.

Per `feat/arpg-combat` PR 2 — first end-to-end mode is SHOT
(throwing_axe). PR 3 (HELD), PR 4 (WHIP), PR 5 (combo) extend the
runtime with mode-specific resolution paths via the dispatcher
registry on `strike.py`.

## Tunneling protection — segment-vs-sphere CCD

Per-frame physics advances the ball discretely; at high speeds + low
target radii the ball can skip through targets between samples. The
runtime uses segment-vs-sphere intersection (earliest TOI in [0,1])
between prev_pos and new_pos, NOT just the end position. Mirrors
`BallisticsSolver._earliest_wall_impact` shape but against entity
spheres instead of wall planes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from core.systems.ballistics import (
    BallisticsSolver, ContactProfile, MotionVector, WallPlane,
)
from core.systems.strike import Strike


# Default max-age for in-flight Strikes — past this, the Strike fades
# without resolution. SHOT mode at 18 m/s × 5s = 90m total flight, well
# beyond the player's typical perception envelope. Per-mode overrides
# land via Strike's mode-specific knobs in future PRs.
DEFAULT_MAX_AGE_S: float = 5.0


@dataclass
class ActiveStrike:
    """Mutable runtime wrapper around a frozen Strike. The brain
    advances this each tick until contact OR max_age."""

    strike:        Strike
    current_state: MotionVector
    age_seconds:   float = 0.0
    max_age_s:     float = DEFAULT_MAX_AGE_S
    solver:        BallisticsSolver | None = None

    # When a strike resolves (hit or fade), set to True so the runtime
    # tick filters it out at end of frame. Resolution side-effects
    # (state events, activity emits) are fired by the resolver.
    resolved:      bool = False
    resolved_kind: str | None = None              # "landed" | "missed" | "absorbed"

    # Telemetry the brain can stash on resolve for post-hoc analysis
    # (vault.combat_sessions, future PR 7).
    contact_target_kind: str | None = None
    contact_pos:         tuple[float, float, float] | None = None


def make_active(strike: Strike, walls: list[WallPlane] | None = None) -> ActiveStrike:
    """Construct an ActiveStrike wrapping a freshly-spawned Strike.

    `walls` defaults to empty (no chamber walls — outdoor / cavern
    open-world flight). Per-mode handlers can pass chamber_walls when
    relevant (e.g., volley_chamber containment).
    """
    solver = BallisticsSolver(strike.profile, walls or [])
    return ActiveStrike(
        strike        = strike,
        current_state = strike.initial_state,
        solver        = solver,
    )


def kinetic_energy(state: MotionVector, mass: float) -> float:
    """½·m·v². Used by the damage formula in resolution. Returned in
    kg·m²/s². For per-frame UI checks; not the only damage input —
    coupling + target.hardness also factor."""
    vx, vy, vz = state.vel
    speed_sq = vx * vx + vy * vy + vz * vz
    return 0.5 * mass * speed_sq


def tick_active_strikes(
    active_strikes: list[ActiveStrike],
    entities: list[dict[str, Any]],
    kind_config: dict[str, dict[str, Any]],
    dt: float,
    *,
    on_resolve: Any = None,
) -> list[dict[str, Any]]:
    """Advance all active strikes by `dt`, check entity collisions,
    resolve hits + fades. Returns a list of resolution events the
    caller forwards to state_events / activity_loop / vault telemetry.

    Each ActiveStrike's `resolved` flag is set on hit or fade. Caller
    is expected to filter out resolved strikes at end of frame.

    `on_resolve` is an optional callable(active_strike, target_entity_or_none)
    invoked per resolution — lets the brain emit StateEvents,
    activity_loop signals, and trigger creature engagements without
    this module knowing the brain's surface.
    """
    events: list[dict[str, Any]] = []
    for active in active_strikes:
        if active.resolved:
            continue
        # Physics advance — capture prev_pos for segment-vs-sphere CCD.
        prev_pos = active.current_state.pos
        new_state, _wall_contacts = active.solver.step(active.current_state, dt)
        active.current_state = new_state
        active.age_seconds += dt

        # Age-based fade — strike never reached anything
        if active.age_seconds >= active.max_age_s:
            active.resolved = True
            active.resolved_kind = "missed"
            events.append({
                "kind":        "strike_missed",
                "weapon_kind": active.strike.weapon_kind,
                "mode":        active.strike.mode,
                "source":      active.strike.source_actor,
                "fade_pos":    new_state.pos,
            })
            if on_resolve is not None:
                on_resolve(active, None)
            continue

        # Entity collision check — segment-vs-sphere CCD. Catches
        # tunneling when ball traverses more than 2×combined_radius
        # per frame.
        hit_entity = _find_collision(
            prev_pos,
            active.current_state.pos,
            active.strike.profile.ball_radius,
            entities,
            kind_config,
        )
        if hit_entity is not None:
            active.resolved = True
            active.resolved_kind = "landed"
            active.contact_target_kind = str(hit_entity.get("kind", ""))
            active.contact_pos = active.current_state.pos
            events.append({
                "kind":          "strike_landed",
                "weapon_kind":   active.strike.weapon_kind,
                "mode":          active.strike.mode,
                "source":        active.strike.source_actor,
                "target_kind":   active.contact_target_kind,
                "target_id":     hit_entity.get("id"),
                "contact_pos":   active.contact_pos,
                "kinetic_energy": kinetic_energy(
                    active.current_state, active.strike.profile.ball_mass,
                ),
                "on_contact":    active.strike.on_contact,
            })
            if on_resolve is not None:
                on_resolve(active, hit_entity)
            continue
    return events


def _find_collision(
    prev_pos:    tuple[float, float, float],
    new_pos:     tuple[float, float, float],
    ball_radius: float,
    entities:    list[dict[str, Any]],
    kind_config: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Segment-vs-sphere CCD across nearby entities. Returns the entity
    whose sphere is hit EARLIEST along the prev→new segment (smallest
    TOI in [0, 1]), or None if no entity is hit.

    Catches tunneling that simple end-position-distance checks miss:
    a 10 m/s ball at 60Hz dt=0.016 moves 0.16m/frame, but 0.2s test
    ticks move 2m — easily skipping through a 1m-diameter target.
    """
    earliest_t: float = 2.0    # > any valid t ∈ [0, 1]
    earliest_ent: dict[str, Any] | None = None
    for ent in entities:
        try:
            ex = float(ent.get("x", 0.0))
            ey = float(ent.get("y", 0.0))
            ez = float(ent.get("z", 0.0))
        except (TypeError, ValueError):
            continue
        kind = str(ent.get("kind", ""))
        ent_r = _entity_collision_radius(kind, kind_config)
        if ent_r <= 0:
            continue
        contact_r = ball_radius + ent_r
        toi = _segment_sphere_intersect(prev_pos, new_pos, (ex, ey, ez), contact_r)
        if toi is not None and toi < earliest_t:
            earliest_t = toi
            earliest_ent = ent
    return earliest_ent


def _segment_sphere_intersect(
    p0:     tuple[float, float, float],
    p1:     tuple[float, float, float],
    center: tuple[float, float, float],
    r:      float,
) -> float | None:
    """Return earliest t ∈ [0, 1] where segment p0→p1 intersects the
    sphere at `center` with radius `r`, or None if no intersection.

    Closed-form quadratic: |p0 + t·d - C|² = r²
        (m + t·d) · (m + t·d) = r²    where m = p0 - C, d = p1 - p0
        a·t² + b·t + c = 0
            a = d · d
            b = 2 (m · d)
            c = m · m - r²
    """
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    dz = p1[2] - p0[2]
    a = dx * dx + dy * dy + dz * dz
    if a < 1e-12:
        # Zero-length segment — point-vs-sphere check
        mx = p0[0] - center[0]
        my = p0[1] - center[1]
        mz = p0[2] - center[2]
        if mx * mx + my * my + mz * mz <= r * r:
            return 0.0
        return None
    mx = p0[0] - center[0]
    my = p0[1] - center[1]
    mz = p0[2] - center[2]
    b = 2.0 * (mx * dx + my * dy + mz * dz)
    c = mx * mx + my * my + mz * mz - r * r
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    sqrt_disc = math.sqrt(disc)
    t1 = (-b - sqrt_disc) / (2.0 * a)
    t2 = (-b + sqrt_disc) / (2.0 * a)
    # Earliest non-negative t in [0, 1]; handle starts-inside case
    # (t1 negative, t2 positive ⇒ ball started inside sphere, immediate
    # contact).
    if t1 >= 0.0 and t1 <= 1.0:
        return t1
    if t2 >= 0.0 and t2 <= 1.0:
        return t2
    if t1 < 0.0 and t2 >= 0.0:
        # Started inside the sphere; treat as immediate contact.
        return 0.0
    return None


def _entity_collision_radius(
    kind:        str,
    kind_config: dict[str, dict[str, Any]],
) -> float:
    """Pull entity collision radius from kind_config, falling back to
    a small default. Strike doesn't currently reference kind_config's
    `engagement` slot — that lookup happens at resolution time in the
    brain (so this stays a pure geometry helper)."""
    cfg = kind_config.get(kind) or {}
    bounds = cfg.get("bounds") or {}
    r = bounds.get("radius")
    if r is not None:
        try:
            return float(r)
        except (TypeError, ValueError):
            pass
    # Fallback: env kinds typically 0.5-1.0m, creatures similar.
    # Returning 0.5 is conservative and reasonable for V1.
    return 0.5
