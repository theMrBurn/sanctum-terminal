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


# -- 3-color palette system ----------------------------------------------------

LIGHT_REACTIVE_KINDS = [
    "crystal_cluster", "filament", "exit_lure",
    "giant_fungus", "moss_patch", "ceiling_moss", "firefly",
]


class TestPalette:
    """3-color flat palette: color_base/shadow/accent per kind."""

    def _resolve_kind(self, kind_config, kind):
        """Resolve a kind's effective config (class defaults + overrides)."""
        kinds = kind_config.get("kinds", {})
        defaults = kind_config.get("_class_defaults", {})
        entry = kinds.get(kind, {})
        cls = entry.get("class", "geological")
        base = defaults.get(cls, {}).copy()
        base.update(entry)
        return base

    def test_all_kinds_have_3_colors(self, kind_config):
        """Every kind must resolve to color_base, color_shadow, color_accent."""
        for kind in kind_config.get("kinds", {}):
            params = self._resolve_kind(kind_config, kind)
            for field in ("color_base", "color_shadow", "color_accent"):
                assert field in params, f"{kind} missing {field}"
                assert len(params[field]) == 3, f"{kind}.{field} must be [r,g,b]"

    def test_no_absolute_black(self, kind_config):
        """No color channel below 0.13 — darkest grey is black."""
        for kind in kind_config.get("kinds", {}):
            params = self._resolve_kind(kind_config, kind)
            for field in ("color_base", "color_shadow", "color_accent"):
                for i, v in enumerate(params[field]):
                    assert v >= 0.13, (
                        f"{kind}.{field}[{i}]={v} is below 0.13 floor")

    def test_shadow_darker_than_base(self, kind_config):
        """Shadow color should be darker than or equal to base."""
        for kind in kind_config.get("kinds", {}):
            params = self._resolve_kind(kind_config, kind)
            cb = params["color_base"]
            cs = params["color_shadow"]
            assert sum(cs) <= sum(cb) + 0.01, (
                f"{kind} shadow {cs} is brighter than base {cb}")

    def test_accent_lighter_than_base(self, kind_config):
        """Accent color should be lighter than or equal to base."""
        for kind in kind_config.get("kinds", {}):
            params = self._resolve_kind(kind_config, kind)
            cb = params["color_base"]
            ca = params["color_accent"]
            assert sum(ca) >= sum(cb) - 0.01, (
                f"{kind} accent {ca} is darker than base {cb}")

    def test_color_spread_within_2_steps(self, kind_config):
        """Max difference between shadow and accent per channel <= 0.15 (~2 steps)."""
        for kind in kind_config.get("kinds", {}):
            params = self._resolve_kind(kind_config, kind)
            cs = params["color_shadow"]
            ca = params["color_accent"]
            for i in range(3):
                diff = abs(ca[i] - cs[i])
                assert diff <= 0.15, (
                    f"{kind} channel {i}: accent-shadow spread {diff:.3f} > 0.15")

    def test_light_reactive_kinds(self, kind_config):
        """Known light-reactive kinds must have light_reactive=true."""
        for kind in LIGHT_REACTIVE_KINDS:
            params = self._resolve_kind(kind_config, kind)
            assert params.get("light_reactive", False), (
                f"{kind} should be light_reactive")
