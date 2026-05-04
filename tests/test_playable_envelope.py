"""Tests for core.systems.playable_envelope.compute_envelope_pushback.

Contract:
    Given player position (x, y) in world XZ plane and a radius,
    return the pushback vector (dx, dy) that nudges the player toward
    origin when outside the radius. Soft — zero inside, linear outside.

    Pure function. Deterministic. No state.
"""
from __future__ import annotations

import math

import pytest

from core.systems.playable_envelope import compute_envelope_pushback


def test_origin_zero_pushback():
    """Player at origin: zero pushback regardless of radius."""
    dx, dy = compute_envelope_pushback(0.0, 0.0, radius=50.0)
    assert dx == 0.0
    assert dy == 0.0


def test_inside_radius_zero_pushback():
    """Player well inside radius: zero pushback."""
    dx, dy = compute_envelope_pushback(10.0, 10.0, radius=50.0)
    assert dx == 0.0
    assert dy == 0.0


def test_exactly_at_radius_zero_pushback():
    """Player exactly on the boundary: still zero (envelope activates *past* radius)."""
    dx, dy = compute_envelope_pushback(50.0, 0.0, radius=50.0)
    assert dx == pytest.approx(0.0, abs=1e-9)
    assert dy == pytest.approx(0.0, abs=1e-9)


def test_outside_radius_pushes_toward_origin():
    """Player past radius on +X axis: pushback is in -X direction."""
    dx, dy = compute_envelope_pushback(60.0, 0.0, radius=50.0, softness=1.0)
    assert dx < 0.0           # push toward origin
    assert abs(dy) < 1e-9     # no Y component for axis-aligned overshoot


def test_pushback_magnitude_scales_with_overshoot():
    """10m overshoot with softness=1 → magnitude 10. 20m overshoot → 20."""
    dx1, _ = compute_envelope_pushback(60.0, 0.0, radius=50.0, softness=1.0)
    dx2, _ = compute_envelope_pushback(70.0, 0.0, radius=50.0, softness=1.0)
    assert dx1 == pytest.approx(-10.0)
    assert dx2 == pytest.approx(-20.0)


def test_softness_amplifies_pushback():
    """Same overshoot, double softness → double magnitude."""
    dx_soft, _ = compute_envelope_pushback(60.0, 0.0, radius=50.0, softness=1.0)
    dx_firm, _ = compute_envelope_pushback(60.0, 0.0, radius=50.0, softness=2.0)
    assert dx_firm == pytest.approx(dx_soft * 2.0)


def test_diagonal_pushback_points_toward_origin():
    """Player at (30, 40) = dist 50 on boundary. Move to (60, 80) = dist 100.
    Pushback direction = (-30, -40)/50 normalized, magnitude = 50 × softness."""
    dx, dy = compute_envelope_pushback(60.0, 80.0, radius=50.0, softness=1.0)
    # dist = 100, overshoot = 50, magnitude = 50 * 1.0 = 50
    # direction = -(60, 80)/100 = (-0.6, -0.8)
    assert dx == pytest.approx(-30.0)
    assert dy == pytest.approx(-40.0)


def test_negative_radius_clamps_to_zero_pushback():
    """Defensive: a misconfigured negative radius shouldn't crash or push."""
    dx, dy = compute_envelope_pushback(10.0, 10.0, radius=-5.0)
    assert dx == 0.0
    assert dy == 0.0


def test_zero_radius_pushes_everything_back():
    """radius=0 → every non-origin position gets pushed (soft reset)."""
    dx, dy = compute_envelope_pushback(3.0, 4.0, radius=0.0, softness=1.0)
    # dist = 5, overshoot = 5, push magnitude = 5 * 1.0 = 5
    # direction = -(3,4)/5 = (-0.6, -0.8)
    assert dx == pytest.approx(-3.0)
    assert dy == pytest.approx(-4.0)


def test_pure_function_no_side_effects():
    """Same inputs produce same outputs across calls (no hidden state)."""
    a = compute_envelope_pushback(75.0, 25.0, radius=50.0, softness=2.5)
    b = compute_envelope_pushback(75.0, 25.0, radius=50.0, softness=2.5)
    assert a == b


# --- clamp_to_envelope ---


from core.systems.playable_envelope import clamp_to_envelope   # noqa: E402


def test_clamp_origin_passthrough():
    assert clamp_to_envelope(0.0, 0.0, radius=50.0) == (0.0, 0.0)


def test_clamp_inside_passthrough():
    assert clamp_to_envelope(10.0, 20.0, radius=50.0) == (10.0, 20.0)


def test_clamp_exactly_on_boundary_passthrough():
    """Boundary is inclusive — sitting on it doesn't re-clamp."""
    x, y = clamp_to_envelope(50.0, 0.0, radius=50.0)
    assert x == pytest.approx(50.0)
    assert y == pytest.approx(0.0)


def test_clamp_snaps_to_radius_along_direction():
    """(60, 0) past 50-radius → (50, 0). Direction preserved, magnitude = radius."""
    x, y = clamp_to_envelope(60.0, 0.0, radius=50.0)
    assert x == pytest.approx(50.0)
    assert y == pytest.approx(0.0)


def test_clamp_diagonal_snaps_to_radius():
    """(60, 80) dist 100 past 50-radius → (30, 40) dist 50, same direction."""
    x, y = clamp_to_envelope(60.0, 80.0, radius=50.0)
    assert x == pytest.approx(30.0)
    assert y == pytest.approx(40.0)
    assert math.hypot(x, y) == pytest.approx(50.0)


def test_clamp_negative_radius_passthrough():
    """Defensive: misconfigured negative radius should not clamp."""
    assert clamp_to_envelope(100.0, 100.0, radius=-1.0) == (100.0, 100.0)


def test_clamp_zero_radius_collapses_to_origin():
    """radius=0 forces any outside position to origin."""
    x, y = clamp_to_envelope(3.0, 4.0, radius=0.0)
    assert x == pytest.approx(0.0)
    assert y == pytest.approx(0.0)
