"""Continuous terrain height field — rolling elevation for any biome.

Single function: terrain_height(x, y) -> float
Returns elevation offset in meters. Used by:
  - brain_server: entity z placement (entities sit ON the terrain)
  - Godot main.gd: camera Y (player walks ON the terrain)

Same function, same seed, same values — brain and viewer always agree.
Low-frequency layered noise. No cliffs, no sudden drops. Oblivion-style
gentle rolling hills that create sightlines and hidden valleys.
"""

import math

# Config-as-code: tune these to change the feel of the terrain.
# amplitude: max elevation offset in meters (±)
# wavelength: horizontal distance of one full undulation in meters
# octaves: noise layers (1=smooth rolling, 3=more varied, 4=complex)
TERRAIN_CONFIG = {
    "amplitude": 3.0,      # ±3m — enough to hide/reveal objects over a hill
    "wavelength": 60.0,    # broad undulations, Oblivion-scale
    "octaves": 2,          # smooth + one detail layer
}


def _hash2d(x: float, y: float) -> float:
    """Deterministic pseudo-random hash for 2D coordinates."""
    return (math.sin(x * 127.1 + y * 311.7) * 43758.5453) % 1.0


def _noise2d(x: float, y: float) -> float:
    """Value noise with smooth interpolation."""
    ix, iy = int(math.floor(x)), int(math.floor(y))
    fx, fy = x - ix, y - iy
    # Smoothstep
    fx = fx * fx * (3.0 - 2.0 * fx)
    fy = fy * fy * (3.0 - 2.0 * fy)
    a = _hash2d(ix, iy)
    b = _hash2d(ix + 1, iy)
    c = _hash2d(ix, iy + 1)
    d = _hash2d(ix + 1, iy + 1)
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy


def terrain_height(x: float, y: float) -> float:
    """Return terrain elevation at world position (x, y).

    Layered value noise at decreasing wavelengths. Each octave adds finer
    detail at half the amplitude. Result is bounded by ±amplitude.
    """
    amp = TERRAIN_CONFIG["amplitude"]
    wl = TERRAIN_CONFIG["wavelength"]
    octaves = TERRAIN_CONFIG["octaves"]

    total = 0.0
    current_amp = amp
    current_wl = wl

    for _ in range(octaves):
        nx = x / current_wl
        ny = y / current_wl
        # noise2d returns 0-1, center to -0.5..+0.5
        total += (_noise2d(nx, ny) - 0.5) * 2.0 * current_amp
        current_amp *= 0.5
        current_wl *= 0.5

    # Clamp to configured amplitude
    return max(-amp, min(amp, total))
