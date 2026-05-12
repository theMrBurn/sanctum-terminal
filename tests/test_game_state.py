"""Tests for core.systems.game_state — post PR 5 collapse.

Contract:
    Three canonical states (CHARACTER_CREATION / HUB / REFLECTIVE),
    transitions validated against an allowed-set, immutable. Initial
    state is HUB with no mission context. Round-trips through manifest
    dict serialization losslessly. Legacy mission_id / mission_seed /
    results fields survive PR 5 as None-defaulted ghost fields; PR 6
    drops them.
"""
from __future__ import annotations

import pytest

from core.systems.game_state import (
    GameState,
    GameStateName,
    transition,
    is_at_hub,
    to_manifest,
    from_manifest,
)


# --- Construction -----------------------------------------------------------

def test_initial_state_is_hub():
    """Post PR 6: GameState is just a state tag, no mission ghost fields."""
    gs = GameState.initial()
    assert gs.state == GameStateName.HUB
    assert not hasattr(gs, "mission_id")
    assert not hasattr(gs, "mission_seed")
    assert not hasattr(gs, "results")


def test_fresh_character_starts_at_creation():
    gs = GameState.fresh_character()
    assert gs.state == GameStateName.CHARACTER_CREATION


def test_predicates():
    gs = GameState.initial()
    assert is_at_hub(gs)


def test_enum_states_match_canon():
    """PR 5 collapse removed mission states. PR 4 of feat/creature-
    engagement added ENGAGEMENT alongside REFLECTIVE."""
    members = {s.value for s in GameStateName}
    assert members == {
        "CHARACTER_CREATION", "HUB", "REFLECTIVE", "ENGAGEMENT",
    }


# --- Allowed transitions ----------------------------------------------------

def test_character_creation_to_hub():
    """Sealing the 7th pillar finalizes the draft and lands at HUB."""
    gs = GameState.fresh_character()
    gs2 = transition(gs, GameStateName.HUB)
    assert gs2.state == GameStateName.HUB
    # Original unchanged.
    assert gs.state == GameStateName.CHARACTER_CREATION


def test_hub_to_character_creation_redo():
    """Pillar of Reflection re-engages identity creation."""
    gs = GameState.initial()
    gs2 = transition(gs, GameStateName.CHARACTER_CREATION)
    assert gs2.state == GameStateName.CHARACTER_CREATION


def test_hub_to_reflective_engages_fridge():
    gs = GameState.initial()
    gs2 = transition(gs, GameStateName.REFLECTIVE)
    assert gs2.state == GameStateName.REFLECTIVE


def test_reflective_to_hub_returns():
    gs = transition(GameState.initial(), GameStateName.REFLECTIVE)
    gs2 = transition(gs, GameStateName.HUB)
    assert gs2.state == GameStateName.HUB


# --- Illegal transitions ----------------------------------------------------

def test_hub_directly_to_old_mission_states_rejected():
    """The legacy mission states no longer exist as enum members."""
    with pytest.raises(ValueError):
        GameStateName("MISSION_SELECT")
    with pytest.raises(ValueError):
        GameStateName("IN_MISSION")
    with pytest.raises(ValueError):
        GameStateName("RESULTS")


def test_character_creation_to_reflective_rejected():
    """Only HUB ↔ REFLECTIVE; can't jump straight from creation."""
    gs = GameState.fresh_character()
    with pytest.raises(ValueError, match="illegal transition"):
        transition(gs, GameStateName.REFLECTIVE)


def test_reflective_to_character_creation_rejected():
    gs = transition(GameState.initial(), GameStateName.REFLECTIVE)
    with pytest.raises(ValueError, match="illegal transition"):
        transition(gs, GameStateName.CHARACTER_CREATION)


# --- Manifest round-trip ----------------------------------------------------

def test_to_manifest_just_carries_state():
    """Post PR 6: manifest.game_state is `{state: str}`. Quest/reflective
    context is on its own manifest blocks."""
    gs = transition(GameState.initial(), GameStateName.REFLECTIVE)
    payload = to_manifest(gs)
    assert payload == {"state": "REFLECTIVE"}


def test_from_manifest_round_trip():
    gs = transition(GameState.initial(), GameStateName.REFLECTIVE)
    restored = from_manifest(to_manifest(gs))
    assert restored == gs


def test_initial_state_round_trip():
    gs = GameState.initial()
    restored = from_manifest(to_manifest(gs))
    assert restored == gs


def test_creation_state_round_trip():
    gs = GameState.fresh_character()
    restored = from_manifest(to_manifest(gs))
    assert restored == gs


# --- Immutability -----------------------------------------------------------

def test_transition_does_not_mutate_input():
    gs = GameState.initial()
    _ = transition(gs, GameStateName.REFLECTIVE)
    assert gs.state == GameStateName.HUB


# --- Creature engagement state (feat/creature-engagement PR 4) ----


def test_hub_to_engagement_allowed():
    gs = transition(GameState.initial(), GameStateName.ENGAGEMENT)
    assert gs.state == GameStateName.ENGAGEMENT


def test_engagement_to_hub_allowed():
    gs = transition(GameState.initial(), GameStateName.ENGAGEMENT)
    back = transition(gs, GameStateName.HUB)
    assert back.state == GameStateName.HUB


def test_engagement_to_reflective_rejected():
    """No direct ENGAGEMENT → REFLECTIVE — return to HUB first."""
    gs = transition(GameState.initial(), GameStateName.ENGAGEMENT)
    with pytest.raises(ValueError, match="illegal transition"):
        transition(gs, GameStateName.REFLECTIVE)


def test_character_creation_to_engagement_rejected():
    gs = GameState.fresh_character()
    with pytest.raises(ValueError, match="illegal transition"):
        transition(gs, GameStateName.ENGAGEMENT)


def test_engagement_state_round_trip_manifest():
    gs = transition(GameState.initial(), GameStateName.ENGAGEMENT)
    restored = from_manifest(to_manifest(gs))
    assert restored == gs
    assert to_manifest(gs) == {"state": "ENGAGEMENT"}
