"""Tests for core.systems.ascii_render.render_view.

Contract:
    Given an entity list, camera (cam_x, cam_y), viewing radius in tiles,
    and a kind→char map, return a list of rows (strings). Player is drawn
    as '@' at the exact center. Entities place by rounding (x-cam_x,
    y-cam_y) to the nearest tile. Brain's +Y is grid "north" = row 0.
    Priority: when multiple entities occupy the same tile, the one with
    the larger collision_radius wins.

    Pure function. Deterministic.
"""
from __future__ import annotations

import pytest

from core.systems.ascii_render import render_view


FLOOR = "."
PLAYER = "@"


def _ent(kind: str, x: float, y: float, r: float = 1.0) -> dict:
    return {"kind": kind, "x": x, "y": y, "collision_radius": r}


def test_empty_world_player_centered():
    grid = render_view([], 0.0, 0.0, radius=3, kind_chars={})
    assert len(grid) == 7
    assert all(len(row) == 7 for row in grid)
    assert grid[3][3] == PLAYER
    # Every other cell is floor.
    for r, row in enumerate(grid):
        for c, ch in enumerate(row):
            if (r, c) != (3, 3):
                assert ch == FLOOR, f"cell ({r},{c})={ch!r} should be floor"


def test_entity_north_of_player():
    """Entity at world (0, 3): 3m +Y means 3 rows above player (rows are
    north-to-south, so lower index = more north)."""
    grid = render_view(
        [_ent("boulder", 0.0, 3.0)], 0.0, 0.0, radius=5,
        kind_chars={"boulder": "o"},
    )
    # Player at row 5, col 5. Boulder 3 rows up = row 2.
    assert grid[2][5] == "o"
    assert grid[5][5] == PLAYER


def test_entity_south_of_player():
    grid = render_view(
        [_ent("boulder", 0.0, -3.0)], 0.0, 0.0, radius=5,
        kind_chars={"boulder": "o"},
    )
    # 3m -Y = 3 rows south (higher row index).
    assert grid[8][5] == "o"


def test_entity_east_of_player():
    grid = render_view(
        [_ent("boulder", 4.0, 0.0)], 0.0, 0.0, radius=5,
        kind_chars={"boulder": "o"},
    )
    # +X is east = higher column.
    assert grid[5][9] == "o"


def test_entity_out_of_radius_not_drawn():
    grid = render_view(
        [_ent("boulder", 10.0, 0.0)], 0.0, 0.0, radius=5,
        kind_chars={"boulder": "o"},
    )
    for row in grid:
        assert "o" not in row


def test_camera_translation():
    """Camera offset shifts the view — entity at world (10, 10) with
    camera at (10, 10) draws at center? No: player IS the camera, so
    (10, 10) is where the player sits; entity there would underneath @."""
    grid = render_view(
        [_ent("boulder", 11.0, 10.0)], 10.0, 10.0, radius=3,
        kind_chars={"boulder": "o"},
    )
    # Camera at (10, 10). Boulder at (11, 10) = +1 east.
    assert grid[3][4] == "o"


def test_priority_by_collision_radius():
    """Two entities same tile: larger collision_radius wins."""
    grid = render_view(
        [
            _ent("grass", 0.0, 2.0, r=0.0),
            _ent("boulder", 0.0, 2.0, r=2.5),
        ],
        0.0, 0.0, radius=5,
        kind_chars={"grass": ",", "boulder": "o"},
    )
    assert grid[3][5] == "o"


def test_unknown_kind_falls_back_to_question_mark():
    grid = render_view(
        [_ent("mystery", 1.0, 0.0)], 0.0, 0.0, radius=3,
        kind_chars={},  # empty map
    )
    assert grid[3][4] == "?"


def test_grid_size_scales_with_radius():
    """radius=10 → 21 × 21 grid."""
    grid = render_view([], 0.0, 0.0, radius=10, kind_chars={})
    assert len(grid) == 21
    assert all(len(row) == 21 for row in grid)
    assert grid[10][10] == PLAYER


def test_player_never_overwritten_by_entity_at_same_tile():
    """Even if an entity sits exactly under the player's tile, '@' is
    preserved — the player is the frame of reference."""
    grid = render_view(
        [_ent("boulder", 0.0, 0.0, r=5.0)], 0.0, 0.0, radius=3,
        kind_chars={"boulder": "o"},
    )
    assert grid[3][3] == PLAYER


def test_pure_function_determinism():
    ents = [_ent("boulder", 1.0, 2.0)]
    a = render_view(ents, 0.0, 0.0, radius=5, kind_chars={"boulder": "o"})
    b = render_view(ents, 0.0, 0.0, radius=5, kind_chars={"boulder": "o"})
    assert a == b
