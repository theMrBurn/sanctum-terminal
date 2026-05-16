"""vault.biome_thing_state — per-tile interaction persistence.

Per `feat/biome-greenhouse` PR 4 + `design_path_memory`. Caverns
remember kicked offsets + picked-up tombstones across brain
restarts.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.vault import vault as Vault


@pytest.fixture
def v(tmp_path: Path):
    return Vault(db_path=tmp_path / "v.db")


def test_pickup_persists(v):
    v.biome_thing_state_set_picked_up("cavern", 1, 2, "longsword")
    state = v.biome_thing_state_get("cavern", 1, 2, "longsword")
    assert state is not None
    assert state["picked_up"] is True


def test_pickup_idempotent(v):
    v.biome_thing_state_set_picked_up("cavern", 1, 2, "longsword")
    v.biome_thing_state_set_picked_up("cavern", 1, 2, "longsword")
    assert v.biome_thing_state_get("cavern", 1, 2, "longsword")["picked_up"]


def test_kick_accumulates(v):
    new_dx, new_dy = v.biome_thing_state_add_kick(
        "cavern", 1, 2, "longsword", dx=0.5, dy=0.0)
    assert new_dx == pytest.approx(0.5)
    assert new_dy == pytest.approx(0.0)
    new_dx, new_dy = v.biome_thing_state_add_kick(
        "cavern", 1, 2, "longsword", dx=0.3, dy=0.2)
    assert new_dx == pytest.approx(0.8)
    assert new_dy == pytest.approx(0.2)


def test_kick_then_pickup_keeps_both(v):
    """Pickup after kick — both flags+offset persist in the same row."""
    v.biome_thing_state_add_kick(
        "cavern", 1, 2, "longsword", dx=0.5, dy=0.5)
    v.biome_thing_state_set_picked_up("cavern", 1, 2, "longsword")
    state = v.biome_thing_state_get("cavern", 1, 2, "longsword")
    assert state["picked_up"] is True
    assert state["kick_dx"] == pytest.approx(0.5)


def test_for_tile_returns_all_things(v):
    v.biome_thing_state_set_picked_up("cavern", 1, 2, "a")
    v.biome_thing_state_set_picked_up("cavern", 1, 2, "b")
    v.biome_thing_state_set_picked_up("cavern", 1, 3, "c")    # different tile
    tile_state = v.biome_thing_state_for_tile("cavern", 1, 2)
    assert sorted(tile_state.keys()) == ["a", "b"]


def test_unknown_returns_none(v):
    assert v.biome_thing_state_get("cavern", 0, 0, "ghost") is None


def test_biomes_isolated(v):
    v.biome_thing_state_set_picked_up("cavern",  1, 2, "thing")
    v.biome_thing_state_set_picked_up("outdoor", 1, 2, "thing")
    cav = v.biome_thing_state_get("cavern",  1, 2, "thing")
    out = v.biome_thing_state_get("outdoor", 1, 2, "thing")
    assert cav["picked_up"] and out["picked_up"]


def test_clear_biome(v):
    v.biome_thing_state_set_picked_up("cavern",  1, 2, "a")
    v.biome_thing_state_set_picked_up("outdoor", 1, 2, "b")
    dropped = v.biome_thing_state_clear(biome="cavern")
    assert dropped == 1
    assert v.biome_thing_state_get("cavern", 1, 2, "a") is None
    assert v.biome_thing_state_get("outdoor", 1, 2, "b") is not None


def test_clear_all(v):
    v.biome_thing_state_set_picked_up("cavern",  1, 2, "a")
    v.biome_thing_state_set_picked_up("outdoor", 1, 2, "b")
    dropped = v.biome_thing_state_clear()
    assert dropped == 2
    assert v.biome_thing_state_get("cavern", 1, 2, "a") is None
    assert v.biome_thing_state_get("outdoor", 1, 2, "b") is None


def test_persistence_across_vault_instances(tmp_path: Path):
    """State survives reopening the vault — confirms it's on disk,
    not in-memory."""
    db = tmp_path / "v.db"
    v1 = Vault(db_path=db)
    v1.biome_thing_state_set_picked_up("cavern", 5, 5, "longsword")
    v1.biome_thing_state_add_kick("cavern", 5, 5, "longsword", 0.3, 0.7)
    del v1
    v2 = Vault(db_path=db)
    state = v2.biome_thing_state_get("cavern", 5, 5, "longsword")
    assert state["picked_up"] is True
    assert state["kick_dx"] == pytest.approx(0.3)
    assert state["kick_dy"] == pytest.approx(0.7)
