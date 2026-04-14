"""Tests for core.systems.combat_session.CombatSession.

Contract:
    session = CombatSession(participants, attack_lib, roll_die)
    session.round                      → int (0 before first resolve)
    session.ended                      → bool
    session.outcome                    → "active" | "victory" | "defeat" | "fled"
    session.living_enemies()           → list[Participant]
    session.living_players()           → list[Participant]
    session.resolve(actions)           → log: list[dict]
        After resolve, session.participants is updated, round += 1, and
        session.outcome reflects end-state transitions.

    Stateful wrapper around combat.resolve_round. Tracks round index,
    detects end conditions, holds participants between rounds. Pure
    function math stays in combat.py — this module adds state.
"""
from __future__ import annotations

import pytest

from core.systems.combat import (
    Participant, Action, AttackDef, Formula, ScriptedRoller,
)
from core.systems.combat_session import CombatSession


# --- Fixtures ----------------------------------------------------------------

def _player(hp=10, speed=10, **kw) -> Participant:
    base = dict(
        id="p", name="Hero", hp=hp, max_hp=10,
        str_=12, dex=10, wil=10, speed=speed, defense=11,
        element_mods={}, side="player",
        inventory=(), status={}, alive=True,
    )
    base.update(kw)
    return Participant(**base)


def _rat(id="r1", hp=4, speed=14, **kw) -> Participant:
    base = dict(
        id=id, name="Rat", hp=hp, max_hp=4,
        str_=4, dex=12, wil=4, speed=speed, defense=10,
        element_mods={"fire": 1.3}, side="enemy",
        inventory=(), status={}, alive=True,
    )
    base.update(kw)
    return Participant(**base)


BASIC = AttackDef(
    name="strike", verb="attack", element="physical",
    hit_formula=Formula(dice=(1, 20), stat="str_", const=0),
    damage_formula=Formula(dice=(1, 6), stat="str_", const=0),
    target_stat="defense", status=None,
)
BITE = AttackDef(
    name="rat_bite", verb="attack", element="physical",
    hit_formula=Formula(dice=(1, 20), stat="str_", const=0),
    damage_formula=Formula(dice=(1, 3), stat=None, const=1),
    target_stat="defense", status=None,
)
LIB = {"strike": BASIC, "rat_bite": BITE}


# --- Initial state -----------------------------------------------------------

def test_session_starts_at_round_zero_active():
    s = CombatSession([_player(), _rat()], LIB, ScriptedRoller([]))
    assert s.round == 0
    assert s.ended is False
    assert s.outcome == "active"


def test_living_enemies_initial():
    s = CombatSession([_player(), _rat(), _rat(id="r2")], LIB, ScriptedRoller([]))
    assert len(s.living_enemies()) == 2
    assert len(s.living_players()) == 1


# --- Round advance -----------------------------------------------------------

def test_resolve_advances_round():
    s = CombatSession([_player(speed=100), _rat()], LIB, ScriptedRoller([20, 1]))
    actions = [Action("p", "attack", "strike", "r1")]
    log = s.resolve(actions)
    assert s.round == 1
    assert isinstance(log, list)
    assert len(log) > 0


def test_resolve_returns_updated_participants():
    s = CombatSession([_player(speed=100), _rat()], LIB, ScriptedRoller([20, 1]))
    actions = [Action("p", "attack", "strike", "r1")]
    s.resolve(actions)
    rat = next(p for p in s.participants if p.id == "r1")
    # 1 + 12 str = 13 damage; rat has 4 hp → dead.
    assert rat.alive is False


# --- End conditions ----------------------------------------------------------

def test_victory_when_all_enemies_dead():
    s = CombatSession([_player(speed=100), _rat()], LIB, ScriptedRoller([20, 1]))
    s.resolve([Action("p", "attack", "strike", "r1")])
    assert s.ended is True
    assert s.outcome == "victory"


def test_defeat_when_player_dies():
    p = _player(hp=1, speed=1)
    r = _rat(speed=100)
    # Rat hits, d3=2 + 1 const = 3 damage → player dies.
    s = CombatSession([p, r], LIB, ScriptedRoller([20, 2]))
    s.resolve([Action("r1", "attack", "rat_bite", "p")])
    assert s.ended is True
    assert s.outcome == "defeat"


def test_fled_outcome_on_successful_flee():
    p = _player(dex=20, speed=100)
    r = _rat()
    s = CombatSession([p, r], LIB, ScriptedRoller([5]))  # dex 5 ≤ 20 = success
    s.resolve([Action("p", "flee", "", "")])
    assert s.ended is True
    assert s.outcome == "fled"


def test_multi_round_active_until_resolved():
    p = _player(hp=10, speed=100, str_=1)  # weak — can't one-shot
    r = _rat(hp=10, str_=0)
    s = CombatSession([p, r], LIB, ScriptedRoller(
        [20, 2, 18, 1,     # round 1: player hits 3, rat hits 2
         20, 2, 18, 1,     # round 2: player hits 3, rat hits 2
         20, 2, 18, 1]     # round 3: player hits 3, rat hits 2
    ))
    s.resolve([
        Action("p", "attack", "strike", "r1"),
        Action("r1", "attack", "rat_bite", "p"),
    ])
    assert s.round == 1
    assert s.outcome == "active"
    s.resolve([
        Action("p", "attack", "strike", "r1"),
        Action("r1", "attack", "rat_bite", "p"),
    ])
    assert s.round == 2
    assert s.outcome == "active"


def test_resolve_after_ended_is_noop():
    s = CombatSession([_player(speed=100), _rat()], LIB, ScriptedRoller([20, 1]))
    s.resolve([Action("p", "attack", "strike", "r1")])
    assert s.ended
    before = s.round
    log = s.resolve([Action("p", "attack", "strike", "r1")])
    # No advance, empty log.
    assert s.round == before
    assert log == []


# --- Accessors after resolution ---------------------------------------------

def test_participants_accessor_reflects_current_state():
    s = CombatSession([_player(speed=100), _rat()], LIB, ScriptedRoller([20, 1]))
    s.resolve([Action("p", "attack", "strike", "r1")])
    # rat dead → living_enemies empty
    assert s.living_enemies() == []
    # but participants list still has the corpse
    assert any(p.id == "r1" for p in s.participants)
