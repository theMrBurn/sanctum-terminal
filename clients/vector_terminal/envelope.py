"""Playable envelope clamp — port of godot/main.gd:5386-5405.

Brain ships `playable_envelope.radius` and `playable_envelope.softness`.
Soft pushback nudges the player back when outside the radius, with
softness controlling pushback rate; a hard clamp catches anyone still
outside after the pushback step.
"""
from __future__ import annotations

import math


def clamp_to_envelope(
    x: float,
    z: float,
    radius: float,
    softness: float,
    dt: float,
) -> tuple[float, float]:
    """Return new (x, z) after envelope pushback + hard clamp.

    Operates on the horizontal plane only (vertical y stays untouched).
    Brain envelope is centered at world origin per the manifest contract.
    """
    if radius <= 0.0:
        return x, z
    dist = math.hypot(x, z)
    if dist <= radius:
        return x, z
    overshoot = dist - radius
    pushback = overshoot * softness * dt
    inv_d = 1.0 / dist
    new_x = x - x * inv_d * pushback
    new_z = z - z * inv_d * pushback
    new_dist = math.hypot(new_x, new_z)
    if new_dist > radius:
        scale = radius / new_dist
        new_x *= scale
        new_z *= scale
    return new_x, new_z
