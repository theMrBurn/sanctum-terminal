"""BallisticsSolver — discrete-time projectile physics tests.

T4 of `feat_make-brain-ping-pong` PR 4. Pins the solver's correctness
across the modes that matter for arcade vanilla AND tennis_sim:

  - Determinism: same init + dt = same trajectory
  - Vanilla (zero forces): straight-line motion, perfect bounce
  - Gravity: ballistic arc, terminal-velocity-free fall
  - Drag: speed monotonically decreases, asymptotes to drag terminal
  - Magnus: spin deflects trajectory perpendicular to velocity
  - Wall reflection: swept-sphere CCD, restitution scaling
  - NO TUNNELING: 100 m/s ball through 12m cube must hit walls each
    transit, never escape

Coordinate convention (brain space): x lateral, y forward, z up.
"""
from __future__ import annotations

import math

import pytest

from core.systems.ballistics import (
    BallisticsParams, BallisticsSolver, MotionVector, WallPlane,
    chamber_walls, for_chamber,
)


# ----------------------------------------------------------------------
# Helpers / fixtures
# ----------------------------------------------------------------------


VANILLA = {
    "ball_mass":         1.0,
    "ball_radius":       0.15,
    "ball_drag_coeff":   0.0,
    "ball_magnus_coeff": 0.0,
    "gravity_y":         0.0,
    "wall_restitution":  1.0,
}

CHAMBER_12 = {
    "size":   [12.0, 12.0, 12.0],
    "origin": [0.0, 0.0, 0.0],
}


def _spawn(pos=(0.0, 0.0, 1.6),
           vel=(0.0, 0.0, 0.0),
           spin=(0.0, 0.0, 0.0),
           t=0.0) -> MotionVector:
    return MotionVector(pos=pos, vel=vel, spin=spin, timestamp=t)


def _approx(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


# ----------------------------------------------------------------------
# Determinism
# ----------------------------------------------------------------------


def test_solver_is_deterministic_under_repeated_step():
    solver = for_chamber(VANILLA, CHAMBER_12)
    init = _spawn(pos=(0.0, 0.0, 6.0), vel=(3.0, 0.0, 0.0))
    a, _ = solver.step(init, 0.1, substeps=4)
    b, _ = solver.step(init, 0.1, substeps=4)
    assert a == b


def test_substep_count_does_not_break_determinism_for_smooth_path():
    """A trajectory with no collisions must be invariant under substep
    count: more substeps is just smaller dt steps of the same maths."""
    p = dict(VANILLA, gravity_y=-9.81)
    solver = for_chamber(p, CHAMBER_12)
    init = _spawn(pos=(0.0, 0.0, 6.0), vel=(2.0, 0.0, 0.0))
    a, _ = solver.step(init, 0.1, substeps=4)
    b, _ = solver.step(init, 0.1, substeps=8)
    # Tolerant compare — Euler integration changes slightly with dt.
    assert _approx(a.pos, b.pos, tol=0.05)


# ----------------------------------------------------------------------
# Zero-force / arcade vanilla path
# ----------------------------------------------------------------------


def test_vanilla_straight_line_motion():
    """gravity=drag=magnus=0 → exact linear motion."""
    solver = for_chamber(VANILLA, CHAMBER_12)
    init = _spawn(pos=(0.0, 0.0, 6.0), vel=(2.0, 0.0, 0.0))
    state, contacts = solver.step(init, 1.0, substeps=4)
    assert _approx(state.pos, (2.0, 0.0, 6.0), tol=1e-9)
    assert _approx(state.vel, (2.0, 0.0, 0.0), tol=1e-9)
    assert contacts == []


def test_vanilla_at_rest_remains_at_rest():
    """A stationary ball with zero forces must not drift (the V2
    acceptance — ball spawns stationary in arcade vanilla)."""
    solver = for_chamber(VANILLA, CHAMBER_12)
    init = _spawn(pos=(0.0, 0.0, 1.6), vel=(0.0, 0.0, 0.0))
    state, contacts = solver.step(init, 0.5, substeps=4)
    assert _approx(state.pos, (0.0, 0.0, 1.6), tol=1e-9)
    assert _approx(state.vel, (0.0, 0.0, 0.0), tol=1e-9)
    assert contacts == []


# ----------------------------------------------------------------------
# Gravity
# ----------------------------------------------------------------------


def test_gravity_only_freefall_matches_kinematic_solution():
    """For pure gravity, Euler should track the kinematic position to
    within the integrator's first-order error. With dt=1/60 and 4
    substeps, fall over 0.5s should be very close to ½·g·t²."""
    p = dict(VANILLA, gravity_y=-9.81)
    solver = for_chamber(p, CHAMBER_12)
    init = _spawn(pos=(0.0, 0.0, 6.0), vel=(0.0, 0.0, 0.0))
    state = init
    dt = 1.0 / 60.0
    for _ in range(30):                    # 0.5s
        state, _ = solver.step(state, dt, substeps=4)
    expected_drop = 0.5 * 9.81 * 0.5 * 0.5  # ½·g·t² = 1.226 m
    drop = 6.0 - state.pos[2]
    assert abs(drop - expected_drop) < 0.05


def test_gravity_does_not_affect_lateral_velocity():
    p = dict(VANILLA, gravity_y=-9.81)
    solver = for_chamber(p, CHAMBER_12)
    init = _spawn(pos=(0.0, 0.0, 6.0), vel=(2.0, 0.0, 0.0))
    state, _ = solver.step(init, 0.2, substeps=4)
    assert abs(state.vel[0] - 2.0) < 1e-6
    assert abs(state.vel[1]) < 1e-9


# ----------------------------------------------------------------------
# Drag
# ----------------------------------------------------------------------


def test_drag_decreases_speed_monotonically():
    """With non-zero drag and no gravity, |v| must decay over time."""
    p = dict(VANILLA, ball_drag_coeff=0.5)
    solver = for_chamber(p, CHAMBER_12)
    state = _spawn(pos=(0.0, 0.0, 6.0), vel=(20.0, 0.0, 0.0))
    speeds = []
    for _ in range(10):
        state, _ = solver.step(state, 0.05, substeps=8)
        speeds.append(math.sqrt(sum(v * v for v in state.vel)))
    # Strictly decreasing
    assert all(speeds[i] > speeds[i + 1] for i in range(len(speeds) - 1))
    # And we lost meaningful energy
    assert speeds[-1] < 20.0 * 0.95


# ----------------------------------------------------------------------
# Magnus (sign convention pin)
# ----------------------------------------------------------------------


def test_magnus_with_backspin_lifts_ball():
    """+C_L on backspin → ball lifts (+z). Sign convention pin per AC.
    v=(+x,0,0), ω=(0,+y,0) is backspin for a ball moving +x.
    v × ω = (0, 0, +xz) → +z = lift."""
    p = dict(VANILLA, ball_magnus_coeff=0.5)
    solver = for_chamber(p, CHAMBER_12)
    init = _spawn(pos=(0.0, 0.0, 6.0), vel=(20.0, 0.0, 0.0),
                  spin=(0.0, 5.0, 0.0))
    state, _ = solver.step(init, 0.1, substeps=8)
    assert state.vel[2] > 0.0


def test_magnus_with_topspin_drops_ball():
    """ω=(0,-y,0) on +x velocity = topspin → ball drops (-z)."""
    p = dict(VANILLA, ball_magnus_coeff=0.5)
    solver = for_chamber(p, CHAMBER_12)
    init = _spawn(pos=(0.0, 0.0, 6.0), vel=(20.0, 0.0, 0.0),
                  spin=(0.0, -5.0, 0.0))
    state, _ = solver.step(init, 0.1, substeps=8)
    assert state.vel[2] < 0.0


def test_magnus_zero_when_spin_zero():
    p = dict(VANILLA, ball_magnus_coeff=0.5)
    solver = for_chamber(p, CHAMBER_12)
    init = _spawn(pos=(0.0, 0.0, 6.0), vel=(20.0, 0.0, 0.0),
                  spin=(0.0, 0.0, 0.0))
    state, _ = solver.step(init, 0.1, substeps=4)
    assert abs(state.vel[1]) < 1e-9
    assert abs(state.vel[2]) < 1e-9


# ----------------------------------------------------------------------
# Wall reflection
# ----------------------------------------------------------------------


def test_swept_sphere_bounces_off_east_wall_with_restitution():
    """Ball moving +x at 5 m/s, restitution 0.85 → -x at 4.25 m/s."""
    p = dict(VANILLA, wall_restitution=0.85)
    solver = for_chamber(p, CHAMBER_12)
    # Spawn near east wall (x = +6), heading east at 5 m/s.
    # Wall is at x = +6; ball radius 0.15; impact should fire within
    # this step.
    init = _spawn(pos=(5.0, 0.0, 6.0), vel=(5.0, 0.0, 0.0))
    state, contacts = solver.step(init, 0.5, substeps=4)
    assert len(contacts) >= 1
    east_hit = next((c for c in contacts if c.contact_kind == "wall_strike"), None)
    assert east_hit is not None
    assert east_hit.paddle_normal == (-1.0, 0.0, 0.0)
    # Outgoing velocity along x should equal -e * incoming
    assert abs(east_hit.outgoing.vel[0] - (-0.85 * 5.0)) < 1e-6


def test_perfect_restitution_preserves_speed_off_wall():
    p = dict(VANILLA, wall_restitution=1.0)
    solver = for_chamber(p, CHAMBER_12)
    init = _spawn(pos=(5.0, 0.0, 6.0), vel=(5.0, 0.0, 0.0))
    state, contacts = solver.step(init, 1.0, substeps=4)
    speed_after = math.sqrt(sum(v * v for v in state.vel))
    assert abs(speed_after - 5.0) < 1e-6
    assert any(c.contact_kind == "wall_strike" for c in contacts)


def test_floor_bounce_flips_z_only():
    p = dict(VANILLA, gravity_y=-9.81, wall_restitution=0.9)
    solver = for_chamber(p, CHAMBER_12)
    init = _spawn(pos=(0.0, 0.0, 1.0), vel=(0.0, 0.0, -5.0))
    state, contacts = solver.step(init, 0.5, substeps=8)
    floor_hits = [c for c in contacts if c.paddle_normal == (0.0, 0.0, 1.0)]
    assert floor_hits, "expected at least one floor hit"
    # First floor hit reverses z velocity (scaled by e)
    fc = floor_hits[0]
    assert fc.outgoing.vel[2] > 0.0


# ----------------------------------------------------------------------
# NO TUNNELING — the load-bearing test
# ----------------------------------------------------------------------


def test_no_tunneling_at_100_mps_through_12m_cube():
    """Ball at 100 m/s with default substep count must hit a wall every
    transit and never escape the cube.

    At 100 m/s, the ball traverses 12m in 0.12s = ~7 outer frames at
    1/60. With substep=4, each substep is 0.0042s = ~0.42m of travel.
    Ball radius is 0.15m. CCD must catch the imminent wall in the
    0.42m sweep before the ball passes through.
    """
    solver = for_chamber(VANILLA, CHAMBER_12)
    state = _spawn(pos=(0.0, 0.0, 6.0), vel=(100.0, 0.0, 0.0))
    half = 6.0
    radius = 0.15
    # Run for 1 second of game time — ball should bounce many times.
    for _ in range(60):
        state, _ = solver.step(state, 1.0 / 60.0, substeps=4)
        # Ball center never leaves the cube minus its radius (with a
        # small numerical tolerance).
        for axis_i in range(3):
            if axis_i == 2:                  # z spans 0..12, not -6..+6
                assert -1e-3 <= state.pos[axis_i] <= 12.0 + 1e-3, (
                    f"tunneled in z: pos={state.pos}"
                )
            else:
                assert -half - 1e-3 <= state.pos[axis_i] <= half + 1e-3, (
                    f"tunneled in axis {axis_i}: pos={state.pos}"
                )


def test_no_tunneling_diagonal_high_speed():
    """Ball going diagonally at 80 m/s — tests that multi-axis CCD
    picks the correct earliest impact."""
    solver = for_chamber(VANILLA, CHAMBER_12)
    state = _spawn(pos=(0.0, 0.0, 6.0), vel=(60.0, 60.0, 60.0))
    half = 6.0
    for _ in range(30):
        state, _ = solver.step(state, 1.0 / 60.0, substeps=4)
        assert -half - 1e-3 <= state.pos[0] <= half + 1e-3
        assert -half - 1e-3 <= state.pos[1] <= half + 1e-3
        assert -1e-3 <= state.pos[2] <= 12.0 + 1e-3


# ----------------------------------------------------------------------
# chamber_walls factory
# ----------------------------------------------------------------------


def test_chamber_walls_six_inward_normals():
    walls = chamber_walls((12.0, 12.0, 12.0), (0.0, 0.0, 0.0))
    assert len(walls) == 6
    names = {w.name for w in walls}
    assert names == {"floor", "ceiling", "north", "south", "east", "west"}
    # All normals point inward (centroid is +z above floor, between walls)
    centroid = (0.0, 0.0, 6.0)
    for w in walls:
        delta = (centroid[0] - w.point[0],
                 centroid[1] - w.point[1],
                 centroid[2] - w.point[2])
        n_dot = (w.normal[0] * delta[0] +
                 w.normal[1] * delta[1] +
                 w.normal[2] * delta[2])
        assert n_dot > 0, f"wall {w.name} normal points outward: {w.normal}"


# ----------------------------------------------------------------------
# Profile loading from dict
# ----------------------------------------------------------------------


def test_params_from_profile_uses_safe_defaults_when_keys_missing():
    p = BallisticsParams.from_profile({})
    assert p.ball_mass == 1.0
    assert p.ball_radius == 0.15
    assert p.gravity_y == 0.0
    assert p.wall_restitution == 1.0


def test_params_from_profile_reads_arcade_vanilla():
    p = BallisticsParams.from_profile(VANILLA)
    assert p.ball_drag_coeff == 0.0
    assert p.gravity_y == 0.0
    assert p.wall_restitution == 1.0


def test_params_from_profile_reads_tennis_sim_overrides():
    sim = {**VANILLA, "ball_drag_coeff": 0.55, "gravity_y": -9.81,
           "wall_restitution": 0.85, "ball_magnus_coeff": 0.175}
    p = BallisticsParams.from_profile(sim)
    assert p.ball_drag_coeff == 0.55
    assert p.gravity_y == -9.81
    assert p.wall_restitution == 0.85
    assert p.ball_magnus_coeff == 0.175
