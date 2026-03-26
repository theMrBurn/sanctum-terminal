import json
from pathlib import Path

import pytest


@pytest.fixture
def manifest():
    path = Path("config/manifest.json")
    assert path.exists(), "config/manifest.json not found"
    return json.load(open(path))


# ── Meta ──────────────────────────────────────────────────────────────────────


class TestMeta:

    def test_meta_exists(self, manifest):
        assert "meta" in manifest

    def test_meta_has_version(self, manifest):
        assert "version" in manifest["meta"]

    def test_meta_has_project(self, manifest):
        assert manifest["meta"]["project"] == "sanctum-terminal"


# ── World ─────────────────────────────────────────────────────────────────────


class TestWorld:

    def test_world_exists(self, manifest):
        assert "world" in manifest

    def test_world_ground_z_is_float(self, manifest):
        assert isinstance(manifest["world"]["ground_z"], float)

    def test_world_move_speed_is_float(self, manifest):
        assert isinstance(manifest["world"]["move_speed"], float)

    def test_world_interact_dist_is_float(self, manifest):
        assert isinstance(manifest["world"]["interact_dist"], float)

    def test_world_camera_start_is_list_of_three(self, manifest):
        cs = manifest["world"]["camera_start"]
        assert isinstance(cs, list)
        assert len(cs) == 3

    def test_world_background_color_is_list_of_three(self, manifest):
        bg = manifest["world"]["background_color"]
        assert isinstance(bg, list)
        assert len(bg) == 3


# ── Avatar ────────────────────────────────────────────────────────────────────


class TestAvatar:

    def test_avatar_exists(self, manifest):
        assert "avatar" in manifest

    def test_avatar_height_is_float(self, manifest):
        assert isinstance(manifest["avatar"]["height"], float)

    def test_avatar_gravity_is_float(self, manifest):
        assert isinstance(manifest["avatar"]["gravity"], float)

    def test_avatar_friction_is_float(self, manifest):
        assert isinstance(manifest["avatar"]["friction"], float)

    def test_avatar_color_is_list_of_three(self, manifest):
        c = manifest["avatar"]["color"]
        assert isinstance(c, list)
        assert len(c) == 3


# ── Tiers ─────────────────────────────────────────────────────────────────────


class TestTiers:

    def test_tiers_exists(self, manifest):
        assert "tiers" in manifest

    def test_all_three_tiers_present(self, manifest):
        for tier in ["surface", "dungeon", "boss"]:
            assert tier in manifest["tiers"]

    def test_tier_ranges_are_lists_of_two(self, manifest):
        for _tier, rng in manifest["tiers"].items():
            assert isinstance(rng, list)
            assert len(rng) == 2

    def test_tier_ranges_are_contiguous(self, manifest):
        tiers = manifest["tiers"]
        assert tiers["surface"][1] + 1 == tiers["dungeon"][0]
        assert tiers["dungeon"][1] + 1 == tiers["boss"][0]

    def test_tier_ranges_cover_1_to_10(self, manifest):
        tiers = manifest["tiers"]
        assert tiers["surface"][0] == 1
        assert tiers["boss"][1] == 10


# ── Atmosphere ────────────────────────────────────────────────────────────────


class TestAtmosphere:

    def test_atmosphere_exists(self, manifest):
        assert "atmosphere" in manifest

    def test_all_tiers_have_atmosphere(self, manifest):
        for tier in ["default", "surface", "dungeon", "boss"]:
            assert tier in manifest["atmosphere"]

    def test_atmosphere_has_u_fog(self, manifest):
        for tier in ["default", "surface", "dungeon", "boss"]:
            assert "u_fog" in manifest["atmosphere"][tier]

    def test_atmosphere_has_u_exp(self, manifest):
        for tier in ["default", "surface", "dungeon", "boss"]:
            assert "u_exp" in manifest["atmosphere"][tier]

    def test_u_fog_is_list_of_four(self, manifest):
        for tier in ["default", "surface", "dungeon", "boss"]:
            fog = manifest["atmosphere"][tier]["u_fog"]
            assert isinstance(fog, list)
            assert len(fog) == 4

    def test_u_exp_increases_with_tier(self, manifest):
        atm = manifest["atmosphere"]
        assert atm["surface"]["u_exp"] < atm["dungeon"]["u_exp"]
        assert atm["dungeon"]["u_exp"] < atm["boss"]["u_exp"]


# ── Biomes ────────────────────────────────────────────────────────────────────


class TestBiomes:

    EXPECTED_BIOMES = [
        "VOID",
        "NEON",
        "IRON",
        "SILICA",
        "FROZEN",
        "SULPHUR",
        "BASALT",
        "VERDANT",
        "MYCELIUM",
        "CHROME",
    ]

    def test_biomes_exists(self, manifest):
        assert "biomes" in manifest

    def test_all_10_biomes_present(self, manifest):
        for biome in self.EXPECTED_BIOMES:
            assert biome in manifest["biomes"]

    def test_each_biome_has_v_id(self, manifest):
        for biome in self.EXPECTED_BIOMES:
            assert "v_id" in manifest["biomes"][biome]

    def test_each_biome_has_u_fog(self, manifest):
        for biome in self.EXPECTED_BIOMES:
            assert "u_fog" in manifest["biomes"][biome]

    def test_each_biome_has_u_exp(self, manifest):
        for biome in self.EXPECTED_BIOMES:
            assert "u_exp" in manifest["biomes"][biome]

    def test_biome_u_fog_is_list_of_four(self, manifest):
        for biome in self.EXPECTED_BIOMES:
            fog = manifest["biomes"][biome]["u_fog"]
            assert isinstance(fog, list)
            assert len(fog) == 4


# ── Tier biome map ────────────────────────────────────────────────────────────


class TestTierBiomeMap:

    def test_tier_biome_map_exists(self, manifest):
        assert "tier_biome_map" in manifest

    def test_all_tiers_mapped(self, manifest):
        for tier in ["surface", "dungeon", "boss"]:
            assert tier in manifest["tier_biome_map"]

    def test_mapped_biomes_exist(self, manifest):
        for _tier, biome in manifest["tier_biome_map"].items():
            assert biome in manifest["biomes"]


# ── Environment ───────────────────────────────────────────────────────────────


class TestEnvironment:

    def test_environment_exists(self, manifest):
        assert "environment" in manifest

    def test_default_city_exists(self, manifest):
        env = manifest["environment"]
        assert "default_city" in env
        assert env["default_city"] in env["registry"]

    def test_registry_has_required_cities(self, manifest):
        registry = manifest["environment"]["registry"]
        for city in ["portland", "seattle", "miami"]:
            assert city in registry

    def test_each_city_has_lat_lon(self, manifest):
        for _city, data in manifest["environment"]["registry"].items():
            assert "lat" in data
            assert "lon" in data

    def test_update_rate_is_int(self, manifest):
        assert isinstance(manifest["environment"]["update_rate"], int)


# ── Observer ──────────────────────────────────────────────────────────────────


class TestObserver:

    def test_observer_exists(self, manifest):
        assert "observer" in manifest

    def test_observer_has_required_keys(self, manifest):
        obs = manifest["observer"]
        for key in [
            "base_visibility",
            "heat_attack_rate",
            "heat_decay_rate",
            "heat_scale",
            "pulse_duration",
            "pulse_reset",
        ]:
            assert key in obs

    def test_observer_values_are_numeric(self, manifest):
        for _key, val in manifest["observer"].items():
            assert isinstance(val, (int, float))


# ── Economy ───────────────────────────────────────────────────────────────────


class TestEconomy:

    def test_economy_exists(self, manifest):
        assert "economy" in manifest

    def test_economy_has_required_keys(self, manifest):
        eco = manifest["economy"]
        for key in ["info_request_weight", "energy_cost_weight", "throughput_target"]:
            assert key in eco

    def test_throughput_target_between_0_and_1(self, manifest):
        t = manifest["economy"]["throughput_target"]
        assert 0.0 <= t <= 1.0
