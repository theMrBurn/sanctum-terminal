"""Top-level engine orchestration.

Wires GridNode (where am I) + primitive_for_depth (what does it look
like) + Camera (how do I see it) + WorldState (what did the player
change) into a single `render(node, camera) -> Iterator[DrawLine]`.

The engine is *stateless apart from the WorldState ledger*. Two callers
holding the same GridNode + Camera + WorldState get byte-identical
output. That's what "seed-deterministic" means in practice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from grid_node import GRID_SIZE, GridNode
from primitives import (
    AMBER,
    Camera,
    DIM,
    DrawLine,
    GREEN,
    Vec3,
    VectorGeometry,
    faceted_sphere,
    primitive_for_depth,
    stream_geometry,
    wireframe_cube,
    wireframe_walls,
)
from world_state import WorldState


@dataclass
class FractalEngine:
    state: WorldState = field(default_factory=WorldState)

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    def move(self, node: GridNode, dx: int, dy: int) -> GridNode:
        """Translate within the *current* depth's grid.

        Scale invariance directive: this function does NOT know what
        depth it's at. dx/dy are tile-units; the renderer is the one
        that scales them via node.world_scale(). Identical math at
        depth=0 and depth=3.
        """
        if not node.path:
            # Root node has no parent context — moving "within" the
            # galaxy at depth=0 just rebinds path to the chosen tile.
            return node.child(_clamp(dx, 0, GRID_SIZE - 1), _clamp(dy, 0, GRID_SIZE - 1))
        last = node.path[-1]
        new_x = _clamp(last.x + dx, 0, GRID_SIZE - 1)
        new_y = _clamp(last.y + dy, 0, GRID_SIZE - 1)
        if (new_x, new_y) == (last.x, last.y):
            return node
        # Pop current tile, descend into new one from the *parent's* seed.
        parent_seed = node.path[-1] if False else None  # placeholder
        # Reconstruct parent: its seed must be one whose child(last.x,
        # last.y) hashes to node.seed. We don't have that — but we can
        # treat node.path as authoritative and re-derive from a
        # synthesized parent seed (same trick as GridNode.parent).
        from grid_node import derive_seed
        parent_seed_real = derive_seed(node.seed, last.x, last.y, node.depth - 1)
        from grid_node import Coord
        new_path = node.path[:-1] + (Coord(new_x, new_y),)
        new_seed = derive_seed(parent_seed_real, new_x, new_y, node.depth)
        return GridNode(seed=new_seed, depth=node.depth, path=new_path)

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self, node: GridNode, camera: Camera) -> Iterator[DrawLine]:
        """Emit a DrawLine stream for the given node + camera.

        Floating-origin rule: all geometry is positioned relative to
        the *node's* center (the world's local origin), not absolute
        world coords. Vertex magnitudes stay bounded.
        """
        # 1. The substrate grid (depth-appropriate primitive).
        base = primitive_for_depth(node.depth)
        yield from stream_geometry(base, Vec3(0, 0, 0), 1.0, camera)

        # 2. Per-tile glyphs from procedural generation.
        for tile_geom, origin in self._procedural_glyphs(node):
            yield from stream_geometry(tile_geom, origin, 1.0, camera)

        # 3. Player-driven deltas overlay last.
        for delta in self.state.get(node):
            geom, origin = self._delta_glyph(node, delta)
            if geom is not None:
                yield from stream_geometry(geom, origin, 1.0, camera)

    # ------------------------------------------------------------------
    # Procedural glyph picking
    # ------------------------------------------------------------------

    def _procedural_glyphs(self, node: GridNode) -> Iterator[tuple[VectorGeometry, Vec3]]:
        """Walk the 10x10 grid; emit a glyph per tile based on its sub-seed.

        Cheap deterministic noise: hash (node.seed, x, y) → 0..1. We
        only spawn when noise > threshold so the world isn't a dense
        forest of cubes.
        """
        from grid_node import derive_seed

        cell = 1.0 / GRID_SIZE
        half = 0.5 - cell * 0.5
        for x in range(GRID_SIZE):
            for y in range(GRID_SIZE):
                seed = derive_seed(node.seed, x, y, node.depth + 1)
                # Take 4 bytes → [0, 1).
                roll = (seed & 0xFFFFFFFF) / 0xFFFFFFFF
                if roll < 0.65:
                    continue
                origin = Vec3(-half + x * cell, 0.0, -half + y * cell)
                glyph = self._glyph_for(node.depth, roll)
                yield glyph, origin

    def _glyph_for(self, depth: int, roll: float) -> VectorGeometry:
        if depth <= 0:
            return faceted_sphere(radius=0.03, rings=3, segments=5)
        if depth == 1:
            return faceted_sphere(radius=0.025, rings=3, segments=5)
        if depth == 2:
            return wireframe_cube(size=0.06)
        return wireframe_walls(size=0.08, height=0.04)

    def _delta_glyph(
        self, node: GridNode, delta
    ) -> tuple[VectorGeometry | None, Vec3]:
        if delta.tile is None:
            return None, Vec3(0, 0, 0)
        cell = 1.0 / GRID_SIZE
        half = 0.5 - cell * 0.5
        x, y = delta.tile
        origin = Vec3(-half + x * cell, 0.02, -half + y * cell)
        if delta.kind == "place":
            geom = wireframe_cube(size=0.07)
        elif delta.kind == "remove":
            # Removed glyph = a dim X — render as a degenerate "empty"
            # marker so the player can see "I cleared this".
            geom = VectorGeometry(
                edges=(
                    (Vec3(-0.03, 0, -0.03), Vec3(0.03, 0, 0.03)),
                    (Vec3(-0.03, 0, 0.03), Vec3(0.03, 0, -0.03)),
                ),
                color=DIM,
            )
        else:
            geom = faceted_sphere(radius=0.025, rings=3, segments=5)
        return geom, origin


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))
