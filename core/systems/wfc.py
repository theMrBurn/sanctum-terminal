"""Wave Function Collapse — minimal constraint-propagation solver.

Generic over any state + adjacency rule. Used by `biome_elevation`
to resolve per-tile elevation levels with tier-based transition
weights (per `feat/biome-greenhouse` elevation extension 2026-05-17).

Algorithm (classic WFC):
  1. Each cell starts in superposition: a set of allowed options.
  2. Pick the lowest-entropy unsolved cell (fewest options remaining).
  3. Collapse it to one option, picked weighted-random from its set.
  4. Propagate: every neighbor's set is intersected with options that
     the adjacency rule allows given this collapse. Recurse on any
     cell whose set actually shrank.
  5. Repeat until every cell has exactly one option (solved) OR a
     cell has zero options (failed — caller retries with new seed).

Pure-Python, no dependencies, no I/O. Deterministic given the same
seed.
"""
from __future__ import annotations

import random
from typing import Callable


# Type aliases
Coord = tuple[int, int]
OptionSet = set[int]
AdjacencyFn = Callable[[int, int], bool]
# AdjacencyFn(a, b) → True if option `a` may be adjacent to option `b`.


# ── Generic grid solver ───────────────────────────────────────────


class WFCError(RuntimeError):
    """Raised when WFC failed (a cell collapsed to zero options).
    Caller can retry with a different seed."""


def solve_grid(
    width:       int,
    height:      int,
    options:     list[int],
    adjacency:   AdjacencyFn,
    weights:     dict[int, float] | None = None,
    seed:        int = 0,
    max_retries: int = 16,
) -> dict[Coord, int]:
    """Solve a width × height grid where each cell picks one option.

    Returns {(x, y): chosen_option} for every cell. Raises WFCError
    after `max_retries` attempts.

    `adjacency(a, b)` must be symmetric for correct propagation.
    `weights[option]` biases random collapse picks; missing entries
    default to 1.0. Zero weight means "never collapse to this option
    unless it's the only one left."
    """
    if not options:
        raise ValueError("WFC: options list must be non-empty")

    base_weights = {int(o): float(weights.get(o, 1.0)) if weights else 1.0
                    for o in options}

    last_err: Exception | None = None
    for attempt in range(max_retries):
        rng = random.Random((seed << 8) ^ attempt)
        try:
            return _solve_once(width, height, options, adjacency,
                                 base_weights, rng)
        except WFCError as exc:
            last_err = exc
            continue
    raise WFCError(
        f"WFC failed after {max_retries} attempts; last error: {last_err}"
    )


def _solve_once(
    width:     int,
    height:    int,
    options:   list[int],
    adjacency: AdjacencyFn,
    weights:   dict[int, float],
    rng:       random.Random,
) -> dict[Coord, int]:
    """One WFC pass. Raises WFCError on contradiction."""
    # Initial state: every cell has every option.
    grid: dict[Coord, OptionSet] = {
        (x, y): set(options)
        for x in range(width) for y in range(height)
    }

    total_cells = width * height
    solved = 0

    while solved < total_cells:
        # 1. Pick lowest-entropy unsolved cell.
        target: Coord | None = None
        best_entropy = float("inf")
        for cell, opts in grid.items():
            n = len(opts)
            if n <= 1:
                continue
            if n < best_entropy:
                best_entropy = n
                target = cell
        if target is None:
            break       # everything's solved (every cell |opts| == 1)

        # 2. Collapse to one weighted-random option.
        opts = list(grid[target])
        opt_weights = [max(0.0001, weights.get(o, 1.0)) for o in opts]
        chosen = rng.choices(opts, weights=opt_weights, k=1)[0]
        grid[target] = {chosen}

        # 3. Propagate.
        _propagate(grid, target, adjacency, width, height)

        # 4. Recount solved cells (propagation may collapse more).
        solved = sum(1 for opts in grid.values() if len(opts) == 1)

    # Result: every cell has exactly one option.
    result: dict[Coord, int] = {}
    for cell, opts in grid.items():
        if len(opts) != 1:
            raise WFCError(
                f"cell {cell} ended with {len(opts)} options "
                f"(should be 1) — adjacency rules over-constrained"
            )
        result[cell] = next(iter(opts))
    return result


def _propagate(
    grid:      dict[Coord, OptionSet],
    seed_cell: Coord,
    adjacency: AdjacencyFn,
    width:     int,
    height:    int,
) -> None:
    """Constraint propagation from `seed_cell` outward. Each neighbor's
    option set is intersected with options the adjacency rule permits
    given some option of `seed_cell`. If a neighbor's set shrinks,
    propagate from it too.

    Raises WFCError if any cell collapses to zero options."""
    stack: list[Coord] = [seed_cell]
    while stack:
        cell = stack.pop()
        cell_opts = grid[cell]
        for neighbor in _neighbors(cell, width, height):
            neighbor_opts = grid[neighbor]
            if len(neighbor_opts) <= 1:
                continue        # already solved; can't shrink further
            # Compute which options the neighbor COULD be given cell's
            # current options.
            allowed: OptionSet = set()
            for cell_opt in cell_opts:
                for n_opt in neighbor_opts:
                    if adjacency(cell_opt, n_opt):
                        allowed.add(n_opt)
                        # Optimization: if we've already covered all
                        # neighbor's options, no need to keep checking.
                        if len(allowed) == len(neighbor_opts):
                            break
                if len(allowed) == len(neighbor_opts):
                    break
            if not allowed:
                raise WFCError(
                    f"propagation eliminated all options at {neighbor} "
                    f"(after collapsing {cell})"
                )
            if allowed != neighbor_opts:
                grid[neighbor] = allowed
                stack.append(neighbor)


def _neighbors(cell: Coord, width: int, height: int) -> list[Coord]:
    """4-connectivity (N/E/S/W) neighbors of a cell."""
    x, y = cell
    out: list[Coord] = []
    if x > 0:
        out.append((x - 1, y))
    if x < width - 1:
        out.append((x + 1, y))
    if y > 0:
        out.append((x, y - 1))
    if y < height - 1:
        out.append((x, y + 1))
    return out
