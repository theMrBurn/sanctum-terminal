"""magic_staff tests — feat/arpg-combat PR 5 (combo weapon).

Covers:
- fire_staff combo profile shape (modes sub-dict)
- is_combo / sub_profile helpers
- on_primary / on_secondary spawn correct mode
- Spin-curve magnus on shot mode
"""
from __future__ import annotations

import pytest

from core.systems import strike
from core.systems.strike import HeldVerb
from core.systems.weapons import magic_staff


@pytest.fixture(autouse=True)
def _reset_dispatchers():
    strike._reset_dispatchers_for_tests()
    yield
    strike._reset_dispatchers_for_tests()


# ── fire_staff profile ────────────────────────────────────────────────


def test_fire_staff_has_modes_sub_dict():
    p = magic_staff.FIRE_STAFF_PROFILE
    assert "modes" in p
    assert "held" in p["modes"]
    assert "shot" in p["modes"]


def test_fire_staff_held_sub_profile_uses_stab_default():
    held = magic_staff.FIRE_STAFF_PROFILE["modes"]["held"]
    assert held["mode"] == "held"
    assert held["default_verb"] == "STAB"
    assert "STAB" in held["held_verbs"]
    assert "RIPOSTE" in held["held_verbs"]
    assert "SLASH" not in held["held_verbs"]    # staff doesn't slash


def test_fire_staff_shot_sub_profile_has_magnus_curve():
    shot = magic_staff.FIRE_STAFF_PROFILE["modes"]["shot"]
    assert shot["mode"] == "shot"
    assert shot["ball_magnus_coeff"] > 0           # fire bolt curves
    assert shot["shot_initial_v"] > 0


# ── is_combo / sub_profile ────────────────────────────────────────────


def test_is_combo_true_for_combo_profile():
    assert magic_staff.is_combo(magic_staff.FIRE_STAFF_PROFILE) is True


def test_is_combo_false_for_simple_profile():
    simple = {"mode": "held", "ball_mass": 1.0}
    assert magic_staff.is_combo(simple) is False


def test_is_combo_false_for_empty_modes_dict():
    assert magic_staff.is_combo({"modes": {}}) is False


def test_sub_profile_returns_held_sub_for_held_mode():
    sub = magic_staff.sub_profile(magic_staff.FIRE_STAFF_PROFILE, "held")
    assert sub is not None
    assert sub["mode"] == "held"
    assert sub["default_verb"] == "STAB"


def test_sub_profile_returns_shot_sub_for_shot_mode():
    sub = magic_staff.sub_profile(magic_staff.FIRE_STAFF_PROFILE, "shot")
    assert sub is not None
    assert sub["mode"] == "shot"
    assert sub["shot_initial_v"] == 24.0


def test_sub_profile_returns_none_for_unsupported_mode():
    sub = magic_staff.sub_profile(magic_staff.FIRE_STAFF_PROFILE, "whip")
    assert sub is None


def test_sub_profile_carries_parent_metadata():
    """weapon_class + profile_name should propagate from parent so
    Strike.weapon_kind populates correctly."""
    parent = {**magic_staff.FIRE_STAFF_PROFILE, "profile_name": "fire_staff"}
    sub = magic_staff.sub_profile(parent, "held")
    assert sub["weapon_class"] == "magic_staff"
    assert sub["profile_name"] == "fire_staff"


def test_sub_profile_returns_shallow_copy_not_reference():
    """Caller mutation must not pollute the parent profile."""
    sub = magic_staff.sub_profile(magic_staff.FIRE_STAFF_PROFILE, "held")
    sub["ball_mass"] = 999.0
    sub2 = magic_staff.sub_profile(magic_staff.FIRE_STAFF_PROFILE, "held")
    assert sub2["ball_mass"] != 999.0


# ── on_primary / on_secondary spawn ───────────────────────────────────


def test_on_primary_returns_held_strike_with_stab_default():
    s = magic_staff.on_primary(
        weapon_profile=magic_staff.FIRE_STAFF_PROFILE,
        camera_state={"pos": (0, 0, 1.6), "forward": (0, 1, 0)},
        source_actor="player",
    )
    assert s.mode == "held"
    assert s.held_verb == HeldVerb.STAB


def test_on_secondary_returns_shot_strike_with_magnus():
    s = magic_staff.on_secondary(
        weapon_profile=magic_staff.FIRE_STAFF_PROFILE,
        camera_state={"pos": (0, 0, 1.6), "forward": (0, 1, 0)},
        source_actor="player",
    )
    assert s.mode == "shot"
    assert s.profile.ball_magnus_coeff == 0.15


def test_on_primary_raises_if_profile_missing_held_sub():
    with pytest.raises(ValueError, match="no `held`"):
        magic_staff.on_primary(
            weapon_profile={"modes": {"shot": {"mode": "shot"}}},
            camera_state={"pos": (0, 0, 0), "forward": (0, 1, 0)},
            source_actor="player",
        )


def test_on_secondary_raises_if_profile_missing_shot_sub():
    with pytest.raises(ValueError, match="no `shot`"):
        magic_staff.on_secondary(
            weapon_profile={"modes": {"held": {"mode": "held"}}},
            camera_state={"pos": (0, 0, 0), "forward": (0, 1, 0)},
            source_actor="player",
        )


# ── Combo weapon spawn produces both modes ────────────────────────────


def test_combo_weapon_spawn_held_then_shot_produces_distinct_strikes():
    """Same weapon, different mode args → different Strike modes."""
    cam = {"pos": (0, 0, 1.6), "forward": (0, 1, 0)}
    held_strike = magic_staff.on_primary(
        weapon_profile=magic_staff.FIRE_STAFF_PROFILE,
        camera_state=cam,
        source_actor="player",
    )
    shot_strike = magic_staff.on_secondary(
        weapon_profile=magic_staff.FIRE_STAFF_PROFILE,
        camera_state=cam,
        source_actor="player",
    )
    assert held_strike.mode == "held"
    assert shot_strike.mode == "shot"
    # Both use same weapon profile but different physics shapes
    assert held_strike.profile.ball_magnus_coeff == 0.0
    assert shot_strike.profile.ball_magnus_coeff == 0.15
