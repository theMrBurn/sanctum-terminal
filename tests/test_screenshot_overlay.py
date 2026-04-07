"""Tests for screenshot telemetry overlay config.

TDD: config shape defined here, then implemented in kind_config.json
and consumed by main.gd _save_tag().

The overlay burns a single telemetry line into every screenshot PNG so
Claude (or any reviewer) can read position, entity counts, and scene
state directly from the image without needing a paired tag JSON.
"""

import json
from pathlib import Path

import pytest


KIND_CONFIG_PATH = Path(__file__).parent.parent / "godot" / "kind_config.json"


@pytest.fixture(scope="module")
def kind_config():
    with open(KIND_CONFIG_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def overlay_cfg(kind_config):
    return kind_config["_global"]["screenshot_overlay"]


# -- Config existence ----------------------------------------------------------

class TestScreenshotOverlayConfig:
    """_global.screenshot_overlay must exist with required fields."""

    def test_overlay_section_exists(self, kind_config):
        assert "screenshot_overlay" in kind_config["_global"], (
            "_global missing screenshot_overlay config")

    def test_enabled_is_bool(self, overlay_cfg):
        assert isinstance(overlay_cfg["enabled"], bool)

    def test_font_size_positive_int(self, overlay_cfg):
        fs = overlay_cfg["font_size"]
        assert isinstance(fs, int) and fs > 0, (
            f"font_size must be positive int, got {fs}")

    def test_position_is_valid(self, overlay_cfg):
        valid = ("top_left", "top_right", "bottom_left", "bottom_right")
        assert overlay_cfg["position"] in valid, (
            f"position must be one of {valid}")

    def test_color_is_rgba(self, overlay_cfg):
        c = overlay_cfg["color"]
        assert len(c) == 4, "color must be [R, G, B, A]"
        for v in c:
            assert 0.0 <= v <= 1.0, f"color value {v} out of range"

    def test_fields_is_list(self, overlay_cfg):
        assert isinstance(overlay_cfg["fields"], list)
        assert len(overlay_cfg["fields"]) >= 1, "need at least one field"


# -- Field validation ----------------------------------------------------------

VALID_FIELDS = {
    "biome", "position", "heading", "fov", "tension_state", "tension_budget",
    "entities_visible", "day_phase", "tiles", "outline_mode",
    "kind_summary", "timestamp",
}


class TestOverlayFields:
    """Each field in the overlay config must map to available telemetry."""

    def test_all_fields_recognized(self, overlay_cfg):
        for f in overlay_cfg["fields"]:
            assert f in VALID_FIELDS, (
                f"unrecognized overlay field '{f}', valid: {sorted(VALID_FIELDS)}")

    def test_position_field_present(self, overlay_cfg):
        """Position is the most useful field for cross-referencing screenshots."""
        assert "position" in overlay_cfg["fields"]

    def test_entities_visible_present(self, overlay_cfg):
        assert "entities_visible" in overlay_cfg["fields"]

    def test_biome_present(self, overlay_cfg):
        assert "biome" in overlay_cfg["fields"]


# -- Format contract -----------------------------------------------------------

class TestOverlayFormat:
    """The overlay format must produce a readable single line."""

    def test_separator_is_string(self, overlay_cfg):
        assert isinstance(overlay_cfg.get("separator", " | "), str)

    def test_background_is_bool(self, overlay_cfg):
        """Semi-transparent background behind text for readability."""
        assert isinstance(overlay_cfg["background"], bool)
