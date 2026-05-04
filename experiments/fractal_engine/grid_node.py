"""Recursive grid topology for the Unified Fractal Engine.

The whole world is a stack of 10x10 grids. A "node" at any depth is
identified by its parent seed plus its coordinate in the parent grid.
Children are generated lazily and deterministically from a sub-seed.

Depth 0 = Galaxy        (10x10 of solar systems)
Depth 1 = Solar System  (10x10 of overworld regions)
Depth 2 = Overworld     (10x10 of dungeons)
Depth 3 = Dungeon Floor (10x10 of rooms / tiles)

Beyond depth 3 we keep recursing — there is no hardcoded floor — but
the primitive resolver caps its visual mapping there. New depth tiers
are a config-as-code problem, not an engine problem.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional

GRID_SIZE = 10  # 10x10 tiles per node, by directive.

# Each step "down" into a child compresses world units by this factor.
# A tile at depth=d is 1/SCALE_PER_LEVEL^d world units across.
SCALE_PER_LEVEL = 10.0


# ---------------------------------------------------------------------------
# Deterministic seed hashing
# ---------------------------------------------------------------------------


def derive_seed(parent_seed: int, x: int, y: int, depth: int) -> int:
    """Hash (parent_seed, x, y, depth) → child seed.

    Using sha256 instead of Python's hash() because hash() is salted per
    process, which would break determinism across runs. We want
    "same seed everywhere, forever."
    """
    payload = f"{parent_seed}:{x}:{y}:{depth}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    # 64-bit unsigned int is plenty for child seeds and stays JSON-safe.
    return int.from_bytes(digest[:8], "big")


# ---------------------------------------------------------------------------
# GridNode
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Coord:
    """Tile coordinate within a parent grid (0..GRID_SIZE-1)."""

    x: int
    y: int

    def in_bounds(self) -> bool:
        return 0 <= self.x < GRID_SIZE and 0 <= self.y < GRID_SIZE


@dataclass(frozen=True)
class GridNode:
    """A 10x10 region at a given recursion depth.

    `seed` is the deterministic identifier — two GridNodes with the
    same seed describe the same region, anywhere in the call graph.

    `path` is the chain of (x, y) coords from the root. It's used as
    the WorldState ledger key so deltas survive zoom-in/zoom-out.
    """

    seed: int
    depth: int = 0
    path: tuple[Coord, ...] = field(default_factory=tuple)

    # ------------------------------------------------------------------
    # Recursion
    # ------------------------------------------------------------------

    def child(self, x: int, y: int) -> "GridNode":
        """Zoom IN: pick tile (x, y) and generate a sub-grid from it."""
        coord = Coord(x, y)
        if not coord.in_bounds():
            raise ValueError(f"Coord {coord} outside {GRID_SIZE}x{GRID_SIZE} grid")
        return GridNode(
            seed=derive_seed(self.seed, x, y, self.depth + 1),
            depth=self.depth + 1,
            path=self.path + (coord,),
        )

    def parent(self, x: int, y: int) -> "GridNode":
        """Zoom OUT: nest *this* grid into tile (x, y) of a NEW parent.

        We don't store back-pointers — there's no canonical parent. Going
        out is itself a generative act: you choose where this grid sits
        in the next layer up. The ledger key tells you whether you've
        been somewhere before.
        """
        if self.depth == 0:
            raise ValueError("Already at root depth (galaxy); cannot zoom out further")
        coord = Coord(x, y)
        if not coord.in_bounds():
            raise ValueError(f"Coord {coord} outside {GRID_SIZE}x{GRID_SIZE} grid")
        # The parent's seed has to be one whose child(x, y) hashes back
        # to *this* node's seed. There's no inverse for sha256, so the
        # honest answer is: we generate a fresh parent seed and treat
        # the child slot at (x, y) as authoritative for *this* subtree.
        # This matches roguelike "leave the dungeon" semantics: the
        # overworld outside is procedurally regenerated, but the
        # dungeon you came from stays intact via WorldState.
        parent_path = self.path[:-1] if self.path else ()
        parent_seed = derive_seed(self.seed, x, y, self.depth - 1)
        return GridNode(seed=parent_seed, depth=self.depth - 1, path=parent_path)

    def transition_level(self, direction: str, x: int = 0, y: int = 0) -> "GridNode":
        """Single entry point: 'in' or 'out'.

        Direction 'in' requires (x, y) — which tile to descend into.
        Direction 'out' takes (x, y) — which slot the current grid
        should occupy in its newly-generated parent.
        """
        if direction == "in":
            return self.child(x, y)
        if direction == "out":
            return self.parent(x, y)
        raise ValueError(f"unknown direction {direction!r}; expected 'in' or 'out'")

    # ------------------------------------------------------------------
    # Scale / floating origin
    # ------------------------------------------------------------------

    def world_scale(self) -> float:
        """Local world units per tile at this depth.

        At depth=0 a tile is 1.0 wide; at depth=3 a tile is 1e-3 wide.
        Renderers use this to size primitives consistently — but the
        camera always works in *local* space, so vertices stay in a
        sane numeric range regardless of depth.
        """
        return SCALE_PER_LEVEL ** (-self.depth)

    def ledger_key(self) -> str:
        """Stable string key for WorldState.

        Format: G[x,y].S[x,y].O[x,y].D[x,y]... — one segment per depth.
        """
        prefixes = ("G", "S", "O", "D", "R", "X", "Y", "Z")
        parts = []
        for i, coord in enumerate(self.path):
            tag = prefixes[i] if i < len(prefixes) else f"L{i}"
            parts.append(f"{tag}[{coord.x},{coord.y}]")
        return ".".join(parts) if parts else "ROOT"
