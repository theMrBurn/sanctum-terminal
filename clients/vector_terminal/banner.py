"""Banner compositing — 7-layer camera-anchored cylinders.

Per `design_banner_compositing` (2026-05-01): seven concentric
wireframe cylinders centered on the camera at factor-of-7 radii.
Each layer carries a role + tint + opacity + distance + height
shipped from the brain in `manifest.banner_layers`.

V1 renders STATIC wireframe cylinders only — sells the structural
illusion of bounded perception. Per-role renderers (silhouettes
projected from far entities, lighthouse beacons, foreground particles,
HUD migration) layer on as the design pin's role table fills in.

The outermost cylinder IS the player's perceptual horizon. Combined
with `playable_radius=0`, this is what makes endless walk feel
endless without truly-infinite-procedural memory cost.

Camera-anchored — cylinders translate 1:1 with the player. They never
grow, never rotate, never move radially. Only their CONTENT changes
(in V1: nothing; in V2+: per-role projections).
"""
from __future__ import annotations

from typing import Any

import pyray as rl


# Slices per cylinder. 24 reads smooth in wireframe at typical viewing
# distances; lower values feel polygonal (could be a deliberate
# aesthetic choice later — pin if so).
_SLICES = 24


def draw_banner_layers(manifest: dict, camera) -> None:
    """Draw all banner cylinders camera-anchored. Call AFTER
    `begin_mode_3d` and BEFORE entity rendering so the cylinders
    visually sit behind / around world geometry.

    Reads layer config from `manifest.banner_layers`. Each layer is a
    dict with `distance`, `height`, `opacity`, `tint` (RGB 0-1).
    Layers with non-positive distance / height / opacity are skipped
    (defensive — shouldn't happen in production config).

    No-op when manifest has no banner_layers key (older brains, tests).
    """
    layers: list[dict] = manifest.get("banner_layers") or []
    if not layers:
        return

    cam_x = camera.position.x
    cam_z = camera.position.z

    # Iterate outer → inner so any future alpha-blending is depth-correct.
    sorted_layers = sorted(
        layers,
        key=lambda L: float(L.get("distance", 0.0)),
        reverse=True,
    )

    for layer in sorted_layers:
        distance = float(layer.get("distance", 0.0))
        height = float(layer.get("height", 0.0))
        opacity = float(layer.get("opacity", 0.0))
        tint = layer.get("tint") or [0.5, 0.5, 0.5]

        if distance <= 0.0 or height <= 0.0 or opacity <= 0.0:
            continue

        color = _layer_color(tint, opacity)
        position = rl.Vector3(cam_x, 0.0, cam_z)

        # Cylinder rises from y=0 (floor) to y=height. Radius is the
        # layer's distance from camera. Anchored on camera horizontally,
        # so it translates with the player.
        rl.draw_cylinder_wires(
            position,
            distance,  # radius_top
            distance,  # radius_bottom (cylindrical, not conical)
            height,
            _SLICES,
            color,
        )


def _layer_color(tint: Any, opacity: float) -> tuple[int, int, int, int]:
    """Convert config color (RGB 0-1) + opacity to raylib RGBA bytes.
    Defensive: clamps inputs to [0, 1] in case config drifts."""
    def _byte(v: float) -> int:
        return max(0, min(255, int(round(float(v) * 255))))

    if not isinstance(tint, (list, tuple)) or len(tint) < 3:
        tint = (0.5, 0.5, 0.5)
    return (_byte(tint[0]), _byte(tint[1]), _byte(tint[2]), _byte(opacity))
