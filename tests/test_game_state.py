"""Tests for core.systems.game_state — the loop state machine.

Contract:
    Four canonical states (HUB / MISSION_SELECT / IN_MISSION / RESULTS),
    transitions validated against an allowed-set, immutable. Initial state
    is HUB with no mission context. Round-trips through manifest dict
    serialization losslessly.
"""
from __future__ import annotations

import pytest

from core.systems.game_state import (
    GameState,
    GameStateName,
    transition,
    is_at_hub,
    is_in_mission,
    to_manifest,
    from_manifest,
)


# --- Construction -----------------------------------------------------------

def test_initial_state_is_hub_with_no_context():
    gs = GameState.initial()
    assert gs.state == GameStateName.HUB
    assert gs.mission_id is None
    assert gs.mission_seed is None
    assert gs.results is None


def test_predicates():
    gs = GameState.initial()
    assert is_at_hub(gs)
    assert not is_in_mission(gs)


# --- Allowed transitions ----------------------------------------------------

def test_hub_to_mission_select():
    gs = GameState.initial()
    gs2 = transition(gs, GameStateName.MISSION_SELECT)
    assert gs2.state == GameStateName.MISSION_SELECT
    # Original unchanged
    assert gs.state == GameStateName.HUB


def test_mission_select_to_hub_cancels():
    gs = transition(GameState.initial(), GameStateName.MISSION_SELECT)
    gs = transition(gs, GameStateName.HUB)
    assert gs.state == GameStateName.HUB


def test_mission_select_to_in_mission_carries_mission_id():
    gs = transition(GameState.initial(), GameStateName.MISSION_SELECT)
    gs = transition(
        gs,
        GameStateName.IN_MISSION,
        mission_id="anomaly_hunt_01",
        mission_seed=42,
    )
    assert gs.state == GameStateName.IN_MISSION
    assert gs.mission_id == "anomaly_hunt_01"
    assert gs.mission_seed == 42
    assert is_in_mission(gs)


def test_in_mission_to_results_carries_payload():
    gs = transition(GameState.initial(), GameStateName.MISSION_SELECT)
    gs = transition(gs, GameStateName.IN_MISSION, mission_id="m1", mission_seed=7)
    gs = transition(
        gs,
        GameStateName.RESULTS,
        results={"loot": ["torch_handcrafted"], "xp": 100},
    )
    assert gs.state == GameStateName.RESULTS
    assert gs.results == {"loot": ["torch_handcrafted"], "xp": 100}
    # Mission context preserved through RESULTS for the summary screen
    assert gs.mission_id == "m1"


def test_results_to_hub_clears_context():
    """Acknowledging results returns to a clean HUB — no stale mission."""
    gs = transition(GameState.initial(), GameStateName.MISSION_SELECT)
    gs = transition(gs, GameStateName.IN_MISSION, mission_id="m1", mission_seed=7)
    gs = transition(gs, GameStateName.RESULTS, results={"xp": 50})
    gs = transition(gs, GameStateName.HUB)
    assert gs.state == GameStateName.HUB
    assert gs.mission_id is None
    assert gs.mission_seed is None
    assert gs.results is None


def test_in_mission_to_hub_aborts():
    """Quitting / escaping mid-mission returns to hub without RESULTS."""
    gs = transition(GameState.initial(), GameStateName.MISSION_SELECT)
    gs = transition(gs, GameStateName.IN_MISSION, mission_id="m1", mission_seed=7)
    gs = transition(gs, GameStateName.HUB)
    assert gs.state == GameStateName.HUB
    assert gs.mission_id is None


# --- Illegal transitions ----------------------------------------------------

def test_hub_to_in_mission_directly_rejected():
    gs = GameState.initial()
    with pytest.raises(ValueError, match="illegal transition"):
        transition(gs, GameStateName.IN_MISSION, mission_id="m1")


def test_hub_to_results_directly_rejected():
    gs = GameState.initial()
    with pytest.raises(ValueError, match="illegal transition"):
        transition(gs, GameStateName.RESULTS)


def test_results_to_in_mission_rejected():
    gs = transition(GameState.initial(), GameStateName.MISSION_SELECT)
    gs = transition(gs, GameStateName.IN_MISSION, mission_id="m1", mission_seed=1)
    gs = transition(gs, GameStateName.RESULTS)
    with pytest.raises(ValueError, match="illegal transition"):
        transition(gs, GameStateName.IN_MISSION, mission_id="m2")


def test_in_mission_requires_mission_id():
    gs = transition(GameState.initial(), GameStateName.MISSION_SELECT)
    with pytest.raises(ValueError, match="requires mission_id"):
        transition(gs, GameStateName.IN_MISSION)


# --- Manifest round-trip ----------------------------------------------------

def test_to_manifest_includes_all_fields():
    gs = transition(GameState.initial(), GameStateName.MISSION_SELECT)
    gs = transition(gs, GameStateName.IN_MISSION, mission_id="m1", mission_seed=42)
    payload = to_manifest(gs)
    assert payload["state"] == "IN_MISSION"
    assert payload["mission_id"] == "m1"
    assert payload["mission_seed"] == 42
    assert payload["results"] is None


def test_from_manifest_round_trip():
    gs = transition(GameState.initial(), GameStateName.MISSION_SELECT)
    gs = transition(gs, GameStateName.IN_MISSION, mission_id="m1", mission_seed=7)
    gs = transition(gs, GameStateName.RESULTS, results={"xp": 25})
    restored = from_manifest(to_manifest(gs))
    assert restored == gs


def test_initial_state_round_trip():
    gs = GameState.initial()
    restored = from_manifest(to_manifest(gs))
    assert restored == gs


# --- Immutability -----------------------------------------------------------

def test_transition_does_not_mutate_input():
    gs = GameState.initial()
    _ = transition(gs, GameStateName.MISSION_SELECT)
    assert gs.state == GameStateName.HUB
    assert gs.mission_id is None


# --- REFLECTIVE state (PR 3.5 step 5) --------------------------------------


def test_reflective_state_is_in_enum():
    """REFLECTIVE was added alongside the consequences engine + fridge
    substrate per design_reflective_loop. Survives PR 5's collapse."""
    assert GameStateName.REFLECTIVE.value == "REFLECTIVE"


def test_hub_to_reflective_allowed():
    """Walking up to fridge (voluntary) or routed via consequences engine
    (forced HP=0) — both transitions land here."""
    gs = transition(GameState.initial(), GameStateName.REFLECTIVE)
    assert gs.state == GameStateName.REFLECTIVE


def test_reflective_to_hub_allowed():
    """Commit or abort returns the player to HUB."""
    gs = transition(GameState.initial(), GameStateName.REFLECTIVE)
    gs = transition(gs, GameStateName.HUB)
    assert gs.state == GameStateName.HUB


def test_reflective_clears_mission_context():
    """Returning HUB after reflective wipes mission_id/seed/results
    same as any other HUB transition."""
    gs = transition(GameState.initial(), GameStateName.REFLECTIVE)
    gs = transition(gs, GameStateName.HUB)
    assert gs.mission_id is None
    assert gs.mission_seed is None
    assert gs.results is None


def test_illegal_transitions_to_reflective():
    """Only HUB can enter REFLECTIVE — never directly from
    CHARACTER_CREATION, MISSION_SELECT, IN_MISSION, RESULTS."""
    forbidden_sources = [
        GameStateName.CHARACTER_CREATION,
        GameStateName.MISSION_SELECT,
        GameStateName.IN_MISSION,
        GameStateName.RESULTS,
    ]
    for src in forbidden_sources:
        gs = GameState(state=src, mission_id=None, mission_seed=None, results=None)
        with pytest.raises(ValueError, match="illegal transition"):
            transition(gs, GameStateName.REFLECTIVE)


def test_illegal_transitions_from_reflective():
    """REFLECTIVE only exits to HUB — never directly to MISSION_SELECT
    or IN_MISSION etc."""
    gs = transition(GameState.initial(), GameStateName.REFLECTIVE)
    forbidden_targets = [
        GameStateName.CHARACTER_CREATION,
        GameStateName.MISSION_SELECT,
        GameStateName.IN_MISSION,
        GameStateName.RESULTS,
    ]
    for tgt in forbidden_targets:
        with pytest.raises(ValueError, match="illegal transition"):
            transition(gs, tgt)


def test_reflective_round_trips_via_manifest():
    gs = transition(GameState.initial(), GameStateName.REFLECTIVE)
    restored = from_manifest(to_manifest(gs))
    assert restored == gs
