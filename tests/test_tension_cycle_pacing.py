"""TensionCycle hybrid-pacing tests — PR 15.

Covers the pace_multiplier setter + clamp + behavioral knob (multiplier
applied to budget_ceiling AND hold_seconds). Pre-PR-15 behavior must
hold at multiplier=1.0 (no regression).
"""
from __future__ import annotations

import pytest

from core.systems.tension_cycle import TensionCycle, OUTDOOR_CYCLE


def _fresh_cycle():
    """OUTDOOR cycle with a small budget_max so tests can drive
    transitions in a few ticks."""
    cfg = {
        **OUTDOOR_CYCLE,
        "budget_max": 100,
    }
    c = TensionCycle(config=cfg)
    c.board()
    return c


# ── pace_multiplier setter + clamp ────────────────────────────────────


def test_pace_multiplier_default_is_one():
    c = TensionCycle()
    assert c.pace_multiplier == 1.0


def test_set_pace_multiplier_in_range():
    c = TensionCycle()
    c.set_pace_multiplier(0.9)
    assert c.pace_multiplier == 0.9
    c.set_pace_multiplier(1.1)
    assert c.pace_multiplier == 1.1


def test_set_pace_multiplier_clamps_low():
    c = TensionCycle()
    c.set_pace_multiplier(0.5)         # below MIN
    assert c.pace_multiplier == c.PACE_MULTIPLIER_MIN


def test_set_pace_multiplier_clamps_high():
    c = TensionCycle()
    c.set_pace_multiplier(2.0)         # above MAX
    assert c.pace_multiplier == c.PACE_MULTIPLIER_MAX


# ── behavior: pre-PR-15 unchanged at multiplier 1.0 ───────────────────


def test_default_behavior_advances_at_normal_ceiling():
    """At multiplier=1.0, transition fires at the normal ceiling."""
    c = _fresh_cycle()
    open_ceiling = c._config["open"]["budget_ceiling"]
    # Push budget JUST past normal ceiling
    over_count = int((open_ceiling + 0.05) * c._config["budget_max"])
    c.tick(0.1, over_count)
    assert c.state == "building"        # advanced


# ── behavior: multiplier > 1 delays advancement ───────────────────────


def test_high_multiplier_delays_transition():
    """At multiplier=1.15 (reflective dominant), normal-ceiling budget
    is NOT enough to advance — needs more pressure."""
    c = _fresh_cycle()
    c.set_pace_multiplier(1.15)
    open_ceiling = c._config["open"]["budget_ceiling"]
    # Same budget that WOULD advance at 1.0 should now stay
    over_count = int((open_ceiling + 0.05) * c._config["budget_max"])
    c.tick(0.1, over_count)
    assert c.state == "open"            # held


def test_high_multiplier_advances_at_scaled_ceiling():
    """Push past the scaled ceiling and the cycle still advances."""
    c = _fresh_cycle()
    c.set_pace_multiplier(1.15)
    open_ceiling = c._config["open"]["budget_ceiling"]
    over_count = int((open_ceiling * 1.15 + 0.05) * c._config["budget_max"])
    c.tick(0.1, over_count)
    assert c.state == "building"        # advanced past scaled threshold


# ── behavior: multiplier < 1 hastens advancement ──────────────────────


def test_low_multiplier_advances_below_normal_ceiling():
    """At multiplier=0.85 (active dominant), even less-than-normal
    pressure advances the cycle."""
    c = _fresh_cycle()
    c.set_pace_multiplier(0.85)
    open_ceiling = c._config["open"]["budget_ceiling"]
    # Below normal ceiling but above scaled ceiling
    sub_count = int((open_ceiling * 0.85 + 0.02) * c._config["budget_max"])
    # Sanity: this would NOT advance at multiplier=1.0
    assert sub_count < open_ceiling * c._config["budget_max"]
    c.tick(0.1, sub_count)
    assert c.state == "building"


# ── behavior: hold_seconds also scales ────────────────────────────────


def test_hold_seconds_extends_with_high_multiplier():
    """States with hold_seconds (dump, rebirth) hold longer when
    multiplier is high (reflective dominant)."""
    c = _fresh_cycle()
    # Force into rebirth state directly
    c.force_state("rebirth")
    rebirth_hold = c._config["rebirth"]["hold_seconds"]
    c.set_pace_multiplier(1.15)
    # Tick for normal hold duration — should NOT advance yet because
    # scaled hold is 1.15x longer.
    c.tick(rebirth_hold + 0.1, 0)
    assert c.state == "rebirth"


def test_hold_seconds_shortens_with_low_multiplier():
    """Active-dominant: shorter holds → faster dump→rebirth transitions."""
    c = _fresh_cycle()
    c.force_state("rebirth")
    rebirth_hold = c._config["rebirth"]["hold_seconds"]
    c.set_pace_multiplier(0.85)
    # Scaled hold is 0.85 * normal — past that should advance.
    # First tick to start the hold timer (after lerp settles)
    c._lerp_t = 1.0   # simulate settled
    scaled_hold = rebirth_hold * 0.85
    c.tick(scaled_hold + 0.1, 0)
    assert c.state == "open"            # cycled past rebirth
