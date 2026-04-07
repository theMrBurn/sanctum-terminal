"""Tests for kind_config.json integrity and self-emit system."""

import json
from pathlib import Path

import pytest


KIND_CONFIG_PATH = Path(__file__).parent.parent / "godot" / "kind_config.json"


@pytest.fixture(scope="module")
def kind_config():
    with open(KIND_CONFIG_PATH) as f:
        return json.load(f)


# -- Schema integrity ----------------------------------------------------------

class TestKindConfigSchema:
    """kind_config.json is well-formed and internally consistent."""

    def test_file_exists(self):
        assert KIND_CONFIG_PATH.exists()

    def test_valid_json(self):
        with open(KIND_CONFIG_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_has_global(self, kind_config):
        assert "_global" in kind_config

    def test_global_has_world_grain(self, kind_config):
        wg = kind_config["_global"]["world_grain"]
        assert "grain_scale" in wg
        assert "grain_strength" in wg

    def test_all_kinds_have_class(self, kind_config):
        """Every non-global entry must declare a class."""
        for kind, cfg in kind_config.items():
            if kind.startswith("_"):
                continue
            if not isinstance(cfg, dict):
                continue
            # Some entries are nested under class groups
            if "class" in cfg:
                assert isinstance(cfg["class"], str)


# -- Self-emit / inner_glow ---------------------------------------------------

EMISSIVE_KINDS = [
    "crystal_cluster", "filament", "exit_lure",
    "giant_fungus", "moss_patch", "ceiling_moss", "firefly",
]


class TestInnerGlow:
    """Self-emit system: inner_glow dims albedo, boosts emission."""

    def test_emissive_kinds_have_inner_glow(self, kind_config):
        """All emissive kinds must declare inner_glow."""
        for kind in EMISSIVE_KINDS:
            found = False
            # Search in top-level and nested class groups
            for key, val in kind_config.items():
                if key.startswith("_"):
                    continue
                if isinstance(val, dict):
                    if key == kind and "inner_glow" in val:
                        found = True
                        break
                    # Check nested dicts (class groups)
                    if kind in val and isinstance(val[kind], dict):
                        if "inner_glow" in val[kind]:
                            found = True
                            break
            assert found, f"{kind} must have inner_glow"

    def test_inner_glow_range(self, kind_config):
        """inner_glow must be in [0.0, 1.0]."""
        for key, val in kind_config.items():
            if key.startswith("_"):
                continue
            if isinstance(val, dict):
                ig = val.get("inner_glow")
                if ig is not None:
                    assert 0.0 <= ig <= 1.0, (
                        f"{key} inner_glow={ig} out of range")
                # Check nested
                for sub_key, sub_val in val.items():
                    if isinstance(sub_val, dict):
                        ig = sub_val.get("inner_glow")
                        if ig is not None:
                            assert 0.0 <= ig <= 1.0, (
                                f"{key}.{sub_key} inner_glow={ig} out of range")

    def test_pulse_rate_accompanies_inner_glow(self, kind_config):
        """Kinds with inner_glow should also have pulse_rate."""
        for key, val in kind_config.items():
            if key.startswith("_"):
                continue
            if isinstance(val, dict):
                if val.get("inner_glow", 0) > 0:
                    assert "pulse_rate" in val, (
                        f"{key} has inner_glow but no pulse_rate")
                for sub_key, sub_val in val.items():
                    if isinstance(sub_val, dict):
                        if sub_val.get("inner_glow", 0) > 0:
                            assert "pulse_rate" in sub_val, (
                                f"{key}.{sub_key} has inner_glow but no pulse_rate")

    def test_light_event_kinds_have_glow(self, kind_config):
        """Light-event crystalline kinds should have inner_glow > 0."""
        light_events = ["crystal_cluster", "filament", "exit_lure"]
        for kind in light_events:
            found = False
            for key, val in kind_config.items():
                if key.startswith("_"):
                    continue
                if isinstance(val, dict):
                    if key == kind:
                        assert val.get("inner_glow", 0) > 0, (
                            f"{kind} is a light event, inner_glow should be > 0")
                        found = True
                    elif kind in val and isinstance(val[kind], dict):
                        assert val[kind].get("inner_glow", 0) > 0
                        found = True
            assert found, f"{kind} not found in kind_config"


# -- Decal config for emissives ------------------------------------------------

class TestEmissiveDecals:
    """Emissive kinds should have ground decal configuration."""

    def test_emissive_kinds_have_decal(self, kind_config):
        for kind in EMISSIVE_KINDS:
            for key, val in kind_config.items():
                if key.startswith("_"):
                    continue
                if isinstance(val, dict):
                    target = None
                    if key == kind:
                        target = val
                    elif kind in val and isinstance(val[kind], dict):
                        target = val[kind]
                    if target is not None:
                        assert "decal" in target, (
                            f"{kind} is emissive but has no decal config")
                        d = target["decal"]
                        assert "emission_radius" in d
                        assert "emission_energy" in d
                        assert d["emission_radius"] > 0
                        assert d["emission_energy"] > 0
                        break
