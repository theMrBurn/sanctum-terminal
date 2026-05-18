"""terrain.py — client-side elevation cache."""
from __future__ import annotations

from clients.vector_terminal import terrain


def test_empty_cache_returns_zero():
    cache = terrain.ElevationCache()
    assert terrain.floor_y_at(cache, 0, 0) == 0.0
    assert terrain.tile_level_at(cache, 0, 0) == 0


def test_update_from_manifest_loads_field():
    cache = terrain.ElevationCache()
    terrain.update_from_manifest(cache, {
        "elevation": {
            "tile_size":      12.0,
            "level_height_m": 1.0,
            "tiles": [
                [0, 0, 0],
                [1, 0, 2],
                [0, 1, 3],
            ],
        }
    })
    assert cache.has_data
    assert cache.field[(0, 0)] == 0
    assert cache.field[(1, 0)] == 2
    assert cache.field[(0, 1)] == 3


def test_floor_y_at_returns_world_z():
    cache = terrain.ElevationCache()
    terrain.update_from_manifest(cache, {
        "elevation": {
            "tile_size":      10.0,
            "level_height_m": 1.0,
            "tiles":          [[0, 0, 0], [1, 0, 3]],
        }
    })
    # Center of tile (0,0) — level 0 — floor at y=0
    assert terrain.floor_y_at(cache, 0, 0) == 0.0
    # Center of tile (1,0) — level 3 — floor at y=3.0
    assert terrain.floor_y_at(cache, 10.0, 0) == 3.0


def test_floor_y_scales_with_level_height():
    cache = terrain.ElevationCache()
    terrain.update_from_manifest(cache, {
        "elevation": {
            "tile_size":      10.0,
            "level_height_m": 2.5,           # 2.5m per level
            "tiles":          [[0, 0, 2]],
        }
    })
    assert terrain.floor_y_at(cache, 0, 0) == 5.0


def test_unknown_tile_defaults_to_zero():
    cache = terrain.ElevationCache()
    terrain.update_from_manifest(cache, {
        "elevation": {
            "tile_size":      10.0,
            "level_height_m": 1.0,
            "tiles":          [[0, 0, 5]],
        }
    })
    # Way out of bounds → default 0
    assert terrain.floor_y_at(cache, 1000.0, 1000.0) == 0.0


def test_no_elevation_block_is_noop():
    cache = terrain.ElevationCache()
    terrain.update_from_manifest(cache, {})    # missing block
    assert not cache.has_data
    assert terrain.floor_y_at(cache, 100, 100) == 0.0


def test_empty_tiles_list_marks_no_data():
    cache = terrain.ElevationCache()
    terrain.update_from_manifest(cache, {
        "elevation": {"tile_size": 12.0, "level_height_m": 1.0, "tiles": []}
    })
    assert not cache.has_data


def test_tile_level_at_returns_int():
    cache = terrain.ElevationCache()
    terrain.update_from_manifest(cache, {
        "elevation": {
            "tile_size":      10.0,
            "level_height_m": 1.0,
            "tiles":          [[2, 3, 4]],
        }
    })
    assert terrain.tile_level_at(cache, 20.0, 30.0) == 4
    assert isinstance(terrain.tile_level_at(cache, 20.0, 30.0), int)
