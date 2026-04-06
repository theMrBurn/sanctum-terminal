"""Tests for stamp composition system in world_gen."""

import math
import pytest

from core.systems.biome_data import (
    CAVERN_STAMPS, OUTDOOR_STAMPS, HARD_OBJECTS, BIOME_REGISTRY,
)
from core.systems.world_gen import _emit_stamp, generate_tile


# -- Data integrity ------------------------------------------------------------

class TestStampData:
    """Stamp definitions are well-formed and internally consistent."""

    @pytest.mark.parametrize("stamps,label", [
        (CAVERN_STAMPS, "cavern"),
        (OUTDOOR_STAMPS, "outdoor"),
    ])
    def test_stamps_non_empty(self, stamps, label):
        assert len(stamps) >= 2, f"{label} needs at least 2 stamps for rotation"

    @pytest.mark.parametrize("stamps,label", [
        (CAVERN_STAMPS, "cavern"),
        (OUTDOOR_STAMPS, "outdoor"),
    ])
    def test_stamps_have_required_fields(self, stamps, label):
        for s in stamps:
            assert "name" in s, f"{label} stamp missing name"
            assert "footprint" in s, f"{label} stamp {s.get('name')} missing footprint"
            assert "members" in s, f"{label} stamp {s.get('name')} missing members"
            assert len(s["members"]) >= 2, f"stamp {s['name']} needs ≥2 members"

    @pytest.mark.parametrize("stamps,label", [
        (CAVERN_STAMPS, "cavern"),
        (OUTDOOR_STAMPS, "outdoor"),
    ])
    def test_member_fields(self, stamps, label):
        for s in stamps:
            for m in s["members"]:
                assert "kind" in m, f"member in {s['name']} missing kind"
                assert "dx" in m and "dy" in m, f"member in {s['name']} missing dx/dy"
                assert "hard" in m, f"member in {s['name']} missing hard flag"

    @pytest.mark.parametrize("stamps,label", [
        (CAVERN_STAMPS, "cavern"),
        (OUTDOOR_STAMPS, "outdoor"),
    ])
    def test_unique_names(self, stamps, label):
        names = [s["name"] for s in stamps]
        assert len(names) == len(set(names)), f"duplicate stamp names in {label}"

    @pytest.mark.parametrize("stamps,label", [
        (CAVERN_STAMPS, "cavern"),
        (OUTDOOR_STAMPS, "outdoor"),
    ])
    def test_members_within_footprint(self, stamps, label):
        """All member offsets should fit inside the stamp's footprint radius."""
        for s in stamps:
            fp = s["footprint"]
            for m in s["members"]:
                dist = math.sqrt(m["dx"] ** 2 + m["dy"] ** 2)
                assert dist <= fp + 0.5, (
                    f"{s['name']}.{m['kind']} at ({m['dx']},{m['dy']}) "
                    f"dist={dist:.1f} exceeds footprint {fp}"
                )

    def test_stamps_in_biome_registry(self):
        for biome_name in ("cavern", "outdoor"):
            reg = BIOME_REGISTRY[biome_name]
            assert "stamps" in reg, f"{biome_name} registry missing stamps"
            assert len(reg["stamps"]) >= 2


# -- Placement logic -----------------------------------------------------------

class TestStampPlacement:
    """_emit_stamp places members correctly and respects collisions."""

    def _make_stamp(self, footprint=5.0, members=None):
        if members is None:
            members = [
                {"kind": "boulder", "dx": 0.0, "dy": 0.0, "scale_mult": None, "hard": True},
                {"kind": "moss_patch", "dx": 2.0, "dy": 1.0, "scale_mult": None, "hard": False},
            ]
        return {"name": "test", "footprint": footprint, "members": members}

    def test_basic_placement(self):
        import random
        stamp = self._make_stamp()
        spawns, solids = [], []
        placed = _emit_stamp(stamp, 50.0, 50.0, spawns, solids, random.Random(1))
        assert placed == 2
        assert len(spawns) == 2
        kinds = {s[0] for s in spawns}
        assert "boulder" in kinds
        assert "moss_patch" in kinds

    def test_footprint_collision_rejects_stamp(self):
        """Stamp is rejected if footprint overlaps existing solid."""
        import random
        stamp = self._make_stamp(footprint=5.0)
        solids = [(50.0, 50.0, 3.0)]  # existing solid at stamp center
        spawns = []
        placed = _emit_stamp(stamp, 50.0, 50.0, spawns, solids, random.Random(1))
        assert placed == 0
        assert len(spawns) == 0

    def test_footprint_reserved_after_placement(self):
        """After placement, footprint center is in solid_positions."""
        import random
        stamp = self._make_stamp()
        spawns, solids = [], []
        _emit_stamp(stamp, 50.0, 50.0, spawns, solids, random.Random(1))
        centers = [(s[0], s[1]) for s in solids]
        assert any(abs(x - 50.0) < 0.01 and abs(y - 50.0) < 0.01
                   for x, y, _ in solids)

    def test_scale_mult_in_meta(self):
        """Members with scale_mult get it in their meta dict."""
        import random
        stamp = self._make_stamp(members=[
            {"kind": "crystal_cluster", "dx": 0.0, "dy": 0.0,
             "scale_mult": 1.3, "hard": True},
            {"kind": "moss_patch", "dx": 1.0, "dy": 0.0,
             "scale_mult": None, "hard": False},
        ])
        spawns, solids = [], []
        _emit_stamp(stamp, 50.0, 50.0, spawns, solids, random.Random(1))
        crystal = [s for s in spawns if s[0] == "crystal_cluster"][0]
        moss = [s for s in spawns if s[0] == "moss_patch"][0]
        assert crystal[4] is not None
        assert crystal[4]["stamp_scale_mult"] == 1.3
        assert moss[4] is None  # no meta for None scale_mult

    def test_rotation_varies_positions(self):
        """Different RNG seeds produce different member positions."""
        import random
        stamp = self._make_stamp(members=[
            {"kind": "boulder", "dx": 3.0, "dy": 0.0, "scale_mult": None, "hard": True},
        ])
        spawns1, solids1 = [], []
        _emit_stamp(stamp, 50.0, 50.0, spawns1, solids1, random.Random(1))
        spawns2, solids2 = [], []
        _emit_stamp(stamp, 50.0, 50.0, spawns2, solids2, random.Random(999))
        # Positions should differ due to random rotation
        pos1 = spawns1[0][1]
        pos2 = spawns2[0][1]
        assert abs(pos1[0] - pos2[0]) > 0.1 or abs(pos1[1] - pos2[1]) > 0.1


# -- Integration with generate_tile -------------------------------------------

class TestStampsInGeneration:
    """Stamps integrate correctly with the full tile generation pipeline."""

    def test_cavern_tile_has_stamp_members(self):
        _, spawns = generate_tile(42, "cavern")
        stamp_members = [s for s in spawns if s[4] and "stamp_scale_mult" in s[4]]
        assert len(stamp_members) > 0, "no stamp members found in cavern tile"

    def test_outdoor_tile_has_stamp_members(self):
        _, spawns = generate_tile(42, "outdoor")
        stamp_members = [s for s in spawns if s[4] and "stamp_scale_mult" in s[4]]
        assert len(stamp_members) > 0, "no stamp members found in outdoor tile"

    def test_different_seeds_produce_different_stamp_counts(self):
        """Stamp placement varies by seed (not deterministic count)."""
        counts = []
        for seed in [1, 2, 3, 4, 5]:
            _, spawns = generate_tile(seed, "cavern")
            stamp_count = sum(1 for s in spawns if s[4] and "stamp_scale_mult" in s[4])
            counts.append(stamp_count)
        # At least 2 different counts across 5 seeds
        assert len(set(counts)) >= 2, f"all seeds produced same stamp count: {counts}"

    def test_stamp_members_within_tile_bounds(self):
        """All stamp-placed entities should be within tile boundaries."""
        tile_size = 288.0
        _, spawns = generate_tile(42, "cavern", tile_size=tile_size)
        for s in spawns:
            if s[4] and "stamp_scale_mult" in s[4]:
                x, y = s[1]
                assert -10 < x < tile_size + 10, f"stamp member at x={x} out of bounds"
                assert -10 < y < tile_size + 10, f"stamp member at y={y} out of bounds"

    def test_total_spawn_count_reasonable(self):
        """Stamps shouldn't cause spawn explosion (< 2x baseline)."""
        _, spawns = generate_tile(42, "cavern")
        # Baseline was ~2854 before stamps, now should be < 6000
        assert len(spawns) < 6000, f"too many spawns: {len(spawns)}"
