"""biome_elevation — per-biome WFC-driven terrain field."""
from __future__ import annotations

import pytest

from core.systems import biome_elevation


# ── Field shape ─────────────────────────────────────────────────


def test_solve_returns_full_grid():
    field = biome_elevation.solve_elevation_field("cavern", tile_range=2)
    # (2*2+1)² = 25 tiles
    assert len(field) == 25
    for tx, ty in field.keys():
        assert -2 <= tx <= 2
        assert -2 <= ty <= 2


def test_flat_biome_returns_all_same_level():
    field = biome_elevation.solve_elevation_field("workroom", tile_range=2)
    assert len(field) == 25
    assert len(set(field.values())) == 1
    assert next(iter(field.values())) == 0


def test_hub_is_flat():
    field = biome_elevation.solve_elevation_field("hub", tile_range=1)
    assert set(field.values()) == {0}


def test_unknown_biome_falls_back_to_flat():
    field = biome_elevation.solve_elevation_field("phantom", tile_range=2)
    assert set(field.values()) == {0}


# ── Determinism ─────────────────────────────────────────────────


def test_same_biome_and_seed_same_field():
    f1 = biome_elevation.solve_elevation_field("cavern", base_seed=42)
    f2 = biome_elevation.solve_elevation_field("cavern", base_seed=42)
    assert f1 == f2


def test_different_seeds_can_produce_different_fields():
    sigs = set()
    for s in range(8):
        field = biome_elevation.solve_elevation_field("cavern", base_seed=s)
        sigs.add(tuple(sorted(field.items())))
    assert len(sigs) >= 2


# ── Biome-specific behavior ─────────────────────────────────────


def test_cavern_uses_full_level_range():
    """Statistical: 25 tiles × cavern's [0,4] range should hit ≥3
    distinct levels."""
    field = biome_elevation.solve_elevation_field("cavern", base_seed=1)
    distinct_levels = set(field.values())
    assert len(distinct_levels) >= 3


def test_outdoor_smooth_no_large_jumps():
    """Outdoor max_adjacent_diff=1 — no large cliffs."""
    field = biome_elevation.solve_elevation_field("outdoor", base_seed=3)
    for (x, y), v in field.items():
        for nx, ny in [(x+1, y), (x, y+1)]:
            if (nx, ny) in field:
                assert abs(v - field[(nx, ny)]) <= 1, (
                    f"outdoor allowed adjacency diff > 1 at "
                    f"({x},{y})={v} vs ({nx},{ny})={field[(nx,ny)]}"
                )


def test_cavern_can_have_cliffs():
    """Cavern's max_adjacent_diff=4 means we MIGHT see diffs > 1.
    Statistical — try several seeds, at least one should yield a
    cliff somewhere."""
    found_big = False
    for s in range(20):
        field = biome_elevation.solve_elevation_field("cavern", base_seed=s)
        for (x, y), v in field.items():
            for nx, ny in [(x+1, y), (x, y+1)]:
                if (nx, ny) in field and abs(v - field[(nx, ny)]) >= 2:
                    found_big = True
                    break
            if found_big:
                break
        if found_big:
            break
    assert found_big, "cavern should produce SOMETIMES cliffs over 20 seeds"


# ── Tier classification ─────────────────────────────────────────


def test_classify_transition_zero_is_flat():
    assert biome_elevation.classify_transition(0) == "flat"


def test_classify_transition_one_is_step():
    assert biome_elevation.classify_transition(1) == "step"
    assert biome_elevation.classify_transition(-1) == "step"


def test_classify_transition_two_is_ledge():
    assert biome_elevation.classify_transition(2) == "ledge"


def test_classify_transition_three_is_cliff():
    assert biome_elevation.classify_transition(3) == "cliff"


def test_classify_transition_four_plus_is_wall():
    assert biome_elevation.classify_transition(4) == "wall"
    assert biome_elevation.classify_transition(10) == "wall"


# ── floor_z conversion ──────────────────────────────────────────


def test_field_to_floor_z_scales_by_level_height():
    assert biome_elevation.field_to_floor_z(0) == 0.0
    assert biome_elevation.field_to_floor_z(1) == biome_elevation.LEVEL_HEIGHT_M
    assert biome_elevation.field_to_floor_z(3) == 3.0 * biome_elevation.LEVEL_HEIGHT_M


# ── ELEV_TILE_M + helpers (2026-05-17 decouple) ─────────────────


def test_elev_tile_m_is_finer_than_biome_stamp():
    # ELEV_TILE_M (12m) must be much smaller than typical biome stamp
    # tile_size (288m) — that's the whole point of the decouple.
    assert biome_elevation.ELEV_TILE_M < 50.0
    assert biome_elevation.ELEV_TILE_M == 12.0


def test_elev_tile_range_default_covers_visible_radius():
    # Default range × spacing should cover at least cavern fog far.
    r = biome_elevation.ELEV_TILE_RANGE_DEFAULT
    assert r * biome_elevation.ELEV_TILE_M >= 80.0


def test_world_xy_to_elev_tile_at_origin():
    assert biome_elevation.world_xy_to_elev_tile(0.0, 0.0) == (0, 0)


def test_world_xy_to_elev_tile_rounds_to_nearest():
    # Tiles centered on integer*ELEV_TILE_M (12m).
    assert biome_elevation.world_xy_to_elev_tile(11.9, 0.0) == (1, 0)
    assert biome_elevation.world_xy_to_elev_tile(5.9, -23.5) == (0, -2)


def test_world_xy_to_elev_tile_round_trip():
    # Snap a few points back & forth — within tile, coords map to
    # same integer tile.
    for wx, wy in [(0, 0), (3.5, -2.0), (50.0, 100.0), (-30.0, 12.0)]:
        tx, ty = biome_elevation.world_xy_to_elev_tile(wx, wy)
        rx = tx * biome_elevation.ELEV_TILE_M
        ry = ty * biome_elevation.ELEV_TILE_M
        assert biome_elevation.world_xy_to_elev_tile(rx, ry) == (tx, ty)


# ── Description ─────────────────────────────────────────────────


def test_describe_field_counts_transitions():
    field = biome_elevation.solve_elevation_field("cavern", base_seed=1)
    desc = biome_elevation.describe_field(field)
    assert desc["tile_count"] == 25
    assert "transitions" in desc
    assert sum(desc["transitions"].values()) > 0


def test_describe_flat_field_only_flat_transitions():
    field = biome_elevation.solve_elevation_field("hub")
    desc = biome_elevation.describe_field(field)
    assert desc["level_min"] == 0
    assert desc["level_max"] == 0
    assert desc["transitions"]["flat"] > 0
    assert desc["transitions"]["step"] == 0
