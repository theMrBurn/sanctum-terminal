"""Playable envelope — soft pushback toward origin when player strays
outside the biome's bounded-play radius.

The cavern (and every biome built on the stamp_world grid) is formally
infinite — slots extend forever, content thins past the authored anchors.
Wall planes are cosmetic (see memory project_walls_are_cosmetic.md); they
do not collide. Without an envelope, clipping past any obstacle lets the
player wander unbounded.

This module is the pure-function envelope: given position + radius +
softness, return an XZ pushback vector. Godot applies the vector each
physics frame after collision resolution so the boundary reads as a
gentle drift back, not a wall.

Brain owns radius/softness per-biome via BIOME_REGISTRY. Godot reads
from manifest.
"""
from __future__ import annotations

import math
from typing import Tuple


def compute_envelope_pushback(x: float, y: float, radius: float,
                              softness: float = 1.0) -> Tuple[float, float]:
    """Return XZ pushback vector (dx, dy) nudging the player toward
    origin when outside `radius`. Zero inside (including exactly on the
    boundary). Linear falloff past radius, scaled by `softness`.

    Math:
        dist     = hypot(x, y)
        overshoot = max(0, dist - radius)
        magnitude = overshoot * softness
        direction = (-x / dist, -y / dist)
        pushback  = direction * magnitude

    Defensive: radius < 0 is treated as zero-pushback (misconfigured).
    At origin (dist == 0), direction is undefined → zero pushback.
    """
    if radius < 0.0:
        return 0.0, 0.0
    dist = math.hypot(x, y)
    if dist <= radius:
        return 0.0, 0.0
    if dist <= 0.0:
        return 0.0, 0.0
    overshoot = dist - radius
    magnitude = overshoot * softness
    inv_dist = 1.0 / dist
    return (-x * inv_dist * magnitude, -y * inv_dist * magnitude)


def clamp_to_envelope(x: float, y: float, radius: float) -> Tuple[float, float]:
    """Hard clamp — any (x, y) outside `radius` snaps onto the boundary
    along its original direction from origin. Inside or exactly on the
    boundary = passthrough. Complements compute_envelope_pushback: the
    pushback gives the soft drift feel, the clamp is the absolute
    guarantee that FOV never crosses the boundary.

    Defensive: radius < 0 → passthrough (misconfigured). radius = 0
    collapses any non-origin position to origin.
    """
    if radius < 0.0:
        return x, y
    dist = math.hypot(x, y)
    if dist <= radius:
        return x, y
    if dist <= 0.0:
        return x, y
    scale = radius / dist
    return x * scale, y * scale
