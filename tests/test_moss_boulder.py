"""
tests/test_moss_boulder.py

Regression tests for the light layer composition system.
Any base object + any light layer = composed entity.
Headless Panda3D — no display.
"""

import pytest
from panda3d.core import NodePath


@pytest.fixture
def root():
    return NodePath("test_root")


# -- Config tables -------------------------------------------------------------

class TestLightLayerConfig:
    """LIGHT_LAYERS and LIGHT_AFFINITY must be well-formed."""

    def test_light_layers_exist(self):
        from core.systems.ambient_life import LIGHT_LAYERS
        assert len(LIGHT_LAYERS) >= 3  # moss, crystal, torch

    def test_each_layer_has_required_keys(self):
        from core.systems.ambient_life import LIGHT_LAYERS
        required = {"material", "shell_scale", "decal_radius_mult",
                    "decal_surface", "inner_darken", "hues"}
        for name, cfg in LIGHT_LAYERS.items():
            missing = required - set(cfg.keys())
            assert not missing, f"{name} missing keys: {missing}"

    def test_each_hue_has_required_keys(self):
        from core.systems.ambient_life import LIGHT_LAYERS
        for name, cfg in LIGHT_LAYERS.items():
            for i, hue in enumerate(cfg["hues"]):
                for k in ("color", "glow", "decal"):
                    assert k in hue, f"{name} hue[{i}] missing '{k}'"

    def test_affinity_references_valid_layers(self):
        from core.systems.ambient_life import LIGHT_LAYERS, LIGHT_AFFINITY
        for biome, objects in LIGHT_AFFINITY.items():
            for kind, layers in objects.items():
                for layer_name in layers:
                    assert layer_name in LIGHT_LAYERS, \
                        f"Affinity {biome}/{kind} references unknown layer '{layer_name}'"

    def test_affinity_probabilities_valid(self):
        from core.systems.ambient_life import LIGHT_AFFINITY
        for biome, objects in LIGHT_AFFINITY.items():
            for kind, layers in objects.items():
                for layer_name, prob in layers.items():
                    assert 0.0 <= prob <= 1.0, \
                        f"{biome}/{kind}/{layer_name} prob {prob} out of range"


# -- resolve_light_layer -------------------------------------------------------

class TestResolveLight:
    """Deterministic layer resolution from affinity table."""

    def test_returns_none_for_unknown_kind(self):
        from core.systems.ambient_life import resolve_light_layer
        assert resolve_light_layer("unicorn", seed=42) is None

    def test_returns_none_for_zero_affinity(self):
        from core.systems.ambient_life import resolve_light_layer
        # grass_tuft has no affinity entry
        assert resolve_light_layer("grass_tuft", seed=42) is None

    def test_deterministic(self):
        from core.systems.ambient_life import resolve_light_layer
        a = resolve_light_layer("boulder", seed=42)
        b = resolve_light_layer("boulder", seed=42)
        assert a == b

    def test_different_seeds_can_differ(self):
        from core.systems.ambient_life import resolve_light_layer
        results = set()
        for s in range(100):
            results.add(resolve_light_layer("boulder", seed=s))
        # Should get both None and "moss" across 100 seeds
        assert None in results, "All boulders got light — expected some dark"
        assert len(results) > 1, "All boulders identical — expected variation"


# -- apply_light_layer ---------------------------------------------------------

class TestApplyLightLayer:
    """Generic compositor wraps any node with glow shell + decal."""

    def test_adds_children(self, root):
        from core.systems.ambient_life import build_boulder, apply_light_layer
        node = build_boulder(root, seed=42)
        before = node.getNumChildren()
        apply_light_layer(node, "moss", seed=42)
        after = node.getNumChildren()
        assert after > before, "Light layer should add children (shell + decal)"

    def test_shell_is_self_lit(self, root):
        from core.systems.ambient_life import build_boulder, apply_light_layer
        node = build_boulder(root, seed=42)
        apply_light_layer(node, "moss", seed=42)
        # Last-1 child should be the shell (last is decal)
        shell = node.getChild(node.getNumChildren() - 2)
        cs = shell.getColorScale()
        assert max(cs[0], cs[1], cs[2]) > 1.0, f"Shell colorScale too dim: {cs}"

    def test_works_on_different_base_objects(self, root):
        from core.systems.ambient_life import (
            build_boulder, build_dead_log, build_stalagmite,
            apply_light_layer,
        )
        for builder in (build_boulder, build_dead_log, build_stalagmite):
            node = builder(root, seed=42)
            result = apply_light_layer(node, "moss", seed=42)
            assert result is node  # returns same node, modified in place

    def test_different_layer_types(self, root):
        from core.systems.ambient_life import build_boulder, apply_light_layer
        for layer in ("moss", "crystal", "torch"):
            node = build_boulder(root, seed=42)
            apply_light_layer(node, layer, seed=42)
            assert node.getNumChildren() >= 2  # at least shell + decal added

    def test_unknown_layer_is_noop(self, root):
        from core.systems.ambient_life import build_boulder, apply_light_layer
        node = build_boulder(root, seed=42)
        before = node.getNumChildren()
        apply_light_layer(node, "lava", seed=42)
        assert node.getNumChildren() == before


# -- Spawn integration ---------------------------------------------------------

class TestSpawnComposition:
    """AmbientManager.spawn() auto-composes via affinity table."""

    def test_spawn_still_works(self, root):
        from core.systems.ambient_life import AmbientManager
        mgr = AmbientManager(root)
        entity = mgr.spawn("boulder", pos=(0, 0, 0), seed=42)
        assert entity is not None

    def test_spawn_respects_affinity(self, root):
        """Over many seeds, some boulders should get light layers."""
        from core.systems.ambient_life import AmbientManager
        mgr = AmbientManager(root)
        child_counts = []
        for s in range(50):
            e = mgr.spawn("boulder", pos=(s, 0, 0), seed=s)
            child_counts.append(e.node.getNumChildren())
        # Some should have more children (lit) than others (dark)
        assert len(set(child_counts)) > 1, "All boulders identical — composition not firing"

    def test_non_affinity_objects_unchanged(self, root):
        """Objects with no affinity should never get self-lit glow shells."""
        from core.systems.ambient_life import AmbientManager
        mgr = AmbientManager(root)
        for s in range(20):
            e = mgr.spawn("grass_tuft", pos=(s, 0, 0), seed=s)
            # No child should have cranked colorScale (> 1.0 = self-lit)
            for ci in range(e.node.getNumChildren()):
                cs = e.node.getChild(ci).getColorScale()
                assert max(cs[0], cs[1], cs[2]) <= 1.5, \
                    f"Grass tuft seed={s} child {ci} has glow: {cs}"
