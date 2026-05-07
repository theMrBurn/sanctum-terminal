"""Ball wireframe renderer.

Reads `manifest["ball"]` ({exists, x, y, z, vx, vy, vz, radius, color})
and draws the active ball as a wireframe sphere. No-op when the manifest
has no ball key or `exists` is false.

Per `.claude/feature/feat_make-brain-ping-pong.md` PR 4.
"""
from __future__ import annotations

import pyray as rl


# Brain emits position in brain space (x lateral, y forward, z up).
# Raylib's Vector3 is (x_right, y_up, z_forward). Conversion:
#     raylib.x = brain.x
#     raylib.y = brain.z
#     raylib.z = brain.y


def _color_from(rgb: list | None) -> "rl.Color":
    if not rgb:
        return rl.Color(240, 240, 80, 255)        # default: high-vis yellow
    r = int(max(0.0, min(1.0, float(rgb[0] if len(rgb) > 0 else 0.95))) * 255)
    g = int(max(0.0, min(1.0, float(rgb[1] if len(rgb) > 1 else 0.95))) * 255)
    b = int(max(0.0, min(1.0, float(rgb[2] if len(rgb) > 2 else 0.30))) * 255)
    return rl.Color(r, g, b, 255)


def render(manifest: dict) -> None:
    """Draw the ball wireframe sphere. Silent no-op when no ball."""
    ball = manifest.get("ball")
    if not ball or not ball.get("exists"):
        return
    bx = float(ball.get("x", 0.0))
    by = float(ball.get("y", 0.0))
    bz = float(ball.get("z", 0.0))
    radius = float(ball.get("radius", 0.15))
    color = _color_from(ball.get("color"))

    center = rl.Vector3(bx, bz, by)              # brain → raylib coord swap
    # Wireframe sphere — rl.draw_sphere_wires(center, radius, rings, slices, color).
    # 8 rings × 12 slices is enough fidelity to read as round at game distances
    # without overdrawing edges.
    rl.draw_sphere_wires(center, radius, 8, 12, color)
