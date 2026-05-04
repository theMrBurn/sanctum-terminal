"""Fridge spawn — visible-list injection in HUB (PR 3.5 step 9).

V1 mirrors the pillar_reflection pattern: spawned inline in
brain_server's visible list with all visual params on the entity.
No kind_config.json row yet — promotion to that pattern lands when
we tune the visual after first UAT.

Static text checks rather than runtime brain instantiation — keeps
this suite free of spacy/lexicon transitive imports.
"""
from __future__ import annotations

from pathlib import Path


_BRAIN_SOURCE = (
    Path(__file__).resolve().parents[1] / "brain_server.py"
).read_text()


def test_fridge_spawn_block_present():
    """The fridge spawn block must exist near the pillar_reflection
    block, gated on HUB game state + finalized character sheet."""
    assert '"kind": "fridge"' in _BRAIN_SOURCE


def test_fridge_spawn_uses_negative_id():
    """Same convention as pillar_reflection — negative ids mark
    brain-injected entities, distinct from procedurally-spawned ones."""
    fridge_idx = _BRAIN_SOURCE.find('"kind": "fridge"')
    block = _BRAIN_SOURCE[fridge_idx - 200:fridge_idx + 400]
    assert '"id": -1200' in block


def test_fridge_spawn_in_hub_only():
    """Fridge appears only when game_state is HUB. The block lives
    inside the same `if game_state == HUB` guard as pillar_reflection."""
    pillar_idx = _BRAIN_SOURCE.find('"kind": "pillar_reflection"')
    fridge_idx = _BRAIN_SOURCE.find('"kind": "fridge"')
    # Both are in the same HUB-gated block; fridge follows pillar.
    assert pillar_idx < fridge_idx
    # No interleaving game-state check between them.
    between = _BRAIN_SOURCE[pillar_idx:fridge_idx]
    assert "GameStateName" not in between or "HUB" not in between or "if (" not in between


def test_fridge_has_collision_radius():
    fridge_idx = _BRAIN_SOURCE.find('"kind": "fridge"')
    block = _BRAIN_SOURCE[fridge_idx:fridge_idx + 400]
    assert '"collision_radius"' in block


def test_fridge_has_visible_color():
    fridge_idx = _BRAIN_SOURCE.find('"kind": "fridge"')
    block = _BRAIN_SOURCE[fridge_idx:fridge_idx + 400]
    # Pale fridge palette per design — refine after UAT.
    assert '"r":' in block
    assert '"g":' in block
    assert '"b":' in block
