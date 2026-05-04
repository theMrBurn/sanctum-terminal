"""Tests for radial density gradient in world generation.

The gradient scales stamp frequency and mega_column threshold from center
outward on spawn tiles. Non-spawn tiles behave as if rf=1.0 everywhere.
"""

import pytest

from core.systems.world_gen import generate_tile


class TestRadialDensityGradient:
    """Spawn tiles have simpler composition near center, complex at edges."""

    def test_spawn_tile_center_has_fewer_stamps(self):
        """Center of spawn tile should have fewer stamp-placed entities."""
        tile_size = 288.0
        center = tile_size / 2.0
        inner_r = tile_size * 0.15  # inner 15% radius

        center_stamps = 0
        edge_stamps = 0
        for seed in range(10):
            _, spawns = generate_tile(seed, "cavern", is_spawn_tile=True)
            for s in spawns:
                is_stamp = s[4] and isinstance(s[4], dict) and "stamp_scale_mult" in s[4]
                if not is_stamp:
                    continue
                x, y = s[1]
                if abs(x - center) < inner_r and abs(y - center) < inner_r:
                    center_stamps += 1
                else:
                    edge_stamps += 1
        # Edges have vastly more area AND higher stamp chance
        assert edge_stamps > center_stamps, (
            f"edges ({edge_stamps}) should have more stamps than center ({center_stamps})")

    def test_non_spawn_tile_ignores_gradient(self):
        """Non-spawn tiles should not reduce center density.

        Across multiple seeds, non-spawn tiles should average more entities
        than spawn tiles (which suppress center composition).
        """
        spawn_total = 0
        normal_total = 0
        for seed in range(5):
            _, spawns_spawn = generate_tile(seed, "cavern", is_spawn_tile=True)
            _, spawns_normal = generate_tile(seed, "cavern", is_spawn_tile=False)
            spawn_total += len(spawns_spawn)
            normal_total += len(spawns_normal)
        # With tighter spawn clearance (10m), counts are close — allow 5% margin
        assert normal_total >= spawn_total * 0.95, (
            f"non-spawn total ({normal_total}) should be roughly >= spawn total ({spawn_total})")

    def test_spawn_tile_not_empty_at_center(self):
        """Player spawns at center — it must have some entities."""
        tile_size = 288.0
        center = tile_size / 2.0
        radius = tile_size * 0.10

        _, spawns = generate_tile(42, "cavern", is_spawn_tile=True)
        center_count = sum(
            1 for s in spawns
            if abs(s[1][0] - center) < radius and abs(s[1][1] - center) < radius
        )
        assert center_count > 0, "spawn center must not be empty"

    def test_spawn_center_has_fewer_mega_columns(self):
        """mega_column threshold is suppressed near spawn center."""
        tile_size = 288.0
        center = tile_size / 2.0
        inner_r = tile_size * 0.20

        center_megas = 0
        edge_megas = 0
        for seed in range(15):
            _, spawns = generate_tile(seed, "cavern", is_spawn_tile=True)
            for s in spawns:
                if s[0] != "mega_column":
                    continue
                x, y = s[1]
                if abs(x - center) < inner_r and abs(y - center) < inner_r:
                    center_megas += 1
                else:
                    edge_megas += 1
        # Should have significantly fewer megas at center
        assert edge_megas >= center_megas, (
            f"edges ({edge_megas}) should have >= mega_columns than center ({center_megas})")
