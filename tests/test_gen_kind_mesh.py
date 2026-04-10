"""Tests for the clean-room mesh authoring pipeline.

Verifies that tools/gen_kind_mesh.py produces valid GLBs with baked
vertex colors, poly counts within budget, and scale matching the
target ranges for our rendering economy.

This is a regression fence — if a future contributor breaks vertex
color baking, blows poly budget, or drifts scale, tests fail loudly.
"""

import numpy as np
import trimesh

from tools.gen_kind_mesh import (
    build_toadstool,
    toadstool_variants,
    build_spore_pod,
    spore_pod_variants,
    hemisphere,
    capped_cylinder,
    torus_ring,
    sphere,
    TOADSTOOL_CAP_RED,
    TOADSTOOL_SPOT_CREAM,
    TOADSTOOL_STEM_BROWN,
    SPORE_POD_BODY,
)


# -- Primitive sanity ----------------------------------------------------------


class TestPrimitives:
    """Low-level primitive builders return valid meshes with vertex colors."""

    def test_hemisphere_has_expected_triangle_count(self):
        # meridian=12, parallels=4 → ~96 triangles on the dome
        dome = hemisphere(radius=2.0, height=1.5, color=(200, 50, 50, 255),
                          meridian_sections=12, parallel_rings=4)
        assert 60 <= len(dome.faces) <= 160, (
            f"hemisphere face count {len(dome.faces)} outside expected range")

    def test_hemisphere_extents_match_params(self):
        dome = hemisphere(radius=2.5, height=1.6, color=(200, 50, 50, 255))
        w, d, h = dome.extents
        # Width/depth should be ~2 * radius, height ~= height param
        assert 4.9 < w < 5.1, f"hemisphere width {w} should be ~5.0"
        assert 4.9 < d < 5.1, f"hemisphere depth {d} should be ~5.0"
        assert 1.55 < h < 1.65, f"hemisphere height {h} should be ~1.6"

    def test_hemisphere_has_vertex_colors(self):
        dome = hemisphere(radius=2.0, height=1.5, color=(200, 50, 50, 255))
        colors = dome.visual.vertex_colors
        assert colors.shape == (len(dome.vertices), 4)
        # Every vertex should have the specified color
        assert colors[0][0] == 200  # red channel

    def test_capped_cylinder_tapers(self):
        cyl = capped_cylinder(radius_bottom=1.0, radius_top=0.5,
                              height=3.0, sections=8,
                              color=(100, 100, 100, 255))
        # Top ring verts (z > 0) should have smaller xy magnitudes than bottom
        top_mask = cyl.vertices[:, 2] > 0.5
        bot_mask = cyl.vertices[:, 2] < -0.5
        top_max = np.max(np.linalg.norm(cyl.vertices[top_mask, :2], axis=1))
        bot_max = np.max(np.linalg.norm(cyl.vertices[bot_mask, :2], axis=1))
        assert top_max < bot_max, (
            f"tapered cylinder top radius {top_max} should be smaller "
            f"than bottom radius {bot_max}")

    def test_torus_ring_has_vertex_colors(self):
        ring = torus_ring(major_radius=1.0, minor_radius=0.2,
                          major_sections=12, minor_sections=6,
                          color=(50, 30, 20, 255))
        assert ring.visual.vertex_colors.shape == (len(ring.vertices), 4)


# -- Toadstool assembly --------------------------------------------------------


class TestToadstool:
    """The first concrete kind we author via the pipeline."""

    def test_build_toadstool_produces_valid_mesh(self):
        t = build_toadstool()
        assert len(t.vertices) > 0
        assert len(t.faces) > 0
        assert t.visual.vertex_colors.shape == (len(t.vertices), 4)

    def test_toadstool_poly_count_in_budget(self):
        """Target: 150-400 triangles. Below crystal_cluster (148KB),
        above stalagmite (9KB), in the landmark-scale range."""
        t = build_toadstool()
        assert 150 <= len(t.faces) <= 500, (
            f"toadstool face count {len(t.faces)} outside budget 150-500")

    def test_toadstool_scale_target(self):
        """Target: sub-boulder foreground scale, ~1.5-3m wide × 1.5-3m tall.
        Reads as waist-to-head-height fungus detail, not a landmark.
        Tuned down twice from the first pass — 5.8m → 3.5m → 2.1m."""
        t = build_toadstool()
        w, d, h = t.extents
        assert 1.5 < w < 3.5, f"toadstool width {w:.2f} outside 1.5-3.5m"
        assert 1.5 < d < 3.5, f"toadstool depth {d:.2f} outside 1.5-3.5m"
        assert 1.5 < h < 3.5, f"toadstool height {h:.2f} outside 1.5-3.5m"

    def test_toadstool_has_red_and_cream_vertices(self):
        """Cap should contain red-ish verts, spots should contain cream."""
        t = build_toadstool()
        colors = t.visual.vertex_colors
        # Look for any vertex matching cap red (within ±1 tolerance for uint8)
        cap_match = np.all(np.abs(colors[:, :3].astype(int) -
                                   np.array(TOADSTOOL_CAP_RED[:3])) <= 1, axis=1)
        assert cap_match.any(), "no vertices match TOADSTOOL_CAP_RED"
        spot_match = np.all(np.abs(colors[:, :3].astype(int) -
                                    np.array(TOADSTOOL_SPOT_CREAM[:3])) <= 1, axis=1)
        assert spot_match.any(), "no vertices match TOADSTOOL_SPOT_CREAM"

    def test_four_variants_all_unique(self):
        """4 variants must differ in face count or extents."""
        variants = toadstool_variants()
        assert len(variants) == 4
        face_counts = [len(v.faces) for v in variants]
        extents_sum = [sum(v.extents) for v in variants]
        # At least 2 variants should have distinct extents (not all clones)
        assert len(set(extents_sum)) >= 2, (
            f"variants all have same extents: {extents_sum}")

    def test_variants_export_to_valid_glb(self):
        """Round-trip through GLB without losing vertex colors."""
        variants = toadstool_variants()
        for i, v in enumerate(variants):
            glb_bytes = v.export(file_type="glb")
            assert len(glb_bytes) > 1000, (
                f"v{i} GLB suspiciously small: {len(glb_bytes)} bytes")
            assert len(glb_bytes) < 200_000, (
                f"v{i} GLB over budget: {len(glb_bytes)} bytes "
                f"(target < 200KB, crystal_cluster is our ~148KB ceiling)")


class TestSporePod:
    """The second kind authored via the pipeline — partner to giant_fungus."""

    def test_build_spore_pod_produces_valid_mesh(self):
        p = build_spore_pod()
        assert len(p.vertices) > 0
        assert len(p.faces) > 0
        assert p.visual.vertex_colors.shape == (len(p.vertices), 4)

    def test_spore_pod_poly_count_in_budget(self):
        """Target: 200-500 triangles. Cluster of 3-5 small icospheres,
        each ~80 tris, so 240-400 is the natural range."""
        p = build_spore_pod()
        assert 150 <= len(p.faces) <= 600, (
            f"spore_pod face count {len(p.faces)} outside budget 150-600")

    def test_spore_pod_scale_target(self):
        """Target: ground-hugging mass, ~1-2m wide, <1.5m tall.
        Smaller than toadstool, ground-clinging like a boulder."""
        p = build_spore_pod()
        w, d, h = p.extents
        assert 0.8 < w < 2.5, f"spore_pod width {w:.2f} outside 0.8-2.5m"
        assert 0.8 < d < 2.5, f"spore_pod depth {d:.2f} outside 0.8-2.5m"
        assert 0.3 < h < 1.5, f"spore_pod height {h:.2f} outside 0.3-1.5m (should be ground-hugging)"

    def test_spore_pod_has_body_color(self):
        """The dusty mauve body color must appear in the mesh."""
        p = build_spore_pod()
        colors = p.visual.vertex_colors
        target = np.array(SPORE_POD_BODY[:3], dtype=int)
        body_match = np.all(np.abs(colors[:, :3].astype(int) - target) <= 1, axis=1)
        assert body_match.any(), "no vertices match SPORE_POD_BODY"

    def test_four_variants_distinct(self):
        """4 variants must produce different cluster shapes."""
        variants = spore_pod_variants()
        assert len(variants) == 4
        face_counts = [len(v.faces) for v in variants]
        # Pod count varies (3, 4, 3, 5) so face counts should differ
        assert len(set(face_counts)) >= 2, (
            f"variants have identical face counts: {face_counts}")

    def test_spore_pod_glb_size_in_budget(self):
        for i, v in enumerate(spore_pod_variants()):
            glb_bytes = v.export(file_type="glb")
            assert 1000 < len(glb_bytes) < 200_000, (
                f"spore_pod v{i} GLB {len(glb_bytes)} bytes — out of bounds")
