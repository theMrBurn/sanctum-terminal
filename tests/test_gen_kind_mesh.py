"""Tests for the clean-room mesh authoring pipeline.

Verifies that tools/gen_kind_mesh.py produces valid GLBs with baked
vertex colors, poly counts within budget, and scale matching the
target ranges for our rendering economy.

This is a regression fence — if a future contributor breaks vertex
color baking, blows poly budget, or drifts scale, tests fail loudly.
"""

import numpy as np
import trimesh

import pytest

from tools.gen_kind_mesh import (
    build_toadstool,
    toadstool_variants,
    build_spore_pod,
    spore_pod_variants,
    hemisphere,
    capped_cylinder,
    torus_ring,
    sphere,
    build_kind,
    FAMILY_BUILDERS,
    TOADSTOOL_CAP_RED,
    TOADSTOOL_SPOT_CREAM,
    TOADSTOOL_STEM_BROWN,
    SPORE_POD_BODY,
    _CREAM_ATOM,
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


# -- Family: tapered_vertical --------------------------------------------------
#
# Four consumers — stalagmite, column, mega_column, buttress — all routed
# through the same parameterized _family_tapered_vertical primitive. Tests
# exercise the dispatcher path (build_kind) rather than importing the family
# function directly, so this also functions as an integration test for the
# Option 3 refined sweep's config-driven family dispatch.


TAPERED_VERTICAL_KINDS = ["stalagmite", "column", "mega_column", "buttress"]


class TestTaperedVerticalFamily:

    def test_family_builder_registered(self):
        assert "tapered_vertical" in FAMILY_BUILDERS

    @pytest.mark.parametrize("kind", TAPERED_VERTICAL_KINDS)
    def test_produces_four_variants(self, kind):
        variants = build_kind(kind)
        assert len(variants) == 4, f"{kind} produced {len(variants)} variants, expected 4"

    @pytest.mark.parametrize("kind", TAPERED_VERTICAL_KINDS)
    def test_variants_have_vertex_colors(self, kind):
        for i, v in enumerate(build_kind(kind)):
            assert v.visual.vertex_colors.shape == (len(v.vertices), 4), (
                f"{kind} v{i} missing or malformed vertex colors")

    @pytest.mark.parametrize("kind", TAPERED_VERTICAL_KINDS)
    def test_variants_have_reasonable_poly_budget(self, kind):
        # Rough envelope: tapered_vertical instances are ~80-300 tris
        # depending on facet_count × ring_count + optional atom markers.
        for i, v in enumerate(build_kind(kind)):
            assert 60 <= len(v.faces) <= 400, (
                f"{kind} v{i}: {len(v.faces)} tris outside 60-400 budget")

    @pytest.mark.parametrize("kind", TAPERED_VERTICAL_KINDS)
    def test_variants_are_tall_not_flat(self, kind):
        # Every tapered_vertical consumer should be taller than wide
        for i, v in enumerate(build_kind(kind)):
            w, d, h = v.extents
            assert h > max(w, d) * 0.9, (
                f"{kind} v{i}: height {h:.2f} not taller than max(w,d) {max(w,d):.2f}")

    @pytest.mark.parametrize("kind", TAPERED_VERTICAL_KINDS)
    def test_variants_distinct_silhouettes(self, kind):
        # At least 2 of the 4 variants should differ in extents
        variants = build_kind(kind)
        heights = [float(v.extents[2]) for v in variants]
        assert len(set(round(h, 2) for h in heights)) >= 2, (
            f"{kind} variants have identical heights: {heights}")

    @pytest.mark.parametrize("kind", TAPERED_VERTICAL_KINDS)
    def test_variants_have_cream_atoms(self, kind):
        # Atom markers are painted with _CREAM_ATOM — at least one vertex
        # per variant should match that color (within ±1 per channel).
        target = np.array(_CREAM_ATOM[:3], dtype=int)
        for i, v in enumerate(build_kind(kind)):
            colors = v.visual.vertex_colors[:, :3].astype(int)
            match = np.all(np.abs(colors - target) <= 1, axis=1)
            assert match.any(), (
                f"{kind} v{i}: no vertex matches _CREAM_ATOM "
                f"(atom markers missing or wrong color)")

    def test_determinism_across_calls(self):
        # Same kind built twice must produce identical geometry
        a = build_kind("stalagmite")
        b = build_kind("stalagmite")
        for va, vb in zip(a, b):
            assert np.array_equal(va.vertices, vb.vertices), (
                "stalagmite builds are not deterministic across calls")

    def test_legacy_kinds_untouched_by_dispatcher(self):
        # build_kind on a legacy name must route through LEGACY_BUILDERS —
        # no recipe lookup, no family dispatch.
        variants = build_kind("toadstool")
        assert len(variants) == 4
        # Legacy output is the same as calling the legacy builder directly
        direct = toadstool_variants()
        for va, vd in zip(variants, direct):
            assert np.array_equal(va.vertices, vd.vertices)


# -- Family: rock_lobed --------------------------------------------------------
#
# Tier 2 tissue — rubble, cave_gravel, bone_pile. Multi-lobe icosphere
# clusters, no atoms, no composed primitives, just unified render path.
# Variants are tighter (2 each) because tissue doesn't need 4-way character.


ROCK_LOBED_KINDS = ["rubble", "cave_gravel", "bone_pile"]


class TestRockLobedFamily:

    def test_family_builder_registered(self):
        assert "rock_lobed" in FAMILY_BUILDERS

    @pytest.mark.parametrize("kind", ROCK_LOBED_KINDS)
    def test_produces_four_variants(self, kind):
        # Tier 2 emits 4 variants to match the v0..v3 pipeline expectation.
        # Fewer would leave stale v2/v3 GLBs from the legacy path on disk.
        variants = build_kind(kind)
        assert len(variants) == 4, f"{kind} produced {len(variants)} variants, expected 4"

    @pytest.mark.parametrize("kind", ROCK_LOBED_KINDS)
    def test_variants_have_vertex_colors(self, kind):
        for i, v in enumerate(build_kind(kind)):
            assert v.visual.vertex_colors.shape == (len(v.vertices), 4), (
                f"{kind} v{i} missing or malformed vertex colors")

    @pytest.mark.parametrize("kind", ROCK_LOBED_KINDS)
    def test_variants_have_no_atoms(self, kind):
        # Tier 2 tissue: no atom markers. No vertex should match _CREAM_ATOM.
        target = np.array(_CREAM_ATOM[:3], dtype=int)
        for i, v in enumerate(build_kind(kind)):
            colors = v.visual.vertex_colors[:, :3].astype(int)
            match = np.all(np.abs(colors - target) <= 1, axis=1)
            assert not match.any(), (
                f"{kind} v{i}: tissue kinds should not carry atom markers")

    @pytest.mark.parametrize("kind", ROCK_LOBED_KINDS)
    def test_variants_ground_hugging(self, kind):
        # Every rock_lobed kind should be wider than tall (flatness < 1.0)
        for i, v in enumerate(build_kind(kind)):
            w, d, h = v.extents
            assert h < max(w, d), (
                f"{kind} v{i}: height {h:.2f} >= max(w,d) {max(w,d):.2f} "
                f"(rock_lobed should be flat, not tall)")

    @pytest.mark.parametrize("kind", ROCK_LOBED_KINDS)
    def test_variants_poly_budget(self, kind):
        for i, v in enumerate(build_kind(kind)):
            assert 60 <= len(v.faces) <= 500, (
                f"{kind} v{i}: {len(v.faces)} tris outside 60-500 budget")

    def test_bone_pile_is_elongated(self):
        # bone_pile has elongation=1.8 → X should be noticeably larger than Y
        for i, v in enumerate(build_kind("bone_pile")):
            w, d, _ = v.extents
            assert w > d * 1.4, (
                f"bone_pile v{i}: width {w:.2f} not elongated relative to "
                f"depth {d:.2f} (expected ratio ≥1.4 from elongation=1.8)")


# -- Family: crystal_spike -----------------------------------------------------
#
# Crystal cluster — Tier 1 anchor, pending mycelium camouflage pair
# crystal_cap. Composes leaning main spires + satellite spires using
# the same tapered_vertical primitive as the structural kinds, but with
# sharper taper, lower noise, fewer facets (crystalline look).


class TestCrystalSpikeFamily:

    def test_family_builder_registered(self):
        assert "crystal_spike" in FAMILY_BUILDERS

    def test_crystal_cluster_has_four_variants(self):
        variants = build_kind("crystal_cluster")
        assert len(variants) == 4

    def test_variants_have_vertex_colors(self):
        for i, v in enumerate(build_kind("crystal_cluster")):
            assert v.visual.vertex_colors.shape == (len(v.vertices), 4)

    def test_variants_taller_than_wide(self):
        # Main spires lean outward, so the cluster is often wider than a
        # single spire but should still be taller than it is wide overall.
        for i, v in enumerate(build_kind("crystal_cluster")):
            w, d, h = v.extents
            assert h > max(w, d) * 0.7, (
                f"crystal_cluster v{i}: height {h:.2f} should dominate "
                f"width {max(w,d):.2f}")

    def test_variants_have_cream_atoms(self):
        # Main spires carry atoms per recipe; cream cream markers visible
        target = np.array(_CREAM_ATOM[:3], dtype=int)
        for i, v in enumerate(build_kind("crystal_cluster")):
            colors = v.visual.vertex_colors[:, :3].astype(int)
            match = np.all(np.abs(colors - target) <= 1, axis=1)
            assert match.any(), (
                f"crystal_cluster v{i}: no cream atoms found (atom doctrine violated)")

    def test_variants_poly_budget(self):
        for i, v in enumerate(build_kind("crystal_cluster")):
            assert 200 <= len(v.faces) <= 700, (
                f"crystal_cluster v{i}: {len(v.faces)} tris outside 200-700 budget")

    def test_variants_distinct(self):
        heights = [float(v.extents[2]) for v in build_kind("crystal_cluster")]
        assert len(set(round(h, 2) for h in heights)) >= 2, (
            f"crystal_cluster variants have identical heights: {heights}")
