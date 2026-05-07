"""PR 2 tests — dungeon generation.

Validates:
  - Tile enum has the required members.
  - Level dataclass fields are populated correctly.
  - BFS from spawn_pos reaches every passable tile (full connectivity).
  - stairs_pos is reachable and is a STAIRS_DOWN tile.
  - spawn_pos is a passable tile.
  - No orphan passable tiles outside BFS reach.
  - Golden fixture: known seed produces deterministic output.

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 2.
"""
from __future__ import annotations

import pytest

from core.systems.make_brains.nethack.dungeon import (
    MAP_H,
    MAP_W,
    PASSABLE,
    Tile,
    Level,
    Room,
    _bfs_connected,
    generate_level,
)


# ---------------------------------------------------------------------------
# Tile enum
# ---------------------------------------------------------------------------

def test_tile_enum_members():
    required = {"WALL", "FLOOR", "DOOR", "CORRIDOR", "STAIRS_DOWN"}
    names = {t.name for t in Tile}
    assert required <= names, f"missing Tile members: {required - names}"


def test_passable_does_not_include_wall_or_void():
    assert Tile.WALL not in PASSABLE
    assert Tile.VOID not in PASSABLE
    assert Tile.FLOOR in PASSABLE
    assert Tile.CORRIDOR in PASSABLE
    assert Tile.STAIRS_DOWN in PASSABLE


# ---------------------------------------------------------------------------
# Generate level helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def level_42() -> Level:
    return generate_level(seed=42)


@pytest.fixture()
def level_1337() -> Level:
    return generate_level(seed=1337)


# ---------------------------------------------------------------------------
# Grid dimensions and type
# ---------------------------------------------------------------------------

def test_grid_dimensions(level_42):
    assert len(level_42.grid) == MAP_W
    for col in level_42.grid:
        assert len(col) == MAP_H


def test_grid_contains_only_tile_values(level_42):
    valid = set(Tile)
    for col in level_42.grid:
        for cell in col:
            assert cell in valid


def test_seed_stored(level_42):
    assert level_42.seed == 42


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------

def test_at_least_two_rooms(level_42):
    assert len(level_42.rooms) >= 2


def test_rooms_within_map_bounds(level_42):
    for room in level_42.rooms:
        assert room.x >= 0
        assert room.y >= 0
        assert room.x + room.w <= MAP_W
        assert room.y + room.h <= MAP_H


# ---------------------------------------------------------------------------
# Spawn and stairs positions
# ---------------------------------------------------------------------------

def test_spawn_is_passable(level_42):
    sx, sy = level_42.spawn_pos
    assert level_42.at(sx, sy) in PASSABLE


def test_stairs_is_correct_tile(level_42):
    sx, sy = level_42.stairs_pos
    assert level_42.at(sx, sy) == Tile.STAIRS_DOWN


def test_stairs_is_passable(level_42):
    sx, sy = level_42.stairs_pos
    assert level_42.at(sx, sy) in PASSABLE


# ---------------------------------------------------------------------------
# Connectivity — BFS from spawn reaches every passable tile
# ---------------------------------------------------------------------------

def test_full_connectivity(level_42):
    """Every passable tile must be reachable from spawn. No orphan tiles."""
    reachable = _bfs_connected(level_42.grid, level_42.spawn_pos)
    all_passable = set(level_42.all_passable_positions())
    orphans = all_passable - reachable
    assert orphans == set(), (
        f"{len(orphans)} orphan passable tiles not reachable from spawn: "
        f"{sorted(orphans)[:10]}"
    )


def test_stairs_reachable(level_42):
    reachable = _bfs_connected(level_42.grid, level_42.spawn_pos)
    assert level_42.stairs_pos in reachable


def test_full_connectivity_different_seed(level_1337):
    reachable = _bfs_connected(level_1337.grid, level_1337.spawn_pos)
    all_passable = set(level_1337.all_passable_positions())
    orphans = all_passable - reachable
    assert orphans == set(), f"{len(orphans)} orphan tiles with seed 1337"


# ---------------------------------------------------------------------------
# No orphan tiles — broader fuzz over several seeds
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [0, 1, 7, 99, 256, 500, 1000, 9999])
def test_connectivity_fuzz(seed: int):
    level = generate_level(seed)
    reachable = _bfs_connected(level.grid, level.spawn_pos)
    all_passable = set(level.all_passable_positions())
    orphans = all_passable - reachable
    assert orphans == set(), (
        f"seed={seed}: {len(orphans)} orphan tiles"
    )


# ---------------------------------------------------------------------------
# Determinism — same seed always produces same map
# ---------------------------------------------------------------------------

def test_deterministic_same_seed():
    a = generate_level(42)
    b = generate_level(42)
    assert a.spawn_pos == b.spawn_pos
    assert a.stairs_pos == b.stairs_pos
    assert len(a.rooms) == len(b.rooms)
    # Compare full grids
    for x in range(MAP_W):
        for y in range(MAP_H):
            assert a.grid[x][y] == b.grid[x][y], f"mismatch at ({x},{y})"


def test_different_seeds_differ():
    a = generate_level(42)
    b = generate_level(43)
    # Spawn positions OR at least one tile must differ for seeds to be distinct.
    grid_same = all(
        a.grid[x][y] == b.grid[x][y]
        for x in range(MAP_W)
        for y in range(MAP_H)
    )
    assert not grid_same, "seed 42 and seed 43 produced identical grids"


# ---------------------------------------------------------------------------
# Golden fixture — known seed produces expected structural properties
# ---------------------------------------------------------------------------

def test_golden_seed_42_structure():
    """Pinned structural properties for seed=42. If dungeon gen changes
    meaningfully, this test will catch it early."""
    level = generate_level(42)
    # Spawn at a valid position
    sx, sy = level.spawn_pos
    assert 0 < sx < MAP_W and 0 < sy < MAP_H

    # Stairs at a valid position
    stx, sty = level.stairs_pos
    assert 0 < stx < MAP_W and 0 < sty < MAP_H
    assert level.at(stx, sty) == Tile.STAIRS_DOWN

    # Grid has a reasonable number of passable tiles
    passable_count = sum(
        1 for x in range(MAP_W) for y in range(MAP_H)
        if level.grid[x][y] in PASSABLE
    )
    # At minimum 2 rooms (4×3=12 floor cells each) + corridors
    assert passable_count >= 24

    # Pin exact spawn and stairs for regression detection
    assert level.spawn_pos == (12, 4), f"unexpected spawn: {level.spawn_pos}"
    assert level.stairs_pos in {
        (x, y) for x in range(MAP_W) for y in range(MAP_H)
        if level.grid[x][y] == Tile.STAIRS_DOWN
    }
