"""strike_renderer — visualizes in-flight ARPG combat Strikes.

Per `feat_arpg-combat.md` PR 2 (SHOT). Reads `manifest.active_strikes`
and renders ball + trail per Strike. SHOT mode is the V1 path (ball
flies in straight-ish line under physics).

PR 6 (visual polish) extends per-mode:
- SHOT: ball + trail (this PR)
- HELD: weapon mesh + impact glow
- WHIP: ball + chain segments
- Multi-Strike z-ordering

For V1 simplicity each mode shares one render path here — a small
sphere wireframe at the strike's current position with intensity
modulated by `distance_fade.intensity`. PR 6 splits into per-mode
helpers.
"""
from __future__ import annotations

from typing import Any

import pyray as rl

from clients.vector_terminal import config as cfg
from clients.vector_terminal import distance_fade


# Strike ball — small wireframe sphere, slightly larger than the
# physical hitbox to read at distance.
_RENDER_RADIUS_SCALE = 1.2
_RENDER_SLICES       = 8


def draw_strikes(manifest: dict[str, Any], camera) -> None:
    """Draw all active strikes from the manifest. Call inside
    `begin_mode_3d` so spheres composite with world geometry.

    Each strike entry must carry `x/y/z` (current position),
    `ball_radius`, `mode`, `weapon_kind`. Color follows the
    vector-terminal amber phosphor identity, intensity dimmed by
    distance via `distance_fade`.
    """
    strikes: list[dict[str, Any]] = manifest.get("active_strikes") or []
    if not strikes:
        return

    cam_x = camera.position.x
    cam_y = camera.position.y
    cam_z = camera.position.z

    for s in strikes:
        try:
            x = float(s.get("x", 0.0))
            y = float(s.get("y", 0.0))
            z = float(s.get("z", 0.0))
            r = float(s.get("ball_radius", 0.3))
        except (TypeError, ValueError):
            continue

        # Brain emits y=forward, z=up. raylib renders xz-floor + y-up,
        # so swap y↔z for the visual position. Same convention as ball.py.
        pos = rl.Vector3(x, z, y)

        # Distance from camera for phosphor intensity.
        # Camera position is in raylib coords (y=up); recompute distance
        # in raylib space directly.
        dx = pos.x - cam_x
        dy = pos.y - cam_y
        dz = pos.z - cam_z
        dist = (dx * dx + dy * dy + dz * dz) ** 0.5

        intensity = distance_fade.intensity(dist)
        amber = (
            int(cfg.AMBER_RGB[0] * intensity),
            int(cfg.AMBER_RGB[1] * intensity),
            int(cfg.AMBER_RGB[2] * intensity),
            255,
        )

        # Wireframe sphere — small ball.
        render_r = r * _RENDER_RADIUS_SCALE
        rl.draw_sphere_wires(pos, render_r, _RENDER_SLICES, _RENDER_SLICES, amber)
