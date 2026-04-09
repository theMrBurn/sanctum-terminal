"""
tests/test_tile_prefetch.py

Tile prefetch radius — ensures BrainWorld generates enough tiles ahead
of camera movement so entities exist before the wake system needs them.

Pure logic — no Godot, no rendering.
"""

import math
import pytest

from core.systems.biome_data import BIOME_REGISTRY
from core.systems.spatial_wake import WAKE_CHAINS


# -- Config-driven prefetch radius ---------------------------------------------

class TestPrefetchConfig:

    def test_cavern_has_prefetch_radius(self):
        assert "tile_prefetch_radius" in BIOME_REGISTRY["cavern"]

    def test_outdoor_has_prefetch_radius(self):
        assert "tile_prefetch_radius" in BIOME_REGISTRY["outdoor"]

    def test_prefetch_radius_at_least_2(self):
        """radius=1 was the original bug — 3x3 grid left gaps."""
        for biome, reg in BIOME_REGISTRY.items():
            r = reg.get("tile_prefetch_radius", 1)
            assert r >= 2, f"{biome} prefetch radius {r} < 2"


# -- Tile coverage vs wake radius ----------------------------------------------

class TestTileCoverageExceedsWake:
    """The prefetch grid must guarantee that tiles are loaded before
    the camera can see entities in them via the wake system."""

    def _max_wake_radius(self, biome):
        chain_key = biome if biome in WAKE_CHAINS else "outdoor"
        return max(link["radius"] for link in WAKE_CHAINS[chain_key])

    def _tile_size(self, biome):
        """Tile size from registry or default."""
        return BIOME_REGISTRY.get(biome, {}).get("tile_size", 288.0)

    def test_cavern_prefetch_covers_wake(self):
        """Worst case: camera at tile edge, entity at near edge of outermost
        tile. The gap must be < max wake radius so entities are visible."""
        biome = "cavern"
        ts = self._tile_size(biome)
        radius = BIOME_REGISTRY[biome]["tile_prefetch_radius"]
        max_wake = self._max_wake_radius(biome)
        # Camera at tile edge can see (radius - 0.5) * tile_size ahead
        # at the near edge of the farthest loaded tile.
        coverage_ahead = (radius - 0.5) * ts
        assert coverage_ahead > max_wake, \
            f"Cavern: coverage {coverage_ahead:.0f}m < wake {max_wake:.0f}m"

    def test_outdoor_prefetch_covers_wake(self):
        biome = "outdoor"
        ts = self._tile_size(biome)
        radius = BIOME_REGISTRY[biome]["tile_prefetch_radius"]
        max_wake = self._max_wake_radius(biome)
        coverage_ahead = (radius - 0.5) * ts
        assert coverage_ahead > max_wake, \
            f"Outdoor: coverage {coverage_ahead:.0f}m < wake {max_wake:.0f}m"


# -- BrainWorld tile generation ------------------------------------------------

class TestBrainWorldTileGeneration:
    """Integration: verify BrainWorld generates the correct tile grid."""

    @pytest.fixture
    def world(self):
        from brain_server import BrainWorld
        return BrainWorld("cavern", base_seed=42)

    def test_spawn_tile_loaded_at_init(self, world):
        assert (0, 0) in world.loaded_tiles

    def test_get_manifest_generates_correct_grid(self, world):
        """get_manifest at (0, 0) should eventually load the full prefetch grid.

        With tiles_per_frame capping generation, multiple calls are needed
        to fill the grid. This mirrors real usage: the brain responds every
        frame and incrementally builds out the tile cache.
        """
        expected_radius = BIOME_REGISTRY["cavern"]["tile_prefetch_radius"]
        grid_size = (2 * expected_radius + 1) ** 2
        # Call enough times to generate all tiles (1 per frame + spawn already cached)
        for _ in range(grid_size):
            world.get_manifest(0.0, 0.0, 0.0, 0.0, 0.0, 0.1)
        for dx in range(-expected_radius, expected_radius + 1):
            for dy in range(-expected_radius, expected_radius + 1):
                assert (dx, dy) in world.exchange._tile_cache, \
                    f"Tile ({dx},{dy}) not in exchange cache with radius={expected_radius}"

    def test_entities_exist_ahead_of_camera(self, world):
        """After ensure_tiles, entities should exist at distances the wake
        system can reach in the next tile over."""
        world.ensure_tiles_around(0.0, 0.0)
        # Check that entities exist in the tile ahead (+1, 0)
        tile_size = world.tile_size
        # Entities in tile (1, 0) have x in [0, tile_size]
        found_ahead = False
        for eid, ent in world.entities.items():
            if ent["x"] > tile_size * 0.3:  # well into the next tile
                found_ahead = True
                break
        assert found_ahead, "No entities found ahead of camera in adjacent tile"

    def test_walking_edge_generates_new_tiles(self, world):
        """Simulate walking to tile boundary — new tiles must appear."""
        ts = world.tile_size
        # Walk to edge of tile (0,0) heading +x
        world.ensure_tiles_around(ts - 1.0, 0.0)
        tiles_before = len(world.loaded_tiles)
        # Cross into tile (1,0)
        world.ensure_tiles_around(ts + 1.0, 0.0)
        tiles_after = len(world.loaded_tiles)
        assert tiles_after > tiles_before, \
            "Crossing tile boundary did not generate new tiles"
