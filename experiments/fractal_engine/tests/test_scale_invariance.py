"""Scale invariance: 1 unit at depth 3 and depth 0 use the same move() logic.

This is the load-bearing property of the whole engine. If movement
math diverges between depths, the "everything is a grid" promise is
broken.
"""

import pytest

from engine import FractalEngine
from grid_node import GRID_SIZE, GridNode


@pytest.fixture
def engine():
    return FractalEngine()


def test_move_dx_dy_translates_one_tile_at_every_depth(engine):
    """A (+1, 0) move shifts the path by exactly one tile, regardless of depth."""
    root = GridNode(seed=42, depth=0)

    # Build a chain root → depth 1 → depth 2 → depth 3, parking at (1, 1) each level.
    deep = root.child(1, 1).child(1, 1).child(1, 1)
    assert deep.depth == 3

    moved = engine.move(deep, 1, 0)
    assert moved.path[-1].x == 2
    assert moved.path[-1].y == 1

    # Now do the same move at depth 1.
    shallow = root.child(1, 1)
    moved_shallow = engine.move(shallow, 1, 0)
    assert moved_shallow.path[-1].x == 2
    assert moved_shallow.path[-1].y == 1

    # Tile delta is identical even though world_scale differs by 100x.
    assert deep.world_scale() != pytest.approx(shallow.world_scale())


def test_move_clamps_at_grid_edges(engine):
    node = GridNode(seed=1, depth=0).child(0, 0)
    # Cannot move off the left edge.
    same = engine.move(node, -1, 0)
    assert same.path[-1].x == 0


def test_move_changes_seed_deterministically(engine):
    node = GridNode(seed=99, depth=0).child(3, 3)
    a = engine.move(node, 1, 0)
    b = engine.move(node, 1, 0)
    assert a.seed == b.seed  # determinism
    c = engine.move(node, 0, 1)
    assert a.seed != c.seed   # but distinct neighbors get distinct seeds


def test_world_scale_decreases_geometrically_with_depth():
    n0 = GridNode(seed=0, depth=0)
    n1 = n0.child(1, 1)
    n2 = n1.child(1, 1)
    n3 = n2.child(1, 1)
    assert n0.world_scale() == pytest.approx(1.0)
    assert n1.world_scale() == pytest.approx(0.1)
    assert n2.world_scale() == pytest.approx(0.01)
    assert n3.world_scale() == pytest.approx(0.001)


def test_full_grid_movement_round_trip(engine):
    """Walking 9 east then 9 west returns the same tile coord."""
    node = GridNode(seed=7, depth=0).child(0, 0)
    cur = node
    for _ in range(9):
        cur = engine.move(cur, 1, 0)
    assert cur.path[-1].x == 9
    for _ in range(9):
        cur = engine.move(cur, -1, 0)
    assert cur.path[-1].x == 0


def test_grid_size_is_ten():
    """Sanity: the directive says 10x10 means 10x10."""
    assert GRID_SIZE == 10
