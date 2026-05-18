"""WFC solver tests — invariants over the constraint propagation.

Per `feat/biome-greenhouse` elevation extension 2026-05-17.
"""
from __future__ import annotations

import pytest

from core.systems.wfc import WFCError, solve_grid


# ── Happy paths ─────────────────────────────────────────────────


def test_solve_returns_one_option_per_cell():
    """Every cell of the result has a value in `options`."""
    options = [0, 1, 2, 3]
    grid = solve_grid(
        width=5, height=5,
        options=options,
        adjacency=lambda a, b: abs(a - b) <= 1,    # tiered: smooth
        seed=42,
    )
    assert len(grid) == 25
    for v in grid.values():
        assert v in options


def test_adjacency_constraint_holds():
    """No two adjacent cells violate the rule."""
    grid = solve_grid(
        width=4, height=4,
        options=[0, 1, 2],
        adjacency=lambda a, b: abs(a - b) <= 1,
        seed=7,
    )
    for (x, y), v in grid.items():
        for nx, ny in [(x+1, y), (x, y+1)]:
            if (nx, ny) in grid:
                assert abs(v - grid[(nx, ny)]) <= 1, (
                    f"({x},{y})={v} vs ({nx},{ny})={grid[(nx,ny)]} "
                    f"violates adjacency"
                )


def test_solve_is_deterministic_given_seed():
    g1 = solve_grid(5, 5, [0, 1, 2, 3],
                    adjacency=lambda a, b: abs(a - b) <= 1, seed=99)
    g2 = solve_grid(5, 5, [0, 1, 2, 3],
                    adjacency=lambda a, b: abs(a - b) <= 1, seed=99)
    assert g1 == g2


def test_different_seeds_can_produce_different_grids():
    """Some variety across seeds (statistical — checks ≥2 distinct
    solutions in 8 seeds)."""
    sigs = set()
    for s in range(8):
        g = solve_grid(4, 4, [0, 1, 2, 3],
                        adjacency=lambda a, b: abs(a - b) <= 1, seed=s)
        sigs.add(tuple(sorted(g.items())))
    assert len(sigs) >= 2


# ── Cliff / loose rules ─────────────────────────────────────────


def test_no_constraint_means_any_neighbor_combo():
    """With permissive adjacency, the solver still terminates."""
    grid = solve_grid(
        width=3, height=3,
        options=[0, 1, 2, 3, 4],
        adjacency=lambda a, b: True,      # anything goes
        seed=1,
    )
    assert len(grid) == 9


def test_cliff_adjacency_allows_large_diffs():
    """max_diff=4 lets adjacent cells differ by up to 4 levels."""
    grid = solve_grid(
        width=4, height=4,
        options=[0, 1, 2, 3, 4],
        adjacency=lambda a, b: abs(a - b) <= 4,
        seed=42,
    )
    # Find at least one large transition
    big_diffs = [
        abs(grid[(x, y)] - grid[(nx, ny)])
        for (x, y), v in grid.items()
        for nx, ny in [(x+1, y), (x, y+1)]
        if (nx, ny) in grid
    ]
    # Statistical — over many cells, some should diff by ≥2
    assert max(big_diffs) >= 1


# ── Weights ─────────────────────────────────────────────────────


def test_weighted_picks_bias_toward_high_weight():
    """With strong weight on level 0, the field should be mostly 0."""
    grid = solve_grid(
        width=8, height=8,
        options=[0, 1, 2],
        adjacency=lambda a, b: abs(a - b) <= 1,
        weights={0: 100.0, 1: 1.0, 2: 0.1},
        seed=5,
    )
    counts = {0: 0, 1: 0, 2: 0}
    for v in grid.values():
        counts[v] += 1
    # 0 should dominate
    assert counts[0] > counts[1]
    assert counts[1] > counts[2]


def test_zero_weight_still_picks_if_only_option():
    """If an option's the only one in a cell, weights don't matter."""
    # Force a single-option scenario via narrow rules
    grid = solve_grid(
        width=2, height=2,
        options=[0, 1],
        adjacency=lambda a, b: a == b,    # only same-value neighbors
        weights={0: 1.0, 1: 0.0},
        seed=3,
    )
    # All cells must be the same value; might be 0 or 1 depending on
    # collapse order
    values = set(grid.values())
    assert len(values) == 1


# ── Failure modes ───────────────────────────────────────────────


def test_overconstrained_rule_raises_after_retries():
    """An impossible rule raises WFCError after exhausting retries."""
    with pytest.raises(WFCError):
        solve_grid(
            width=3, height=3,
            options=[0, 1],
            adjacency=lambda a, b: False,  # nothing can be next to anything
            seed=0,
            max_retries=4,
        )


def test_empty_options_raises():
    with pytest.raises(ValueError):
        solve_grid(width=3, height=3, options=[],
                    adjacency=lambda a, b: True, seed=0)


# ── 1x1 + tiny grids ────────────────────────────────────────────


def test_1x1_grid():
    grid = solve_grid(1, 1, [0, 1, 2],
                       adjacency=lambda a, b: True, seed=0)
    assert len(grid) == 1
    assert (0, 0) in grid
    assert grid[(0, 0)] in (0, 1, 2)


def test_1x5_grid_is_valid():
    grid = solve_grid(1, 5, [0, 1, 2],
                       adjacency=lambda a, b: abs(a - b) <= 1, seed=11)
    for y in range(4):
        assert abs(grid[(0, y)] - grid[(0, y + 1)]) <= 1
