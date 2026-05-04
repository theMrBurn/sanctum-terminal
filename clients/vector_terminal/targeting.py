"""Crosshair raycast — find the entity at the player's reticle.

Pure function. Camera position + normalized forward + entity list →
the entity intersected by the ray within max_range, or None. Uses each
entity's collision_radius (or a heuristic default) as the hit radius
in 3D space.
"""
from __future__ import annotations

import math


def entity_at_crosshair(
    cam_x: float, cam_y: float, cam_z: float,
    fx: float, fy: float, fz: float,
    entities: list[dict],
    max_range: float,
    radius_default: float,
) -> dict | None:
    """Return the closest entity intersected by the look ray (in XZ), or None.

    Entities are treated as vertical cylinders for targeting — pitch is
    ignored. Looking forward and tapping F targets whichever entity sits
    in your XZ direction within max_range. This matches FPS-game user
    instinct where ground-level objects don't require looking down.
    """
    fxz = math.hypot(fx, fz)
    if fxz < 1e-6:
        return None  # camera looking straight up/down — no XZ direction
    fx2d = fx / fxz
    fz2d = fz / fxz

    best: dict | None = None
    best_t = max_range
    for ent in entities:
        ex = float(ent.get("x", 0.0))
        ez = float(ent.get("y", 0.0))   # raylib Z from manifest Y
        dx = ex - cam_x
        dz = ez - cam_z
        t = dx * fx2d + dz * fz2d
        if t <= 0.0 or t >= best_t:
            continue
        px = cam_x + fx2d * t
        pz = cam_z + fz2d * t
        perp = math.hypot(ex - px, ez - pz)
        radius = float(ent.get("collision_radius", 0.0)) or radius_default
        if perp <= radius:
            best = ent
            best_t = t
    return best
