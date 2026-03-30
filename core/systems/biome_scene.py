"""
core/systems/biome_scene.py

BiomeSceneBuilder -- composes a biome scene from renderer + trees.

Usage:
    builder = BiomeSceneBuilder(render_root, seed=42)
    nodes = builder.build("VERDANT")  # floor + scatter + trees
    builder.clear()                    # remove all
    builder.build("CHROME")            # different biome

Biomes with trees: VERDANT, MYCELIUM
Biomes without: everything else (scatter only)
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from core.systems.biome_renderer import BiomeRenderer
from core.systems.tree_builder import TreeBuilder


# Biomes that get trees
_TREE_BIOMES = {"VERDANT", "MYCELIUM"}

# Scatter count per biome feel
_SCATTER_COUNTS = {
    "VOID":     8,
    "NEON":     15,
    "IRON":     20,
    "SILICA":   10,
    "FROZEN":   12,
    "SULPHUR":  14,
    "BASALT":   18,
    "VERDANT":  10,
    "MYCELIUM": 16,
    "CHROME":   12,
}


def _load_tree_blueprint():
    path = Path(__file__).parent.parent.parent / "config" / "blueprints" / "verdant.json"
    if path.exists():
        return json.load(open(path))
    return {"trees": {}, "palette": {}}


class BiomeSceneBuilder:
    """
    Composes a complete biome scene: ground + scatter + trees.

    Parameters
    ----------
    render_root : Panda3D NodePath
    seed        : int -- deterministic generation
    radius      : float -- scene radius in metres
    """

    def __init__(self, render_root, seed: int = 42, radius: float = 50.0):
        self.render_root = render_root
        self.seed        = seed
        self.radius      = radius
        self.nodes       = []     # all spawned node dicts/NodePaths
        self._renderer   = None
        self._tree_bp    = _load_tree_blueprint()
        self._tree_builder = TreeBuilder()

    def build(self, biome_key: str) -> list:
        """
        Build a complete biome scene.
        Returns list of node dicts (each has at least "np" or "geom_node").
        """
        self.clear()
        rng = random.Random(self.seed)

        # Floor + scatter via BiomeRenderer
        self._renderer = BiomeRenderer(
            self.render_root, biome_key=biome_key, seed=self.seed
        )
        count = _SCATTER_COUNTS.get(biome_key, 12)
        self._renderer.render_scene(encounter_density=count / 45.0, seed=self.seed)

        for np in self._renderer.nodes:
            self.nodes.append({"np": np, "role": "scatter", "biome": biome_key})

        # Trees for vegetated biomes
        if biome_key in _TREE_BIOMES and self._tree_bp.get("trees"):
            tree_count = rng.randint(15, 30)
            tree_nodes = self._tree_builder.build_forest(
                self._tree_bp, rng,
                x1=-self.radius * 0.8, x2=self.radius * 0.8,
                y1=-self.radius * 0.8, y2=self.radius * 0.8,
                count=tree_count,
            )
            for tn in tree_nodes:
                np = self.render_root.attachNewNode(tn["geom_node"])
                np.setPos(tn["x"], tn["y"], tn["z"])
                self.nodes.append({
                    "np": np, "role": tn.get("role", "tree"),
                    "biome": biome_key, "tree_type": tn.get("tree_type", ""),
                })

        return self.nodes

    def clear(self):
        """Remove all scene nodes."""
        if self._renderer:
            self._renderer.clear()
        for entry in self.nodes:
            np = entry.get("np")
            if np and not np.isEmpty():
                try:
                    np.removeNode()
                except Exception:
                    pass
        self.nodes = []
