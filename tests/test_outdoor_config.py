"""
tests/test_outdoor_config.py

Visual tuning + FrameComposer config validation.
Pure logic tests — no rendering, no Panda3D.
"""

import math
import pytest

from core.systems.ambient_life import (
    BIOME_REGISTRY, OUTDOOR_COLOR_SCALES, OUTDOOR_PALETTE, CAVERN_PALETTE,
    DOME_HEIGHT, biome_config, set_active_biome, _cavern_color,
)


# -- Visual tuning: ambient brightness ----------------------------------------

class TestOutdoorAmbient:
    """Outdoor day ambient must be bright enough to read as daylight."""

    def test_outdoor_palette_floor_warmer_than_cavern(self):
        """Ground floor should be brighter outdoors (more ambient light)."""
        o_sum = sum(OUTDOOR_PALETTE["floor"])
        c_sum = sum(CAVERN_PALETTE["floor"])
        assert o_sum >= c_sum, "Outdoor floor darker than cavern"

    def test_outdoor_palette_organic_greener_than_cavern(self):
        o = OUTDOOR_PALETTE["dead_organic"]
        c = CAVERN_PALETTE["dead_organic"]
        assert o[1] > c[1], "Outdoor organic should be greener"

    def test_outdoor_palette_has_green_bias(self):
        """Organic keys should have green > red (PNW forest)."""
        org = OUTDOOR_PALETTE["dead_organic"]
        assert org[1] > org[0], "dead_organic green should exceed red"


# -- Visual tuning: color scales -----------------------------------------------

class TestOutdoorColorScales:
    """Color scales compensate for builder flattenStrong baking (~0.50-0.55).
    Values must be bright enough to read against dark ground."""

    def test_boulder_reads_green(self):
        """Fern-boulder green channel must dominate."""
        b = OUTDOOR_COLOR_SCALES["boulder"]
        assert b[1] > b[0], "boulder green should exceed red"
        assert b[1] > b[2], "boulder green should exceed blue"

    def test_boulder_bright_enough(self):
        """After multiply with baked ~0.50, result should be > 0.25 green."""
        b = OUTDOOR_COLOR_SCALES["boulder"]
        baked_green = 0.50  # typical builder baked value
        result_green = b[1] * baked_green
        assert result_green > 0.25, f"Boulder green {result_green} too dark after bake"

    def test_column_reads_warm(self):
        """Tree bark: red > blue (warm brown)."""
        c = OUTDOOR_COLOR_SCALES["column"]
        assert c[0] > c[2], "column red should exceed blue (warm bark)"

    def test_moss_not_neon(self):
        """Moss green channel must be < 1.5 (not neon glow)."""
        m = OUTDOOR_COLOR_SCALES["moss_patch"]
        assert m[1] < 1.5, f"Moss green {m[1]} is neon territory"

    def test_all_scales_have_four_components(self):
        for kind, scale in OUTDOOR_COLOR_SCALES.items():
            assert len(scale) == 4, f"{kind} scale has {len(scale)} components, need 4"
            assert scale[3] == 1.0, f"{kind} alpha should be 1.0"

    def test_firefly_stays_bright(self):
        """Fireflies are self-lit — scale should be > 1.0 on at least one channel."""
        f = OUTDOOR_COLOR_SCALES["firefly"]
        assert max(f[:3]) > 1.0, "Firefly should have emissive-range values"


# -- Biome registry -----------------------------------------------------------

class TestBiomeRegistry:
    """All biome keys present and consistent."""

    def test_both_biomes_registered(self):
        assert "cavern" in BIOME_REGISTRY
        assert "outdoor" in BIOME_REGISTRY

    def test_required_keys_present(self):
        required = ["palette", "color_scales", "companions", "spectrum", "motes", "tile_variants"]
        for biome in BIOME_REGISTRY:
            for key in required:
                assert key in BIOME_REGISTRY[biome], f"{biome} missing '{key}'"

    def test_biome_config_reads_active(self):
        set_active_biome("outdoor")
        p = biome_config("palette")
        assert p == OUTDOOR_PALETTE
        set_active_biome("cavern")
        p = biome_config("palette")
        assert p == CAVERN_PALETTE

    def test_cavern_color_auto_biome(self):
        """_cavern_color reads _active_biome automatically."""
        import random
        rng = random.Random(42)
        set_active_biome("outdoor")
        outdoor_color = _cavern_color("stone", rng)
        rng = random.Random(42)
        set_active_biome("cavern")
        cavern_color = _cavern_color("stone", rng)
        # Different palettes should produce different colors
        assert outdoor_color != cavern_color
        set_active_biome("cavern")  # reset


# -- Dome height ---------------------------------------------------------------

class TestDomeHeight:

    def test_outdoor_taller_than_cavern(self):
        assert DOME_HEIGHT["outdoor"] > DOME_HEIGHT["cavern"]

    def test_outdoor_dome_reasonable(self):
        assert 40.0 <= DOME_HEIGHT["outdoor"] <= 60.0


# -- Tension cycle config ------------------------------------------------------

class TestOutdoorTensionConfig:

    def setup_method(self):
        from core.systems.tension_cycle import OUTDOOR_CYCLE
        self.cycle = OUTDOOR_CYCLE

    def test_budget_max_accommodates_companion_spawns(self):
        """UAT showed 320-488 active. budget_max must give headroom."""
        assert self.cycle["budget_max"] >= 600

    def test_bands_are_sequential(self):
        """States advance sequentially. Rebirth wraps back to 0 (cycle reset)."""
        from core.systems.tension_cycle import STATE_ORDER
        prev_ceiling = 0.0
        for state_name in STATE_ORDER:
            cfg = self.cycle[state_name]
            if state_name == "rebirth":
                # Rebirth resets budget — floor is 0.0 by design
                assert cfg["budget_floor"] == 0.0
            else:
                assert cfg["budget_floor"] >= prev_ceiling - 0.01, \
                    f"{state_name} floor {cfg['budget_floor']} < prev ceiling {prev_ceiling}"
            assert cfg["budget_ceiling"] > cfg["budget_floor"], \
                f"{state_name} ceiling <= floor"
            prev_ceiling = cfg["budget_ceiling"]

    def test_fog_ranges_narrow_with_tension(self):
        """Each state should have tighter fog than the previous."""
        from core.systems.tension_cycle import STATE_ORDER
        prev_far = 999.0
        for state_name in STATE_ORDER:
            if state_name == "rebirth":
                continue  # rebirth opens back up
            cfg = self.cycle[state_name]
            assert cfg["fog"][1] <= prev_far, \
                f"{state_name} fog_far {cfg['fog'][1]} > prev {prev_far}"
            prev_far = cfg["fog"][1]

    def test_lerp_speed_is_gradual(self):
        assert self.cycle.get("lerp_speed", 3.0) >= 4.0, "Lerp should be >= 4s for weather feel"

    def test_dump_hold_long_enough(self):
        assert self.cycle["dump"]["hold_seconds"] >= 4.0

    def test_rebirth_hold_long_enough(self):
        assert self.cycle["rebirth"]["hold_seconds"] >= 6.0
