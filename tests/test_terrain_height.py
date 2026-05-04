"""Tests for terrain height via macro stamp grid.

terrain_height() reads elevation from the active macro stamp.
Returns 0.0 when no stamp is active (flat fallback).
"""

import pytest

from core.systems.macro_stamp import (
    terrain_height, set_active_stamp, TERRAIN_CONFIG,
)
from core.systems.biome_data import MACRO_STAMP_CAVERN_CHAMBER


class TestTerrainConfig:
    """Config has required fields."""

    def test_config_has_amplitude(self):
        assert "amplitude" in TERRAIN_CONFIG
        assert TERRAIN_CONFIG["amplitude"] > 0

    def test_config_has_elevation_step(self):
        assert "elevation_step" in TERRAIN_CONFIG
        assert TERRAIN_CONFIG["elevation_step"] > 0


@pytest.fixture(autouse=True)
def activate_stamp():
    """Activate cavern chamber stamp for terrain tests."""
    set_active_stamp(MACRO_STAMP_CAVERN_CHAMBER, 288.0)
    yield
    set_active_stamp(None)


class TestTerrainHeight:
    """terrain_height() returns smooth, bounded elevation from grid."""

    def test_returns_float(self):
        h = terrain_height(0.0, 0.0)
        assert isinstance(h, float)

    def test_bounded_by_amplitude(self):
        amp = TERRAIN_CONFIG["amplitude"]
        for x in range(-200, 200, 40):
            for y in range(-200, 200, 40):
                h = terrain_height(float(x), float(y))
                assert -amp - 0.1 <= h <= amp + 0.1

    def test_deterministic(self):
        h1 = terrain_height(42.5, -17.3)
        h2 = terrain_height(42.5, -17.3)
        assert h1 == h2

    def test_flat_grid_is_flat(self):
        """All-zero elevation grid should return 0.0 everywhere."""
        # Active stamp is cavern_chamber which is currently flat
        for x in range(0, 280, 40):
            h = terrain_height(float(x), 0.0)
            assert h == 0.0, f"flat grid should be 0.0, got {h} at x={x}"

    def test_flat_when_no_stamp(self):
        set_active_stamp(None)
        assert terrain_height(50.0, 50.0) == 0.0
