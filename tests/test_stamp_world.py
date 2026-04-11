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

    def test_scale_fade_at_edge(self):
        """Entities near the visibility edge should be scaled smaller than full size."""
        from core.systems.stamp_world import _scale_factor, SCALE_FADE_BAND, SCALE_MIN
        radius = 49.0
        # Inside fade band → full size
        assert _scale_factor(0.0, radius) == 1.0
        assert _scale_factor(20.0, radius) == 1.0
        assert _scale_factor(radius - SCALE_FADE_BAND - 0.1, radius) == 1.0
        # At the edge → smallest
        assert _scale_factor(radius, radius) == SCALE_MIN
        # Mid-band → between SCALE_MIN and 1.0
        mid = _scale_factor(radius - SCALE_FADE_BAND / 2, radius)
        assert SCALE_MIN < mid < 1.0

    def test_far_entities_have_smaller_scale_than_near(self):
        """An entity at the visibility edge should have a smaller sx than the same kind near the camera."""
        from core.systems.stamp_world import get_visible
        ents = get_visible(cam_x=0, cam_y=0, radius=49,
                           seed=42, biome_name="cavern")
        # Bin by distance and check that far entities are smaller on average
        near = []
        far = []
        for e in ents:
            dist = math.sqrt(e["x"] ** 2 + e["y"] ** 2)
            if dist < 20:
                near.append(e["sx"])
            elif dist > 40:
                far.append(e["sx"])
        if near and far:
            assert sum(far) / len(far) < sum(near) / len(near), \
                "Far entities should average smaller scale than near"

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


# ---------------------------------------------------------------------------
# collision_radius — player physics boundaries
# ---------------------------------------------------------------------------
#
# _make_entity reads from PLAYER_COLLISION_RADII (biome_data.py) and scales
# by per-variant size. The Godot _physics_process loop consumes these
# radii via `collision_objects` and pushes the player out. This test class
# guards the brain-side half of that contract.

class TestCollisionRadius:

    def test_hard_kind_carries_collision(self):
        from core.systems.stamp_world import get_visible
        ents = get_visible(cam_x=0, cam_y=0, radius=49,
                           seed=42, biome_name="cavern")
        mega = [e for e in ents if e["kind"] == "mega_column"]
        assert len(mega) > 0, "Expected mega_columns in hub spawn"
        for e in mega:
            assert e["collision_radius"] > 0.5, (
                f"mega_column missing collision: {e['collision_radius']}")

    def test_soft_kind_has_zero_collision(self):
        from core.systems.stamp_world import get_visible
        ents = get_visible(cam_x=0, cam_y=0, radius=49,
                           seed=42, biome_name="cavern")
        # Tissue should walk-through: grass_tuft, moss_patch, cave_gravel, rubble
        for soft_kind in ("grass_tuft", "moss_patch", "cave_gravel"):
            soft = [e for e in ents if e["kind"] == soft_kind]
            if not soft:
                continue  # not in this particular view
            for e in soft:
                assert e["collision_radius"] == 0.0, (
                    f"{soft_kind} should be walk-through but has radius "
                    f"{e['collision_radius']}")

    def test_doorframe_is_walk_through(self):
        """Doorframes are architectural gates — explicitly omitted from the
        collision table so the player can walk through them as the visual
        language promises. This is a regression guard for that contract."""
        from core.systems.stamp_world import get_visible
        ents = get_visible(cam_x=0, cam_y=0, radius=49,
                           seed=42, biome_name="cavern")
        doors = [e for e in ents if e["kind"] == "doorframe"]
        # Hub has doorframes at N and S arches — must be present
        assert len(doors) >= 2, "Expected doorframes in hub"
        for e in doors:
            assert e["collision_radius"] == 0.0, (
                f"doorframe must be walk-through but has radius "
                f"{e['collision_radius']}")

    def test_collision_scales_with_variant(self):
        """Per-variant size variance should scale the collision radius
        proportionally, so small variants have small collision and large
        variants have large collision."""
        from core.systems.stamp_world import get_visible
        ents = get_visible(cam_x=0, cam_y=0, radius=49,
                           seed=42, biome_name="cavern")
        # Group same-kind entities and check their radius correlates with sv
        by_kind: dict = {}
        for e in ents:
            if e["collision_radius"] == 0.0:
                continue
            by_kind.setdefault(e["kind"], []).append(e)
        # Find a kind with multiple instances and verify correlation
        for kind, group in by_kind.items():
            if len(group) < 3:
                continue
            svs = [e["sv"] for e in group]
            rs = [e["collision_radius"] for e in group]
            # Pearson-ish: larger sv should mean larger collision_radius
            # Cheap check: the max-sv instance has the max radius (± rounding)
            max_sv_idx = svs.index(max(svs))
            min_sv_idx = svs.index(min(svs))
            assert rs[max_sv_idx] >= rs[min_sv_idx], (
                f"{kind}: collision radius should scale with sv but doesn't")
            return  # one kind tested is enough
        pytest.skip("No kind had enough instances to test scaling")

    def test_hub_arches_are_walkable(self):
        """Each cardinal arch in the origin hub must have enough gap between
        its hard members for the player (0.5m buffer) to pass through.
        This is a composition regression guard — if the hub layout changes
        and an arch becomes too tight, this test catches it."""
        from core.systems.stamp_world import stamp_at

        hub_ents = stamp_at(0, 0, seed=42, biome_name="cavern")
        # Collect hard entities (those with non-zero collision)
        hard = [(e["kind"], e["x"], e["y"], e["collision_radius"])
                for e in hub_ents if e["collision_radius"] > 0.0]

        PLAYER_BUFFER = 0.5

        # S arch at y ≈ -12 — find hard members at y < -11 and confirm
        # there's a walkable gap at x=0
        s_arch_hards = [h for h in hard if h[2] < -11]
        for kind, hx, hy, hr in s_arch_hards:
            distance_to_centerline = abs(hx)
            assert distance_to_centerline > (hr + PLAYER_BUFFER) - 0.01, (
                f"S arch blocked: {kind} at ({hx},{hy}) r={hr} "
                f"leaves only {distance_to_centerline - hr - PLAYER_BUFFER}m "
                f"clearance at centerline")

        # N arch at y ≈ 12
        n_arch_hards = [h for h in hard if h[2] > 11]
        for kind, hx, hy, hr in n_arch_hards:
            distance_to_centerline = abs(hx)
            assert distance_to_centerline > (hr + PLAYER_BUFFER) - 0.01, (
                f"N arch blocked: {kind} at ({hx},{hy}) r={hr}")
