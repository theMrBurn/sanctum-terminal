"""BallisticsSolver — discrete-time 3D projectile physics for make-brains.

Brain-side authoritative solver. Same module powers ping_pong (V1) and
future combat encounters in the main brain (the "tennis math = combat
math" hypothesis). Single-player + localhost = brain-authoritative is
the simplest correct architecture — no client replication, no rollback.

Per `.claude/feature/feat_make-brain-ping-pong.md` PR 4.

Required reading consulted while authoring:
  - Erin Catto, "Continuous Collision," GDC 2013
    https://box2d.org/files/ErinCatto_ContinuousCollision_GDC2013.pdf
  - Mehta et al., "Review of Tennis Ball Aerodynamics," 2008 — tennis_sim
    drag/Magnus coefficients are sourced here.

## Sign / convention pins

Coordinate space is BRAIN space: x lateral, y forward (player-facing
into the cube), z up.

Magnus sign convention (most-mis-implemented detail in indie tennis
threads — pinned here so the integrator stays correct as we tune):

    +C_L on backspin → ball lifts (rises)
    −C_L on topspin  → ball drops

Reflection (per AC §"Physics contract"):

    v_ball_n' = (1 + e)·v_paddle_n − e·v_ball_n          # normal component
    v_ball_t' = v_ball_t + friction·v_paddle_t            # tangential (spin imparts here)

where e = wall_restitution, friction = paddle/ball tangential coupling.
Wall collisions use v_paddle = (0,0,0) so reflection collapses to:

    v_ball_n' = -e · v_ball_n

## Substep discipline

Fixed dt 1/60 outer, 4-8 inner substeps per Catto GDC 2015. Default 4.
At 100 m/s ball + 12m room, ball moves ~1.66m per outer frame; 4
substeps = ~0.42m per substep, well under ball radius for arcade
ball (0.15m). CCD remains mandatory because outer dt can stretch
under heavy load.

## CCD technique

Swept-sphere vs infinite plane — for each wall plane and the ball's
start->end segment over a substep, compute time-of-impact (TOI) by
intersecting `(p0 + t·v - C) · n = ±r` with t ∈ [0, 1]. Earliest
positive TOI wins; reflect at the contact, advance with remaining
time. No bisection needed for a single moving sphere vs static plane —
the closed-form solution is exact.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Iterable


# ----------------------------------------------------------------------
# Abstract keys — pinned in AC §"MotionVector / ContactProfile"
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class MotionVector:
    """Snapshot of a ballistic body's instantaneous state."""
    pos:        tuple[float, float, float]    # m
    vel:        tuple[float, float, float]    # m/s
    spin:       tuple[float, float, float]    # rad/s; axis × magnitude (Magnus axis)
    timestamp:  float                          # solver time, seconds since session start


@dataclass(frozen=True)
class ContactProfile:
    """Single ball/paddle (or ball/wall) contact event.

    Universal substrate — same record describes ping-pong strikes today
    and combat weapon-arc impacts in the future. Fields populated for
    every contact regardless of contact_kind.
    """
    contact_point:   tuple[float, float, float]
    incoming:        MotionVector
    paddle_normal:   tuple[float, float, float]    # unit normal of contact surface
    paddle_velocity: tuple[float, float, float]    # m/s; (0,0,0) for static walls
    outgoing:        MotionVector
    coupling_factor: float                          # 1.0 = full energy transfer (vanilla)
    contact_kind:    str                            # "wall_strike" / "paddle_strike" /
                                                    # "block" / "parry" (block + parry V3+)


@dataclass(frozen=True)
class WallPlane:
    """Static plane of the chamber. Inward normal points INTO the room.

    `interaction_kind` controls what happens when a moving ball hits the
    plane (per ARPG-combat PR 1, audit feat_arpg-combat.md):
      - `reflect`     — bounce off per `wall_restitution`. V1 ping-pong
                        chamber walls all use this. Default.
      - `absorb`      — ball stops at contact. Energy transferred. Used
                        for combat hitboxes representing creatures /
                        env entities that consume Strikes.
      - `passthrough` — ball continues with reduced speed
                        (`passthrough_coupling`). Used for combat
                        hitboxes that let multi-hit Strikes plow through
                        (held-mode multi-target swings).

    Default `reflect` preserves V1 ping-pong behavior — existing
    chamber_walls() ships pure-reflect planes, no migration needed.
    """
    point:  tuple[float, float, float]          # any point on the plane
    normal: tuple[float, float, float]          # unit, pointing INTO playable volume
    name:   str                                  # "floor" / "ceiling" / "north" / etc., for debugging
    interaction_kind: str = "reflect"            # "reflect" | "absorb" | "passthrough"
    passthrough_coupling: float = 0.85           # speed retention on passthrough; 1.0 = no loss


# ----------------------------------------------------------------------
# Helpers — small vector ops kept local so we don't pull numpy in for V1
# ----------------------------------------------------------------------


def _add(a, b):    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def _sub(a, b):    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _scale(a, s):  return (a[0] * s,   a[1] * s,   a[2] * s)
def _dot(a, b):    return  a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )
def _length(a):    return math.sqrt(_dot(a, a))


# ----------------------------------------------------------------------
# Chamber wall-plane factory
# ----------------------------------------------------------------------


def chamber_walls(size: tuple[float, float, float],
                  origin: tuple[float, float, float]) -> list[WallPlane]:
    """Six inward-facing planes for an axis-aligned cube.

    `origin` is bottom-center (x_center, y_center, z=floor). `size` is
    the (x, y, z) extent. Matches PingPongHandler.CHAMBER_GEOMETRY.
    """
    sx, sy, sz = float(size[0]), float(size[1]), float(size[2])
    ox, oy, oz = float(origin[0]), float(origin[1]), float(origin[2])
    half_x, half_y = sx / 2.0, sy / 2.0
    return [
        WallPlane((ox,           oy,           oz),         (0.0, 0.0,  1.0), "floor"),
        WallPlane((ox,           oy,           oz + sz),    (0.0, 0.0, -1.0), "ceiling"),
        WallPlane((ox - half_x,  oy,           oz),         ( 1.0, 0.0, 0.0), "west"),
        WallPlane((ox + half_x,  oy,           oz),         (-1.0, 0.0, 0.0), "east"),
        WallPlane((ox,           oy - half_y,  oz),         (0.0,  1.0, 0.0), "south"),
        WallPlane((ox,           oy + half_y,  oz),         (0.0, -1.0, 0.0), "north"),
    ]


# ----------------------------------------------------------------------
# Solver
# ----------------------------------------------------------------------


@dataclass
class BallisticsParams:
    """Snapshot of the active profile params consumed per substep."""
    ball_mass:         float = 1.0
    ball_radius:       float = 0.15
    ball_drag_coeff:   float = 0.0
    ball_magnus_coeff: float = 0.0
    gravity_y:         float = 0.0
    wall_restitution:  float = 1.0
    air_density:       float = 1.225            # kg/m³ at sea level — fixed for V1

    @classmethod
    def from_profile(cls, params: dict) -> "BallisticsParams":
        return cls(
            ball_mass         = float(params.get("ball_mass",         1.0)),
            ball_radius       = float(params.get("ball_radius",       0.15)),
            ball_drag_coeff   = float(params.get("ball_drag_coeff",   0.0)),
            ball_magnus_coeff = float(params.get("ball_magnus_coeff", 0.0)),
            gravity_y         = float(params.get("gravity_y",         0.0)),
            wall_restitution  = float(params.get("wall_restitution",  1.0)),
        )


class BallisticsSolver:
    """Brain-side ball physics. Stateless across instances — solver
    object is just a config holder; the ball state is passed in/out.

    Usage:
        solver = BallisticsSolver(params, walls)
        new_state, contacts = solver.step(state, dt, substeps=4)
    """

    def __init__(
        self,
        params: BallisticsParams,
        walls: Iterable[WallPlane],
    ):
        self.params = params
        self.walls = list(walls)

    # -- Public step -------------------------------------------------------

    def step(
        self,
        state: MotionVector,
        dt: float,
        substeps: int = 4,
    ) -> tuple[MotionVector, list[ContactProfile]]:
        """Advance ball state by `dt` total, sub-divided into `substeps`.

        Returns the new state and any wall ContactProfiles fired during
        the advance (for telemetry / state-event emission).
        """
        if substeps < 1:
            substeps = 1
        sub_dt = dt / substeps
        contacts: list[ContactProfile] = []
        for _ in range(substeps):
            state, sub_contacts = self._substep(state, sub_dt)
            contacts.extend(sub_contacts)
        return state, contacts

    # -- One inner substep -------------------------------------------------

    def _substep(
        self,
        state: MotionVector,
        dt: float,
    ) -> tuple[MotionVector, list[ContactProfile]]:
        # Semi-implicit Euler — apply forces to velocity FIRST, then
        # advance position with the updated velocity. More stable than
        # explicit Euler for forces that depend on velocity (drag).
        vel = self._apply_forces(state.vel, state.spin, dt)
        contacts: list[ContactProfile] = []

        # CCD against walls — find earliest impact within the substep.
        # Reflect, consume time, and continue until no impact remains
        # within the budget (handles corners + multi-bounce per substep
        # at extreme velocities).
        time_left = dt
        pos = state.pos
        guard = 0
        while time_left > 0.0:
            toi, hit_wall = self._earliest_wall_impact(pos, vel, time_left)
            if hit_wall is None:
                pos = _add(pos, _scale(vel, time_left))
                time_left = 0.0
                break
            # Advance to the impact point. Use a tiny epsilon to avoid
            # immediately re-colliding with the same plane (numerical
            # tolerance for the next CCD step).
            pos = _add(pos, _scale(vel, toi))
            incoming = MotionVector(
                pos=pos, vel=vel, spin=state.spin,
                timestamp=state.timestamp + (dt - time_left + toi),
            )

            # Dispatch per WallPlane.interaction_kind. ARPG-combat PR 1
            # adds absorb/passthrough alongside the original reflect path.
            ikind = hit_wall.interaction_kind
            if ikind == "absorb":
                # Ball stops at contact. Used for hitboxes that consume
                # the Strike (sword vs single-target).
                new_vel = (0.0, 0.0, 0.0)
                contact_kind = "wall_absorb"
                coupling     = self.params.wall_restitution    # legacy compat — reports profile coupling
                outgoing = MotionVector(
                    pos=pos, vel=new_vel, spin=state.spin,
                    timestamp=incoming.timestamp,
                )
                contacts.append(ContactProfile(
                    contact_point   = pos,
                    incoming        = incoming,
                    paddle_normal   = hit_wall.normal,
                    paddle_velocity = (0.0, 0.0, 0.0),
                    outgoing        = outgoing,
                    coupling_factor = coupling,
                    contact_kind    = contact_kind,
                ))
                # Ball stops in place. Time budget exhausted — exit loop
                # so further CCD doesn't re-impact (vel=0 anyway).
                vel = new_vel
                time_left = 0.0
                break
            elif ikind == "passthrough":
                # Ball continues through with energy loss. Used for
                # hitboxes that let multi-hit swings plow through.
                new_vel = _scale(vel, hit_wall.passthrough_coupling)
                contact_kind = "wall_passthrough"
                outgoing = MotionVector(
                    pos=pos, vel=new_vel, spin=state.spin,
                    timestamp=incoming.timestamp,
                )
                contacts.append(ContactProfile(
                    contact_point   = pos,
                    incoming        = incoming,
                    paddle_normal   = hit_wall.normal,
                    paddle_velocity = (0.0, 0.0, 0.0),
                    outgoing        = outgoing,
                    coupling_factor = hit_wall.passthrough_coupling,
                    contact_kind    = contact_kind,
                ))
                # Nudge OUTWARD (along -normal) so next CCD doesn't
                # immediately re-detect this plane. Ball is now on the
                # outside.
                pos = _add(pos, _scale(hit_wall.normal, -1e-5))
                vel = new_vel
                time_left -= toi
            else:
                # Default "reflect" — original V1 ping-pong behavior.
                new_vel = self._reflect(vel, hit_wall.normal)
                outgoing = MotionVector(
                    pos=pos, vel=new_vel, spin=state.spin,
                    timestamp=incoming.timestamp,
                )
                contacts.append(ContactProfile(
                    contact_point   = pos,
                    incoming        = incoming,
                    paddle_normal   = hit_wall.normal,
                    paddle_velocity = (0.0, 0.0, 0.0),
                    outgoing        = outgoing,
                    coupling_factor = self.params.wall_restitution,
                    contact_kind    = "wall_strike",
                ))
                # Nudge out of the plane by an epsilon along its normal
                # so next CCD doesn't immediately re-detect a TOI at 0.
                pos = _add(pos, _scale(hit_wall.normal, 1e-5))
                vel = new_vel
                time_left -= toi
            guard += 1
            if guard > 32:
                # Pathological geometry / corner case — break to avoid
                # infinite loop. In practice never reached for the cube.
                break

        new_state = MotionVector(
            pos=pos, vel=vel, spin=state.spin,
            timestamp=state.timestamp + dt,
        )
        return new_state, contacts

    # -- Force integration ------------------------------------------------

    def _apply_forces(
        self,
        vel: tuple[float, float, float],
        spin: tuple[float, float, float],
        dt: float,
    ) -> tuple[float, float, float]:
        p = self.params
        ax, ay, az = 0.0, 0.0, 0.0

        # Gravity — applied along z (brain z-up). Profile sign convention:
        # gravity_y < 0 = downward (matches realistic earth).
        # Field name is `gravity_y` for legacy convention (player-relative),
        # but the force lives on the world z axis (up/down). gravity_y < 0
        # = downward = subtract from z velocity.
        az += p.gravity_y

        # Drag — F = -0.5 * ρ * Cd * A * |v| * v ;  A = π·r²
        if p.ball_drag_coeff != 0.0:
            speed = _length(vel)
            if speed > 1e-9:
                area = math.pi * p.ball_radius * p.ball_radius
                drag_factor = (
                    -0.5 * p.air_density * p.ball_drag_coeff * area * speed
                    / max(p.ball_mass, 1e-9)
                )
                ax += vel[0] * drag_factor
                ay += vel[1] * drag_factor
                az += vel[2] * drag_factor

        # Magnus — F ∝ v × ω (NOT ω × v).
        # Sign convention pin (most-mis-implemented detail in indie tennis
        # threads — verify before tuning):
        #   v=(+x,0,0), ω=(0,+y,0) → backspin going +x → v × ω = (0,0,+z)
        #     → ball lifts. +C_L on backspin lifts. ✓
        #   v=(+x,0,0), ω=(0,-y,0) → topspin  going +x → v × ω = (0,0,-z)
        #     → ball drops. ✓
        if p.ball_magnus_coeff != 0.0 and (spin[0] != 0 or spin[1] != 0 or spin[2] != 0):
            area = math.pi * p.ball_radius * p.ball_radius
            magnus_dir = _cross(vel, spin)     # v × ω = lift direction
            mag_factor = (
                0.5 * p.air_density * p.ball_magnus_coeff * area
                / max(p.ball_mass, 1e-9)
            )
            # (v × ω) carries both direction and a |v|·|ω|·sin(θ) magnitude,
            # dimensionally matching the |v| in the standard Magnus law.
            # Simple linear coupling for V1 — refinable when sim mode goes
            # under physical scrutiny.
            ax += magnus_dir[0] * mag_factor
            ay += magnus_dir[1] * mag_factor
            az += magnus_dir[2] * mag_factor

        return (
            vel[0] + ax * dt,
            vel[1] + ay * dt,
            vel[2] + az * dt,
        )

    # -- CCD ---------------------------------------------------------------

    def _earliest_wall_impact(
        self,
        pos: tuple[float, float, float],
        vel: tuple[float, float, float],
        time_budget: float,
    ) -> tuple[float, "WallPlane | None"]:
        """Closed-form swept-sphere vs plane.

        Plane: n·(x - point) = 0. Sphere center moves p(t) = pos + t·vel.
        Sphere of radius r contacts the plane when |n·(p(t) - point)| = r.
        Inward-facing normal means valid TOI = the moment the sphere's
        leading face touches the plane: n·(p(t) - point) = r (sphere
        approaching from the inside).

        Returns (toi, plane) for earliest impact in [0, time_budget],
        or (time_budget, None) if no impact.
        """
        r = self.params.ball_radius
        best_toi: float = float("inf")
        best_wall: WallPlane | None = None

        for wall in self.walls:
            n = wall.normal
            # Distance from sphere center to plane (signed, positive
            # means inside the room when normal points inward).
            d0 = _dot(_sub(pos, wall.point), n)
            vn = _dot(vel, n)
            if vn >= -1e-9:
                # Moving away from / parallel to plane — no impending impact.
                continue
            # Solve n·(pos + t·vel - point) = r  =>  t = (r - d0) / vn
            toi = (r - d0) / vn
            if toi < -1e-7 or toi > time_budget + 1e-9:
                continue
            toi = max(0.0, toi)            # clamp tiny negatives from float jitter
            if toi < best_toi:
                best_toi = toi
                best_wall = wall

        if best_wall is None:
            return time_budget, None
        return best_toi, best_wall

    # -- Reflection -------------------------------------------------------

    def _reflect(
        self,
        vel: tuple[float, float, float],
        normal: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        """Reflection against a static wall:

            v_n' = -e · v_n            (component along normal flips, scaled by e)
            v_t' =      v_t            (tangential unchanged for V1; spin friction
                                        will live here for paddle strikes)
        """
        e = self.params.wall_restitution
        v_n = _dot(vel, normal)
        # Decompose: v = v_n·n + v_t
        v_n_vec = _scale(normal, v_n)
        v_t_vec = _sub(vel, v_n_vec)
        # Reflect normal component, keep tangential
        v_n_new = _scale(normal, -e * v_n)
        return _add(v_n_new, v_t_vec)

    # -- Paddle strike ---------------------------------------------------

    def paddle_strike(
        self,
        ball: MotionVector,
        paddle_pos:      tuple[float, float, float],
        paddle_normal:   tuple[float, float, float],
        paddle_velocity: tuple[float, float, float],
        coupling: float | None = None,
        friction: float | None = None,
    ) -> tuple[MotionVector, ContactProfile]:
        """Apply a paddle reflection to the ball state.

        Reflection (per AC §"Physics contract"):
            v_n' = (1 + e) · v_paddle_n − e · v_ball_n
            v_t' = v_ball_t + friction · v_paddle_t

        where:
            e = coupling (default = profile coupling_factor; 1.0 in vanilla)
            friction = paddle/ball tangential coupling (default = same as e for V1
                       — when spin-from-paddle motion lands in Stage 3, this
                       becomes its own knob)

        Caller is responsible for hitbox check (PingPongHandler.on_strike does
        that). This method assumes the paddle is in contact.

        Coordinate space: brain (x lateral, y forward, z up). Paddle normal
        should be a unit vector pointing AWAY from the paddle face — same
        direction the ball is being pushed.
        """
        # Normalize paddle normal in case caller passed something close.
        n_len = _length(paddle_normal)
        if n_len < 1e-9:
            # Degenerate normal — treat as no-contact passthrough rather
            # than crash. Returns ball unchanged with a synthetic profile.
            n = (0.0, 0.0, 1.0)
        else:
            n = _scale(paddle_normal, 1.0 / n_len)

        e = float(coupling) if coupling is not None else 1.0
        f = float(friction) if friction is not None else e

        # Decompose ball velocity into normal + tangential (relative to paddle face).
        v_ball_n = _dot(ball.vel, n)
        v_ball_n_vec = _scale(n, v_ball_n)
        v_ball_t_vec = _sub(ball.vel, v_ball_n_vec)

        # Decompose paddle velocity the same way.
        v_pad_n = _dot(paddle_velocity, n)
        v_pad_n_vec = _scale(n, v_pad_n)
        v_pad_t_vec = _sub(paddle_velocity, v_pad_n_vec)

        # Reflection — normal flipped + paddle's normal velocity coupled in,
        # tangential picks up friction × paddle tangential.
        new_v_n_vec = _scale(n, (1.0 + e) * v_pad_n - e * v_ball_n)
        new_v_t_vec = _add(v_ball_t_vec, _scale(v_pad_t_vec, f))
        new_vel = _add(new_v_n_vec, new_v_t_vec)

        new_state = MotionVector(
            pos=ball.pos, vel=new_vel, spin=ball.spin,
            timestamp=ball.timestamp,
        )
        contact = ContactProfile(
            contact_point   = ball.pos,
            incoming        = ball,
            paddle_normal   = n,
            paddle_velocity = paddle_velocity,
            outgoing        = new_state,
            coupling_factor = e,
            contact_kind    = "paddle_strike",
        )
        return new_state, contact


# ----------------------------------------------------------------------
# Convenience constructor for the volley_chamber V1 use case
# ----------------------------------------------------------------------


def for_chamber(profile_params: dict, chamber_geometry: dict) -> BallisticsSolver:
    """Build a solver from a ping_pong profile + the chamber geometry dict
    PingPongHandler.manifest_keys() emits."""
    params = BallisticsParams.from_profile(profile_params)
    walls = chamber_walls(
        tuple(chamber_geometry.get("size") or (12.0, 12.0, 12.0)),
        tuple(chamber_geometry.get("origin") or (0.0, 0.0, 0.0)),
    )
    return BallisticsSolver(params, walls)
