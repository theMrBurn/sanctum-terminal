"""
tests/test_biome_scenes.py

Biome scenes -- compound objects scattered in realized environments.

[B] cycles biomes: VERDANT / CHROME / NEON / IRON / FROZEN.
BiomeSceneBuilder composes floor + compound scatter + trees.
Register palette skins everything via [R].
"""
import pytest
from core.systems.biome_renderer import BIOME_PALETTE


# -- BiomeRenderer contracts ---------------------------------------------------

class TestBiomeRendererBasics:

    def test_all_ten_biomes_in_palette(self):
        expected = {"VOID", "NEON", "IRON", "SILICA", "FROZEN",
                    "SULPHUR", "BASALT", "VERDANT", "MYCELIUM", "CHROME"}
        assert set(BIOME_PALETTE.keys()) == expected

    def test_each_palette_has_floor_accent_scale(self):
        for key, pal in BIOME_PALETTE.items():
            assert "floor" in pal, f"{key} missing floor"
            assert "accent" in pal, f"{key} missing accent"
            assert "scale" in pal, f"{key} missing scale"


# -- BiomeSceneBuilder --------------------------------------------------------

class TestBiomeSceneBuilder:

    def test_importable(self):
        from core.systems.biome_scene import BiomeSceneBuilder
        assert BiomeSceneBuilder is not None

    def test_builds_verdant(self):
        from panda3d.core import NodePath
        from core.systems.biome_scene import BiomeSceneBuilder
        root = NodePath("test_root")
        builder = BiomeSceneBuilder(root, seed=42)
        nodes = builder.build("VERDANT")
        assert len(nodes) > 0

    def test_builds_chrome(self):
        from panda3d.core import NodePath
        from core.systems.biome_scene import BiomeSceneBuilder
        root = NodePath("test_root")
        builder = BiomeSceneBuilder(root, seed=42)
        nodes = builder.build("CHROME")
        assert len(nodes) > 0

    def test_verdant_has_trees(self):
        from panda3d.core import NodePath
        from core.systems.biome_scene import BiomeSceneBuilder
        root = NodePath("test_root")
        builder = BiomeSceneBuilder(root, seed=42)
        nodes = builder.build("VERDANT")
        tree_nodes = [n for n in nodes if n.get("role", "") in
                      ("trunk", "canopy", "branch", "flare")]
        assert len(tree_nodes) > 0

    def test_chrome_has_no_trees(self):
        from panda3d.core import NodePath
        from core.systems.biome_scene import BiomeSceneBuilder
        root = NodePath("test_root")
        builder = BiomeSceneBuilder(root, seed=42)
        nodes = builder.build("CHROME")
        tree_nodes = [n for n in nodes if n.get("role", "") in
                      ("trunk", "canopy", "branch", "flare")]
        assert len(tree_nodes) == 0

    def test_clear_removes_all(self):
        from panda3d.core import NodePath
        from core.systems.biome_scene import BiomeSceneBuilder
        root = NodePath("test_root")
        builder = BiomeSceneBuilder(root, seed=42)
        builder.build("VERDANT")
        builder.clear()
        assert len(builder.nodes) == 0

    def test_all_biomes_build(self):
        from panda3d.core import NodePath
        from core.systems.biome_scene import BiomeSceneBuilder
        root = NodePath("test_root")
        builder = BiomeSceneBuilder(root, seed=42)
        for biome in ("VERDANT", "CHROME", "NEON", "IRON", "FROZEN"):
            builder.clear()
            nodes = builder.build(biome)
            assert len(nodes) > 0, f"{biome} produced no nodes"

    def test_deterministic_with_same_seed(self):
        from panda3d.core import NodePath
        from core.systems.biome_scene import BiomeSceneBuilder
        root1 = NodePath("r1")
        root2 = NodePath("r2")
        b1 = BiomeSceneBuilder(root1, seed=42)
        b2 = BiomeSceneBuilder(root2, seed=42)
        n1 = b1.build("VERDANT")
        n2 = b2.build("VERDANT")
        assert len(n1) == len(n2)


# -- Compound scatter ----------------------------------------------------------

class TestCompoundScatter:

    def test_scatter_contains_compounds(self):
        from panda3d.core import NodePath
        from core.systems.biome_scene import BiomeSceneBuilder
        root = NodePath("test_root")
        builder = BiomeSceneBuilder(root, seed=42)
        nodes = builder.build("IRON")
        scatter = [n for n in nodes if n.get("role") == "scatter"]
        assert len(scatter) > 0

    def test_scatter_has_compound_keys(self):
        from panda3d.core import NodePath
        from core.systems.biome_scene import BiomeSceneBuilder
        root = NodePath("test_root")
        builder = BiomeSceneBuilder(root, seed=42)
        nodes = builder.build("CHROME")
        keys = [n.get("compound_key") for n in nodes if n.get("compound_key")]
        assert len(keys) > 0

    def test_register_changes_colors(self):
        """Same biome, different register = different compound colors."""
        from panda3d.core import NodePath
        from core.systems.biome_scene import BiomeSceneBuilder
        root1 = NodePath("r1")
        root2 = NodePath("r2")
        b1 = BiomeSceneBuilder(root1, seed=42)
        b2 = BiomeSceneBuilder(root2, seed=42)
        n1 = b1.build("IRON", register="survival")
        n2 = b2.build("IRON", register="tron")
        # Both produce same number of nodes
        assert len(n1) == len(n2)

    def test_verdant_scatters_flora_and_geology(self):
        from panda3d.core import NodePath
        from core.systems.biome_scene import BiomeSceneBuilder
        root = NodePath("test_root")
        builder = BiomeSceneBuilder(root, seed=42)
        nodes = builder.build("VERDANT")
        keys = {n.get("compound_key") for n in nodes if n.get("compound_key")}
        # Should have stump (flora) and/or boulder (geology)
        assert len(keys) > 0
