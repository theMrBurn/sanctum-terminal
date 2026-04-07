"""Tests for projection banner layer configuration."""

import pytest

from core.systems.biome_data import (
    CAVERN_BANNER_LAYERS, OUTDOOR_BANNER_LAYERS, BIOME_REGISTRY,
)


# -- Config integrity ----------------------------------------------------------

class TestBannerLayerConfig:
    """Banner layer definitions follow the factor-of-7 architecture."""

    @pytest.mark.parametrize("layers,label", [
        (CAVERN_BANNER_LAYERS, "cavern"),
        (OUTDOOR_BANNER_LAYERS, "outdoor"),
    ])
    def test_exactly_seven_layers(self, layers, label):
        assert len(layers) == 7, (
            f"{label} banner must have exactly 7 layers (Merkabah), got {len(layers)}")

    @pytest.mark.parametrize("layers,label", [
        (CAVERN_BANNER_LAYERS, "cavern"),
        (OUTDOOR_BANNER_LAYERS, "outdoor"),
    ])
    def test_required_fields(self, layers, label):
        for i, layer in enumerate(layers):
            assert "distance" in layer, f"{label}[{i}] missing distance"
            assert "height" in layer, f"{label}[{i}] missing height"
            assert "opacity" in layer, f"{label}[{i}] missing opacity"
            assert "role" in layer, f"{label}[{i}] missing role"
            assert "tint" in layer, f"{label}[{i}] missing tint"

    @pytest.mark.parametrize("layers,label", [
        (CAVERN_BANNER_LAYERS, "cavern"),
        (OUTDOOR_BANNER_LAYERS, "outdoor"),
    ])
    def test_distances_are_factor_of_7(self, layers, label):
        """Each layer distance should be a multiple of 7m."""
        for i, layer in enumerate(layers):
            d = layer["distance"]
            assert d % 7.0 == 0, (
                f"{label}[{i}] distance={d} is not a factor of 7")

    @pytest.mark.parametrize("layers,label", [
        (CAVERN_BANNER_LAYERS, "cavern"),
        (OUTDOOR_BANNER_LAYERS, "outdoor"),
    ])
    def test_distances_monotonically_increase(self, layers, label):
        for i in range(len(layers) - 1):
            assert layers[i]["distance"] < layers[i + 1]["distance"], (
                f"{label} distances must increase: [{i}]={layers[i]['distance']} "
                f">= [{i+1}]={layers[i+1]['distance']}")

    @pytest.mark.parametrize("layers,label", [
        (CAVERN_BANNER_LAYERS, "cavern"),
        (OUTDOOR_BANNER_LAYERS, "outdoor"),
    ])
    def test_opacity_increases_with_distance(self, layers, label):
        """Farther layers should be more opaque (atmospheric buildup)."""
        for i in range(len(layers) - 1):
            assert layers[i]["opacity"] <= layers[i + 1]["opacity"], (
                f"{label} opacity must increase with distance: "
                f"[{i}]={layers[i]['opacity']} > [{i+1}]={layers[i+1]['opacity']}")

    @pytest.mark.parametrize("layers,label", [
        (CAVERN_BANNER_LAYERS, "cavern"),
        (OUTDOOR_BANNER_LAYERS, "outdoor"),
    ])
    def test_opacity_range(self, layers, label):
        for i, layer in enumerate(layers):
            o = layer["opacity"]
            assert 0.0 < o < 1.0, (
                f"{label}[{i}] opacity={o} must be in (0.0, 1.0)")

    @pytest.mark.parametrize("layers,label", [
        (CAVERN_BANNER_LAYERS, "cavern"),
        (OUTDOOR_BANNER_LAYERS, "outdoor"),
    ])
    def test_tint_is_rgb_triplet(self, layers, label):
        for i, layer in enumerate(layers):
            t = layer["tint"]
            assert len(t) == 3, f"{label}[{i}] tint must be [R, G, B]"
            for c in t:
                assert 0.0 <= c <= 1.0, (
                    f"{label}[{i}] tint value {c} out of range")

    @pytest.mark.parametrize("layers,label", [
        (CAVERN_BANNER_LAYERS, "cavern"),
        (OUTDOOR_BANNER_LAYERS, "outdoor"),
    ])
    def test_unique_roles(self, layers, label):
        roles = [l["role"] for l in layers]
        assert len(roles) == len(set(roles)), (
            f"{label} has duplicate roles: {roles}")

    @pytest.mark.parametrize("layers,label", [
        (CAVERN_BANNER_LAYERS, "cavern"),
        (OUTDOOR_BANNER_LAYERS, "outdoor"),
    ])
    def test_height_positive(self, layers, label):
        for i, layer in enumerate(layers):
            assert layer["height"] > 0, (
                f"{label}[{i}] height must be positive")

    def test_banner_layers_in_biome_registry(self):
        for biome in ("cavern", "outdoor"):
            reg = BIOME_REGISTRY[biome]
            assert "banner_layers" in reg, (
                f"{biome} registry missing banner_layers")
            assert len(reg["banner_layers"]) == 7
