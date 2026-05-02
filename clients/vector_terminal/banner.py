"""Banner compositing — 7-layer camera-anchored cylinders.

Per `design_banner_compositing` (2026-05-01): seven concentric
wireframe cylinders centered on the camera at factor-of-7 radii.
Each layer carries a role + tint + opacity + distance + height
shipped from the brain in `manifest.banner_layers`.

V1.1 (2026-05-01 evening) — MVP demo mode: render only the OUTERMOST
single layer with a gentle breathing oscillation, so we can isolate
the horizon-cylinder primitive and tune it before adding the inner 6.
Restore full 7-layer rendering by setting `_DEMO_OUTERMOST_ONLY = False`.

The outermost cylinder IS the player's perceptual horizon. Combined
with `playable_radius=0`, this is what makes endless walk feel
endless without truly-infinite-procedural memory cost.

Camera-anchored — cylinders translate 1:1 with the player. They never
grow, never rotate, never move radially. Only their CONTENT (and in
demo mode their alpha) changes per frame.
"""
from __future__ import annotations

import math
from typing import Any

import pyray as rl


# Slices per cylinder. 24 reads smooth in wireframe at typical viewing
# distances; lower values feel polygonal (could be a deliberate
# aesthetic choice later — pin if so).
_SLICES = 24

# Wireframe needs much higher alpha than filled meshes to be visible
# against the black background. 6x boost + a 0.25 floor brings the
# config's 0.02–0.21 range into a 0.25–1.0 visible range. Tint is
# passed through unmodulated — biome identity preserved, only alpha
# amplified for the vector-terminal aesthetic.
_WIREFRAME_ALPHA_BOOST = 6.0
_WIREFRAME_ALPHA_FLOOR = 0.25

# Demo mode: render only the outermost layer (the horizon). Strips the
# inner 6 to isolate the single-cylinder primitive for tuning. Flip to
# False once we're happy with the horizon and ready to layer the inner
# 6 back in with their own roles.
_DEMO_OUTERMOST_ONLY = True

# Breathing oscillation — modulates alpha around its base value to make
# the cylinder feel "alive" (atmospheric, not static geometry). Factor-
# of-7 frequency: 1/7 Hz = ~7-second cycle per `feedback_factor_of_7`.
# Amplitude ±0.20 around 1.0 multiplier gives gentle pulse without
# strobing.
_OSCILLATION_HZ = 1.0 / 7.0
_OSCILLATION_DEPTH = 0.20


def draw_banner_layers(manifest: dict, camera, now: float = 0.0) -> None:
    """Draw banner cylinders camera-anchored. Call AFTER `begin_mode_3d`
    and BEFORE entity rendering so the cylinders visually sit behind /
    around world geometry.

    `now` is monotonic seconds, used for the breathing oscillation.

    Demo mode (`_DEMO_OUTERMOST_ONLY = True`): renders only the
    outermost layer — the perceptual horizon — with alpha breathing.
    Strips the inner 6 layers so we can tune the single primitive.

    Full mode: iterates all layers from manifest.banner_layers. Each
    layer is a dict with `distance`, `height`, `opacity`, `tint`
    (RGB 0-1). Defensive on missing / non-positive values.
    """
    layers: list[dict] = manifest.get("banner_layers") or []
    if not layers:
        return

    cam_x = camera.position.x
    cam_z = camera.position.z

    # Outer → inner for depth-correct any future alpha blending.
    sorted_layers = sorted(
        layers,
        key=lambda L: float(L.get("distance", 0.0)),
        reverse=True,
    )

    if _DEMO_OUTERMOST_ONLY:
        sorted_layers = sorted_layers[:1]

    osc_multiplier = _breathing_alpha_multiplier(now)

    for layer in sorted_layers:
        distance = float(layer.get("distance", 0.0))
        height = float(layer.get("height", 0.0))
        opacity = float(layer.get("opacity", 0.0))
        tint = layer.get("tint") or [0.5, 0.5, 0.5]

        if distance <= 0.0 or height <= 0.0 or opacity <= 0.0:
            continue

        # Apply breathing oscillation to alpha multiplier — gentle pulse
        # makes the cylinder feel atmospheric rather than static.
        modulated_opacity = opacity * osc_multiplier
        color = _layer_color(tint, modulated_opacity)
        position = rl.Vector3(cam_x, 0.0, cam_z)

        # Cylinder rises from y=0 (floor) to y=height. Radius is the
        # layer's distance from camera. Anchored on camera horizontally,
        # so it translates with the player.
        rl.draw_cylinder_wires(
            position,
            distance,
            distance,
            height,
            _SLICES,
            color,
        )


def _breathing_alpha_multiplier(now: float) -> float:
    """Sine-wave alpha pulse around 1.0. Cycle = 1/_OSCILLATION_HZ
    seconds; range = [1 - depth, 1 + depth]. Pure function for
    testability."""
    return 1.0 + _OSCILLATION_DEPTH * math.sin(
        now * 2.0 * math.pi * _OSCILLATION_HZ
    )


def _layer_color(tint: Any, opacity: float) -> tuple[int, int, int, int]:
    """Convert config color (RGB 0-1) + opacity to raylib RGBA bytes.

    Defensive: clamps inputs to [0, 1] in case config drifts.

    Vector-terminal-specific brightness handling: the brain's banner_layers
    config (`biome_data.py`) was authored with Godot's filled-mesh
    rendering in mind, where opacity 0.02 against a colored solid is
    visible. In wireframe lines against a black background, those alphas
    read as invisible. We boost wireframe alpha by `_WIREFRAME_ALPHA_BOOST`
    and apply a floor so even the innermost layer is perceptible.

    Tint passes through unmodulated — the biome's color identity is
    preserved; only alpha is amplified.
    """
    def _byte(v: float) -> int:
        return max(0, min(255, int(round(float(v) * 255))))

    if not isinstance(tint, (list, tuple)) or len(tint) < 3:
        tint = (0.5, 0.5, 0.5)
    boosted_alpha = max(_WIREFRAME_ALPHA_FLOOR, float(opacity) * _WIREFRAME_ALPHA_BOOST)
    return (_byte(tint[0]), _byte(tint[1]), _byte(tint[2]), _byte(boosted_alpha))
