"""8-way compass bearing utility — pure-function tests."""
from __future__ import annotations

import math

from core.systems.bearing import bearing


# ── Cardinal directions ──────────────────────────────────────────


def test_due_east():
    assert bearing((0, 0), (10, 0)) == "E"


def test_due_north():
    assert bearing((0, 0), (0, 10)) == "N"


def test_due_west():
    assert bearing((0, 0), (-10, 0)) == "W"


def test_due_south():
    assert bearing((0, 0), (0, -10)) == "S"


# ── Diagonals ─────────────────────────────────────────────────────


def test_northeast():
    assert bearing((0, 0), (10, 10)) == "NE"


def test_northwest():
    assert bearing((0, 0), (-10, 10)) == "NW"


def test_southwest():
    assert bearing((0, 0), (-10, -10)) == "SW"


def test_southeast():
    assert bearing((0, 0), (10, -10)) == "SE"


# ── Off-axis (within sector tolerance) ────────────────────────────


def test_slightly_north_of_east_still_east():
    """Sectors are 45° wide; 10° off-axis stays in the original sector."""
    angle_deg = 10
    rad = math.radians(angle_deg)
    target = (math.cos(rad) * 10, math.sin(rad) * 10)
    assert bearing((0, 0), target) == "E"


def test_thirty_degrees_north_of_east_is_ne():
    """30° from east is closer to NE (45°) than E (0°)."""
    angle_deg = 30
    rad = math.radians(angle_deg)
    target = (math.cos(rad) * 10, math.sin(rad) * 10)
    assert bearing((0, 0), target) == "NE"


def test_translation_invariance():
    """Bearing is from a→b only; doesn't matter where origin sits."""
    assert bearing((100, 100), (110, 100)) == "E"
    assert bearing((-50, 30), (-50, 40)) == "N"


# ── Edge cases ────────────────────────────────────────────────────


def test_identical_positions_empty_string():
    assert bearing((5, 5), (5, 5)) == ""


def test_within_float_tolerance_empty_string():
    """Positions within 1e-6 are treated as identical."""
    assert bearing((0, 0), (1e-7, 1e-7)) == ""


def test_returns_string():
    """Always a string — never None or other type."""
    result = bearing((0, 0), (10, 0))
    assert isinstance(result, str)
    result = bearing((5, 5), (5, 5))
    assert isinstance(result, str)


# ── Distance independence ────────────────────────────────────────


def test_bearing_unaffected_by_distance():
    """A target 10m east and 10000m east produce the same bearing."""
    assert bearing((0, 0), (10, 0)) == bearing((0, 0), (10000, 0))


def test_bearing_round_trip_inverts():
    """bearing(a, b) and bearing(b, a) point opposite directions."""
    assert bearing((0, 0), (10, 0)) == "E"
    assert bearing((10, 0), (0, 0)) == "W"
    assert bearing((0, 0), (10, 10)) == "NE"
    assert bearing((10, 10), (0, 0)) == "SW"
