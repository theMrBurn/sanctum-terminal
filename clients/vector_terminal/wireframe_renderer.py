"""Wireframe mesh renderer — pure edge iteration.

Per `core/systems/wireframe_mesh.py`: WireframeMesh is vertices +
edges. This module renders one by walking the edges and calling
draw_line_3d for each. Position + uniform scale only in V1; rotation
is a future add (matrix transform of vertices before edge draw).

Same renderer handles built-in primitives (cube, tetrahedron, etc.)
AND OBJ-loaded meshes — they're the same data structure.

Optional `skin` argument routes per-edge rendering through a profile
function from `core.systems.edge_skins`. Skin functions operate on
mesh-local coordinates and may emit multiple colored sub-segments per
edge; the renderer transforms each sub-segment back into world space.
Skipping the skin path keeps the original solid-color fast path.
"""
from __future__ import annotations

import pyray as rl

from core.systems.edge_skins import SkinFn
from core.systems.wireframe_mesh import WireframeMesh


def draw_wireframe(
    mesh: WireframeMesh,
    position: tuple[float, float, float],
    scale: float,
    color: tuple[int, int, int, int],
    skin: SkinFn | None = None,
    time: float = 0.0,
    seed: int = 0,
) -> None:
    """Render `mesh` at `position` with uniform `scale`. `color` is
    raylib RGBA (used as fallback when `skin` is None).

    With `skin` supplied, each edge is handed to the skin function in
    mesh-local coordinates; the returned sub-segments are transformed
    to world coords and drawn individually. `time` and `seed` are
    forwarded to the skin so it can drift / desync.
    """
    px, py, pz = position
    verts = mesh.vertices
    for (a_idx, b_idx) in mesh.edges:
        local_a = verts[a_idx]
        local_b = verts[b_idx]
        if skin is None:
            v_a = rl.Vector3(
                px + local_a[0] * scale,
                py + local_a[1] * scale,
                pz + local_a[2] * scale,
            )
            v_b = rl.Vector3(
                px + local_b[0] * scale,
                py + local_b[1] * scale,
                pz + local_b[2] * scale,
            )
            rl.draw_line_3d(v_a, v_b, color)
            continue

        for (s_a, s_b, s_color) in skin(local_a, local_b, time, seed):
            v_a = rl.Vector3(
                px + s_a[0] * scale,
                py + s_a[1] * scale,
                pz + s_a[2] * scale,
            )
            v_b = rl.Vector3(
                px + s_b[0] * scale,
                py + s_b[1] * scale,
                pz + s_b[2] * scale,
            )
            rl.draw_line_3d(v_a, v_b, s_color)
