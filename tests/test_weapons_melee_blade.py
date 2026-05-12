"""melee_blade tests — feat/arpg-combat PR 3 (HELD mode).

Covers:
- iron_sword profile shape (held_verbs list, default_verb)
- supported_verbs() name resolution
- cycle_verb() forward/back/wraparound
- HELD-mode runtime tick (phase tracking, multi-hit, RIPOSTE special-case)
"""
from __future__ import annotations

import pytest

from core.systems import strike, strike_runtime
from core.systems.strike import HeldVerb
from core.systems.weapons import melee_blade


@pytest.fixture(autouse=True)
def _reset_dispatchers():
    strike._reset_dispatchers_for_tests()
    yield
    strike._reset_dispatchers_for_tests()


# ── iron_sword profile ───────────────────────────────────────────────


def test_iron_sword_profile_shape():
    p = melee_blade.IRON_SWORD_PROFILE
    assert p["mode"] == "held"
    assert p["weapon_class"] == "melee_blade"
    assert p["default_verb"] == "SLASH"
    # PUNCH excluded — sword too long for tight forward-thrust
    assert "PUNCH" not in p["held_verbs"]
    assert "SLASH" in p["held_verbs"]
    assert "STAB" in p["held_verbs"]
    assert "HACK" in p["held_verbs"]
    assert "RIPOSTE" in p["held_verbs"]


# ── supported_verbs() ────────────────────────────────────────────────


def test_supported_verbs_resolves_strings_to_enum():
    verbs = melee_blade.supported_verbs(melee_blade.IRON_SWORD_PROFILE)
    assert HeldVerb.SLASH in verbs
    assert HeldVerb.HACK in verbs
    assert HeldVerb.PUNCH not in verbs


def test_supported_verbs_skips_unknown_names():
    profile = {"held_verbs": ["SLASH", "FAKE_VERB", "HACK"]}
    verbs = melee_blade.supported_verbs(profile)
    assert verbs == [HeldVerb.SLASH, HeldVerb.HACK]


def test_supported_verbs_empty_falls_back_to_punch():
    profile = {"held_verbs": []}
    verbs = melee_blade.supported_verbs(profile)
    assert verbs == [HeldVerb.PUNCH]


# ── cycle_verb() ─────────────────────────────────────────────────────


def test_cycle_verb_forward_through_iron_sword_list():
    p = melee_blade.IRON_SWORD_PROFILE
    next_verb = melee_blade.cycle_verb(p, HeldVerb.SLASH, direction=1)
    # SLASH → STAB (next in sword's list)
    assert next_verb == HeldVerb.STAB


def test_cycle_verb_wraps_at_end():
    p = melee_blade.IRON_SWORD_PROFILE
    # iron_sword: [SLASH, STAB, HACK, RIPOSTE]
    next_verb = melee_blade.cycle_verb(p, HeldVerb.RIPOSTE, direction=1)
    assert next_verb == HeldVerb.SLASH


def test_cycle_verb_backward_wraps_at_start():
    p = melee_blade.IRON_SWORD_PROFILE
    prev_verb = melee_blade.cycle_verb(p, HeldVerb.SLASH, direction=-1)
    assert prev_verb == HeldVerb.RIPOSTE


def test_cycle_verb_unknown_current_returns_first():
    p = melee_blade.IRON_SWORD_PROFILE
    # PUNCH not in iron_sword's list; cycle should return first
    result = melee_blade.cycle_verb(p, HeldVerb.PUNCH, direction=1)
    assert result == HeldVerb.SLASH


# ── on_use convenience spawn ─────────────────────────────────────────


def test_on_use_returns_held_strike_with_default_verb():
    s = melee_blade.on_use(
        weapon_profile=melee_blade.IRON_SWORD_PROFILE,
        camera_state={"pos": (0, 0, 1.6), "forward": (0, 1, 0)},
        source_actor="player",
    )
    assert s.mode == "held"
    assert s.held_verb == HeldVerb.SLASH


def test_on_use_explicit_verb_overrides_default():
    s = melee_blade.on_use(
        weapon_profile=melee_blade.IRON_SWORD_PROFILE,
        camera_state={"pos": (0, 0, 1.6), "forward": (0, 1, 0)},
        source_actor="player",
        verb=HeldVerb.HACK,
    )
    assert s.held_verb == HeldVerb.HACK


def test_held_strike_captures_forward_in_held_arc():
    """spawn() captures forward into held_arc["spawn_forward"] so the
    runtime can place the swept hitbox without further input."""
    s = melee_blade.on_use(
        weapon_profile=melee_blade.IRON_SWORD_PROFILE,
        camera_state={"pos": (0, 0, 1.6), "forward": (0, 1, 0)},
        source_actor="player",
    )
    assert s.held_arc.get("spawn_forward") == [0.0, 1.0, 0.0]


# ── HELD runtime tick ────────────────────────────────────────────────


def test_held_strike_no_collision_during_windup():
    """Wind-up phase = no hitbox active. Entity in front of player
    is NOT hit during wind_up."""
    s = melee_blade.on_use(
        weapon_profile=melee_blade.IRON_SWORD_PROFILE,
        camera_state={"pos": (0, 0, 1.6), "forward": (0, 1, 0)},
        source_actor="player",
    )
    active = strike_runtime.make_active(s)
    # SLASH wind_up = 0.08s. tick 0.05s — still in wind-up.
    entities = [{"id": 1, "kind": "pot", "x": 0.0, "y": 1.5, "z": 1.6}]
    kc = {"pot": {"bounds": {"radius": 0.5}}}
    events = strike_runtime.tick_active_strikes([active], entities, kc, dt=0.05)
    assert not any(e["kind"] == "strike_landed" for e in events)
    assert not active.resolved


def test_held_strike_hits_during_active_phase():
    """Active phase — entity in arc gets hit."""
    s = melee_blade.on_use(
        weapon_profile=melee_blade.IRON_SWORD_PROFILE,
        camera_state={"pos": (0, 0, 1.6), "forward": (0, 1, 0)},
        source_actor="player",
    )
    active = strike_runtime.make_active(s)
    # Entity 1.5m forward — within SLASH reach (1.5m) + entity radius
    entities = [{"id": 1, "kind": "pot", "x": 0.0, "y": 1.5, "z": 1.6}]
    kc = {"pot": {"bounds": {"radius": 0.5}}}
    # SLASH: wind_up=0.08, active=0.20. dt=0.18 → progress=0.5, hitbox
    # at the midpoint of the sweep (straight forward).
    strike_runtime.tick_active_strikes([active], entities, kc, dt=0.18)
    assert 1 in active.held_hit_ids


def test_held_strike_multi_hit_in_one_swing():
    """Multiple entities in arc all get hit during active phase, but
    each only once per swing."""
    s = melee_blade.on_use(
        weapon_profile=melee_blade.IRON_SWORD_PROFILE,
        camera_state={"pos": (0, 0, 1.6), "forward": (0, 1, 0)},
        source_actor="player",
    )
    active = strike_runtime.make_active(s)
    # SLASH: reach 1.5m, hitbox_radius 0.4. Hitbox at y=1.5.
    # Two entities both within hitbox.
    entities = [
        {"id": 1, "kind": "pot",     "x": 0.0, "y": 1.5, "z": 1.6},
        {"id": 2, "kind": "crystal", "x": 0.3, "y": 1.5, "z": 1.6},
    ]
    kc = {"pot": {"bounds": {"radius": 0.5}},
          "crystal": {"bounds": {"radius": 0.5}}}
    # First active tick — dt=0.18 puts progress=0.5 (straight forward),
    # so both entities are within the swept hitbox.
    strike_runtime.tick_active_strikes([active], entities, kc, dt=0.18)
    assert 1 in active.held_hit_ids
    assert 2 in active.held_hit_ids
    # Second active tick — same entities, no double-hit (set membership)
    on_resolve_calls = []
    def cb(act, ent):
        on_resolve_calls.append(ent.get("id") if ent else None)
    strike_runtime.tick_active_strikes([active], entities, kc, dt=0.05,
                                        on_resolve=cb)
    # No new hits on second tick (entities already in held_hit_ids)
    assert on_resolve_calls == []


def test_held_strike_resolves_at_end_of_cooldown():
    """Strike resolves when total lifecycle (wind_up + active +
    cooldown) elapses."""
    s = melee_blade.on_use(
        weapon_profile=melee_blade.IRON_SWORD_PROFILE,
        camera_state={"pos": (0, 0, 1.6), "forward": (0, 1, 0)},
        source_actor="player",
    )
    active = strike_runtime.make_active(s)
    # SLASH total = 0.08 + 0.20 + 0.25 = 0.53s
    # Tick beyond — should resolve.
    strike_runtime.tick_active_strikes([active], entities=[], kind_config={}, dt=0.6)
    assert active.resolved
    # No hits → "missed"
    assert active.resolved_kind == "missed"


def test_held_strike_resolved_kind_landed_when_anything_hit():
    """If any entity was struck during active phase, final resolved
    state is 'landed' even if cooldown elapsed."""
    s = melee_blade.on_use(
        weapon_profile=melee_blade.IRON_SWORD_PROFILE,
        camera_state={"pos": (0, 0, 1.6), "forward": (0, 1, 0)},
        source_actor="player",
    )
    active = strike_runtime.make_active(s)
    entities = [{"id": 1, "kind": "pot", "x": 0.0, "y": 1.5, "z": 1.6}]
    kc = {"pot": {"bounds": {"radius": 0.5}}}
    # Active tick — hit
    strike_runtime.tick_active_strikes([active], entities, kc, dt=0.15)
    assert 1 in active.held_hit_ids
    # Past cooldown — resolves as "landed"
    strike_runtime.tick_active_strikes([active], entities=[], kind_config={}, dt=0.6)
    assert active.resolved_kind == "landed"


def test_held_strike_riposte_routes_to_parry_resolution():
    """RIPOSTE auto-routes on_contact to parry_incoming_strike."""
    s = melee_blade.on_use(
        weapon_profile=melee_blade.IRON_SWORD_PROFILE,
        camera_state={"pos": (0, 0, 1.6), "forward": (0, 1, 0)},
        source_actor="player",
        verb=HeldVerb.RIPOSTE,
    )
    assert s.on_contact == "parry_incoming_strike"
    # Active runtime still ticks like other HELD verbs (the runtime
    # doesn't yet differentiate parry; PR 7 + V2 enemy-Strike emission
    # adds the parry collision).
    active = strike_runtime.make_active(s)
    assert active.strike.held_verb == HeldVerb.RIPOSTE


def test_held_max_age_matches_full_lifecycle():
    """make_active sets max_age_s to (wind_up + active + cooldown) for
    HELD strikes so the resolution timing is deterministic."""
    s = melee_blade.on_use(
        weapon_profile=melee_blade.IRON_SWORD_PROFILE,
        camera_state={"pos": (0, 0, 1.6), "forward": (0, 1, 0)},
        source_actor="player",
        verb=HeldVerb.HACK,
    )
    active = strike_runtime.make_active(s)
    arc = s.held_arc
    expected = arc["wind_up_s"] + arc["active_s"] + arc["cooldown_s"]
    assert abs(active.max_age_s - expected) < 1e-6
