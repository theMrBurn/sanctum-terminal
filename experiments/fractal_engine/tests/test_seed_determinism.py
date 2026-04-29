"""Seed determinism + delta-state ledger.

Third pillar of the directive: every grid is 100% reconstructible
from ParentSeed + Coordinates, and only user changes are persisted.
"""

import json
import tempfile
from pathlib import Path

import pytest

from engine import FractalEngine
from grid_node import GridNode, derive_seed
from primitives import Camera, Vec3
from world_state import Delta, WorldState


def test_same_seed_same_node_produces_same_drawlines():
    cam = Camera(position=Vec3(0, 0.6, 1.5))
    a = FractalEngine()
    b = FractalEngine()
    node_a = GridNode(seed=4242, depth=0).child(2, 5)
    node_b = GridNode(seed=4242, depth=0).child(2, 5)
    out_a = list(a.render(node_a, cam))
    out_b = list(b.render(node_b, cam))
    assert out_a == out_b


def test_different_seeds_diverge():
    cam = Camera(position=Vec3(0, 0.6, 1.5))
    a = list(FractalEngine().render(GridNode(seed=1).child(0, 0), cam))
    b = list(FractalEngine().render(GridNode(seed=2).child(0, 0), cam))
    assert a != b


def test_derive_seed_is_pure():
    s1 = derive_seed(123, 4, 5, 1)
    s2 = derive_seed(123, 4, 5, 1)
    assert s1 == s2
    s3 = derive_seed(123, 4, 5, 2)
    assert s1 != s3  # depth must affect the hash


def test_ledger_key_format():
    node = GridNode(seed=0, depth=0).child(2, 3).child(7, 1)
    assert node.ledger_key() == "G[2,3].S[7,1]"


def test_world_state_records_and_recalls():
    ws = WorldState()
    node = GridNode(seed=0, depth=0).child(1, 1)
    assert not ws.has_changes(node)
    ws.record(node, Delta(kind="place", tile=(3, 4)))
    assert ws.has_changes(node)
    deltas = ws.get(node)
    assert len(deltas) == 1
    assert deltas[0].tile == (3, 4)


def test_world_state_round_trips_through_json(tmp_path):
    ws = WorldState()
    node = GridNode(seed=0, depth=0).child(2, 2)
    ws.record(node, Delta(kind="remove", tile=(0, 0)))
    ws.record(node, Delta(kind="tag", payload={"label": "boss"}))

    path = tmp_path / "save.json"
    ws.save(path)
    restored = WorldState.load(path)
    assert restored.get(node)[0].kind == "remove"
    assert restored.get(node)[1].payload == {"label": "boss"}


def test_render_overlays_deltas_on_procedural_base():
    cam = Camera(position=Vec3(0, 0.6, 1.5))
    engine = FractalEngine()
    node = GridNode(seed=77, depth=0).child(1, 1).child(2, 2)

    base_lines = list(engine.render(node, cam))
    engine.state.record(node, Delta(kind="place", tile=(5, 5)))
    decorated_lines = list(engine.render(node, cam))

    # The delta-decorated render has *strictly more* primitives than
    # the base render — the overlay added geometry.
    assert len(decorated_lines) > len(base_lines)


def test_zoom_in_then_out_preserves_ledger_visibility():
    """Walking back to the same node retrieves recorded deltas."""
    engine = FractalEngine()
    overworld = GridNode(seed=1).child(3, 3)
    engine.state.record(overworld, Delta(kind="tag", payload={"note": "shrine"}))

    # Zoom into a dungeon and back.
    dungeon = overworld.child(7, 7)
    assert engine.state.get(dungeon) == []  # different ledger key

    # Walking "back" by reconstructing the overworld node from its
    # path/seed must hit the same key.
    same_overworld = GridNode(
        seed=overworld.seed, depth=overworld.depth, path=overworld.path
    )
    assert engine.state.get(same_overworld)[0].payload["note"] == "shrine"
