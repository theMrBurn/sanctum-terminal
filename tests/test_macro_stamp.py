"""Tests for macro stamp 7x7 grid system.

Macro stamps define per-tile composition + elevation via a 7x7 grid.
Each cell controls density, allowed kind classes, and elevation.
terrain_height() reads from the grid. generate_tile() uses density/allowed.
"""

import pytest

from core.systems.macro_stamp import (
    grid_cell, grid_elevation, grid_density, grid_allowed,
    terrain_height, set_active_stamp, TERRAIN_CONFIG,
)
from core.systems.biome_data import BIOME_REGISTRY


# -- Macro stamp data in biome registry ---------------------------------------

class TestMacroStampInRegistry:
    """Each biome must have at least one macro stamp pattern."""

    def test_cavern_has_macro_stamps(self):
        reg = BIOME_REGISTRY["cavern"]
        assert "macro_stamps" in reg
        assert len(reg["macro_stamps"]) >= 1

    def test_outdoor_has_macro_stamps(self):
        reg = BIOME_REGISTRY["outdoor"]
        assert "macro_stamps" in reg
        assert len(reg["macro_stamps"]) >= 1

    @pytest.mark.parametrize("biome", ["cavern", "outdoor"])
    def test_macro_stamp_structure(self, biome):
        for ms in BIOME_REGISTRY[biome]["macro_stamps"]:
            assert "name" in ms
            assert "elevation" in ms
            assert "density" in ms
            assert "allowed" in ms
            assert len(ms["elevation"]) == 7, f"{ms['name']} elevation must be 7 rows"
            assert len(ms["density"]) == 7, f"{ms['name']} density must be 7 rows"
            assert len(ms["allowed"]) == 7, f"{ms['name']} allowed must be 7 rows"
            for row in ms["elevation"]:
                assert len(row) == 7, f"{ms['name']} elevation row must be 7 cols"
            for row in ms["density"]:
                assert len(row) == 7
            for row in ms["allowed"]:
                assert len(row) == 7


# -- Grid cell lookup ----------------------------------------------------------

class TestGridCell:
    """grid_cell(x, y, tile_size) returns (row, col) indices."""

    def test_center_of_tile(self):
        r, c = grid_cell(144.0, 144.0, 288.0)
        assert r == 3 and c == 3, f"center should be (3,3), got ({r},{c})"

    def test_origin_of_tile(self):
        r, c = grid_cell(0.0, 0.0, 288.0)
        assert r == 0 and c == 0

    def test_far_corner(self):
        r, c = grid_cell(287.0, 287.0, 288.0)
        assert r == 6 and c == 6

    def test_clamps_negative(self):
        r, c = grid_cell(-10.0, -10.0, 288.0)
        assert r == 0 and c == 0

    def test_clamps_over(self):
        r, c = grid_cell(999.0, 999.0, 288.0)
        assert r == 6 and c == 6


# -- Elevation lookup ----------------------------------------------------------

SAMPLE_STAMP = {
    "name": "test",
    "elevation_step": 3.0,
    "elevation": [
        [2, 2, 1, 1, 1, 2, 2],
        [2, 1, 1, 0, 1, 1, 2],
        [1, 1, 0, 0, 0, 1, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 1, 0, 0, 0, 1, 1],
        [2, 1, 1, 0, 1, 1, 2],
        [2, 2, 1, 1, 1, 2, 2],
    ],
    "density": [
        [0.2, 0.3, 0.4, 0.5, 0.4, 0.3, 0.2],
        [0.3, 0.5, 0.6, 0.7, 0.6, 0.5, 0.3],
        [0.4, 0.6, 0.8, 0.9, 0.8, 0.6, 0.4],
        [0.5, 0.7, 0.9, 0.3, 0.9, 0.7, 0.5],
        [0.4, 0.6, 0.8, 0.9, 0.8, 0.6, 0.4],
        [0.3, 0.5, 0.6, 0.7, 0.6, 0.5, 0.3],
        [0.2, 0.3, 0.4, 0.5, 0.4, 0.3, 0.2],
    ],
    "allowed": [
        ["S",   "S",   "SA",  "SA",  "SA",  "S",   "S"],
        ["S",   "SE",  "SEG", "SEG", "SEG", "SE",  "S"],
        ["SA",  "SEG", "ALL", "ALL", "ALL", "SEG", "SA"],
        ["SA",  "SEG", "ALL", "ALL", "ALL", "SEG", "SA"],
        ["SA",  "SEG", "ALL", "ALL", "ALL", "SEG", "SA"],
        ["S",   "SE",  "SEG", "SEG", "SEG", "SE",  "S"],
        ["S",   "S",   "SA",  "SA",  "SA",  "S",   "S"],
    ],
}


class TestGridElevation:
    """grid_elevation returns height in meters from grid cell."""

    def test_center_is_zero(self):
        h = grid_elevation(SAMPLE_STAMP, 144.0, 144.0, 288.0)
        assert h == 0.0, f"center elevation should be 0, got {h}"

    def test_corner_is_high(self):
        h = grid_elevation(SAMPLE_STAMP, 0.0, 0.0, 288.0)
        assert h == 6.0, f"corner elevation should be 6.0 (2*3), got {h}"

    def test_mid_edge(self):
        h = grid_elevation(SAMPLE_STAMP, 144.0, 0.0, 288.0)
        assert h == 3.0, f"mid-edge elevation should be 3.0 (1*3), got {h}"


class TestGridDensity:
    """grid_density returns density multiplier from grid cell."""

    def test_center_is_sparse(self):
        d = grid_density(SAMPLE_STAMP, 144.0, 144.0, 288.0)
        assert d == 0.3, f"center density should be 0.3, got {d}"

    def test_inner_ring_is_dense(self):
        # Cell (2,2) = 0.8
        cell_size = 288.0 / 7.0
        x = cell_size * 2.5
        y = cell_size * 2.5
        d = grid_density(SAMPLE_STAMP, x, y, 288.0)
        assert d == 0.8


class TestGridAllowed:
    """grid_allowed returns expanded kind class set."""

    def test_center_allows_all(self):
        allowed = grid_allowed(SAMPLE_STAMP, 144.0, 144.0, 288.0)
        assert "structural" in allowed
        assert "emissive" in allowed
        assert "scatter" in allowed

    def test_corner_structural_only(self):
        allowed = grid_allowed(SAMPLE_STAMP, 0.0, 0.0, 288.0)
        assert "structural" in allowed
        assert "emissive" not in allowed
        assert "scatter" not in allowed


# -- terrain_height replacement ------------------------------------------------

class TestTerrainHeight:
    """terrain_height() reads from active macro stamp."""

    def setup_method(self):
        set_active_stamp(SAMPLE_STAMP, 288.0)

    def teardown_method(self):
        set_active_stamp(None)

    def test_returns_float(self):
        h = terrain_height(0.0, 0.0)
        assert isinstance(h, float)

    def test_bounded(self):
        amp = TERRAIN_CONFIG["amplitude"]
        for x in range(-200, 200, 40):
            for y in range(-200, 200, 40):
                h = terrain_height(float(x), float(y))
                assert -amp - 0.1 <= h <= amp + 0.1

    def test_deterministic(self):
        h1 = terrain_height(42.5, -17.3)
        h2 = terrain_height(42.5, -17.3)
        assert h1 == h2

    def test_varies(self):
        heights = set()
        for x in range(0, 280, 40):
            heights.add(round(terrain_height(float(x), 0.0), 1))
        assert len(heights) >= 2, f"should vary, got {heights}"
