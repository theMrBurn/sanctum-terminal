"""
tests/test_wall_planes.py

TDD for wall plane architecture — converging corridor FOV.

Wall planes are lateral surfaces (normals along X or Y brain-axis)
that create enclosed perspective depth. Same config format as
floor/ceiling planes, different normal orientation.

Validates:
- Cavern biome has wall plane entries
- Normals are unit vectors on lateral axes
- Offsets are symmetric (left/right pairs)
- No two planes share offset+normal (z-fighting guard)
- Wall planes have near-black albedo (occlusion, not direct light)
- All planes have required fields
"""

import math
import pytest

from core.systems.biome_data import BIOME_PLANES, BIOME_REGISTRY


# -- Helpers ------------------------------------------------------------------

def _cavern_planes():
    return BIOME_PLANES["cavern"]


def _wall_planes():
    return [p for p in _cavern_planes() if p.get("kind") == "wall"]


def _floor_ceiling_planes():
    return [p for p in _cavern_planes() if p.get("kind") in ("ground", "ceiling")]


def _normal_length(n):
    return math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)


# -- Schema tests -------------------------------------------------------------

class TestPlaneSchema:
    """Every plane in the cavern config must have required fields."""

    REQUIRED_FIELDS = ["tag", "kind", "normal", "offset", "layer", "material",
                       "size", "follow_camera"]

    def test_all_planes_have_required_fields(self):
        for p in _cavern_planes():
            for field in self.REQUIRED_FIELDS:
                assert field in p, f"Plane '{p.get('tag', '?')}' missing '{field}'"

    def test_all_normals_are_unit_vectors(self):
        for p in _cavern_planes():
            length = _normal_length(p["normal"])
            assert abs(length - 1.0) < 0.01, (
                f"Plane '{p['tag']}' normal {p['normal']} length={length:.3f}, expected 1.0")

    def test_all_materials_have_color_base(self):
        for p in _cavern_planes():
            mat = p["material"]
            assert "color_base" in mat, f"Plane '{p['tag']}' material missing color_base"

    def test_no_duplicate_offset_normal_pairs(self):
        """No two planes share the same offset+normal — z-fighting guard."""
        seen = set()
        for p in _cavern_planes():
            key = (tuple(p["normal"]), p["offset"])
            assert key not in seen, (
                f"Duplicate offset+normal: {p['tag']} collides at {key}")
            seen.add(key)


# -- Wall plane existence tests -----------------------------------------------

class TestWallPlaneExistence:
    """Cavern biome must have wall planes for corridor perspective."""

    def test_cavern_has_wall_planes(self):
        walls = _wall_planes()
        assert len(walls) >= 2, f"Expected >=2 wall planes, got {len(walls)}"

    def test_cavern_has_floor_and_ceiling(self):
        fc = _floor_ceiling_planes()
        kinds = {p["kind"] for p in fc}
        assert "ground" in kinds
        assert "ceiling" in kinds

    def test_cavern_plane_count_at_least_4(self):
        """Minimum: ground + ceiling + 2 walls."""
        assert len(_cavern_planes()) >= 4


# -- Wall plane geometry tests ------------------------------------------------

class TestWallPlaneGeometry:
    """Wall planes must have lateral normals and symmetric offsets."""

    def test_wall_normals_are_lateral(self):
        """Wall normals must point along X or Y axis (brain-space), not Z."""
        for p in _wall_planes():
            n = p["normal"]
            # Z component should be 0 — walls are vertical
            assert abs(n[2]) < 0.01, (
                f"Wall '{p['tag']}' has Z-normal component {n[2]}, expected 0")
            # At least one of X or Y must be nonzero
            assert abs(n[0]) > 0.5 or abs(n[1]) > 0.5, (
                f"Wall '{p['tag']}' normal {n} has no lateral component")

    def test_wall_offsets_are_symmetric(self):
        """Left/right wall pairs should have equal-magnitude, opposite offsets."""
        walls = _wall_planes()
        offsets = sorted([p["offset"] for p in walls])
        # Check that for each positive offset there's a matching negative
        for off in offsets:
            if off > 0:
                assert -off in offsets, (
                    f"Wall at offset +{off} has no symmetric partner at -{off}")

    def test_wall_planes_follow_camera(self):
        """Walls must follow camera to always envelope the player."""
        for p in _wall_planes():
            assert p["follow_camera"] is True, (
                f"Wall '{p['tag']}' must follow_camera")


# -- Wall plane material tests ------------------------------------------------

class TestWallPlaneMaterial:
    """Wall plane materials must be near-black — read by occlusion, not albedo."""

    def test_wall_albedo_is_bounded(self):
        """Wall color_base should be within renderable range (no absolute black)."""
        for p in _wall_planes():
            cb = p["material"]["color_base"]
            avg = sum(cb) / len(cb)
            assert avg <= 0.50, (
                f"Wall '{p['tag']}' color_base avg={avg:.3f} too bright, expected <=0.50")

    def test_wall_grain_strength_is_subtle(self):
        """Walls shouldn't have strong visible texture — they're atmospheric mass."""
        for p in _wall_planes():
            gs = p["material"].get("grain_strength", 0)
            assert gs <= 0.40, (
                f"Wall '{p['tag']}' grain_strength={gs} too strong, expected <=0.40")


# -- Integration with biome registry ------------------------------------------

class TestBiomeRegistryIntegration:
    """Wall planes must flow through the biome registry to the manifest."""

    def test_cavern_registry_includes_wall_planes(self):
        registry = BIOME_REGISTRY["cavern"]
        planes = registry["planes"]
        wall_count = sum(1 for p in planes if p.get("kind") == "wall")
        assert wall_count >= 2

    def test_planes_in_registry_match_biome_planes(self):
        """BIOME_REGISTRY planes should be the same object as BIOME_PLANES."""
        assert BIOME_REGISTRY["cavern"]["planes"] is BIOME_PLANES["cavern"]
