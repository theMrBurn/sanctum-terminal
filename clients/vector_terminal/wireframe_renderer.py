"""Wireframe mesh renderer — pure edge iteration.

Per `core/systems/wireframe_mesh.py`: WireframeMesh is vertices +
edges. This module renders one by walking the edges and calling
draw_line_3d for each. Position + uniform scale only in V1; rotation
is a future add (matrix transform of vertices before edge draw).

Same renderer handles built-in primitives (cube, tetrahedron, etc.)
AND OBJ-loaded meshes — they're the same data structure.
"""
from __future__ import annotations

import pyray as rl

from core.systems.wireframe_mesh import WireframeMesh


def draw_wireframe(
    mesh: WireframeMesh,
    position: tuple[float, float, float],
    scale: float,
    color: tuple[int, int, int, int],
) -> None:
    """Render `mesh` at `position` with uniform `scale`. `color` is
    raylib RGBA.

    Each edge becomes a 3D line. Performance scales with edge_count *
    `draw_line_3d` cost — fine for tens of meshes per frame at typical
    edge counts (cubes ≈12, OBJ assets typically <500).
    """
    px, py, pz = position
    verts = mesh.vertices
    for (a_idx, b_idx) in mesh.edges:
        ax, ay, az = verts[a_idx]
        bx, by, bz = verts[b_idx]
        v_a = rl.Vector3(px + ax * scale, py + ay * scale, pz + az * scale)
        v_b = rl.Vector3(px + bx * scale, py + by * scale, pz + bz * scale)
        rl.draw_line_3d(v_a, v_b, color)
