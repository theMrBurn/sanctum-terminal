"""Strike primitive tests — feat/arpg-combat PR 1.

Per `.claude/feature/feat_arpg-combat.md` PR 1 acceptance T1.

Covers:
- HeldVerb IntEnum (5 verbs pinned, no extras)
- arc_shape() defaults per verb match spec table
- Strike construction (frozen dataclass)
- spawn() factory per mode (whip / shot / held)
- spawn() handles default_verb fallback for held
- spawn() RIPOSTE auto-routes to parry_incoming_strike
- dispatch register / get / resolve raising stub error
"""
from __future__ import annotations

import pytest

from core.systems import strike
from core.systems.strike import (
    HeldVerb,
    Strike,
    arc_shape,
    register_dispatcher,
    resolve,
    spawn,
)


@pytest.fixture(autouse=True)
def _reset_dispatchers():
    strike._reset_dispatchers_for_tests()
    yield
    strike._reset_dispatchers_for_tests()


# ── HeldVerb IntEnum ──────────────────────────────────────────────────


def test_held_verb_has_five_pinned_values():
    """5 verbs per locked spec. Adding a 6th is a real migration."""
    assert [v.name for v in HeldVerb] == ["PUNCH", "STAB", "SLASH", "HACK", "RIPOSTE"]
    assert int(HeldVerb.PUNCH) == 0
    assert int(HeldVerb.RIPOSTE) == 4


def test_held_verb_int_indexable():
    """Counters / lookup tables can index by int(verb)."""
    table = [0] * 5
    table[int(HeldVerb.SLASH)] = 1
    assert table[int(HeldVerb.SLASH)] == 1
    assert table[int(HeldVerb.HACK)] == 0


# ── arc_shape per verb ────────────────────────────────────────────────


@pytest.mark.parametrize("verb", list(HeldVerb))
def test_arc_shape_returns_full_dict(verb):
    """Every verb has wind_up_s, active_s, cooldown_s, reach_m, hitbox_radius."""
    shape = arc_shape(verb)
    for key in ("wind_up_s", "active_s", "cooldown_s", "reach_m", "hitbox_radius"):
        assert key in shape, f"{verb.name} arc missing {key}"
        assert isinstance(shape[key], float)
        assert shape[key] > 0


def test_arc_shape_returns_copy_not_reference():
    """Caller mutation must not pollute defaults."""
    a = arc_shape(HeldVerb.PUNCH)
    a["reach_m"] = 999.0
    b = arc_shape(HeldVerb.PUNCH)
    assert b["reach_m"] != 999.0


def test_riposte_has_short_active_window():
    """RIPOSTE is a tight parry window (per design_arpg_combat_v1
    timing table — 0.18s active, 0.35s cooldown, defensive feel)."""
    riposte = arc_shape(HeldVerb.RIPOSTE)
    assert riposte["active_s"] < 0.25      # tight
    assert riposte["cooldown_s"] > 0.30    # punishing


def test_hack_has_heavy_windup():
    """HACK windup > other verbs (slow heavy chop signature)."""
    hack = arc_shape(HeldVerb.HACK)
    other_windups = [arc_shape(v)["wind_up_s"]
                     for v in HeldVerb if v != HeldVerb.HACK]
    assert hack["wind_up_s"] > max(other_windups)


def test_stab_has_longest_reach():
    """STAB is the long-reach verb (1.8m); others ≤ 1.5m."""
    stab = arc_shape(HeldVerb.STAB)
    other_reaches = [arc_shape(v)["reach_m"]
                     for v in HeldVerb if v != HeldVerb.STAB]
    assert stab["reach_m"] > max(other_reaches)


# ── Strike construction (frozen dataclass) ────────────────────────────


def test_strike_is_frozen():
    s = spawn(
        weapon_profile={"profile_name": "iron_sword", "shot_initial_v": 12.0},
        mode="shot",
        camera_state={"pos": (0, 0, 0), "forward": (0, 1, 0)},
        source_actor="player",
    )
    with pytest.raises(Exception):     # FrozenInstanceError
        s.weapon_kind = "muddled"      # type: ignore[misc]


# ── spawn() — SHOT mode ───────────────────────────────────────────────


def test_spawn_shot_uses_forward_direction_and_speed():
    cam = {"pos": (0.0, 0.0, 1.5), "forward": (0.0, 1.0, 0.0), "now": 5.0}
    s = spawn(
        weapon_profile={"profile_name": "throwing_axe", "shot_initial_v": 18.0},
        mode="shot",
        camera_state=cam,
        source_actor="player",
    )
    assert s.mode == "shot"
    assert s.weapon_kind == "throwing_axe"
    assert s.shot_initial_v == 18.0
    # initial velocity = forward × shot_initial_v
    assert s.initial_state.vel == (0.0, 18.0, 0.0)
    assert s.initial_state.pos == (0.0, 0.0, 1.5)
    # Default on_contact for shot weapons
    assert s.on_contact == "damage_env"


def test_spawn_shot_falls_back_to_secondary_v():
    """Combo weapons store secondary_v not shot_initial_v — fallback works."""
    cam = {"pos": (0, 0, 0), "forward": (1, 0, 0)}
    s = spawn(
        weapon_profile={"profile_name": "fire_staff", "secondary_v": 24.0},
        mode="shot",
        camera_state=cam,
        source_actor="player",
    )
    assert s.shot_initial_v == 24.0
    assert s.initial_state.vel == (24.0, 0.0, 0.0)


# ── spawn() — WHIP mode ───────────────────────────────────────────────


def test_spawn_whip_spawns_at_tether_distance():
    """WHIP ball spawns at end of tether forward of player."""
    cam = {"pos": (0.0, 0.0, 1.5), "forward": (0.0, 1.0, 0.0), "ang_vel": 4.0}
    s = spawn(
        weapon_profile={"profile_name": "chain_whip", "tether_length": 3.0},
        mode="whip",
        camera_state=cam,
        source_actor="player",
    )
    assert s.mode == "whip"
    assert s.tether_length == 3.0
    # Ball spawns at tether_length forward of player.
    assert s.initial_state.pos == (0.0, 3.0, 1.5)


def test_spawn_whip_swing_velocity_uses_ang_vel_x_tether():
    """paddle_velocity = camera_angular_velocity × tether_length (per ping-pong)."""
    cam = {"pos": (0, 0, 0), "forward": (1, 0, 0), "ang_vel": 5.0}
    s = spawn(
        weapon_profile={"profile_name": "chain_whip", "tether_length": 2.0},
        mode="whip",
        camera_state=cam,
        source_actor="player",
    )
    # 5.0 rad/s × 2.0m = 10.0 m/s along forward
    assert s.initial_state.vel == (10.0, 0.0, 0.0)


# ── spawn() — HELD mode ───────────────────────────────────────────────


def test_spawn_held_uses_default_verb_when_unspecified():
    cam = {"pos": (0, 0, 0), "forward": (0, 1, 0)}
    s = spawn(
        weapon_profile={"profile_name": "iron_sword", "default_verb": "SLASH"},
        mode="held",
        camera_state=cam,
        source_actor="player",
    )
    assert s.mode == "held"
    assert s.held_verb == HeldVerb.SLASH
    assert s.held_arc["reach_m"] == arc_shape(HeldVerb.SLASH)["reach_m"]


def test_spawn_held_explicit_verb_overrides_default():
    cam = {"pos": (0, 0, 0), "forward": (0, 1, 0)}
    s = spawn(
        weapon_profile={"profile_name": "iron_sword", "default_verb": "SLASH"},
        mode="held",
        camera_state=cam,
        source_actor="player",
        held_verb=HeldVerb.HACK,
    )
    assert s.held_verb == HeldVerb.HACK


def test_spawn_held_riposte_routes_to_parry_resolution():
    """RIPOSTE is the only verb whose default on_contact is parry."""
    cam = {"pos": (0, 0, 0), "forward": (0, 1, 0)}
    s = spawn(
        weapon_profile={"profile_name": "iron_sword"},
        mode="held",
        camera_state=cam,
        source_actor="player",
        held_verb=HeldVerb.RIPOSTE,
    )
    assert s.on_contact == "parry_incoming_strike"


def test_spawn_held_non_riposte_uses_damage_env():
    cam = {"pos": (0, 0, 0), "forward": (0, 1, 0)}
    for verb in (HeldVerb.PUNCH, HeldVerb.STAB, HeldVerb.SLASH, HeldVerb.HACK):
        s = spawn(
            weapon_profile={"profile_name": "iron_sword"},
            mode="held",
            camera_state=cam,
            source_actor="player",
            held_verb=verb,
        )
        assert s.on_contact == "damage_env", f"{verb.name} should default to damage_env"


def test_spawn_held_falls_back_to_punch_when_no_default_verb():
    cam = {"pos": (0, 0, 0), "forward": (0, 1, 0)}
    s = spawn(
        weapon_profile={"profile_name": "fists"},     # no default_verb
        mode="held",
        camera_state=cam,
        source_actor="player",
    )
    assert s.held_verb == HeldVerb.PUNCH


# ── spawn() — error paths ─────────────────────────────────────────────


def test_spawn_rejects_unknown_mode():
    cam = {"pos": (0, 0, 0), "forward": (0, 1, 0)}
    with pytest.raises(ValueError, match="unknown mode"):
        spawn(
            weapon_profile={"profile_name": "x"},
            mode="charge",                              # type: ignore[arg-type]
            camera_state=cam,
            source_actor="player",
        )


# ── on_contact override ───────────────────────────────────────────────


def test_spawn_explicit_on_contact_override():
    """Caller can force a specific resolution kind (e.g., apply_effect
    for status-effect weapons in V2)."""
    cam = {"pos": (0, 0, 0), "forward": (0, 1, 0)}
    s = spawn(
        weapon_profile={"profile_name": "poison_dart", "shot_initial_v": 20.0},
        mode="shot",
        camera_state=cam,
        source_actor="player",
        on_contact="apply_effect",
    )
    assert s.on_contact == "apply_effect"


# ── Dispatcher registry + resolve() ───────────────────────────────────


def test_resolve_raises_when_no_dispatcher_registered():
    cam = {"pos": (0, 0, 0), "forward": (0, 1, 0)}
    s = spawn(
        weapon_profile={"profile_name": "throwing_axe", "shot_initial_v": 18.0},
        mode="shot",
        camera_state=cam,
        source_actor="player",
    )
    with pytest.raises(NotImplementedError, match="no dispatcher"):
        resolve(s, world=None)


def test_register_and_resolve_calls_dispatcher():
    calls = []
    def fake_handler(strike_arg, world_arg):
        calls.append((strike_arg.weapon_kind, world_arg))
        return ["mock_contact"]
    register_dispatcher("shot", fake_handler)
    cam = {"pos": (0, 0, 0), "forward": (0, 1, 0)}
    s = spawn(
        weapon_profile={"profile_name": "throwing_axe", "shot_initial_v": 18.0},
        mode="shot",
        camera_state=cam,
        source_actor="player",
    )
    result = resolve(s, world="mock_world")
    assert result == ["mock_contact"]
    assert calls == [("throwing_axe", "mock_world")]


def test_register_dispatcher_overwrites_idempotently():
    """Re-registration replaces the stub — supports PR sequencing where
    later PRs upgrade the handler from stub to real."""
    register_dispatcher("shot", lambda s, w: "old")
    register_dispatcher("shot", lambda s, w: "new")
    cam = {"pos": (0, 0, 0), "forward": (0, 1, 0)}
    s = spawn(
        weapon_profile={"profile_name": "x", "shot_initial_v": 1.0},
        mode="shot", camera_state=cam, source_actor="player",
    )
    assert resolve(s, world=None) == "new"
