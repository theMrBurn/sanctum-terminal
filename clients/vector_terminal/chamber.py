"""Chamber wireframe renderer — 12-edge cube outline for volley_chamber.

Reads `manifest["chamber"]` (origin + size + color) and draws the cube
edges as wireframe lines in 3D. Standalone module so future make-brains
that need similar architectural shells can compose against the same
primitive.

Per `.claude/feature/feat_make-brain-ping-pong.md` PR 3.
"""
from __future__ import annotations

import pyray as rl


def _color_from(rgb: list | None) -> "rl.Color":
    if not rgb:
        return rl.Color(140, 158, 184, 255)
    r = int(max(0.0, min(1.0, float(rgb[0] if len(rgb) > 0 else 0.5))) * 255)
    g = int(max(0.0, min(1.0, float(rgb[1] if len(rgb) > 1 else 0.6))) * 255)
    b = int(max(0.0, min(1.0, float(rgb[2] if len(rgb) > 2 else 0.7))) * 255)
    return rl.Color(r, g, b, 255)


def render(manifest: dict) -> None:
    """Draw the chamber's 12 cube edges. No-op if manifest has no chamber."""
    chamber = manifest.get("chamber")
    if not chamber:
        return

    size = chamber.get("size") or [12.0, 12.0, 12.0]
    origin = chamber.get("origin") or [0.0, 0.0, 0.0]
    color = _color_from(chamber.get("color"))

    # Brain space: x lateral, y forward, z up. Origin is bottom-center;
    # cube spans [-sx/2, +sx/2] in x, [-sy/2, +sy/2] in y, [0, sz] in z.
    sx, sy, sz = float(size[0]), float(size[1]), float(size[2])
    ox, oy, oz = float(origin[0]), float(origin[1]), float(origin[2])

    half_x = sx / 2.0
    half_y = sy / 2.0
    z_lo = oz
    z_hi = oz + sz

    # 8 corners. Brain (x, y, z) → raylib (x, z_up, y_forward).
    # Corner = (raylib x, raylib y, raylib z) for rl.Vector3.
    def V(bx, by, bz):
        return rl.Vector3(ox + bx, bz, oy + by)

    c000 = V(-half_x, -half_y, z_lo)   # bottom: back-left
    c100 = V( half_x, -half_y, z_lo)   # bottom: back-right
    c110 = V( half_x,  half_y, z_lo)   # bottom: front-right
    c010 = V(-half_x,  half_y, z_lo)   # bottom: front-left
    c001 = V(-half_x, -half_y, z_hi)   # top: back-left
    c101 = V( half_x, -half_y, z_hi)   # top: back-right
    c111 = V( half_x,  half_y, z_hi)   # top: front-right
    c011 = V(-half_x,  half_y, z_hi)   # top: front-left

    # 12 edges: 4 bottom, 4 top, 4 verticals
    rl.draw_line_3d(c000, c100, color)
    rl.draw_line_3d(c100, c110, color)
    rl.draw_line_3d(c110, c010, color)
    rl.draw_line_3d(c010, c000, color)

    rl.draw_line_3d(c001, c101, color)
    rl.draw_line_3d(c101, c111, color)
    rl.draw_line_3d(c111, c011, color)
    rl.draw_line_3d(c011, c001, color)

    rl.draw_line_3d(c000, c001, color)
    rl.draw_line_3d(c100, c101, color)
    rl.draw_line_3d(c110, c111, color)
    rl.draw_line_3d(c010, c011, color)
