"""Client-side per-tile elevation lookup — for floor clamping.

Brain emits `manifest.elevation` with the per-tile level field +
tile_size + level_height_m. This module caches it and exposes
floor_y_at(world_x, world_z) for the FPS controls to clamp the
player's camera Y (raylib_y) to the floor of whatever tile the
player is standing on.

Coords:
  brain (x_lateral, y_forward, z_up)
  raylib (x_right, y_up, z_forward)
  brain.x → raylib.x; brain.y → raylib.z; brain.z → raylib.y

When the player walks onto a higher tile, this returns a higher
floor — camera Y will lerp up automatically via the existing FPS
loop. When they walk off a higher tile, gravity pulls them back
to the new (lower) floor.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ElevationCache:
    """Latest elevation field from manifest. Updated each tick."""
    tile_size:      float = 12.0
    level_height_m: float = 1.0
    field:          dict[tuple[int, int], int] = field(default_factory=dict)
    has_data:       bool = False


def update_from_manifest(cache: ElevationCache, manifest: dict) -> None:
    """Pull elevation block from the manifest and refresh the cache.
    No-op if the manifest doesn't carry an elevation block."""
    elev = manifest.get("elevation")
    if not isinstance(elev, dict):
        return
    tiles_raw = elev.get("tiles") or []
    if not tiles_raw:
        cache.has_data = False
        return
    cache.tile_size      = float(elev.get("tile_size", 12.0))
    cache.level_height_m = float(elev.get("level_height_m", 1.0))
    cache.field = {
        (int(t[0]), int(t[1])): int(t[2])
        for t in tiles_raw
        if isinstance(t, (list, tuple)) and len(t) >= 3
    }
    cache.has_data = True


def floor_y_at(
    cache: ElevationCache,
    raylib_x: float,
    raylib_z: float,
) -> float:
    """Return the raylib-Y floor height under (raylib_x, raylib_z).

    Maps the player's raylib XZ → brain tile coord → level → world Z
    in meters. Raylib Y = brain Z directly (both are vertical-up axis
    after the brain↔raylib swap).

    Defaults to 0.0 when no elevation data is loaded (flat biome).
    """
    if not cache.has_data or not cache.field:
        return 0.0
    # Player's brain coords: brain.x = raylib.x, brain.y = raylib.z
    brain_x = raylib_x
    brain_y = raylib_z
    ts = cache.tile_size or 12.0
    # Tile indices — round to nearest (tiles are centered at integer*ts).
    tx = int(round(brain_x / ts))
    ty = int(round(brain_y / ts))
    level = cache.field.get((tx, ty), 0)
    return float(level) * cache.level_height_m


def tile_level_at(
    cache: ElevationCache,
    raylib_x: float,
    raylib_z: float,
) -> int:
    """Raw integer level under the player. Useful for "am I about to
    step UP / step DOWN / face a wall" decisions in fps_controls."""
    if not cache.has_data or not cache.field:
        return 0
    ts = cache.tile_size or 12.0
    tx = int(round(raylib_x / ts))
    ty = int(round(raylib_z / ts))
    return int(cache.field.get((tx, ty), 0))
