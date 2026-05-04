"""Actor base class + Orb (actor subtype) tests.

Covers: Actor lifecycle, Orb construction from config, phase transitions,
choose_intent math (seeded), take_turn effects. All of this is the encounter
primitive's behavior layer; data lives in config/encounters.json.
"""
from __future__ import annotations

import random
import pytest

from core.systems import encounter_config as ec
from core.systems.actor import Actor, Orb, choose_intent


# -- Actor base --------------------------------------------------------------

def test_actor_default_alive():
    a = Actor(name="T", hp=5, max_hp=5)
    assert not a.is_defeated()


def test_actor_take_damage_clamps():
    a = Actor(name="T", hp=5, max_hp=5)
    a.take_damage(3)
    assert a.hp == 2
    a.take_damage(10)
    assert a.hp == 0
    assert a.is_defeated()


def test_actor_take_damage_negative_noop():
    a = Actor(name="T", hp=5, max_hp=5)
    a.take_damage(-4)
    assert a.hp == 5


def test_actor_heal_clamps_to_max():
    a = Actor(name="T", hp=2, max_hp=5)
    a.heal(10)
    assert a.hp == 5


# -- Orb construction from config -------------------------------------------

def test_orb_from_config_loads_watcher():
    orb = Orb.from_config("watcher")
    assert orb.name == "watcher"
    assert orb.hp == 6
    assert orb.max_hp == 6
    assert orb.tags == ["observation_time", "precision_score"]
    assert orb.segments["count"] == 7


def test_orb_from_config_unknown_raises():
    with pytest.raises(KeyError):
        Orb.from_config("not_a_real_actor")


# -- Phase transitions -------------------------------------------------------

def test_orb_phase_composed_at_full_hp():
    orb = Orb.from_config("watcher")
    assert orb.phase() == "composed"


def test_orb_phase_pressured_at_half_hp():
    orb = Orb.from_config("watcher")
    orb.take_damage(3)   # 6 → 3, fraction 0.5
    assert orb.phase() == "pressured"


def test_orb_phase_desperate_at_low_hp():
    orb = Orb.from_config("watcher")
    orb.take_damage(5)   # 6 → 1, fraction 0.17
    assert orb.phase() == "desperate"


# -- choose_intent deterministic ---------------------------------------------

def test_choose_intent_returns_known_intent_name():
    orb = Orb.from_config("watcher")
    rng = random.Random(42)
    name, spec = choose_intent(orb, last_action=None, last_save=None, rng=rng)
    assert name in {"strike", "menace", "withdraw", "reveal", "bind"}
    assert "posture" in spec


def test_choose_intent_defend_bumps_menace():
    """After DEFEND, menace weight is ×3. Over many samples, menace dominates."""
    orb = Orb.from_config("watcher")
    rng = random.Random(1)
    counts = {"strike": 0, "menace": 0, "withdraw": 0, "reveal": 0, "bind": 0}
    for _ in range(500):
        name, _ = choose_intent(orb, last_action="DEFEND", last_save=None, rng=rng)
        counts[name] += 1
    # Base menace 0.30, bumped ×3 = 0.90 effective (vs strike 0.30, others small).
    # Expect menace as clear top pick.
    assert counts["menace"] == max(counts.values()), counts


def test_choose_intent_act_pass_bumps_withdraw():
    """Player landed ACT — orb should lean withdraw (heal/retreat)."""
    orb = Orb.from_config("watcher")
    rng = random.Random(2)
    counts = {"strike": 0, "menace": 0, "withdraw": 0, "reveal": 0, "bind": 0}
    for _ in range(500):
        name, _ = choose_intent(orb, last_action="ACT", last_save="pass", rng=rng)
        counts[name] += 1
    assert counts["withdraw"] > counts["reveal"], counts


def test_choose_intent_deterministic_with_same_seed():
    orb = Orb.from_config("watcher")
    rng_a = random.Random(777)
    rng_b = random.Random(777)
    a = [choose_intent(orb, None, None, rng_a)[0] for _ in range(20)]
    b = [choose_intent(orb, None, None, rng_b)[0] for _ in range(20)]
    assert a == b


# -- take_turn effects -------------------------------------------------------

def _player_with_stats(hp=10, str_save=10, dex_save=10, wil_save=10):
    from core.systems.player_state import PlayerState
    p = PlayerState.new(seed=0, max_hp=hp)
    return p._replace(str_save=str_save, dex_save=dex_save, wil_save=wil_save)


def test_strike_damages_player():
    orb = Orb.from_config("watcher")
    orb.current_intent = ("strike", ec.get_intent("strike"))
    p = _player_with_stats()
    new_p, log = orb.take_turn(p, rng=lambda size: size)   # max roll = max dmg
    assert new_p.hp < p.hp
    assert log["intent"] == "strike"
    assert log["hp_delta"] < 0


def test_withdraw_heals_orb():
    orb = Orb.from_config("watcher")
    orb.take_damage(4)
    before = orb.hp
    orb.current_intent = ("withdraw", ec.get_intent("withdraw"))
    p = _player_with_stats()
    new_p, log = orb.take_turn(p, rng=lambda size: 1)
    assert orb.hp == before + 1
    assert new_p.hp == p.hp   # no damage to player


def test_menace_triggers_progress_delta_flag():
    """menace returns an effect payload the session uses to adjust progress.
    take_turn doesn't own net_passes — the session does."""
    orb = Orb.from_config("watcher")
    orb.current_intent = ("menace", ec.get_intent("menace"))
    p = _player_with_stats()
    new_p, log = orb.take_turn(p, rng=lambda size: 1)
    assert log["effect"] == "progress_delta"
    assert log["value"] == -1


def test_bind_returns_disadvantage_flag():
    orb = Orb.from_config("watcher")
    orb.current_intent = ("bind", ec.get_intent("bind"))
    p = _player_with_stats()
    _, log = orb.take_turn(p, rng=lambda size: 1)
    assert log["effect"] == "disadvantage_next"


def test_reveal_returns_bonus_flag():
    orb = Orb.from_config("watcher")
    orb.current_intent = ("reveal", ec.get_intent("reveal"))
    p = _player_with_stats()
    _, log = orb.take_turn(p, rng=lambda size: 1)
    assert log["effect"] == "bonus_next_read"


def test_take_turn_without_intent_raises():
    orb = Orb.from_config("watcher")
    p = _player_with_stats()
    with pytest.raises(RuntimeError):
        orb.take_turn(p, rng=lambda size: 1)
