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

    # HELD-mode multi-hit ledger. Tracks entity ids (or kind+pos
    # fallback) already struck this swing so a single arc doesn't
    # double-hit the same target. Reset implicitly per Strike (each
    # ActiveStrike is one swing).
    held_hit_ids: set[Any] = field(default_factory=set)

    # Per-verb-swept hitbox position. Updated each frame during HELD
    # active phase by _verb_direction; consumed by CCD + manifest.
    # None outside active phase (CCD skipped anyway). Per
    # feat/arpg-combat PR 9 — brain-side per-verb sweep.
    held_hitbox_pos: tuple[float, float, float] | None = None

    # vault.combat_sessions row id (feat/arpg-combat PR 7). Set when
    # the brain opens a session on weapon_use; closed on resolution.
    # None for non-telemetry contexts (tests, headless).
    session_id: int | None = None

    # weapon_class — read from weapon_profile at spawn time. Used by
    # PR 7 activity-loop differentiation (HUNT for melee/thrown/bow,
    # SOLVE for magic).
    weapon_class: str | None = None


def make_active(strike: Strike, walls: list[WallPlane] | None = None) -> ActiveStrike:
    """Construct an ActiveStrike wrapping a freshly-spawned Strike.

    `walls` defaults to empty (no chamber walls — outdoor / cavern
    open-world flight). Per-mode handlers can pass chamber_walls when
    relevant (e.g., volley_chamber containment).

    HELD-mode max_age_s is sized to the verb's full lifecycle
    (wind_up + active + cooldown) so the strike resolves cleanly when
    the cooldown phase ends. SHOT/WHIP keep the default 5.0s flight
    budget.
    """
    solver = BallisticsSolver(strike.profile, walls or [])
    max_age = DEFAULT_MAX_AGE_S
    if strike.mode == "held" and strike.held_arc:
        # Sum the three phases — strike resolves at end of cooldown.
        max_age = (
            float(strike.held_arc.get("wind_up_s",  0.0)) +
            float(strike.held_arc.get("active_s",   0.0)) +
            float(strike.held_arc.get("cooldown_s", 0.0))
        )
    elif strike.mode == "whip" and strike.held_arc:
        # Sum swing + retract — ball returns to player at end of retract.
        max_age = (
            float(strike.held_arc.get("whip_swing_s",   0.45)) +
            float(strike.held_arc.get("whip_retract_s", 0.30))
        )
    return ActiveStrike(
        strike        = strike,
        current_state = strike.initial_state,
        solver        = solver,
        max_age_s     = max_age,
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
        # Branch by mode — each has different advancement + collision
        # semantics. SHOT advances via BallisticsSolver + segment CCD
        # (single-hit). WHIP swings under physics with multi-hit, then
        # animates retract back to player. HELD doesn't translate; the
        # swing arc IS the hitbox, swept per-frame during active phase.
        if active.strike.mode == "held":
            _tick_held(active, entities, kind_config, dt, on_resolve, events)
        elif active.strike.mode == "whip":
            _tick_whip(active, entities, kind_config, dt, on_resolve, events)
        else:
            _tick_flight(active, entities, kind_config, dt, on_resolve, events)
    return events


def _tick_flight(
    active:      ActiveStrike,
    entities:    list[dict[str, Any]],
    kind_config: dict[str, dict[str, Any]],
    dt:          float,
    on_resolve:  Any,
    events:      list[dict[str, Any]],
) -> None:
    """SHOT / WHIP mode tick — physics-advanced, single-target resolve.
    Used for any Strike that translates through space (ball really
    flies). Multi-hit not supported here — one contact resolves the
    Strike."""
    prev_pos = active.current_state.pos
    new_state, _wall_contacts = active.solver.step(active.current_state, dt)
    active.current_state = new_state
    active.age_seconds += dt

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
        return

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


def _verb_direction(
    verb_name:      str,
    spawn_forward:  tuple[float, float, float],
    progress:       float,
    base_reach:     float,
) -> tuple[tuple[float, float, float], float]:
    """Compute the swept hitbox direction + effective reach for a HELD
    verb at the given progress t ∈ [0, 1] through the active phase.

    Per `design_arpg_combat_v1` HELD verb taxonomy + sketch:
      - PUNCH:   short straight thrust (reach × 0.6, no sweep)
      - STAB:    extended straight thrust (full reach, no sweep)
      - SLASH:   horizontal sweep around UP axis, -60° → +60° as t: 0→1
      - HACK:    vertical chop around RIGHT axis, +60° → -60° (up→down)
      - RIPOSTE: stationary, no sweep (parry zone)

    Returns (direction_unit_vector, effective_reach). Direction is in
    brain coords (x=lateral, y=forward, z=up). Effective reach varies
    per verb (PUNCH shorter than STAB).

    Math:
      Z-axis rotation (SLASH):
        v_new = (cos·v_x - sin·v_y, sin·v_x + cos·v_y, v_z)
      Right-axis rotation (HACK):
        right = (fy, -fx, 0) / |(fy, -fx, 0)|  (horizontal-perp to forward)
        Rodrigues: v_new = v·cos + (k×v)·sin + k(k·v)(1-cos)
    """
    fx, fy, fz = float(spawn_forward[0]), float(spawn_forward[1]), float(spawn_forward[2])
    verb = str(verb_name).upper()

    if verb == "PUNCH":
        return ((fx, fy, fz), base_reach * 0.6)
    if verb in ("STAB", "RIPOSTE"):
        # Straight forward; RIPOSTE stationary (no sweep), STAB extends.
        return ((fx, fy, fz), base_reach)

    if verb == "SLASH":
        # Sweep angle from -60° → +60° across active phase
        half_arc = math.radians(60.0)
        angle = -half_arc + 2.0 * half_arc * progress
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        return (
            (cos_a * fx - sin_a * fy,
             sin_a * fx + cos_a * fy,
             fz),
            base_reach,
        )

    if verb == "HACK":
        # Tilt around right axis: +60° (pointed up) → -60° (pointed down)
        half_arc = math.radians(60.0)
        angle = half_arc - 2.0 * half_arc * progress
        # Right axis = horizontal perpendicular to forward.
        rx, ry = fy, -fx
        rnorm = math.sqrt(rx * rx + ry * ry)
        if rnorm < 1e-6:
            # Forward is near-vertical; fall back to no rotation
            return ((fx, fy, fz), base_reach)
        rx /= rnorm
        ry /= rnorm
        # Rodrigues' formula for rotation around k=(rx, ry, 0):
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        # k × v
        cvx = ry * fz - 0.0 * fy
        cvy = 0.0 * fx - rx * fz
        cvz = rx * fy - ry * fx
        # k · v
        kdv = rx * fx + ry * fy + 0.0 * fz
        nx = fx * cos_a + cvx * sin_a + rx * kdv * (1.0 - cos_a)
        ny = fy * cos_a + cvy * sin_a + ry * kdv * (1.0 - cos_a)
        nz = fz * cos_a + cvz * sin_a + 0.0 * kdv * (1.0 - cos_a)
        return ((nx, ny, nz), base_reach)

    # Unknown verb — straight forward fallback.
    return ((fx, fy, fz), base_reach)


def _tick_whip(
    active:      ActiveStrike,
    entities:    list[dict[str, Any]],
    kind_config: dict[str, dict[str, Any]],
    dt:          float,
    on_resolve:  Any,
    events:      list[dict[str, Any]],
) -> None:
    """WHIP mode tick — two phases: swing (physics + multi-hit), then
    retract (animation back to player). Ball ALWAYS returns to player
    at end of retract (deterministic — even on miss).

    The swing phase runs BallisticsSolver advance + segment-vs-sphere
    CCD with multi-hit (similar to HELD but along a flying ball
    trajectory). The retract phase is animation only — no collisions,
    ball position interpolates from end-of-swing pos toward player_pos
    over retract_duration.

    Per `design_arpg_combat_v1` WHIP AC: STRIKE input INITIATES; multi-
    hit possible per arc; ball returns deterministically.
    """
    # Per-weapon swing/retract durations stored on the strike's profile
    # via raw weapon_profile params. We retrieve via held_arc as a
    # convenience (V1 stores them on Strike.held_arc for WHIP too —
    # `arc_shape` only emits these for HELD verbs, so WHIP picks them
    # up from default factory or via spawn-time injection. For V1, we
    # just default in-place if absent.)
    swing_duration = 0.45
    retract_duration = 0.30
    # Allow Strike.held_arc to override (in case future tooling stamps
    # whip phases there). Best-effort lookup.
    if active.strike.held_arc:
        swing_duration = float(active.strike.held_arc.get("whip_swing_s", swing_duration))
        retract_duration = float(active.strike.held_arc.get("whip_retract_s", retract_duration))
    # max_age = swing + retract (set in make_active for HELD; for WHIP
    # we set it here on first tick).
    if active.max_age_s == DEFAULT_MAX_AGE_S:
        active.max_age_s = swing_duration + retract_duration

    prev_age = active.age_seconds
    active.age_seconds += dt
    new_age = active.age_seconds

    # Phase 1: swing (physics + multi-hit) ------------------------------
    if prev_age < swing_duration:
        # Some or all of dt was during swing.
        swing_dt = min(dt, swing_duration - prev_age)
        prev_pos = active.current_state.pos
        new_state, _ = active.solver.step(active.current_state, swing_dt)
        active.current_state = new_state

        # Multi-hit: check entities along swing segment, accumulate hits
        # in held_hit_ids (reused for whip per the per-active set).
        for ent in entities:
            ent_id = ent.get("id")
            if ent_id is not None and ent_id in active.held_hit_ids:
                continue
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
            contact_r = active.strike.profile.ball_radius + ent_r
            toi = _segment_sphere_intersect(prev_pos, active.current_state.pos,
                                            (ex, ey, ez), contact_r)
            if toi is None:
                continue
            if ent_id is not None:
                active.held_hit_ids.add(ent_id)
            else:
                active.held_hit_ids.add((kind, ex, ey, ez))
            active.contact_target_kind = kind
            active.contact_pos = active.current_state.pos
            events.append({
                "kind":        "strike_landed",
                "weapon_kind": active.strike.weapon_kind,
                "mode":        "whip",
                "source":      active.strike.source_actor,
                "target_kind": kind,
                "target_id":   ent_id,
                "contact_pos": active.current_state.pos,
                "kinetic_energy": kinetic_energy(
                    active.current_state, active.strike.profile.ball_mass,
                ),
                "on_contact":  active.strike.on_contact,
            })
            if on_resolve is not None:
                on_resolve(active, ent)
        # Continue arc — even after hits, ball plows through.

    # Phase 2: retract (animation only — no collisions) ----------------
    # If new_age has crossed into retract territory, stop physics and
    # interpolate ball position toward player. For V1, we just don't
    # advance physics — ball position freezes at end-of-swing, runtime
    # fades it out at end of retract. (Fancy reel-in animation is
    # client-side polish in PR 6.)

    # Resolve at end of total ------------------------------------------
    if new_age >= active.max_age_s:
        active.resolved = True
        active.resolved_kind = "landed" if active.held_hit_ids else "missed"
        events.append({
            "kind":         "swing_complete" if active.held_hit_ids else "strike_missed",
            "weapon_kind":  active.strike.weapon_kind,
            "mode":         "whip",
            "source":       active.strike.source_actor,
            "hit_count":    len(active.held_hit_ids),
        })
        if on_resolve is not None and not active.held_hit_ids:
            on_resolve(active, None)


def _tick_held(
    active:      ActiveStrike,
    entities:    list[dict[str, Any]],
    kind_config: dict[str, dict[str, Any]],
    dt:          float,
    on_resolve:  Any,
    events:      list[dict[str, Any]],
) -> None:
    """HELD mode tick — phase-tracked (wind_up → active → cooldown).
    During active phase, swept-sphere CCD against entities in the
    swing arc volume; multi-hit allowed (each entity hit once per
    swing, tracked via active.held_hit_ids).

    Hitbox position: player_pos + forward × reach. Swing arc as a
    SPHERE for V1; V2 adds true capsule/blade swept-volume.

    Phase boundaries from strike.held_arc (wind_up_s, active_s,
    cooldown_s)."""
    arc = active.strike.held_arc or {}
    wind_up_s = float(arc.get("wind_up_s",  0.0))
    active_s  = float(arc.get("active_s",   0.0))
    cooldown_s = float(arc.get("cooldown_s", 0.0))
    reach     = float(arc.get("reach_m",    1.0))
    radius    = float(arc.get("hitbox_radius", 0.4))
    spawn_fwd = arc.get("spawn_forward") or [0.0, 1.0, 0.0]

    active.age_seconds += dt
    age = active.age_seconds
    total = wind_up_s + active_s + cooldown_s

    # Resolve at end of full lifecycle.
    if age >= total:
        active.resolved = True
        # If we hit anything during the active window, "landed";
        # otherwise "missed".
        active.resolved_kind = "landed" if active.held_hit_ids else "missed"
        events.append({
            "kind":        "strike_missed" if not active.held_hit_ids else "swing_complete",
            "weapon_kind": active.strike.weapon_kind,
            "mode":        active.strike.mode,
            "source":      active.strike.source_actor,
            "hit_count":   len(active.held_hit_ids),
        })
        if on_resolve is not None and not active.held_hit_ids:
            on_resolve(active, None)
        return

    # Outside the active window — no hitbox, just phase-progressing.
    if age < wind_up_s or age > (wind_up_s + active_s):
        return

    # Active phase — compute hitbox center per-verb-swept direction.
    # PR 9: SLASH sweeps horizontally, HACK chops vertically, PUNCH/STAB
    # straight forward (different reach). RIPOSTE stationary.
    px, py, pz = active.current_state.pos
    # Progress through active phase: 0.0 → 1.0
    progress = (age - wind_up_s) / max(active_s, 1e-6)
    progress = max(0.0, min(1.0, progress))
    verb_name = (active.strike.held_verb.name
                  if active.strike.held_verb else "STAB")
    swept_dir, eff_reach = _verb_direction(
        verb_name, spawn_fwd, progress, reach,
    )
    hx = px + swept_dir[0] * eff_reach
    hy = py + swept_dir[1] * eff_reach
    hz = pz + swept_dir[2] * eff_reach
    # Stash on the strike so _strike_to_manifest can read it without
    # recomputing the verb math.
    active.held_hitbox_pos = (hx, hy, hz)

    for ent in entities:
        ent_id = ent.get("id")
        if ent_id is not None and ent_id in active.held_hit_ids:
            continue                # already hit this swing, skip
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
        dx, dy, dz = hx - ex, hy - ey, hz - ez
        d2 = dx * dx + dy * dy + dz * dz
        contact_d = radius + ent_r
        if d2 > contact_d * contact_d:
            continue
        # Hit. Multi-hit semantics: record this entity as struck,
        # emit one contact event, but do NOT resolve the Strike — the
        # arc continues, can hit other entities in same active phase.
        if ent_id is not None:
            active.held_hit_ids.add(ent_id)
        else:
            # No id — fall back to (kind, x, y, z) as a stable identifier
            active.held_hit_ids.add((kind, ex, ey, ez))
        active.contact_target_kind = kind
        active.contact_pos = (hx, hy, hz)
        events.append({
            "kind":          "strike_landed",
            "weapon_kind":   active.strike.weapon_kind,
            "mode":          active.strike.mode,
            "source":        active.strike.source_actor,
            "target_kind":   kind,
            "target_id":     ent_id,
            "contact_pos":   (hx, hy, hz),
            "kinetic_energy": kinetic_energy(
                active.current_state, active.strike.profile.ball_mass,
            ),
            "on_contact":    active.strike.on_contact,
            "held_verb":     active.strike.held_verb.name if active.strike.held_verb else None,
        })
        if on_resolve is not None:
            on_resolve(active, ent)


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
