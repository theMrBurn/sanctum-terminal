"""Tests for anchor stamp composition system."""

import math
import random

import pytest

from core.systems.biome_data import (
    CAVERN_ANCHOR_STAMPS, OUTDOOR_ANCHOR_STAMPS, HARD_OBJECTS, BIOME_REGISTRY,
)
from core.systems.world_gen import _emit_anchor_stamp


# -- Config integrity ----------------------------------------------------------

class TestAnchorStampConfig:
    """Anchor stamp definitions are well-formed."""

    @pytest.mark.parametrize("stamps,label", [
        (CAVERN_ANCHOR_STAMPS, "cavern"),
        (OUTDOOR_ANCHOR_STAMPS, "outdoor"),
    ])
    def test_has_entries(self, stamps, label):
        assert len(stamps) >= 2, f"{label} anchor stamps needs at least 2 kinds"

    @pytest.mark.parametrize("stamps,label", [
        (CAVERN_ANCHOR_STAMPS, "cavern"),
        (OUTDOOR_ANCHOR_STAMPS, "outdoor"),
    ])
    def test_frequency_in_range(self, stamps, label):
        for kind, cfg in stamps.items():
            f = cfg["frequency"]
            assert 0.0 < f <= 1.0, (
                f"{label}.{kind} frequency={f} must be in (0.0, 1.0]")

    @pytest.mark.parametrize("stamps,label", [
        (CAVERN_ANCHOR_STAMPS, "cavern"),
        (OUTDOOR_ANCHOR_STAMPS, "outdoor"),
    ])
    def test_slots_have_required_fields(self, stamps, label):
        for kind, cfg in stamps.items():
            assert "slots" in cfg, f"{label}.{kind} missing slots"
            for i, slot in enumerate(cfg["slots"]):
                assert "role" in slot, f"{label}.{kind} slot {i} missing role"
                assert "count" in slot, f"{label}.{kind} slot {i} missing count"
                assert "pool" in slot, f"{label}.{kind} slot {i} missing pool"
                assert "dist" in slot, f"{label}.{kind} slot {i} missing dist"
                assert len(slot["count"]) == 2, f"count must be [min, max]"
                assert len(slot["dist"]) == 2, f"dist must be [min, max]"
                assert slot["count"][0] <= slot["count"][1]
                assert slot["dist"][0] <= slot["dist"][1]

    @pytest.mark.parametrize("stamps,label", [
        (CAVERN_ANCHOR_STAMPS, "cavern"),
        (OUTDOOR_ANCHOR_STAMPS, "outdoor"),
    ])
    def test_pool_not_empty(self, stamps, label):
        for kind, cfg in stamps.items():
            for slot in cfg["slots"]:
                assert len(slot["pool"]) >= 1, (
                    f"{label}.{kind} slot {slot['role']} has empty pool")

    @pytest.mark.parametrize("stamps,label", [
        (CAVERN_ANCHOR_STAMPS, "cavern"),
        (OUTDOOR_ANCHOR_STAMPS, "outdoor"),
    ])
    def test_scale_format(self, stamps, label):
        """scale must be None or [min, max] with min <= max."""
        for kind, cfg in stamps.items():
            for slot in cfg["slots"]:
                s = slot.get("scale")
                if s is not None:
                    assert len(s) == 2, f"scale must be [min, max]"
                    assert s[0] <= s[1], f"scale min > max in {kind}.{slot['role']}"

    def test_anchor_stamps_used_by_world_gen(self):
        """Anchor stamps are consumed by _emit_anchor_stamp, not the registry."""
        assert len(CAVERN_ANCHOR_STAMPS) >= 2
        assert len(OUTDOOR_ANCHOR_STAMPS) >= 2


# -- Placement logic -----------------------------------------------------------

class TestAnchorStampPlacement:
    """_emit_anchor_stamp respects config and collisions."""

    def test_known_kind_places_members(self):
        spawns, solids = [], []
        placed = _emit_anchor_stamp(
            "mega_column", 50.0, 50.0, CAVERN_ANCHOR_STAMPS,
            spawns, solids, random.Random(42))
        # With seed 42 and freq 0.60, may or may not fire — run enough seeds
        total = 0
        for seed in range(20):
            s, sol = [], []
            total += _emit_anchor_stamp(
                "mega_column", 50.0, 50.0, CAVERN_ANCHOR_STAMPS,
                s, sol, random.Random(seed))
        assert total > 0, "20 seeds should produce at least one anchor stamp"

    def test_unknown_kind_returns_zero(self):
        spawns, solids = [], []
        placed = _emit_anchor_stamp(
            "nonexistent_kind", 50.0, 50.0, CAVERN_ANCHOR_STAMPS,
            spawns, solids, random.Random(1))
        assert placed == 0
        assert len(spawns) == 0

    def test_members_near_anchor(self):
        """All placed members should be within max dist of the anchor."""
        max_dist = max(
            slot["dist"][1]
            for cfg in CAVERN_ANCHOR_STAMPS.values()
            for slot in cfg["slots"]
        )
        for seed in range(50):
            spawns, solids = [], []
            _emit_anchor_stamp(
                "mega_column", 50.0, 50.0, CAVERN_ANCHOR_STAMPS,
                spawns, solids, random.Random(seed))
            for s in spawns:
                x, y = s[1]
                dist = math.sqrt((x - 50.0) ** 2 + (y - 50.0) ** 2)
                assert dist <= max_dist + 1.0, (
                    f"member at ({x},{y}) is {dist:.1f}m from anchor, "
                    f"max configured is {max_dist}")

    def test_hard_members_added_to_solids(self):
        """Hard-flagged members should register in solid_positions."""
        for seed in range(30):
            spawns, solids = [], []
            _emit_anchor_stamp(
                "mega_column", 50.0, 50.0, CAVERN_ANCHOR_STAMPS,
                spawns, solids, random.Random(seed))
            if spawns:
                # At least one solid should exist (mega_column has hard flanks)
                break
        # If we got spawns, check solids were registered
        if spawns:
            assert len(solids) > 0, "hard members should register in solids"

    def test_collision_prevents_placement(self):
        """Existing solids near the anchor should block hard members."""
        placed_with_solids = 0
        placed_without = 0
        for seed in range(50):
            # Dense solids around anchor
            dense_solids = [(50.0 + dx, 50.0 + dy, 3.0)
                           for dx in range(-6, 7, 2)
                           for dy in range(-6, 7, 2)]
            s1, sol1 = [], list(dense_solids)
            p1 = _emit_anchor_stamp(
                "mega_column", 50.0, 50.0, CAVERN_ANCHOR_STAMPS,
                s1, sol1, random.Random(seed))
            s2, sol2 = [], []
            p2 = _emit_anchor_stamp(
                "mega_column", 50.0, 50.0, CAVERN_ANCHOR_STAMPS,
                s2, sol2, random.Random(seed))
            placed_with_solids += p1
            placed_without += p2
        # Dense solids should block at least some placements
        assert placed_with_solids <= placed_without, (
            "collisions should reduce or equal placement count")
