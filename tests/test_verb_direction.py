"""Per-verb swept direction math — feat/arpg-combat PR 9.

Each HELD verb produces a different hitbox trajectory during the active
phase. _verb_direction returns (direction unit vector, effective reach)
for a given progress t ∈ [0, 1].

Coord convention: brain (x=lateral, y=forward, z=up). Forward vectors
live mostly in xy-plane; vertical look-up/down adds z.
"""
from __future__ import annotations

import math

import pytest

from core.systems.strike_runtime import _verb_direction


# Canonical forward (looking +y, fully horizontal)
_FWD_Y = (0.0, 1.0, 0.0)


def _approx(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


# ── PUNCH ─────────────────────────────────────────────────────────────


def test_punch_returns_straight_forward():
    direction, reach = _verb_direction("PUNCH", _FWD_Y, progress=0.5, base_reach=1.0)
    assert _approx(direction, _FWD_Y)


def test_punch_reach_is_shorter_than_base():
    _, reach = _verb_direction("PUNCH", _FWD_Y, progress=0.5, base_reach=1.0)
    assert reach == pytest.approx(0.6)


def test_punch_progress_independent():
    """PUNCH doesn't sweep — direction is the same at every t."""
    d0, _ = _verb_direction("PUNCH", _FWD_Y, progress=0.0, base_reach=1.0)
    d_mid, _ = _verb_direction("PUNCH", _FWD_Y, progress=0.5, base_reach=1.0)
    d_end, _ = _verb_direction("PUNCH", _FWD_Y, progress=1.0, base_reach=1.0)
    assert _approx(d0, d_mid) and _approx(d_mid, d_end)


# ── STAB ──────────────────────────────────────────────────────────────


def test_stab_returns_full_reach_straight_forward():
    direction, reach = _verb_direction("STAB", _FWD_Y, progress=0.5, base_reach=1.8)
    assert _approx(direction, _FWD_Y)
    assert reach == pytest.approx(1.8)


# ── SLASH ─────────────────────────────────────────────────────────────


def test_slash_at_start_swings_60_degrees_left():
    """t=0 → angle = -60° → forward rotated 60° counterclockwise around UP."""
    direction, _ = _verb_direction("SLASH", _FWD_Y, progress=0.0, base_reach=1.5)
    # Rotating (0,1,0) by -60° around +z: (cos·0 - sin·1, sin·0 + cos·1, 0)
    # = (-sin(-60°), cos(-60°), 0) = (sin(60°), cos(60°), 0)
    # Wait, angle is -60°. Rotation formula:
    #   v_new = (cos·v_x - sin·v_y, sin·v_x + cos·v_y, v_z)
    # For v=(0,1,0), angle=-60°:
    #   v_new = (0 - sin(-60°)·1, 0 + cos(-60°)·1, 0)
    #         = (sin(60°), cos(60°), 0)
    #         = (0.866, 0.5, 0)
    assert direction[0] == pytest.approx(math.sin(math.radians(60)), abs=1e-6)
    assert direction[1] == pytest.approx(math.cos(math.radians(60)), abs=1e-6)
    assert direction[2] == pytest.approx(0.0, abs=1e-6)


def test_slash_at_midpoint_is_straight_forward():
    """t=0.5 → angle = 0 → direction == forward."""
    direction, _ = _verb_direction("SLASH", _FWD_Y, progress=0.5, base_reach=1.5)
    assert _approx(direction, _FWD_Y)


def test_slash_at_end_swings_60_degrees_right():
    """t=1 → angle = +60° → forward rotated 60° clockwise around UP."""
    direction, _ = _verb_direction("SLASH", _FWD_Y, progress=1.0, base_reach=1.5)
    # angle = +60°, v=(0,1,0):
    #   v_new = (cos·0 - sin·1, sin·0 + cos·1, 0) = (-sin(60°), cos(60°), 0)
    assert direction[0] == pytest.approx(-math.sin(math.radians(60)), abs=1e-6)
    assert direction[1] == pytest.approx(math.cos(math.radians(60)), abs=1e-6)
    assert direction[2] == pytest.approx(0.0, abs=1e-6)


def test_slash_preserves_unit_length():
    """Rotation preserves vector magnitude. Each progress t should give a unit vector."""
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        direction, _ = _verb_direction("SLASH", _FWD_Y, progress=t, base_reach=1.5)
        mag = math.sqrt(sum(c * c for c in direction))
        assert abs(mag - 1.0) < 1e-6


def test_slash_z_component_unchanged():
    """SLASH rotates around z-axis (up); z-component of direction stays."""
    fwd_with_pitch = (0.0, math.cos(0.3), math.sin(0.3))   # forward with slight upward look
    direction, _ = _verb_direction("SLASH", fwd_with_pitch, progress=0.5, base_reach=1.5)
    assert direction[2] == pytest.approx(math.sin(0.3))


# ── HACK ──────────────────────────────────────────────────────────────


def test_hack_at_start_pitches_60_degrees_up():
    """t=0 → angle = +60° → forward tilted up around right axis."""
    direction, _ = _verb_direction("HACK", _FWD_Y, progress=0.0, base_reach=1.5)
    # For forward=(0,1,0), right=(1,0,0), Rodrigues rotation by +60°:
    # v_new_x = 0 (unchanged on right-axis rotation)
    # v_new_y = cos(60°)·1 = 0.5
    # v_new_z = sin(60°)·1 = 0.866
    assert direction[0] == pytest.approx(0.0, abs=1e-6)
    assert direction[1] == pytest.approx(math.cos(math.radians(60)), abs=1e-6)
    assert direction[2] == pytest.approx(math.sin(math.radians(60)), abs=1e-6)


def test_hack_at_midpoint_is_straight_forward():
    direction, _ = _verb_direction("HACK", _FWD_Y, progress=0.5, base_reach=1.5)
    assert _approx(direction, _FWD_Y, tol=1e-6)


def test_hack_at_end_pitches_60_degrees_down():
    """t=1 → angle = -60° → forward tilted down."""
    direction, _ = _verb_direction("HACK", _FWD_Y, progress=1.0, base_reach=1.5)
    assert direction[0] == pytest.approx(0.0, abs=1e-6)
    assert direction[1] == pytest.approx(math.cos(math.radians(60)), abs=1e-6)
    assert direction[2] == pytest.approx(-math.sin(math.radians(60)), abs=1e-6)


def test_hack_preserves_unit_length():
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        direction, _ = _verb_direction("HACK", _FWD_Y, progress=t, base_reach=1.5)
        mag = math.sqrt(sum(c * c for c in direction))
        assert abs(mag - 1.0) < 1e-6


def test_hack_handles_vertical_forward_gracefully():
    """If player aims straight up, the horizontal-right axis is degenerate.
    Function should fall back to no rotation rather than blow up."""
    fwd_up = (0.0, 0.0, 1.0)
    direction, _ = _verb_direction("HACK", fwd_up, progress=0.0, base_reach=1.5)
    # Falls back to unchanged forward
    assert _approx(direction, fwd_up)


# ── RIPOSTE ───────────────────────────────────────────────────────────


def test_riposte_stationary_at_all_progress():
    """RIPOSTE is a parry zone — no sweep. Direction = forward at any t."""
    for t in (0.0, 0.5, 1.0):
        direction, reach = _verb_direction("RIPOSTE", _FWD_Y, progress=t, base_reach=1.5)
        assert _approx(direction, _FWD_Y)
        assert reach == pytest.approx(1.5)


# ── Unknown verb (defensive fallback) ────────────────────────────────


def test_unknown_verb_falls_back_to_straight_forward():
    direction, reach = _verb_direction("WEIRD", _FWD_Y, progress=0.5, base_reach=1.5)
    assert _approx(direction, _FWD_Y)
    assert reach == pytest.approx(1.5)
