"""
tests/test_biome_scenes.py

Biome scenes in creation lab -- realized environments.

[B] cycles biomes: VERDANT / CHROME / NEON / IRON / FROZEN.
BiomeRenderer composes floor + scatter. TreeBuilder adds vegetation.
Register palette still applies on top via [R].
"""
import pytest
from core.systems.biome_renderer import BiomeRenderer, BIOME_PALETTE


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

    def test_renderer_clear_removes_nodes(self):
        from panda3d.core import NodePath
        root = NodePath("test_root")
        br = BiomeRenderer(root, "VERDANT", seed=42)
        br.render_scene()
        assert len(br.nodes) > 0
        br.clear()
        assert len(br.nodes) == 0


# -- BiomeSceneBuilder (new) --------------------------------------------------

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
