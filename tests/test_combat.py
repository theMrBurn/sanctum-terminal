"""Tests for core.systems.combat.resolve_round.

Contract:
    resolve_round(participants, actions, attack_lib, roll_die) →
        (new_participants, log)

    - Participants sorted by `speed` descending; ties by id for determinism.
    - Each action looked up in attack_lib by action.attack_name.
    - Hit formula rolled, compared to target.<target_stat>.
    - On hit: damage formula rolled, scaled by target.element_mods, halved
      if target is defending this round.
    - Dead actors are skipped (and their queued actions no-op).
    - `roll_die` is injected: roll_die(size) → int in [1, size]. Tests
      supply a scripted roller so outcomes are deterministic.
    - Log is a list of dicts (structured events), not formatted strings.

    Pure function. No I/O.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from core.systems.combat import (
    Participant, Action, AttackDef, Formula,
    resolve_round, ScriptedRoller,
)


# --- Fixtures ----------------------------------------------------------------

def _player(**overrides) -> Participant:
    base = dict(
        id="p", name="Wanderer", hp=10, max_hp=10,
        str_=12, dex=10, wil=10, speed=10, defense=10,
        element_mods={}, side="player",
        inventory=(), status={}, alive=True,
    )
    base.update(overrides)
    return Participant(**base)


def _rat(**overrides) -> Participant:
    base = dict(
        id="r1", name="Rat", hp=4, max_hp=4,
        str_=6, dex=12, wil=4, speed=14, defense=12,
        element_mods={"fire": 1.5, "ice": 0.5}, side="enemy",
        inventory=(), status={}, alive=True,
    )
    base.update(overrides)
    return Participant(**base)


# Minimal attack library used across tests. Config-shaped — moving these
# into kind_config / attack_config is a pure data migration.
BASIC_ATTACK = AttackDef(
    name="basic_attack",
    verb="attack",
    element="physical",
    hit_formula=Formula(dice=(1, 20), stat="str_", const=0),
    damage_formula=Formula(dice=(1, 6), stat="str_", const=0),
    target_stat="defense",
    status=None,
)

FIRE_BOLT = AttackDef(
    name="fire_bolt",
    verb="magic",
    element="fire",
    hit_formula=Formula(dice=(1, 20), stat="wil", const=0),
    damage_formula=Formula(dice=(1, 6), stat="wil", const=0),
    target_stat="wil",   # opposed will
    status=None,
)

RAT_BITE = AttackDef(
    name="rat_bite",
    verb="attack",
    element="physical",
    hit_formula=Formula(dice=(1, 20), stat="str_", const=0),
    damage_formula=Formula(dice=(1, 3), stat=None, const=0),
    target_stat="defense",
    status=None,
)

ATTACK_LIB = {
    "basic_attack": BASIC_ATTACK,
    "fire_bolt": FIRE_BOLT,
    "rat_bite": RAT_BITE,
    # "defend", "flee", "item" verbs don't need an attack_lib entry;
    # they carry their semantics in Action.verb directly.
}


# --- Happy path --------------------------------------------------------------

def test_player_attack_hits_and_damages_rat():
    p = _player()
    r = _rat()
    # Player acts first (but rat has speed 14 vs player 10 — rat first)
    # With only one action this doesn't matter; test ordering separately.
    actions = [Action(actor_id="p", verb="attack", attack_name="basic_attack",
                      target_id="r1")]
    # Scripted rolls: hit d20=18 (hit, 18+12=30 ≥ 12), damage d6=4 → 4+12=16
    rng = ScriptedRoller([18, 4])
    new_parts, log = resolve_round([p, r], actions, ATTACK_LIB, rng)
    rat_after = next(x for x in new_parts if x.id == "r1")
    assert rat_after.hp == 0   # 4 - 16 clamped
    assert rat_after.alive is False
    hit_event = next(e for e in log if e["actor"] == "p" and e["result"] == "hit")
    assert hit_event["damage"] == 16
    assert hit_event["target"] == "r1"


def test_attack_misses_when_roll_below_target_stat():
    p = _player(str_=0)   # strip the bonus so miss is possible
    r = _rat(defense=20)
    actions = [Action(actor_id="p", verb="attack", attack_name="basic_attack",
                      target_id="r1")]
    rng = ScriptedRoller([5])   # 5 + 0 = 5, < 20
    new_parts, log = resolve_round([p, r], actions, ATTACK_LIB, rng)
    rat_after = next(x for x in new_parts if x.id == "r1")
    assert rat_after.hp == r.hp
    miss = next(e for e in log if e["verb"] == "attack")
    assert miss["result"] == "miss"
    assert miss.get("damage", 0) == 0


# --- Speed ordering ----------------------------------------------------------

def test_faster_participant_acts_first():
    p = _player(hp=3, speed=5, str_=10, defense=0)
    r = _rat(speed=20, str_=10, defense=0)
    actions = [
        Action(actor_id="p", verb="attack", attack_name="basic_attack", target_id="r1"),
        Action(actor_id="r1", verb="attack", attack_name="rat_bite", target_id="p"),
    ]
    # Rat hits for 3 (d3=3) → player drops to 0 → dies → player's queued
    # attack is skipped.
    rng = ScriptedRoller([20, 3])   # rat's hit, rat's damage
    new_parts, log = resolve_round([p, r], actions, ATTACK_LIB, rng)
    player_after = next(x for x in new_parts if x.id == "p")
    assert player_after.alive is False
    # Rat survived because player never got their attack off.
    rat_after = next(x for x in new_parts if x.id == "r1")
    assert rat_after.hp == r.hp
    # Player's action logged as skipped (or absent), not a hit.
    player_attacks = [e for e in log if e["actor"] == "p"]
    assert all(e.get("result") != "hit" for e in player_attacks)


# --- Defend -----------------------------------------------------------------

def test_defend_halves_incoming_damage():
    p = _player(hp=10, speed=100)   # player goes first to defend
    r = _rat(str_=0, speed=10)
    actions = [
        Action(actor_id="p", verb="defend", attack_name="", target_id=""),
        Action(actor_id="r1", verb="attack", attack_name="rat_bite", target_id="p"),
    ]
    # Rat hits (d20=18, no str bonus → 18 ≥ defense 10), damage d3=3 →
    # halved to 1 (integer divide). Player HP: 10 - 1 = 9.
    rng = ScriptedRoller([18, 3])
    new_parts, log = resolve_round([p, r], actions, ATTACK_LIB, rng)
    player_after = next(x for x in new_parts if x.id == "p")
    assert player_after.hp == 9


# --- Element mods -----------------------------------------------------------

def test_elemental_weakness_multiplies_damage():
    p = _player(speed=100)
    r = _rat(hp=20)   # element_mods: fire=1.5
    actions = [
        Action(actor_id="p", verb="magic", attack_name="fire_bolt", target_id="r1"),
    ]
    # Hit d20=18, +wil 10 = 28 ≥ rat.wil 4; damage d6=4, +wil 10 = 14,
    # × 1.5 (fire weakness) = 21 → rat HP 20 - 21 = -1 → 0 → dead.
    rng = ScriptedRoller([18, 4])
    new_parts, log = resolve_round([p, r], actions, ATTACK_LIB, rng)
    hit = next(e for e in log if e["result"] == "hit")
    assert hit["damage"] == 21
    assert hit.get("element") == "fire"


def test_elemental_resist_reduces_damage():
    p = _player(speed=100)
    fire_rat = _rat(hp=50, element_mods={"fire": 0.5}, wil=0)
    actions = [
        Action(actor_id="p", verb="magic", attack_name="fire_bolt", target_id="r1"),
    ]
    rng = ScriptedRoller([18, 4])  # 14 raw → ×0.5 → 7
    new_parts, log = resolve_round([p, fire_rat], actions, ATTACK_LIB, rng)
    hit = next(e for e in log if e["result"] == "hit")
    assert hit["damage"] == 7


# --- Dead actors ------------------------------------------------------------

def test_dead_actors_skip_queued_actions():
    p = _player(hp=0, alive=False)
    r = _rat()
    actions = [
        Action(actor_id="p", verb="attack", attack_name="basic_attack", target_id="r1"),
    ]
    # No rolls should be consumed — the roller is untouched.
    rng = ScriptedRoller([])
    new_parts, log = resolve_round([p, r], actions, ATTACK_LIB, rng)
    rat_after = next(x for x in new_parts if x.id == "r1")
    assert rat_after.hp == r.hp
    skipped = next(e for e in log if e["actor"] == "p")
    assert skipped["result"] == "skipped_dead"


def test_dying_mid_round_cancels_later_action():
    # Player goes first, kills rat. Rat's queued bite never fires.
    p = _player(speed=100, str_=100)     # guaranteed one-shot
    r = _rat(hp=1)
    actions = [
        Action(actor_id="p", verb="attack", attack_name="basic_attack", target_id="r1"),
        Action(actor_id="r1", verb="attack", attack_name="rat_bite", target_id="p"),
    ]
    # Player: hit d20=20, damage d6=1 → 1 + 100 = 101. Rat d20 never rolls.
    rng = ScriptedRoller([20, 1])
    new_parts, log = resolve_round([p, r], actions, ATTACK_LIB, rng)
    rat_after = next(x for x in new_parts if x.id == "r1")
    assert rat_after.alive is False
    skipped = next(e for e in log if e["actor"] == "r1")
    assert skipped["result"] == "skipped_dead"


# --- Flee -------------------------------------------------------------------

def test_flee_success_sets_fled_flag():
    p = _player(dex=20, speed=100)
    r = _rat(speed=5)
    actions = [
        Action(actor_id="p", verb="flee", attack_name="", target_id=""),
        Action(actor_id="r1", verb="attack", attack_name="rat_bite", target_id="p"),
    ]
    # Flee uses dex check: d20 ≤ dex (lower = success). Roll 5 ≤ 20 → success.
    # After successful flee, rat's queued attack still processes unless we
    # decide fleeing removes the target — keeping it simple: rat's attack
    # still rolls but the RoundResult carries a fled=True flag so the
    # session layer can end combat.
    rng = ScriptedRoller([5, 18, 2])  # flee roll, rat hit, rat damage
    new_parts, log = resolve_round([p, r], actions, ATTACK_LIB, rng)
    flee_event = next(e for e in log if e["verb"] == "flee")
    assert flee_event["result"] == "fled"
    player_after = next(x for x in new_parts if x.id == "p")
    # Parting blow still landed.
    assert player_after.hp < p.hp


def test_flee_failure_wastes_turn():
    p = _player(dex=2, speed=100)
    r = _rat()
    actions = [
        Action(actor_id="p", verb="flee", attack_name="", target_id=""),
    ]
    rng = ScriptedRoller([15])   # 15 > dex 2 → fail
    new_parts, log = resolve_round([p, r], actions, ATTACK_LIB, rng)
    flee_event = next(e for e in log if e["verb"] == "flee")
    assert flee_event["result"] == "flee_failed"


# --- Purity -----------------------------------------------------------------

def test_original_participants_unmutated():
    p = _player()
    r = _rat()
    actions = [Action(actor_id="p", verb="attack", attack_name="basic_attack",
                      target_id="r1")]
    resolve_round([p, r], actions, ATTACK_LIB, ScriptedRoller([18, 4]))
    assert p.hp == p.max_hp
    assert r.hp == r.max_hp
    assert p.status == {}
    assert r.status == {}
