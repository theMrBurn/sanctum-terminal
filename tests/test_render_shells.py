"""Tests for render shell distance-band system.

Seven concentric shells at factor-of-7 distances. Entities bind to shells
by distance from camera + kind class. Only the innermost shell renders
full 3D geometry. Outer shells project silhouettes or skip entirely.
Biome-agnostic: RENDER_SHELLS is universal, KIND_RENDER_CLASS is universal.
"""

import pytest

from core.systems.biome_data import (
    RENDER_SHELLS, KIND_RENDER_CLASS, BIOME_REGISTRY,
    HARD_OBJECTS,
)


# -- Shell config integrity ----------------------------------------------------

class TestRenderShellConfig:
    """RENDER_SHELLS defines 7 concentric distance bands."""

    def test_exactly_seven_shells(self):
        assert len(RENDER_SHELLS) == 7, (
            f"must have exactly 7 shells (Merkabah), got {len(RENDER_SHELLS)}")

    def test_radii_are_factor_of_7(self):
        for i, shell in enumerate(RENDER_SHELLS):
            expected = (i + 1) * 7
            assert shell["radius"] == expected, (
                f"shell {i} radius={shell['radius']}, expected {expected}")

    def test_radii_monotonically_increase(self):
        for i in range(len(RENDER_SHELLS) - 1):
            assert RENDER_SHELLS[i]["radius"] < RENDER_SHELLS[i + 1]["radius"]

    def test_required_fields(self):
        for i, shell in enumerate(RENDER_SHELLS):
            assert "radius" in shell, f"shell {i} missing radius"
            assert "mode" in shell, f"shell {i} missing mode"
            assert "kind_classes" in shell, f"shell {i} missing kind_classes"

    def test_modes_are_valid(self):
        valid_modes = {"geometry", "silhouette", "hint", "atmosphere", "void"}
        for i, shell in enumerate(RENDER_SHELLS):
            assert shell["mode"] in valid_modes, (
                f"shell {i} mode='{shell['mode']}' not in {valid_modes}")

    def test_innermost_shell_is_geometry(self):
        assert RENDER_SHELLS[0]["mode"] == "geometry", (
            "shell 0 must be full geometry rendering")

    def test_outermost_shell_is_hint_or_void(self):
        """Outermost shell should be hint or void — minimal rendering."""
        assert RENDER_SHELLS[6]["mode"] in ("hint", "void"), (
            f"shell 6 should be hint or void")

    def test_kind_classes_is_list(self):
        for i, shell in enumerate(RENDER_SHELLS):
            assert isinstance(shell["kind_classes"], list), (
                f"shell {i} kind_classes must be a list")


# -- Kind render class mapping -------------------------------------------------

class TestKindRenderClass:
    """Every entity kind maps to a render class for shell assignment."""

    EXPECTED_CLASSES = {"structural", "emissive", "scatter", "ground_cover",
                        "atmosphere", "life"}

    def test_all_hard_objects_classified(self):
        """Every kind in HARD_OBJECTS must have a render class."""
        for kind in HARD_OBJECTS:
            assert kind in KIND_RENDER_CLASS, (
                f"'{kind}' in HARD_OBJECTS but not in KIND_RENDER_CLASS")

    def test_all_classes_valid(self):
        for kind, cls in KIND_RENDER_CLASS.items():
            assert cls in self.EXPECTED_CLASSES, (
                f"'{kind}' has unknown class '{cls}', "
                f"valid: {self.EXPECTED_CLASSES}")

    def test_structural_kinds_present(self):
        structurals = [k for k, v in KIND_RENDER_CLASS.items()
                       if v == "structural"]
        assert "mega_column" in structurals
        assert "column" in structurals
        assert "boulder" in structurals

    def test_emissive_kinds_present(self):
        emissives = [k for k, v in KIND_RENDER_CLASS.items()
                     if v == "emissive"]
        assert "crystal_cluster" in emissives
        assert "giant_fungus" in emissives

    def test_scatter_kinds_present(self):
        scatter = [k for k, v in KIND_RENDER_CLASS.items()
                   if v == "scatter"]
        assert "rubble" in scatter
        assert "cave_gravel" in scatter

    def test_no_empty_class(self):
        """Every class must have at least one kind."""
        for cls in self.EXPECTED_CLASSES:
            members = [k for k, v in KIND_RENDER_CLASS.items() if v == cls]
            assert len(members) >= 1, f"class '{cls}' has no members"


# -- Shell assignment logic ----------------------------------------------------

class TestShellAssignment:
    """Entities should be assignable to shells by distance + kind class."""

    def test_scatter_only_in_geometry_shells(self):
        """Scatter kinds should only appear in geometry-mode shells."""
        scatter_shells = [s for s in RENDER_SHELLS
                          if "scatter" in s["kind_classes"]]
        assert len(scatter_shells) >= 1, "scatter needs at least one shell"
        for s in scatter_shells:
            assert s["mode"] == "geometry", (
                f"scatter in non-geometry shell at radius {s['radius']}")

    def test_structural_spans_multiple_shells(self):
        """Structural kinds should render across geometry + silhouette shells."""
        structural_shells = [s for s in RENDER_SHELLS
                             if "structural" in s["kind_classes"]]
        assert len(structural_shells) >= 3, (
            "structural kinds need at least geometry + 2 silhouette shells")

    def test_emissive_spans_geometry_and_silhouette(self):
        """Emissive kinds should render as geometry locally and silhouette at distance."""
        emissive_shells = [s for s in RENDER_SHELLS
                           if "emissive" in s["kind_classes"]]
        modes = {s["mode"] for s in emissive_shells}
        assert "geometry" in modes, "emissive must have geometry shell"
        assert len(emissive_shells) >= 2, "emissive needs geometry + silhouette"

    def test_life_only_local(self):
        """Life kinds (beetles, rats) should only render in geometry shell."""
        life_shells = [s for s in RENDER_SHELLS
                       if "life" in s["kind_classes"]]
        assert len(life_shells) <= 2, "life kinds don't need far shells"
        assert life_shells[0]["mode"] == "geometry"
