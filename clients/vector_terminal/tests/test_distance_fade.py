"""distance_fade tests — PR 16.

Verifies the dynamic-bound + cfg-fallback contract that wires TensionCycle's
manifest.fog into the wireframe phosphor falloff. Pyray-free; the
distance_fade module deliberately has no rendering deps.
"""
from __future__ import annotations

import pytest

from clients.vector_terminal import config as cfg
from clients.vector_terminal import distance_fade


@pytest.fixture(autouse=True)
def _reset_bounds():
    distance_fade.reset()
    yield
    distance_fade.reset()


# ── fallback to cfg constants when no bounds set ──────────────────────


def test_intensity_full_within_near_default():
    assert distance_fade.intensity(0.0) == 1.0
    assert distance_fade.intensity(cfg.NEAR_DIST - 0.5) == 1.0
    assert distance_fade.intensity(cfg.NEAR_DIST) == 1.0


def test_intensity_min_at_far_default():
    assert distance_fade.intensity(cfg.FAR_FADE) == cfg.MIN_GLOW
    assert distance_fade.intensity(cfg.FAR_FADE + 100) == cfg.MIN_GLOW


def test_intensity_quadratic_fade_default():
    """Midpoint between NEAR and FAR sits closer to 1.0 than to MIN_GLOW
    under quadratic falloff — phosphor-curve shape per PR-Activity-Loop
    contrast pass. At t=0.5 with t² curve, fade fraction is 0.25, not 0.5."""
    mid = (cfg.NEAR_DIST + cfg.FAR_FADE) / 2
    expected = 1.0 - 0.25 * (1.0 - cfg.MIN_GLOW)
    assert abs(distance_fade.intensity(mid) - expected) < 1e-6


def test_intensity_quadratic_falloff_steeper_near_far():
    """At 75% distance under quadratic, intensity is significantly dimmer
    than under linear — confirms the curve shape biases toward bright
    mid-range + sharp far-edge drop."""
    span = cfg.FAR_FADE - cfg.NEAR_DIST
    three_quarters = cfg.NEAR_DIST + 0.75 * span
    # Quadratic: 1.0 - 0.75² * (1-MIN) = 1.0 - 0.5625*(1-MIN)
    expected = 1.0 - 0.5625 * (1.0 - cfg.MIN_GLOW)
    assert abs(distance_fade.intensity(three_quarters) - expected) < 1e-6


def test_active_bounds_returns_cfg_when_unset():
    assert distance_fade.active_bounds() == (cfg.NEAR_DIST, cfg.FAR_FADE)


# ── dynamic bounds override cfg ───────────────────────────────────────


def test_set_bounds_overrides_cfg():
    distance_fade.set_bounds(2.0, 30.0)
    assert distance_fade.active_bounds() == (2.0, 30.0)


def test_set_bounds_changes_intensity_curve():
    """Same distance produces different intensity under different bounds."""
    distance_fade.reset()
    default_at_15m = distance_fade.intensity(15.0)
    # Tighter envelope (TUNNEL/DUMP-shaped)
    distance_fade.set_bounds(2.0, 18.0)
    tunnel_at_15m = distance_fade.intensity(15.0)
    assert tunnel_at_15m < default_at_15m   # entity dimmer under TUNNEL


def test_set_bounds_with_one_none_keeps_other_dynamic():
    distance_fade.set_bounds(2.0, 18.0)
    distance_fade.set_bounds(None, 22.0)        # only update far
    near, far = distance_fade.active_bounds()
    # near reverted to fallback (set_bounds replaces both globals)
    assert near == cfg.NEAR_DIST
    assert far == 22.0


def test_set_bounds_rejects_inverted_pair():
    """near >= far is broken signal — keep prior bounds."""
    distance_fade.set_bounds(2.0, 30.0)
    distance_fade.set_bounds(50.0, 10.0)        # inverted; reject
    assert distance_fade.active_bounds() == (2.0, 30.0)


def test_set_bounds_rejects_equal_pair():
    distance_fade.set_bounds(2.0, 30.0)
    distance_fade.set_bounds(15.0, 15.0)        # degenerate; reject
    assert distance_fade.active_bounds() == (2.0, 30.0)


def test_set_bounds_handles_string_inputs():
    """Manifest may serialize numbers — ensure float coercion works."""
    distance_fade.set_bounds("2.5", "25.0")
    assert distance_fade.active_bounds() == (2.5, 25.0)


def test_set_bounds_handles_garbage_inputs():
    """Bad payload doesn't crash; falls back gracefully."""
    distance_fade.set_bounds("not-a-number", None)
    near, far = distance_fade.active_bounds()
    assert near == cfg.NEAR_DIST                # bad cast → None → fallback
    assert far == cfg.FAR_FADE


# ── reset ────────────────────────────────────────────────────────────


def test_reset_returns_to_cfg_fallback():
    distance_fade.set_bounds(2.0, 30.0)
    distance_fade.reset()
    assert distance_fade.active_bounds() == (cfg.NEAR_DIST, cfg.FAR_FADE)


# ── edge cases ───────────────────────────────────────────────────────


def test_intensity_never_below_min_glow():
    """Even at extreme distance with extreme bounds."""
    distance_fade.set_bounds(0.5, 5.0)
    assert distance_fade.intensity(1000.0) == cfg.MIN_GLOW


def test_intensity_never_above_one():
    distance_fade.set_bounds(10.0, 50.0)
    assert distance_fade.intensity(0.0) == 1.0
    assert distance_fade.intensity(5.0) == 1.0


def test_intensity_lerp_with_dynamic_bounds():
    """Midpoint check with dynamic bounds reproduces the quadratic math."""
    distance_fade.set_bounds(4.0, 20.0)
    expected_at_12 = 1.0 - 0.25 * (1.0 - cfg.MIN_GLOW)  # quadratic midpoint
    assert abs(distance_fade.intensity(12.0) - expected_at_12) < 1e-6
