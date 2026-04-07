"""Macro stamp 7x7 grid — tile-level composition + elevation.

Each tile selects a macro stamp pattern. The 7x7 grid divides the tile
into 49 cells. Each cell defines:
  - elevation: integer height step (0=floor, 1=+step, 2=+2*step, -1=pit)
  - density: multiplier for entity spawn density in this cell
  - allowed: shorthand for which kind classes can spawn here

The grid replaces _radial_factor() and the noise terrain function.
Same function signatures, data-driven from config.

Elevation is interpolated between cell centers for smooth transitions.
No cliffs — adjacent cells differ by at most 1 step.
"""

import math

# Shorthand expansion for allowed kind classes
_ALLOWED_EXPAND = {
    "S":    {"structural"},
    "E":    {"emissive"},
    "G":    {"ground_cover"},
    "A":    {"atmosphere"},
    "L":    {"life"},
    "X":    {"scatter"},
    "SE":   {"structural", "emissive"},
    "SA":   {"structural", "atmosphere"},
    "SG":   {"structural", "ground_cover"},
    "SEG":  {"structural", "emissive", "ground_cover"},
    "SEGA": {"structural", "emissive", "ground_cover", "atmosphere"},
    "ALL":  {"structural", "emissive", "ground_cover", "atmosphere", "scatter", "life"},
}

# Global config — mirrors the old terrain_height module interface
TERRAIN_CONFIG = {
    "amplitude": 6.0,       # max elevation (2 steps * 3m)
    "elevation_step": 3.0,  # meters per grid elevation unit
}

# Active macro stamp — set by brain_server when tile is generated
_active_stamp = None
_active_tile_size = 288.0
_active_tile_origin = (0.0, 0.0)  # world-space origin of the active tile


def set_active_stamp(stamp, tile_size=288.0, origin=(0.0, 0.0)):
    """Set the macro stamp used by terrain_height().

    Called by brain_server when generating the spawn tile.
    """
    global _active_stamp, _active_tile_size, _active_tile_origin
    _active_stamp = stamp
    _active_tile_size = tile_size
    _active_tile_origin = origin


def grid_cell(x, y, tile_size=288.0):
    """Map world-space position to grid (row, col) indices.

    x, y are local to the tile (0..tile_size).
    Returns (row, col) clamped to 0..6.
    """
    cell_size = tile_size / 7.0
    col = int(x / cell_size)
    row = int(y / cell_size)
    col = max(0, min(6, col))
    row = max(0, min(6, row))
    return row, col


def grid_elevation(stamp, x, y, tile_size=288.0):
    """Return elevation in meters at position (x, y) within a tile.

    Reads the grid cell and multiplies by elevation_step.
    Interpolates between cell centers for smooth slopes.
    """
    step = stamp.get("elevation_step", TERRAIN_CONFIG["elevation_step"])
    cell_size = tile_size / 7.0

    # Continuous cell coordinates (fractional)
    cx = x / cell_size - 0.5
    cy = y / cell_size - 0.5

    # Bilinear interpolation between four nearest cell centers
    ix = int(math.floor(cx))
    iy = int(math.floor(cy))
    fx = cx - ix
    fy = cy - iy

    # Smoothstep for organic feel
    fx = fx * fx * (3.0 - 2.0 * fx)
    fy = fy * fy * (3.0 - 2.0 * fy)

    def _elev(r, c):
        r = max(0, min(6, r))
        c = max(0, min(6, c))
        return stamp["elevation"][r][c]

    e00 = _elev(iy, ix)
    e10 = _elev(iy, ix + 1)
    e01 = _elev(iy + 1, ix)
    e11 = _elev(iy + 1, ix + 1)

    e = e00 + (e10 - e00) * fx + (e01 - e00) * fy + (e00 - e10 - e01 + e11) * fx * fy
    return round(e * step, 2)


def grid_density(stamp, x, y, tile_size=288.0):
    """Return density multiplier at position (x, y) within a tile."""
    row, col = grid_cell(x, y, tile_size)
    return stamp["density"][row][col]


def grid_allowed(stamp, x, y, tile_size=288.0):
    """Return set of allowed kind classes at position (x, y)."""
    row, col = grid_cell(x, y, tile_size)
    code = stamp["allowed"][row][col]
    return _ALLOWED_EXPAND.get(code, _ALLOWED_EXPAND["ALL"])


def terrain_height(x, y):
    """Drop-in replacement for the noise terrain_height.

    If a macro stamp is active, reads elevation from the grid.
    Otherwise returns 0.0 (flat).
    """
    if _active_stamp is None:
        return 0.0

    # Convert world coords to tile-local coords
    ox, oy = _active_tile_origin
    lx = x - ox
    ly = y - oy

    # Wrap to tile bounds (handles walking across tile boundaries)
    ts = _active_tile_size
    lx = lx % ts
    ly = ly % ts

    return grid_elevation(_active_stamp, lx, ly, ts)
