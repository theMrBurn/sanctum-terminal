"""Tile-key vs entity-placement alignment — regression for the
"blank world past origin stamp" bug fixed 2026-05-01.

Before the fix:
- `_tile_key(cam) = (floor(cam.x/tile_size), floor(cam.y/tile_size))`
- entity placement = `lx - half + tx * tile_size` → tile (tx, ty)
  entities CENTERED on (tx*tile_size, ty*tile_size)

These two diverge by half a tile. At cam_y=200 (half a tile past
spawn in y), `_tile_key` returned (0, 0) but the tile whose entities
were actually around the camera is (0, 1). The visibility margin
check on tile_cx=(tx+0.5)*tile_size compounded the offset, skipping
exactly the tile the player needed.

These tests pin both sides of the fix:
  1. _tile_key picks the tile whose center is closest to cam
  2. tile_cx/cy in get_entities matches entity placement (no +0.5)
"""
from __future__ import annotations

from core.systems.tile_exchange import TileExchange


# ── _tile_key — closest-center semantics ──────────────────────────


def _make_exchange():
    """A throwaway exchange — just need an instance to call _tile_key.
    Boot is mostly side-effect free for that path."""
    # `outdoor` biome is fully populated in BIOME_REGISTRY; cavern works too.
    return TileExchange(biome_name="outdoor", base_seed=42, tile_size=288.0)


def test_tile_key_origin():
    ex = _make_exchange()
    assert ex._tile_key(0.0, 0.0) == (0, 0)


def test_tile_key_inside_tile_zero():
    ex = _make_exchange()
    # Anywhere within ±144 of (0, 0) is in tile (0, 0).
    assert ex._tile_key(50.0, 50.0) == (0, 0)
    assert ex._tile_key(-50.0, -50.0) == (0, 0)
    assert ex._tile_key(143.0, 0.0) == (0, 0)
    assert ex._tile_key(0.0, -143.0) == (0, 0)


def test_tile_key_crosses_to_neighbor_at_half_tile():
    """The bug-trigger position: cam_y=200 should land in tile (0, 1)
    because tile (0, 1) centered at y=288 is closer than tile (0, 0)
    centered at y=0 (88 vs 200). Pre-fix this returned (0, 0)."""
    ex = _make_exchange()
    assert ex._tile_key(0.0, 200.0) == (0, 1)


def test_tile_key_negative_axis():
    ex = _make_exchange()
    # cam_y=-200 is closer to tile (0, -1) center (-288) than tile (0, 0).
    assert ex._tile_key(0.0, -200.0) == (0, -1)


def test_tile_key_at_tile_boundary():
    """Boundary x=144 is in tile (1, 0) per entity placement
    (tile (1, 0) covers x ∈ [144, 432))."""
    ex = _make_exchange()
    assert ex._tile_key(144.0, 0.0) == (1, 0)


def test_tile_key_well_into_neighbor():
    ex = _make_exchange()
    assert ex._tile_key(300.0, 0.0) == (1, 0)
    assert ex._tile_key(0.0, 300.0) == (0, 1)
    assert ex._tile_key(500.0, 500.0) == (2, 2)


# ── Tile center used by margin check ──────────────────────────────


def test_tile_center_uses_no_half_offset():
    """Confirms the tile_cx/tile_cy formula in get_entities matches
    entity placement: tile (tx, ty) centered at (tx*tile_size,
    ty*tile_size). Reads source rather than calling get_entities to
    avoid spinning up the whole exchange + scoring path.

    Positive-form check only — the buggy `(tx + 0.5)` literal can
    appear in regression-history comments so the negative match
    would be brittle.
    """
    import inspect
    source = inspect.getsource(TileExchange.get_entities)
    assert "tile_cx = tx * self.tile_size" in source
    assert "tile_cy = ty * self.tile_size" in source


# ── End-to-end: walking past origin stamp returns entities ─────────


def test_walking_past_origin_does_not_blank_world():
    """The user-visible regression: at cam_y > 144 (half-tile past
    spawn), brain returned 0 entities. Verifies that after the fix,
    cam at (0, 200) sees entities (assuming the tile generates).

    This test instantiates a real TileExchange and queries get_entities.
    If the bug regresses, this test returns 0 entities at distance.
    """
    ex = _make_exchange()
    # Boot generated tile (0, 0). For cam at (0, 200), we need tile (0, 1).
    # First call to get_entities triggers prefetch which generates it.
    ents_at_origin = ex.get_entities(
        cam_x=0.0, cam_y=0.0, cam_z=2.0,
        heading=0.0, vel_x=0.0, vel_y=0.0,
    )
    # Sanity: spawn tile has content.
    assert len(ents_at_origin) > 0

    # Tick a few times so prefetch fills surrounding tiles. Each call
    # generates `tiles_per_frame` (default 2) tiles. After N calls we
    # have plenty of cached tiles around the origin.
    for _ in range(30):
        ex.get_entities(
            cam_x=0.0, cam_y=0.0, cam_z=2.0,
            heading=0.0, vel_x=0.0, vel_y=0.0,
        )

    # Now move camera to cam_y=200 — half a tile past origin in y.
    # Pre-fix this returned 0 because tile (0, 1) was incorrectly
    # skipped by the margin check. Post-fix it should return entities.
    ents_past_boundary = ex.get_entities(
        cam_x=0.0, cam_y=200.0, cam_z=2.0,
        heading=0.0, vel_x=0.0, vel_y=1.0,
    )
    assert len(ents_past_boundary) > 0, (
        "cam at (0, 200) returned 0 entities — the half-tile alignment "
        "bug has regressed. See test_tile_key_alignment.py docstring."
    )
