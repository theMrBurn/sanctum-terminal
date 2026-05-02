"""Silhouette projection — entities at distance render as flat shapes
on the matching banner cylinder.

Per `design_banner_layer_taxonomy` (2026-05-02): entities in render
shells 4+ (radius ≥ 35m) project as silhouettes onto the banner
cylinder at their angular position from the camera. The cylinder
distance overrides the entity's actual distance — the silhouette
sits "on the horizon" at a fixed depth that matches the cylinder.

This is the LOD transition that makes object-exchange-between-layers
work. Entity walks closer → its `render_shell` decreases → eventually
crosses into "geometry" mode and gets the full wireframe treatment.
The same world entity, two rendering paths gated by distance.

V1 silhouette: a vertical line at the entity's angular position on
the matching cylinder, height proportional to entity scale, color
biased toward dark to read as "thing on horizon."
"""
from __future__ import annotations

import math
from typing import Optional

import pyray as rl

from clients.vector_terminal import config as cfg


# Brain ships entities with `render_shell` index. Map shell index to
# the cylinder distance to project onto. These mirror RENDER_SHELLS
# radii in `core/systems/biome_data.py:2125` — keep in sync.
_SHELL_RADII = (7.0, 14.0, 21.0, 28.0, 35.0, 42.0, 49.0)


# Silhouettes are rendered darker than the entity's natural color so
# they read as "distant, thing-shape" rather than "nearby thing."
_SILHOUETTE_DARKEN = 0.4


# Hint mode (between geometry and silhouette) renders even fainter.
_HINT_DARKEN = 0.2


def draw_silhouette(ent: dict, camera, mode: str = "silhouette") -> None:
    """Project entity onto its assigned banner cylinder as a flat shape.

    `mode` is the entity's render_mode field — usually "silhouette" or
    "hint". Atmosphere mode entities are skipped entirely (caller should
    not invoke this for atmosphere).

    Reads `ent.render_shell` to pick the cylinder distance. Falls back
    to the entity's actual distance if shell is missing (defensive).
    """
    cam_x = camera.position.x
    cam_z = camera.position.z

    ex = float(ent.get("x", 0.0))
    ey = float(ent.get("y", 0.0))  # brain y, raylib z

    shell_idx = ent.get("render_shell")
    cyl_radius = _radius_for_shell(shell_idx, cam_x, cam_z, ex, ey)
    if cyl_radius <= 0.0:
        return

    # Angular position from camera in horizontal plane.
    dx = ex - cam_x
    dy = ey - cam_z
    dist = math.hypot(dx, dy)
    if dist < 1e-6:
        return  # entity at camera — degenerate, skip

    # Project onto cylinder at the same azimuth.
    inv_d = 1.0 / dist
    proj_x = cam_x + dx * inv_d * cyl_radius
    proj_z = cam_z + dy * inv_d * cyl_radius

    # Silhouette height — proportional to entity's z-scale so big things
    # read as tall on the horizon.
    sz = float(ent.get("sz", 1.0))
    base_h = float(ent.get("z", 0.0))
    silh_top = base_h + sz * 1.5  # rough silhouette height

    # Color: entity's natural color, darkened for silhouette / hint.
    r = float(ent.get("r", 0.5))
    g = float(ent.get("g", 0.5))
    b = float(ent.get("b", 0.5))
    factor = _HINT_DARKEN if mode == "hint" else _SILHOUETTE_DARKEN
    color = (
        max(0, min(255, int(r * factor * 255))),
        max(0, min(255, int(g * factor * 255))),
        max(0, min(255, int(b * factor * 255))),
        255,
    )

    # Vertical line marking the entity's silhouette on the cylinder.
    rl.draw_line_3d(
        rl.Vector3(proj_x, base_h, proj_z),
        rl.Vector3(proj_x, silh_top, proj_z),
        color,
    )


def _radius_for_shell(
    shell_idx: Optional[int],
    cam_x: float,
    cam_z: float,
    ex: float,
    ey: float,
) -> float:
    """Map shell index to cylinder radius. Falls back to actual distance
    if shell is missing or invalid."""
    if isinstance(shell_idx, int) and 0 <= shell_idx < len(_SHELL_RADII):
        return _SHELL_RADII[shell_idx]
    # Fallback — use actual distance, clamped to outermost shell.
    actual = math.hypot(ex - cam_x, ey - cam_z)
    return min(actual, _SHELL_RADII[-1])
