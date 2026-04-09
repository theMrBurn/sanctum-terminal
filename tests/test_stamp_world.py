"""
tests/test_stamp_world.py

stamp_world — pure function world generation from the authored stamp
library. The world is an infinite grid of slots; each slot picks one
stamp deterministically from CAVERN_STAMPS or OUTDOOR_STAMPS, plus a
small tissue scatter for connector terrain.

Walk anywhere, you see authored content. The seed IS the world.
"""

import math
import pytest

from core.systems.biome_data import BIOME_REGISTRY, CAVERN_STAMPS, OUTDOOR_STAMPS


# ---------------------------------------------------------------------------
# stamp_at — pure slot lookup
# ---------------------------------------------------------------------------

class TestStampAt:
    """stamp_at(gx, gy, seed, biome) returns the entities at one slot."""

    def test_returns_list_of_entity_dicts(self):
        from core.systems.stamp_world import stamp_at
        roster = stamp_at(0, 0, seed=42, biome_name="cavern")
        assert isinstance(roster, list)
        for ent in roster:
            assert "kind" in ent
            assert "x" in ent
            assert "y" in ent

    def test_deterministic(self):
        """Same coords + seed → same stamp choice + same positions."""
        from core.systems.stamp_world import stamp_at
        a = stamp_at(3, -2, seed=42, biome_name="cavern")
        b = stamp_at(3, -2, seed=42, biome_name="cavern")
        assert len(a) == len(b)
        for ea, eb in zip(a, b):
            assert ea["kind"] == eb["kind"]
            assert ea["x"] == eb["x"]
            assert ea["y"] == eb["y"]

    def test_different_slots_different_stamps(self):
        """Adjacent slots should produce different content."""
        from core.systems.stamp_world import stamp_at
        a = stamp_at(0, 0, seed=42, biome_name="cavern")
        b = stamp_at(1, 0, seed=42, biome_name="cavern")
        a_kinds = sorted(e["kind"] for e in a)
        b_kinds = sorted(e["kind"] for e in b)
        # Either different stamp choice OR different positions
        a_pos = sorted((e["x"], e["y"]) for e in a)
        b_pos = sorted((e["x"], e["y"]) for e in b)
        assert a_kinds != b_kinds or a_pos != b_pos

    def test_entities_centered_on_slot(self):
        """Stamp members should cluster near the slot center."""
        from core.systems.stamp_world import stamp_at, SLOT_SIZE
        gx, gy = 5, -3
        cx = (gx + 0.5) * SLOT_SIZE
        cy = (gy + 0.5) * SLOT_SIZE
        roster = stamp_at(gx, gy, seed=42, biome_name="cavern")
        # All entities should be within slot bounds (slot half-width = SLOT_SIZE/2)
        for ent in roster:
            assert abs(ent["x"] - cx) <= SLOT_SIZE, f"{ent['kind']} x out of slot"
            assert abs(ent["y"] - cy) <= SLOT_SIZE, f"{ent['kind']} y out of slot"

    def test_picks_stamp_from_library(self):
        """The kinds in a slot should match SOME stamp's member kinds."""
        from core.systems.stamp_world import stamp_at
        roster = stamp_at(0, 0, seed=42, biome_name="cavern")
        # Build set of all kinds appearing in any stamp
        all_stamp_kinds = set()
        for stamp in CAVERN_STAMPS:
            for m in stamp["members"]:
                all_stamp_kinds.add(m["kind"])
        # Tissue scatter kinds — allowed even if not in any stamp
        tissue_kinds = {"grass_tuft", "rubble", "cave_gravel", "moss_patch",
                        "leaf_pile", "twig_scatter", "leaf_pile"}
        for ent in roster:
            assert ent["kind"] in (all_stamp_kinds | tissue_kinds), \
                f"{ent['kind']} not in stamp library or tissue"

    def test_outdoor_biome_uses_outdoor_stamps(self):
        from core.systems.stamp_world import stamp_at
        roster = stamp_at(0, 0, seed=42, biome_name="outdoor")
        # Should pick from OUTDOOR_STAMPS, not CAVERN_STAMPS
        outdoor_kinds = set()
        for stamp in OUTDOOR_STAMPS:
            for m in stamp["members"]:
                outdoor_kinds.add(m["kind"])
        # At least the dominant stamp member should be an outdoor kind
        assert any(e["kind"] in outdoor_kinds for e in roster), \
            "No outdoor stamp kinds in outdoor biome slot"


# ---------------------------------------------------------------------------
# get_visible — radius-based slot collection
# ---------------------------------------------------------------------------

class TestGetVisible:
    """get_visible collects entities from slots overlapping the camera circle."""

    def test_returns_entities_near_camera(self):
        from core.systems.stamp_world import get_visible
        ents = get_visible(cam_x=0, cam_y=0, radius=49,
                           seed=42, biome_name="cavern")
        assert len(ents) > 0

    def test_all_within_radius(self):
        from core.systems.stamp_world import get_visible
        cam_x, cam_y, radius = 50.0, -30.0, 49.0
        ents = get_visible(cam_x=cam_x, cam_y=cam_y, radius=radius,
                           seed=42, biome_name="cavern")
        for ent in ents:
            dx = ent["x"] - cam_x
            dy = ent["y"] - cam_y
            assert math.sqrt(dx * dx + dy * dy) <= radius

    def test_walking_changes_visible_set(self):
        from core.systems.stamp_world import get_visible
        a = get_visible(cam_x=0, cam_y=0, radius=49,
                        seed=42, biome_name="cavern")
        b = get_visible(cam_x=200, cam_y=200, radius=49,
                        seed=42, biome_name="cavern")
        a_set = {(e["kind"], round(e["x"], 1), round(e["y"], 1)) for e in a}
        b_set = {(e["kind"], round(e["x"], 1), round(e["y"], 1)) for e in b}
        assert a_set != b_set

    def test_returning_to_position_returns_same_entities(self):
        """Determinism: walking away and back gives the same entities."""
        from core.systems.stamp_world import get_visible
        a = get_visible(cam_x=10, cam_y=20, radius=49,
                        seed=42, biome_name="cavern")
        get_visible(cam_x=500, cam_y=500, radius=49,
                    seed=42, biome_name="cavern")
        b = get_visible(cam_x=10, cam_y=20, radius=49,
                        seed=42, biome_name="cavern")
        a_set = {(e["kind"], round(e["x"], 2), round(e["y"], 2)) for e in a}
        b_set = {(e["kind"], round(e["x"], 2), round(e["y"], 2)) for e in b}
        assert a_set == b_set

    def test_unlimited_in_any_direction(self):
        from core.systems.stamp_world import get_visible
        for cx, cy in [(1000, 0), (-1000, 0), (0, 1000), (0, -1000),
                       (5000, 5000), (-3000, 7000)]:
            ents = get_visible(cam_x=cx, cam_y=cy, radius=49,
                               seed=42, biome_name="cavern")
            assert len(ents) > 0, f"No entities at ({cx}, {cy})"

    def test_min_density_per_visible_circle(self):
        """Every visible circle should have at least N entities — no empty zones."""
        from core.systems.stamp_world import get_visible
        # Sample 20 random positions, each should produce at least 30 entities
        for cx, cy in [(0, 0), (37, 88), (-50, 120), (200, -150), (1000, 1000),
                       (12, 34), (-200, 300), (450, -670), (88, 88), (123, 456)]:
            ents = get_visible(cam_x=cx, cam_y=cy, radius=49,
                               seed=42, biome_name="cavern")
            assert len(ents) >= 30, \
                f"Sparse zone at ({cx}, {cy}): only {len(ents)} entities"
