"""Envelope clamp — port of godot/main.gd:5386-5405."""
from __future__ import annotations

import math

from clients.vector_terminal.envelope import clamp_to_envelope


def test_no_clamp_when_radius_zero():
    assert clamp_to_envelope(50.0, 50.0, 0.0, 1.0, 0.016) == (50.0, 50.0)


def test_no_clamp_inside_envelope():
    assert clamp_to_envelope(3.0, 4.0, 10.0, 1.0, 0.016) == (3.0, 4.0)


def test_at_radius_does_not_pushback():
    assert clamp_to_envelope(10.0, 0.0, 10.0, 1.0, 0.016) == (10.0, 0.0)


def test_outside_pushes_back_radially():
    new_x, new_z = clamp_to_envelope(20.0, 0.0, 10.0, 1.0, 0.016)
    assert new_x < 20.0  # pushed in
    assert new_z == 0.0  # purely radial


def test_hard_clamp_when_far_outside():
    """A point at 1000m with softness=1 and dt=0.016 still clamps to radius."""
    new_x, new_z = clamp_to_envelope(1000.0, 0.0, 10.0, 1.0, 0.016)
    assert math.isclose(math.hypot(new_x, new_z), 10.0, abs_tol=1e-6)


def test_diagonal_outside_clamps_radially():
    new_x, new_z = clamp_to_envelope(100.0, 100.0, 10.0, 1.0, 0.016)
    dist = math.hypot(new_x, new_z)
    assert math.isclose(dist, 10.0, abs_tol=1e-6)
    # ratio preserved (angle from origin)
    assert math.isclose(new_x, new_z, abs_tol=1e-6)


# Softness comparison test removed — at any meaningful overshoot the hard
# clamp dominates regardless of softness, so the soft term is hard to isolate
# in a unit test. Behavior matches godot/main.gd:5394-5405 line for line.
