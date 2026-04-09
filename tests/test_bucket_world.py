"""
tests/test_bucket_world.py

bucket_world — pure function world generation. No cache, no shells,
no scoring. spawn_bucket(bx, by, seed, biome) returns the entities for
one 16m bucket. get_visible(cam_x, cam_y, radius) collects all entities
from buckets that overlap the visible circle.

Old roguelike approach. Hardware is fast enough to run it every frame.
"""

import math
import pytest

from core.systems.biome_data import BIOME_REGISTRY


# ---------------------------------------------------------------------------
# spawn_bucket — pure function
# ---------------------------------------------------------------------------

class TestSpawnBucket:
    """spawn_bucket is pure: same input → same output, no side effects."""

    def test_returns_list_of_dicts(self):
        from core.systems.bucket_world import spawn_bucket
        roster = spawn_bucket(0, 0, seed=42, biome_name="cavern")
        assert isinstance(roster, list)
        for ent in roster:
            assert isinstance(ent, dict)
            assert "kind" in ent
            assert "x" in ent
            assert "y" in ent

    def test_deterministic_same_inputs_same_output(self):
        from core.systems.bucket_world import spawn_bucket
        a = spawn_bucket(3, -2, seed=42, biome_name="cavern")
        b = spawn_bucket(3, -2, seed=42, biome_name="cavern")
        assert len(a) == len(b)
        for ea, eb in zip(a, b):
            assert ea["kind"] == eb["kind"]
            assert ea["x"] == eb["x"]
            assert ea["y"] == eb["y"]

    def test_different_buckets_different_rosters(self):
        from core.systems.bucket_world import spawn_bucket
        a = spawn_bucket(0, 0, seed=42, biome_name="cavern")
        b = spawn_bucket(1, 0, seed=42, biome_name="cavern")
        # Different bucket coords → different positions at minimum
        a_pos = {(round(e["x"], 1), round(e["y"], 1)) for e in a}
        b_pos = {(round(e["x"], 1), round(e["y"], 1)) for e in b}
        assert a_pos != b_pos or (len(a) == 0 and len(b) == 0)

    def test_entities_within_bucket_bounds(self):
        from core.systems.bucket_world import spawn_bucket, BUCKET_SIZE
        bx, by = 5, -3
        roster = spawn_bucket(bx, by, seed=42, biome_name="cavern")
        x_min = bx * BUCKET_SIZE
        x_max = (bx + 1) * BUCKET_SIZE
        y_min = by * BUCKET_SIZE
        y_max = (by + 1) * BUCKET_SIZE
        for ent in roster:
            assert x_min <= ent["x"] <= x_max, f"{ent['kind']} x out of bucket"
            assert y_min <= ent["y"] <= y_max, f"{ent['kind']} y out of bucket"

    def test_entities_have_required_fields(self):
        from core.systems.bucket_world import spawn_bucket
        roster = spawn_bucket(0, 0, seed=42, biome_name="cavern")
        if not roster:
            pytest.skip("Empty bucket — skip field check")
        ent = roster[0]
        for field in ("kind", "x", "y", "z", "sx", "sy", "sz", "r", "g", "b",
                      "heading", "emissive"):
            assert field in ent, f"Missing field: {field}"


class TestSpawnBucketDensity:
    """Density rolls match the biome density table over many buckets."""

    def test_average_density_approximates_biome_table(self):
        """Over 100 buckets, count of each kind should be close to expected."""
        from core.systems.bucket_world import spawn_bucket, BUCKET_SIZE
        from core.systems.biome_data import BIOME_CAVERN_DEFAULT

        bucket_area_sqm = BUCKET_SIZE * BUCKET_SIZE
        n_buckets = 100
        kind_counts = {}
        for bx in range(10):
            for by in range(10):
                for ent in spawn_bucket(bx, by, seed=42, biome_name="cavern"):
                    kind_counts[ent["kind"]] = kind_counts.get(ent["kind"], 0) + 1

        # Check a few high-density kinds — they should appear at all
        assert "boulder" in kind_counts, "boulder should appear in 100 buckets at density 1.20"
        assert "stalagmite" in kind_counts, "stalagmite should appear in 100 buckets at density 1.80"

        # Stalagmite expected: 1.80 / 1000 * 256 * 100 = 46 entities
        # Allow 50% variance
        expected_stalag = 1.80 / 1000.0 * bucket_area_sqm * n_buckets
        assert kind_counts["stalagmite"] > expected_stalag * 0.4, \
            f"stalagmite count {kind_counts['stalagmite']} too low (expected ~{expected_stalag:.0f})"


# ---------------------------------------------------------------------------
# get_visible — radius-based collection
# ---------------------------------------------------------------------------

class TestGetVisible:
    """get_visible collects entities from buckets overlapping the visible circle."""

    def test_returns_entities_near_camera(self):
        from core.systems.bucket_world import get_visible
        ents = get_visible(cam_x=0, cam_y=0, radius=49,
                           seed=42, biome_name="cavern")
        assert len(ents) > 0

    def test_all_entities_within_radius(self):
        from core.systems.bucket_world import get_visible
        cam_x, cam_y, radius = 50.0, -30.0, 49.0
        ents = get_visible(cam_x=cam_x, cam_y=cam_y, radius=radius,
                           seed=42, biome_name="cavern")
        for ent in ents:
            dx = ent["x"] - cam_x
            dy = ent["y"] - cam_y
            dist = math.sqrt(dx * dx + dy * dy)
            assert dist <= radius, f"{ent['kind']} at dist {dist:.1f} > radius {radius}"

    def test_walking_changes_visible_set(self):
        """Different camera positions → different visible entities."""
        from core.systems.bucket_world import get_visible
        a = get_visible(cam_x=0, cam_y=0, radius=49,
                        seed=42, biome_name="cavern")
        b = get_visible(cam_x=200, cam_y=200, radius=49,
                        seed=42, biome_name="cavern")
        a_set = {(e["kind"], round(e["x"], 1), round(e["y"], 1)) for e in a}
        b_set = {(e["kind"], round(e["x"], 1), round(e["y"], 1)) for e in b}
        assert a_set != b_set

    def test_returning_to_position_returns_same_entities(self):
        """Determinism: walking away and back gives the same entities."""
        from core.systems.bucket_world import get_visible
        a = get_visible(cam_x=10, cam_y=20, radius=49,
                        seed=42, biome_name="cavern")
        # walk far away
        get_visible(cam_x=500, cam_y=500, radius=49,
                    seed=42, biome_name="cavern")
        # come back
        b = get_visible(cam_x=10, cam_y=20, radius=49,
                        seed=42, biome_name="cavern")
        a_set = {(e["kind"], round(e["x"], 2), round(e["y"], 2)) for e in a}
        b_set = {(e["kind"], round(e["x"], 2), round(e["y"], 2)) for e in b}
        assert a_set == b_set, "Determinism broken — same position should give same entities"

    def test_no_caching_means_no_state(self):
        """get_visible has no internal state — fresh module call works."""
        from core.systems.bucket_world import get_visible
        ents = get_visible(cam_x=0, cam_y=0, radius=49,
                           seed=42, biome_name="cavern")
        # Just check it didn't crash and returned something
        assert isinstance(ents, list)

    def test_unlimited_generation_in_any_direction(self):
        """Walking far in any direction should still produce entities."""
        from core.systems.bucket_world import get_visible
        for cx, cy in [(1000, 0), (-1000, 0), (0, 1000), (0, -1000),
                       (5000, 5000), (-3000, 7000)]:
            ents = get_visible(cam_x=cx, cam_y=cy, radius=49,
                               seed=42, biome_name="cavern")
            assert len(ents) > 0, f"No entities at far position ({cx}, {cy})"
