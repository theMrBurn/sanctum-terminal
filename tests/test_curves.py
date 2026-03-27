import pytest
from core.systems.curves import (
    apply_scale, check_thresholds, normalize, THRESHOLDS
)


# ── normalize ─────────────────────────────────────────────────────────────────

class TestNormalize:

    def test_clamps_below_zero(self):
        assert normalize(-0.5) == 0.0

    def test_clamps_above_one(self):
        assert normalize(1.5) == 1.0

    def test_passthrough_valid(self):
        assert normalize(0.5) == 0.5

    def test_zero_is_valid(self):
        assert normalize(0.0) == 0.0

    def test_one_is_valid(self):
        assert normalize(1.0) == 1.0


# ── apply_scale ───────────────────────────────────────────────────────────────

class TestApplyScale:

    def test_returns_dict(self):
        result = apply_scale("weight", 0.5)
        assert isinstance(result, dict)

    def test_encounter_density_scales_with_weight(self):
        low  = apply_scale("weight", 0.1)
        high = apply_scale("weight", 0.9)
        assert low["encounter_density"] < high["encounter_density"]

    def test_impact_rating_is_int(self):
        result = apply_scale("weight", 0.5)
        assert isinstance(result["impact_rating"], int)

    def test_impact_rating_in_range(self):
        for s in [0.0, 0.25, 0.5, 0.75, 1.0]:
            r = apply_scale("weight", s)
            assert 1 <= r["impact_rating"] <= 10

    def test_karma_baseline_scales_with_fatigue(self):
        rested    = apply_scale("fatigue", 0.1)
        exhausted = apply_scale("fatigue", 0.9)
        assert rested["karma_baseline"] < exhausted["karma_baseline"]

    def test_ambient_intensity_scales_with_time(self):
        night  = apply_scale("time", 0.1)
        midday = apply_scale("time", 1.0)
        assert night["ambient_intensity"] < midday["ambient_intensity"]

    def test_camera_speed_scales_with_pace(self):
        slow = apply_scale("pace", 0.1)
        fast = apply_scale("pace", 0.9)
        assert slow["camera_speed"] < fast["camera_speed"]

    def test_spawn_radius_inverse_of_enclosure(self):
        open_space = apply_scale("enclosure", 0.1)
        enclosed   = apply_scale("enclosure", 0.9)
        assert open_space["spawn_radius"] > enclosed["spawn_radius"]

    def test_heat_scales_with_energy(self):
        low  = apply_scale("energy", 0.1)
        high = apply_scale("energy", 0.9)
        assert low["heat"] < high["heat"]

    def test_moisture_scales_with_flow(self):
        stuck    = apply_scale("flow", 0.1)
        flowing  = apply_scale("flow", 0.9)
        assert stuck["moisture"] < flowing["moisture"]

    def test_unknown_scale_returns_defaults(self):
        result = apply_scale("unknown_key", 0.5)
        assert "encounter_density" in result


# ── check_thresholds ──────────────────────────────────────────────────────────

class TestCheckThresholds:

    def test_returns_list(self):
        state = {"encounter_density": 0.5, "karma": 0.5}
        result = check_thresholds(state)
        assert isinstance(result, list)

    def test_dungeon_unlock_above_threshold(self):
        state = {"encounter_density": 0.8, "karma": 0.5,
                 "heat": 0.5, "moisture": 0.5, "days_played": 1}
        crossed = check_thresholds(state)
        assert "dungeon_unlock" in crossed

    def test_dungeon_unlock_below_threshold(self):
        state = {"encounter_density": 0.3, "karma": 0.5,
                 "heat": 0.5, "moisture": 0.5, "days_played": 1}
        crossed = check_thresholds(state)
        assert "dungeon_unlock" not in crossed

    def test_ascent_visible_when_karma_low(self):
        state = {"encounter_density": 0.6, "karma": 0.2,
                 "heat": 0.5, "moisture": 0.5, "days_played": 3}
        crossed = check_thresholds(state)
        assert "ascent_visible" in crossed

    def test_ascent_not_visible_high_karma(self):
        state = {"encounter_density": 0.6, "karma": 0.8,
                 "heat": 0.5, "moisture": 0.5, "days_played": 3}
        crossed = check_thresholds(state)
        assert "ascent_visible" not in crossed

    def test_biome_edge_shift_hot_dry(self):
        state = {"encounter_density": 0.5, "karma": 0.5,
                 "heat": 0.9, "moisture": 0.1, "days_played": 1}
        crossed = check_thresholds(state)
        assert "biome_edge_shift" in crossed

    def test_campaign_ready_after_three_days(self):
        state = {"encounter_density": 0.5, "karma": 0.35,
                 "heat": 0.5, "moisture": 0.5, "days_played": 3}
        crossed = check_thresholds(state)
        assert "campaign_ready" in crossed

    def test_campaign_not_ready_day_one(self):
        state = {"encounter_density": 0.5, "karma": 0.35,
                 "heat": 0.5, "moisture": 0.5, "days_played": 1}
        crossed = check_thresholds(state)
        assert "campaign_ready" not in crossed

    def test_torch_upgrade_at_depth_two(self):
        state = {"encounter_density": 0.5, "karma": 0.5,
                 "heat": 0.5, "moisture": 0.5,
                 "days_played": 1, "depth_score": 2}
        crossed = check_thresholds(state)
        assert "torch_upgrade" in crossed

    def test_rare_torch_at_depth_three(self):
        state = {"encounter_density": 0.5, "karma": 0.5,
                 "heat": 0.5, "moisture": 0.5,
                 "days_played": 1, "depth_score": 3}
        crossed = check_thresholds(state)
        assert "rare_torch" in crossed

    def test_empty_state_returns_empty(self):
        crossed = check_thresholds({})
        assert crossed == []

    def test_multiple_thresholds_can_cross_simultaneously(self):
        state = {"encounter_density": 0.9, "karma": 0.2,
                 "heat": 0.9, "moisture": 0.1,
                 "days_played": 3, "depth_score": 3}
        crossed = check_thresholds(state)
        assert len(crossed) >= 3


# ── THRESHOLDS config ─────────────────────────────────────────────────────────

class TestThresholdsConfig:

    def test_thresholds_is_dict(self):
        assert isinstance(THRESHOLDS, dict)

    def test_required_thresholds_exist(self):
        for key in ["dungeon_unlock", "ascent_visible",
                    "biome_edge_shift", "campaign_ready",
                    "torch_upgrade", "rare_torch"]:
            assert key in THRESHOLDS

    def test_threshold_values_are_floats(self):
        for name, conditions in THRESHOLDS.items():
            for key, val in conditions.items():
                if key not in ("direction", "days_played",
                               "depth_score", "days_min"):
                    assert isinstance(val, float),                         f"{name}.{key} should be float, got {type(val)}"
