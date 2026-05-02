"""Regression test for terrain_height vs entity-placement alignment.

Pre-fix (before 2026-05-01):
  terrain_height did `lx = (x - origin) % tile_size` with origin=(0,0).
  At world (0, 0) — which is the tile (0, 0) center under the entity
  placement convention — that read cell (0, 0) of the macro stamp,
  the CORNER. Stamps authored with center-cell features had those
  features land on tile boundaries instead of tile centers.

Post-fix:
  Self-derives tile (tx, ty) from (x, y) using the same convention as
  `_tile_key`, then maps to local coords lx, ly ∈ [0, tile_size). Tile
  centers (world coords (tx*ts, ty*ts)) read stamp center (lx=ly=ts/2).

These tests pin the alignment + the tile-invariance of the stamp.
"""
from __future__ import annotations

import math

from core.systems.macro_stamp import (
    grid_elevation,
    set_active_stamp,
    terrain_height,
)


# A test stamp where elevation = row + col, so the cell read is
# trivially identifiable from the output.
_TEST_STAMP = {
    "elevation": [[r + c for c in range(7)] for r in range(7)],
    "elevation_step": 1.0,
    "density":   [[1.0] * 7 for _ in range(7)],
    "allowed":   [["ALL"] * 7 for _ in range(7)],
}


def _setup():
    set_active_stamp(_TEST_STAMP, tile_size=288.0, origin=(0.0, 0.0))


# ── Tile-center reads stamp center ────────────────────────────────


def test_tile_zero_center_reads_stamp_center():
    """World (0, 0) is the center of tile (0, 0). It should read the
    macro stamp's center cell (3, 3) → elevation 3+3=6."""
    _setup()
    z = terrain_height(0.0, 0.0)
    # Bilinear interpolation may produce a slightly off-integer; we
    # care that it's near 6, not at the corners (0 or 12).
    assert 5.0 < z < 7.0, f"expected ~6 at tile center, got {z}"


def test_tile_one_center_reads_stamp_center():
    """World (288, 0) is the center of tile (1, 0). Same stamp center
    cell (3, 3) → same ~6 elevation."""
    _setup()
    z = terrain_height(288.0, 0.0)
    assert 5.0 < z < 7.0, f"expected ~6 at next tile center, got {z}"


def test_negative_tile_center():
    """World (-288, 0) is tile (-1, 0) center → also stamp center."""
    _setup()
    z = terrain_height(-288.0, 0.0)
    assert 5.0 < z < 7.0


def test_diagonal_tile_centers_match():
    """All tile centers read the same stamp-center elevation, regardless
    of which tile."""
    _setup()
    z00 = terrain_height(0.0, 0.0)
    z11 = terrain_height(288.0, 288.0)
    z_neg = terrain_height(-576.0, 288.0)
    assert abs(z00 - z11) < 1e-3
    assert abs(z00 - z_neg) < 1e-3


# ── Tile-corner reads stamp corner ────────────────────────────────


def test_tile_corner_reads_stamp_corner():
    """World (-144, -144) is the corner of tile (0, 0). It should read
    near cell (0, 0) → elevation 0."""
    _setup()
    z = terrain_height(-144.0, -144.0)
    assert -0.1 < z < 1.0, f"expected ~0 at tile corner (0,0 cell), got {z}"


def test_tile_opposite_corner():
    """World (143.99, 143.99) — just inside tile (0, 0)'s far corner.
    Reads near cell (6, 6) → elevation 12."""
    _setup()
    z = terrain_height(143.99, 143.99)
    # Bilinear may interpolate; expect close to 12 but allow for floor/clamp.
    assert z > 9.0, f"expected high elevation near far corner, got {z}"


# ── Tile invariance ───────────────────────────────────────────────


def test_stamp_pattern_repeats_per_tile():
    """The macro stamp tiles across the world (per
    `design_spawn_macro_stamp`). Position-relative-to-tile-center is
    the only thing that matters for elevation."""
    _setup()
    # Same offset from tile center across multiple tiles.
    z_offset_in_tile_0 = terrain_height(50.0, 50.0)         # tile (0, 0)
    z_offset_in_tile_1 = terrain_height(50.0 + 288.0, 50.0)  # tile (1, 0)
    z_offset_in_tile_neg = terrain_height(50.0 - 288.0, 50.0)  # tile (-1, 0)
    assert abs(z_offset_in_tile_0 - z_offset_in_tile_1) < 1e-3
    assert abs(z_offset_in_tile_0 - z_offset_in_tile_neg) < 1e-3


# ── Self-derivation: ignores legacy global origin ─────────────────


def test_terrain_height_ignores_legacy_origin_arg():
    """The pre-fix `_active_tile_origin` is now vestigial — terrain_height
    self-derives the tile. Setting a non-zero origin should NOT change
    output (back-compat: the setter still accepts the param)."""
    set_active_stamp(_TEST_STAMP, tile_size=288.0, origin=(0.0, 0.0))
    z_default = terrain_height(0.0, 0.0)

    # Even if a legacy caller passes a weird origin, output stays correct.
    set_active_stamp(_TEST_STAMP, tile_size=288.0, origin=(999.0, -42.0))
    z_with_origin = terrain_height(0.0, 0.0)
    assert abs(z_default - z_with_origin) < 1e-3


# ── No active stamp ───────────────────────────────────────────────


def test_no_active_stamp_returns_zero():
    """When no stamp is set, terrain_height returns flat ground (0)."""
    set_active_stamp(None, tile_size=288.0)
    assert terrain_height(0.0, 0.0) == 0.0
    assert terrain_height(100.0, 200.0) == 0.0


# ── Cross-reference: matches _tile_key convention ─────────────────


def test_terrain_height_tile_assignment_matches_tile_key():
    """The (tx, ty) computed inside terrain_height must agree with
    TileExchange._tile_key. Otherwise we'd reintroduce the
    coordinate-mismatch class of bug."""
    from core.systems.tile_exchange import TileExchange

    ex = TileExchange(biome_name="outdoor", base_seed=42, tile_size=288.0)
    ts = 288.0
    half = ts / 2.0

    test_positions = [
        (0.0, 0.0),
        (200.0, 0.0),
        (-200.0, 0.0),
        (143.0, 0.0),
        (144.0, 0.0),
        (288.0, 288.0),
        (-100.0, 500.0),
    ]
    for x, y in test_positions:
        # _tile_key
        tx_key, ty_key = ex._tile_key(x, y)
        # terrain_height's internal derivation (replicated here)
        tx_th = math.floor((x + half) / ts)
        ty_th = math.floor((y + half) / ts)
        assert (tx_key, ty_key) == (tx_th, ty_th), (
            f"tile_key/terrain_height disagreement at ({x}, {y}): "
            f"key={(tx_key, ty_key)} vs th={(tx_th, ty_th)}"
        )
