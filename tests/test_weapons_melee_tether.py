"""melee_tether tests — feat/arpg-combat PR 4 (WHIP mode).

Covers:
- chain_whip profile shape (whip_swing_s + whip_retract_s + tether_length)
- WHIP-mode runtime tick (swing phase + retract phase + multi-hit + return)
"""
from __future__ import annotations

import pytest

from core.systems import strike, strike_runtime
from core.systems.weapons import melee_tether


@pytest.fixture(autouse=True)
def _reset_dispatchers():
    strike._reset_dispatchers_for_tests()
    yield
    strike._reset_dispatchers_for_tests()


# ── chain_whip profile ───────────────────────────────────────────────


def test_chain_whip_profile_shape():
    p = melee_tether.CHAIN_WHIP_PROFILE
    assert p["mode"] == "whip"
    assert p["weapon_class"] == "melee_tether"
    assert p["tether_length"] == 3.0
    assert p["whip_swing_s"] > 0
    assert p["whip_retract_s"] > 0


# ── on_use spawn ─────────────────────────────────────────────────────


def test_on_use_returns_whip_strike():
    s = melee_tether.on_use(
        weapon_profile=melee_tether.CHAIN_WHIP_PROFILE,
        camera_state={"pos": (0, 0, 1.5), "forward": (0, 1, 0), "ang_vel": 4.0},
        source_actor="player",
    )
    assert s.mode == "whip"
    assert s.tether_length == 3.0
    # Spawn pos = player + forward * tether
    assert s.initial_state.pos == (0.0, 3.0, 1.5)


def test_on_use_uses_default_swing_speed_when_ang_vel_zero():
    """When player isn't turning, WHIP still arcs forward at default speed."""
    s = melee_tether.on_use(
        weapon_profile=melee_tether.CHAIN_WHIP_PROFILE,
        camera_state={"pos": (0, 0, 1.5), "forward": (0, 1, 0), "ang_vel": 0.0},
        source_actor="player",
    )
    # Default swing speed is non-zero so ball arcs out
    speed = (s.initial_state.vel[0] ** 2 +
             s.initial_state.vel[1] ** 2 +
             s.initial_state.vel[2] ** 2) ** 0.5
    assert speed > 1.0


def test_whip_strike_carries_phase_timings_in_held_arc():
    s = melee_tether.on_use(
        weapon_profile=melee_tether.CHAIN_WHIP_PROFILE,
        camera_state={"pos": (0, 0, 1.5), "forward": (0, 1, 0), "ang_vel": 4.0},
        source_actor="player",
    )
    assert "whip_swing_s" in s.held_arc
    assert "whip_retract_s" in s.held_arc


# ── make_active sets WHIP max_age_s correctly ────────────────────────


def test_whip_make_active_sets_max_age_to_swing_plus_retract():
    s = melee_tether.on_use(
        weapon_profile=melee_tether.CHAIN_WHIP_PROFILE,
        camera_state={"pos": (0, 0, 1.5), "forward": (0, 1, 0), "ang_vel": 4.0},
        source_actor="player",
    )
    active = strike_runtime.make_active(s)
    expected = melee_tether.CHAIN_WHIP_PROFILE["whip_swing_s"] + \
               melee_tether.CHAIN_WHIP_PROFILE["whip_retract_s"]
    assert abs(active.max_age_s - expected) < 1e-6


# ── WHIP runtime tick — swing phase + multi-hit ──────────────────────


def test_whip_swing_phase_advances_ball_under_physics():
    s = melee_tether.on_use(
        weapon_profile=melee_tether.CHAIN_WHIP_PROFILE,
        camera_state={"pos": (0, 0, 1.5), "forward": (0, 1, 0), "ang_vel": 4.0},
        source_actor="player",
    )
    active = strike_runtime.make_active(s)
    initial_pos = active.current_state.pos
    strike_runtime.tick_active_strikes([active], entities=[], kind_config={}, dt=0.10)
    # Ball should have moved under its initial velocity.
    assert active.current_state.pos != initial_pos


def test_whip_multi_hit_during_swing():
    """Whip ball traveling forward hits multiple entities in its arc."""
    s = melee_tether.on_use(
        weapon_profile={
            **melee_tether.CHAIN_WHIP_PROFILE,
            "tether_length": 1.5,
            "whip_swing_s":  0.5,
            "gravity_y":     0.0,        # disable gravity for predictable line
        },
        camera_state={"pos": (0, 0, 1.5), "forward": (0, 1, 0), "ang_vel": 0.0},
        source_actor="player",
    )
    active = strike_runtime.make_active(s)
    # Ball starts at (0, 1.5, 1.5) with vel (0, 8, 0). After 0.3s travels
    # ~2.4m more = ends at (0, 3.9, 1.5). Place targets at y=2.0 and y=3.0.
    entities = [
        {"id": 1, "kind": "pot", "x": 0.0, "y": 2.0, "z": 1.5},
        {"id": 2, "kind": "pot", "x": 0.0, "y": 3.0, "z": 1.5},
    ]
    kc = {"pot": {"bounds": {"radius": 0.4}}}
    strike_runtime.tick_active_strikes([active], entities, kc, dt=0.30)
    assert 1 in active.held_hit_ids
    assert 2 in active.held_hit_ids


def test_whip_resolves_at_end_of_swing_plus_retract():
    """Total max_age = swing + retract; strike resolves after both."""
    s = melee_tether.on_use(
        weapon_profile=melee_tether.CHAIN_WHIP_PROFILE,
        camera_state={"pos": (0, 0, 1.5), "forward": (0, 1, 0), "ang_vel": 4.0},
        source_actor="player",
    )
    active = strike_runtime.make_active(s)
    # Tick past total lifecycle.
    total = melee_tether.CHAIN_WHIP_PROFILE["whip_swing_s"] + \
            melee_tether.CHAIN_WHIP_PROFILE["whip_retract_s"]
    strike_runtime.tick_active_strikes([active], entities=[], kind_config={},
                                        dt=total + 0.05)
    assert active.resolved


def test_whip_resolved_kind_landed_when_anything_hit():
    s = melee_tether.on_use(
        weapon_profile={
            **melee_tether.CHAIN_WHIP_PROFILE,
            "tether_length": 1.5,
            "whip_swing_s":  0.3,
            "whip_retract_s": 0.2,
            "gravity_y":     0.0,
        },
        camera_state={"pos": (0, 0, 1.5), "forward": (0, 1, 0), "ang_vel": 0.0},
        source_actor="player",
    )
    active = strike_runtime.make_active(s)
    entities = [{"id": 1, "kind": "pot", "x": 0.0, "y": 2.0, "z": 1.5}]
    kc = {"pot": {"bounds": {"radius": 0.5}}}
    # Tick during swing — hit
    strike_runtime.tick_active_strikes([active], entities, kc, dt=0.20)
    assert 1 in active.held_hit_ids
    # Tick past total
    strike_runtime.tick_active_strikes([active], entities=[], kind_config={}, dt=0.40)
    assert active.resolved
    assert active.resolved_kind == "landed"


def test_whip_resolved_kind_missed_when_no_hits():
    s = melee_tether.on_use(
        weapon_profile=melee_tether.CHAIN_WHIP_PROFILE,
        camera_state={"pos": (0, 0, 1.5), "forward": (0, 1, 0), "ang_vel": 4.0},
        source_actor="player",
    )
    active = strike_runtime.make_active(s)
    total = melee_tether.CHAIN_WHIP_PROFILE["whip_swing_s"] + \
            melee_tether.CHAIN_WHIP_PROFILE["whip_retract_s"]
    strike_runtime.tick_active_strikes([active], entities=[], kind_config={},
                                        dt=total + 0.05)
    assert active.resolved
    assert active.resolved_kind == "missed"


def test_whip_no_collisions_during_retract_phase():
    """During retract phase, ball doesn't collide — it's animation."""
    s = melee_tether.on_use(
        weapon_profile={
            **melee_tether.CHAIN_WHIP_PROFILE,
            "tether_length": 1.0,
            "whip_swing_s":  0.05,        # almost-instant swing
            "whip_retract_s": 0.5,        # long retract
            "gravity_y":     0.0,
        },
        camera_state={"pos": (0, 0, 1.5), "forward": (0, 1, 0), "ang_vel": 0.0},
        source_actor="player",
    )
    active = strike_runtime.make_active(s)
    # Tick past swing into retract
    strike_runtime.tick_active_strikes([active], entities=[], kind_config={}, dt=0.10)
    # Now place an entity in front — during retract, no hits should register
    entities = [{"id": 99, "kind": "pot", "x": 0.0, "y": 1.0, "z": 1.5}]
    kc = {"pot": {"bounds": {"radius": 1.0}}}
    strike_runtime.tick_active_strikes([active], entities, kc, dt=0.20)
    # No new hit during retract
    assert 99 not in active.held_hit_ids
