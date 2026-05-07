"""Strike runtime tests — feat/arpg-combat PR 2.

Covers the per-tick advancement + entity collision + resolution path.
Brain integration is exercised end-to-end via test_strike_brain_integration.

Per `.claude/feature/feat_arpg-combat.md` PR 2 acceptance T3.
"""
from __future__ import annotations

import pytest

from core.systems import strike
from core.systems.ballistics import MotionVector
from core.systems.strike import HeldVerb
from core.systems.strike_runtime import (
    ActiveStrike,
    DEFAULT_MAX_AGE_S,
    kinetic_energy,
    make_active,
    tick_active_strikes,
)


@pytest.fixture(autouse=True)
def _reset_dispatchers():
    strike._reset_dispatchers_for_tests()
    yield
    strike._reset_dispatchers_for_tests()


# ── kinetic_energy ────────────────────────────────────────────────────


def test_kinetic_energy_zero_at_rest():
    state = MotionVector(pos=(0, 0, 0), vel=(0, 0, 0), spin=(0, 0, 0), timestamp=0.0)
    assert kinetic_energy(state, mass=2.0) == 0.0


def test_kinetic_energy_half_mv_squared():
    state = MotionVector(pos=(0, 0, 0), vel=(3.0, 4.0, 0), spin=(0, 0, 0), timestamp=0.0)
    # ½ · 2 · 25 = 25
    assert kinetic_energy(state, mass=2.0) == pytest.approx(25.0)


# ── make_active wraps a strike with a solver ──────────────────────────


def test_make_active_wraps_strike_with_solver():
    s = strike.spawn(
        weapon_profile={"profile_name": "throwing_axe", "shot_initial_v": 18.0,
                        "ball_mass": 2.0, "ball_radius": 0.3},
        mode="shot",
        camera_state={"pos": (0, 0, 1.5), "forward": (0, 1, 0)},
        source_actor="player",
    )
    active = make_active(s)
    assert active.strike is s
    assert active.current_state == s.initial_state
    assert active.age_seconds == 0.0
    assert active.max_age_s == DEFAULT_MAX_AGE_S
    assert active.solver is not None
    assert active.resolved is False


# ── tick_active_strikes — advance + age ───────────────────────────────


def test_tick_advances_position_under_velocity():
    s = strike.spawn(
        weapon_profile={"profile_name": "x", "shot_initial_v": 10.0,
                        "ball_mass": 1.0, "ball_radius": 0.3,
                        "gravity_y": 0.0},
        mode="shot",
        camera_state={"pos": (0.0, 0.0, 0.0), "forward": (0.0, 1.0, 0.0)},
        source_actor="player",
    )
    active = make_active(s)
    tick_active_strikes([active], entities=[], kind_config={}, dt=0.1)
    # 10 m/s × 0.1s = 1.0m forward
    assert abs(active.current_state.pos[1] - 1.0) < 1e-3
    assert active.age_seconds == pytest.approx(0.1)
    assert active.resolved is False


def test_tick_resolves_strike_at_max_age():
    s = strike.spawn(
        weapon_profile={"profile_name": "x", "shot_initial_v": 10.0,
                        "ball_mass": 1.0, "ball_radius": 0.3, "gravity_y": 0.0},
        mode="shot",
        camera_state={"pos": (0, 0, 0), "forward": (0, 1, 0)},
        source_actor="player",
    )
    active = make_active(s)
    active.max_age_s = 0.5
    events = tick_active_strikes([active], entities=[], kind_config={}, dt=0.6)
    assert active.resolved is True
    assert active.resolved_kind == "missed"
    assert any(e["kind"] == "strike_missed" for e in events)


# ── tick_active_strikes — entity collision ────────────────────────────


def test_tick_resolves_on_env_entity_contact():
    """Ball heading toward an env entity hits it within the tick."""
    s = strike.spawn(
        weapon_profile={"profile_name": "x", "shot_initial_v": 10.0,
                        "ball_mass": 1.0, "ball_radius": 0.3, "gravity_y": 0.0},
        mode="shot",
        camera_state={"pos": (0, 0, 1.0), "forward": (0, 1, 0)},
        source_actor="player",
    )
    active = make_active(s)
    # Place a "pot" entity 1m forward.
    entities = [{"id": 42, "kind": "pot", "x": 0.0, "y": 1.0, "z": 1.0}]
    kind_config = {"pot": {"bounds": {"radius": 0.5}}}
    events = tick_active_strikes([active], entities, kind_config, dt=0.2)
    assert active.resolved is True
    assert active.resolved_kind == "landed"
    assert any(e["kind"] == "strike_landed" for e in events)
    landed = next(e for e in events if e["kind"] == "strike_landed")
    assert landed["target_kind"] == "pot"
    assert landed["target_id"] == 42


def test_tick_skips_entities_outside_collision_radius():
    """Distant entity not in path; ball doesn't collide."""
    s = strike.spawn(
        weapon_profile={"profile_name": "x", "shot_initial_v": 10.0,
                        "ball_mass": 1.0, "ball_radius": 0.3, "gravity_y": 0.0},
        mode="shot",
        camera_state={"pos": (0, 0, 1.0), "forward": (0, 1, 0)},
        source_actor="player",
    )
    active = make_active(s)
    # Entity 50m off to the side.
    entities = [{"id": 1, "kind": "pot", "x": 50.0, "y": 0.5, "z": 1.0}]
    kind_config = {"pot": {"bounds": {"radius": 0.5}}}
    tick_active_strikes([active], entities, kind_config, dt=0.1)
    assert active.resolved is False


def test_tick_uses_default_collision_radius_when_kind_unbounded():
    """kind_config without bounds.radius falls back to default 0.5m."""
    s = strike.spawn(
        weapon_profile={"profile_name": "x", "shot_initial_v": 10.0,
                        "ball_mass": 1.0, "ball_radius": 0.3, "gravity_y": 0.0},
        mode="shot",
        camera_state={"pos": (0, 0, 1.0), "forward": (0, 1, 0)},
        source_actor="player",
    )
    active = make_active(s)
    # Entity exactly 0.7m forward — within 0.3 (ball) + 0.5 (default) = 0.8m
    entities = [{"id": 7, "kind": "uncategorized", "x": 0.0, "y": 0.7, "z": 1.0}]
    tick_active_strikes([active], entities, kind_config={}, dt=0.1)
    assert active.resolved is True


# ── on_resolve callback wiring ────────────────────────────────────────


def test_on_resolve_called_with_target_on_hit():
    s = strike.spawn(
        weapon_profile={"profile_name": "x", "shot_initial_v": 10.0,
                        "ball_mass": 1.0, "ball_radius": 0.3, "gravity_y": 0.0},
        mode="shot",
        camera_state={"pos": (0, 0, 1.0), "forward": (0, 1, 0)},
        source_actor="player",
    )
    active = make_active(s)
    entities = [{"id": 9, "kind": "crystal", "x": 0.0, "y": 0.7, "z": 1.0}]
    kind_config = {"crystal": {"bounds": {"radius": 0.5}}}
    callback_args = []
    def on_resolve(act, target):
        callback_args.append((act.resolved_kind, target))
    tick_active_strikes([active], entities, kind_config, dt=0.1,
                        on_resolve=on_resolve)
    assert len(callback_args) == 1
    kind, target = callback_args[0]
    assert kind == "landed"
    assert target["kind"] == "crystal"


def test_on_resolve_called_with_none_on_fade():
    s = strike.spawn(
        weapon_profile={"profile_name": "x", "shot_initial_v": 10.0,
                        "ball_mass": 1.0, "ball_radius": 0.3, "gravity_y": 0.0},
        mode="shot",
        camera_state={"pos": (0, 0, 0), "forward": (0, 1, 0)},
        source_actor="player",
    )
    active = make_active(s)
    active.max_age_s = 0.05
    callback_args = []
    def on_resolve(act, target):
        callback_args.append((act.resolved_kind, target))
    tick_active_strikes([active], entities=[], kind_config={}, dt=0.1,
                        on_resolve=on_resolve)
    assert len(callback_args) == 1
    assert callback_args[0] == ("missed", None)


# ── multiple strikes in flight ────────────────────────────────────────


def test_tick_handles_multiple_strikes_independently():
    """Each strike advances and resolves on its own."""
    s1 = strike.spawn(
        weapon_profile={"profile_name": "axe", "shot_initial_v": 10.0,
                        "ball_mass": 1.0, "ball_radius": 0.3, "gravity_y": 0.0},
        mode="shot",
        camera_state={"pos": (0, 0, 1.0), "forward": (0, 1, 0)},
        source_actor="player",
    )
    s2 = strike.spawn(
        weapon_profile={"profile_name": "axe", "shot_initial_v": 10.0,
                        "ball_mass": 1.0, "ball_radius": 0.3, "gravity_y": 0.0},
        mode="shot",
        camera_state={"pos": (5, 0, 1.0), "forward": (0, 1, 0)},
        source_actor="player",
    )
    a1 = make_active(s1)
    a2 = make_active(s2)
    a1.max_age_s = 0.05    # short — will fade
    a2.max_age_s = 5.0     # long — will continue
    tick_active_strikes([a1, a2], entities=[], kind_config={}, dt=0.1)
    assert a1.resolved and a1.resolved_kind == "missed"
    assert not a2.resolved
