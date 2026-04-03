"""
tests/test_frame_composer.py

FrameComposer — directed wandering via composed spatial frames.
Pure geometry tests — no rendering, no Panda3D.
"""

import math
import pytest

from core.systems.frame_composer import FrameComposer, FRAMING_CONFIG


# -- Config validation ---------------------------------------------------------

class TestFramingConfig:

    def test_cavern_config_exists(self):
        assert "cavern" in FRAMING_CONFIG

    def test_outdoor_config_exists(self):
        assert "outdoor" in FRAMING_CONFIG

    def test_required_keys(self):
        required = ["frame_kinds", "accent_kinds", "pair_spacing", "gap_width",
                     "nudge_bias", "min_walkable", "frame_collision"]
        for biome in ["cavern", "outdoor"]:
            for key in required:
                assert key in FRAMING_CONFIG[biome], f"{biome} missing '{key}'"

    def test_pair_spacing_is_range(self):
        for biome in FRAMING_CONFIG:
            ps = FRAMING_CONFIG[biome]["pair_spacing"]
            assert len(ps) == 2
            assert ps[0] < ps[1], f"{biome} pair_spacing min >= max"

    def test_min_walkable_positive(self):
        """Minimum walkable gap must be positive."""
        for biome in FRAMING_CONFIG:
            assert FRAMING_CONFIG[biome]["min_walkable"] >= 3.0

    def test_nudge_bias_valid_probability(self):
        for biome in FRAMING_CONFIG:
            nb = FRAMING_CONFIG[biome]["nudge_bias"]
            assert 0.0 <= nb <= 1.0


# -- compose_along_path --------------------------------------------------------

class TestComposeAlongPath:
    """Core function: given two hex nodes, compose framing pairs between them."""

    def setup_method(self):
        self.composer = FrameComposer(seed=42)

    def test_returns_list_of_placements(self):
        result = self.composer.compose_along_path(
            node_a=(0, 0), node_b=(40, 0), config=FRAMING_CONFIG["cavern"])
        assert isinstance(result, list)
        assert len(result) > 0

    def test_placements_have_required_fields(self):
        result = self.composer.compose_along_path(
            node_a=(0, 0), node_b=(40, 0), config=FRAMING_CONFIG["cavern"])
        for placement in result:
            assert "kind" in placement
            assert "pos" in placement
            assert "heading" in placement
            assert "role" in placement  # "frame_left", "frame_right", or "accent"

    def test_frame_kinds_from_config(self):
        cfg = FRAMING_CONFIG["cavern"]
        result = self.composer.compose_along_path(
            node_a=(0, 0), node_b=(40, 0), config=cfg)
        frame_kinds = {p["kind"] for p in result if p["role"].startswith("frame")}
        for k in frame_kinds:
            assert k in cfg["frame_kinds"], f"Frame kind '{k}' not in config"

    def test_accent_kinds_from_config(self):
        cfg = FRAMING_CONFIG["cavern"]
        result = self.composer.compose_along_path(
            node_a=(0, 0), node_b=(40, 0), config=cfg)
        accent_kinds = {p["kind"] for p in result if p["role"] == "accent"}
        for k in accent_kinds:
            assert k in cfg["accent_kinds"], f"Accent kind '{k}' not in config"

    def test_produces_at_least_one_frame_pair(self):
        """Minimum: 2 frame objects + 1 accent."""
        result = self.composer.compose_along_path(
            node_a=(0, 0), node_b=(40, 0), config=FRAMING_CONFIG["cavern"])
        frames = [p for p in result if p["role"].startswith("frame")]
        accents = [p for p in result if p["role"] == "accent"]
        assert len(frames) >= 2, f"Expected >= 2 frames, got {len(frames)}"
        assert len(accents) >= 1, f"Expected >= 1 accent, got {len(accents)}"

    def test_frame_pair_flanks_the_path(self):
        """Left frame and right frame should be on opposite sides of the path midpoint."""
        result = self.composer.compose_along_path(
            node_a=(0, 0), node_b=(40, 0), config=FRAMING_CONFIG["cavern"])
        lefts = [p for p in result if p["role"] == "frame_left"]
        rights = [p for p in result if p["role"] == "frame_right"]
        if lefts and rights:
            # Path is along X axis — left should have negative Y, right positive Y
            # (or vice versa, depending on perpendicular direction)
            l_y = lefts[0]["pos"][1]
            r_y = rights[0]["pos"][1]
            assert l_y != r_y, "Left and right frames should not be at same Y"

    def test_accent_between_frames(self):
        """Accent should be near the path midpoint, between the frame pair."""
        result = self.composer.compose_along_path(
            node_a=(0, 0), node_b=(40, 0), config=FRAMING_CONFIG["cavern"])
        accents = [p for p in result if p["role"] == "accent"]
        if accents:
            ax = accents[0]["pos"][0]
            # Should be roughly between node_a (0) and node_b (20)
            assert 2.0 <= ax <= 18.0, f"Accent at x={ax}, expected near midpoint"

    def test_gap_width_respected(self):
        """Distance between left and right frame should leave walkable space."""
        cfg = FRAMING_CONFIG["outdoor"]
        result = self.composer.compose_along_path(
            node_a=(0, 0), node_b=(40, 0), config=cfg)
        lefts = [p for p in result if p["role"] == "frame_left"]
        rights = [p for p in result if p["role"] == "frame_right"]
        if lefts and rights:
            lp = lefts[0]["pos"]
            rp = rights[0]["pos"]
            dist = math.sqrt((lp[0] - rp[0]) ** 2 + (lp[1] - rp[1]) ** 2)
            # After subtracting collision radii, must have min_walkable clearance
            frame_coll = cfg["frame_collision"]
            l_coll = frame_coll.get(lefts[0]["kind"], 3.0)
            r_coll = frame_coll.get(rights[0]["kind"], 3.0)
            walkable = dist - l_coll - r_coll
            assert walkable >= cfg["min_walkable"] * 0.8, \
                f"Walkable gap {walkable:.1f}m too narrow (need {cfg['min_walkable']}m)"

    def test_deterministic_with_same_seed(self):
        c1 = FrameComposer(seed=99)
        c2 = FrameComposer(seed=99)
        r1 = c1.compose_along_path((0, 0), (20, 0), FRAMING_CONFIG["cavern"])
        r2 = c2.compose_along_path((0, 0), (20, 0), FRAMING_CONFIG["cavern"])
        assert len(r1) == len(r2)
        for p1, p2 in zip(r1, r2):
            assert p1["kind"] == p2["kind"]
            assert p1["pos"] == p2["pos"]

    def test_different_seeds_differ(self):
        c1 = FrameComposer(seed=1)
        c2 = FrameComposer(seed=9999)
        r1 = c1.compose_along_path((0, 0), (20, 0), FRAMING_CONFIG["cavern"])
        r2 = c2.compose_along_path((0, 0), (20, 0), FRAMING_CONFIG["cavern"])
        # At least one placement should differ (positions are seeded)
        positions_1 = [p["pos"] for p in r1]
        positions_2 = [p["pos"] for p in r2]
        assert positions_1 != positions_2

    def test_outdoor_config_produces_results(self):
        result = self.composer.compose_along_path(
            node_a=(0, 0), node_b=(25, 0), config=FRAMING_CONFIG["outdoor"])
        assert len(result) >= 3  # at least one frame pair + accent


# -- Nudge bias ----------------------------------------------------------------

class TestNudgeBias:
    """Off-center placement to suggest turns."""

    def test_nudge_shifts_accent_off_center(self):
        """With nudge_bias=1.0, accent should be offset from path centerline."""
        cfg = dict(FRAMING_CONFIG["cavern"])
        cfg["nudge_bias"] = 1.0  # always nudge
        composer = FrameComposer(seed=42)
        result = composer.compose_along_path(
            node_a=(0, 0), node_b=(40, 0), config=cfg)
        accents = [p for p in result if p["role"] == "accent"]
        if accents:
            # With path along X axis, nudge should offset Y from centerline (0)
            ay = accents[0]["pos"][1]
            assert abs(ay) > 0.5, f"Accent Y={ay} too close to centerline for full nudge"

    def test_zero_nudge_keeps_accent_centered(self):
        cfg = dict(FRAMING_CONFIG["cavern"])
        cfg["nudge_bias"] = 0.0
        composer = FrameComposer(seed=42)
        result = composer.compose_along_path(
            node_a=(0, 0), node_b=(40, 0), config=cfg)
        accents = [p for p in result if p["role"] == "accent"]
        if accents:
            ay = accents[0]["pos"][1]
            assert abs(ay) < 2.0, f"Accent Y={ay} too far from centerline for zero nudge"


# -- Short paths ---------------------------------------------------------------

class TestShortPaths:
    """Paths shorter than pair_spacing should still produce minimal composition."""

    def test_very_short_path(self):
        """5m path should produce at least a minimal frame."""
        composer = FrameComposer(seed=42)
        result = composer.compose_along_path(
            node_a=(0, 0), node_b=(5, 0), config=FRAMING_CONFIG["cavern"])
        # Short paths might produce fewer placements but shouldn't crash
        assert isinstance(result, list)

    def test_zero_length_path(self):
        """Same node twice — should return empty, not crash."""
        composer = FrameComposer(seed=42)
        result = composer.compose_along_path(
            node_a=(10, 10), node_b=(10, 10), config=FRAMING_CONFIG["cavern"])
        assert isinstance(result, list)
        assert len(result) == 0
