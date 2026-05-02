"""Reflective-mode brain cmd handler wiring (PR 3.5 step 8).

Validates that brain_server.py defines and wires the five reflective
cmd handlers:
  - engage_fridge       (voluntary entry from HUB)
  - place_magnet        (append to composed)
  - remove_magnet       (pop by index)
  - commit_reflective   (eval AC; on success push trigger-specific event)
  - abort_reflective    (voluntary-only; back to HUB without commit)

These tests use static text checks of brain_server.py rather than
importing it — keeps the suite free of spacy/lexicon transitive deps.
The behavior of each handler is exercised end-to-end via the wiring
test in test_consequences_wiring.py and the state-machine tests in
test_reflective_state_machine.py.
"""
from __future__ import annotations

from pathlib import Path


_BRAIN_SOURCE = (
    Path(__file__).resolve().parents[1] / "brain_server.py"
).read_text()


# ── Imports + initialization ──────────────────────────────────────


def test_brain_imports_reflective_state_machine():
    assert (
        "from core.systems.reflective import state_machine as reflective_sm"
        in _BRAIN_SOURCE
    )


def test_brain_imports_reflective_state_dataclass():
    assert "from core.systems.reflective import ReflectiveState" in _BRAIN_SOURCE


def test_brain_world_initializes_reflective_state():
    assert "self.reflective: ReflectiveState = ReflectiveState()" in _BRAIN_SOURCE


# ── Cmd handler presence ──────────────────────────────────────────


def test_engage_fridge_handler_exists():
    assert 'msg.get("cmd") == "engage_fridge"' in _BRAIN_SOURCE


def test_place_magnet_handler_exists():
    assert 'msg.get("cmd") == "place_magnet"' in _BRAIN_SOURCE


def test_remove_magnet_handler_exists():
    assert 'msg.get("cmd") == "remove_magnet"' in _BRAIN_SOURCE


def test_commit_reflective_handler_exists():
    assert 'msg.get("cmd") == "commit_reflective"' in _BRAIN_SOURCE


def test_abort_reflective_handler_exists():
    assert 'msg.get("cmd") == "abort_reflective"' in _BRAIN_SOURCE


# ── engage_fridge guards ──────────────────────────────────────────


def test_engage_fridge_only_from_hub():
    """engage_fridge must check game_state == HUB before transitioning.
    Voluntary entry is hub-only; HP=0 path doesn't go through this cmd."""
    # The handler must reference the HUB check before calling enter.
    engage_block_start = _BRAIN_SOURCE.find('msg.get("cmd") == "engage_fridge"')
    engage_block_end = _BRAIN_SOURCE.find(
        'msg.get("cmd") ==', engage_block_start + 1
    )
    block = _BRAIN_SOURCE[engage_block_start:engage_block_end]
    assert "GameStateName.HUB" in block
    assert "reflective_sm.enter" in block
    assert 'trigger="voluntary"' in block


def test_engage_fridge_transitions_game_state():
    engage_block_start = _BRAIN_SOURCE.find('msg.get("cmd") == "engage_fridge"')
    engage_block_end = _BRAIN_SOURCE.find(
        'msg.get("cmd") ==', engage_block_start + 1
    )
    block = _BRAIN_SOURCE[engage_block_start:engage_block_end]
    assert "gs.GameStateName.REFLECTIVE" in block
    assert "gs.transition" in block


def test_engage_fridge_emits_reflect_state_event():
    engage_block_start = _BRAIN_SOURCE.find('msg.get("cmd") == "engage_fridge"')
    engage_block_end = _BRAIN_SOURCE.find(
        'msg.get("cmd") ==', engage_block_start + 1
    )
    block = _BRAIN_SOURCE[engage_block_start:engage_block_end]
    assert "REFLECT" in block
    assert "REG_RITUAL" in block


# ── commit_reflective branching ───────────────────────────────────


def test_commit_handler_branches_by_trigger():
    """On commit success, the handler emits one of two events keyed
    on world.reflective.trigger."""
    commit_start = _BRAIN_SOURCE.find('msg.get("cmd") == "commit_reflective"')
    commit_end = _BRAIN_SOURCE.find('msg.get("cmd") ==', commit_start + 1)
    block = _BRAIN_SOURCE[commit_start:commit_end]
    assert '"reflective_committed_from_hp_zero"' in block
    assert '"reflective_committed_voluntary"' in block


def test_commit_handler_calls_state_machine_commit():
    commit_start = _BRAIN_SOURCE.find('msg.get("cmd") == "commit_reflective"')
    commit_end = _BRAIN_SOURCE.find('msg.get("cmd") ==', commit_start + 1)
    block = _BRAIN_SOURCE[commit_start:commit_end]
    assert "reflective_sm.commit" in block


def test_commit_handler_emits_failure_state_event_on_ac_fail():
    """When AC eval returns False, brain emits a 'NOT YET' toast so
    the player gets feedback. V1 placeholder copy; voice authoring
    is a content-arc follow-up."""
    commit_start = _BRAIN_SOURCE.find('msg.get("cmd") == "commit_reflective"')
    commit_end = _BRAIN_SOURCE.find('msg.get("cmd") ==', commit_start + 1)
    block = _BRAIN_SOURCE[commit_start:commit_end]
    assert "NOT YET" in block


# ── abort_reflective guard ────────────────────────────────────────


def test_abort_only_for_voluntary_entry():
    """V1: HP=0 path locks until commit. Only voluntary entry can abort."""
    abort_start = _BRAIN_SOURCE.find('msg.get("cmd") == "abort_reflective"')
    abort_end = _BRAIN_SOURCE.find(
        '\n            # Camera update', abort_start
    )
    if abort_end == -1:
        abort_end = abort_start + 5000  # bound the search window
    block = _BRAIN_SOURCE[abort_start:abort_end]
    assert 'reflective.trigger != "voluntary"' in block
    assert "reflective_sm.exit" in block
    assert "GameStateName.HUB" in block


def test_abort_emits_state_event():
    abort_start = _BRAIN_SOURCE.find('msg.get("cmd") == "abort_reflective"')
    abort_end = _BRAIN_SOURCE.find(
        '\n            # Camera update', abort_start
    )
    if abort_end == -1:
        abort_end = abort_start + 5000
    block = _BRAIN_SOURCE[abort_start:abort_end]
    assert "reflective_aborted" in block or "LATER" in block


# ── place_magnet / remove_magnet guards ───────────────────────────


def test_place_magnet_gated_on_reflective_state():
    place_start = _BRAIN_SOURCE.find('msg.get("cmd") == "place_magnet"')
    place_end = _BRAIN_SOURCE.find('msg.get("cmd") ==', place_start + 1)
    block = _BRAIN_SOURCE[place_start:place_end]
    assert "GameStateName.REFLECTIVE" in block
    assert "reflective_sm.place_magnet" in block


def test_remove_magnet_gated_on_reflective_state():
    rem_start = _BRAIN_SOURCE.find('msg.get("cmd") == "remove_magnet"')
    rem_end = _BRAIN_SOURCE.find('msg.get("cmd") ==', rem_start + 1)
    block = _BRAIN_SOURCE[rem_start:rem_end]
    assert "GameStateName.REFLECTIVE" in block
    assert "reflective_sm.remove_magnet" in block
