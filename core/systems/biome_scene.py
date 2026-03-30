"""
core/systems/biome_scene.py

BiomeSceneBuilder -- composes a biome scene from compounds + trees.

Usage:
    builder = BiomeSceneBuilder(render_root, seed=42)
    nodes = builder.build("VERDANT", register="survival")
    builder.clear()
    builder.build("CHROME", register="tron")

Everything in the scene is a compound object from compounds.json.
Register palette skins the entire biome. Same geometry, different world.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from panda3d.core import Material, Vec4

from core.systems.biome_renderer import BiomeRenderer, _make_plane_geom, BIOME_PALETTE
from core.systems.primitive_factory import PrimitiveFactory
from core.systems.tree_builder import TreeBuilder
from core.systems.model_loader import ModelLoader, REGISTER_TINTS


# Biomes that get trees
_TREE_BIOMES = {"VERDANT", "MYCELIUM"}

# Scatter count per biome feel
_SCATTER_COUNTS = {
    "VOID":     6,
    "NEON":     12,
    "IRON":     16,
    "SILICA":   8,
    "FROZEN":   10,
    "SULPHUR":  12,
    "BASALT":   14,
    "VERDANT":  10,
    "MYCELIUM": 14,
    "CHROME":   10,
}

# Which compound categories appear in which biomes
_BIOME_CATEGORIES = {
    "VERDANT":  ["geology", "flora"],
    "MYCELIUM": ["geology", "flora"],
    "CHROME":   ["remnant", "geology"],
    "NEON":     ["remnant", "geology"],
    "IRON":     ["geology", "remnant"],
    "FROZEN":   ["geology"],
    "SILICA":   ["geology"],
    "SULPHUR":  ["geology"],
    "BASALT":   ["geology"],
    "VOID":     ["remnant"],
}


def _load_compounds():
    path = Path(__file__).parent.parent.parent / "config" / "blueprints" / "compounds.json"
    if path.exists():
        return json.load(open(path))
    return {}


def _load_tree_blueprint():
    path = Path(__file__).parent.parent.parent / "config" / "blueprints" / "verdant.json"
    if path.exists():
        return json.load(open(path))
    return {"trees": {}, "palette": {}}


class BiomeSceneBuilder:
    """
    Composes a complete biome scene from compound objects + trees.

    Parameters
    ----------
    render_root : Panda3D NodePath
    seed        : int -- deterministic generation
    radius      : float -- scene radius in metres
    """

    def __init__(self, render_root, seed: int = 42, radius: float = 50.0,
                 panda_loader=None):
        self.render_root    = render_root
        self.seed           = seed
        self.radius         = radius
        self.nodes          = []
        self._factory       = PrimitiveFactory()
        self._compounds     = _load_compounds()
        self._tree_bp       = _load_tree_blueprint()
        self._tree_builder  = TreeBuilder()
        self._model_loader  = ModelLoader(panda_loader) if panda_loader else None
        self._floor_np      = None

    def build(self, biome_key: str, register: str = "survival") -> list:
        """
        Build a complete biome scene with compound scatter + trees.
        Returns list of node dicts.
        """
        self.clear()
        rng = random.Random(self.seed)

        # Floor
        pal = BIOME_PALETTE.get(biome_key, BIOME_PALETTE["VOID"])
        floor_geom = _make_plane_geom(
            int(self.radius * 2), int(self.radius * 2), pal["floor"]
        )
        self._floor_np = self.render_root.attachNewNode(floor_geom)
        self._floor_np.setPos(0, 0, 0)
        self.nodes.append({"np": self._floor_np, "role": "floor", "biome": biome_key})

        # Scatter compound objects
        scatter_keys = self._get_scatter_keys(biome_key)
        count = _SCATTER_COUNTS.get(biome_key, 10)

        for _ in range(count):
            if not scatter_keys:
                break
            key = rng.choice(scatter_keys)
            bp = self._compounds[key]

            x = rng.uniform(-self.radius * 0.7, self.radius * 0.7)
            y = rng.uniform(-self.radius * 0.7, self.radius * 0.7)
            # Keep objects out of immediate player space
            if abs(x) < 4 and abs(y) < 4:
                x += 6 * (1 if x >= 0 else -1)

            root = self._spawn_compound(key, bp, register, (x, y, 0.0))
            if root:
                # Random rotation for variety
                root.setH(rng.uniform(0, 360))
                self.nodes.append({
                    "np": root, "role": "scatter", "biome": biome_key,
                    "compound_key": key,
                })

        # Trees + environment models (imported when available, fallback to procedural)
        if self._model_loader and biome_key in _TREE_BIOMES:
            self._scatter_imported_models(biome_key, register, rng)
        elif biome_key in _TREE_BIOMES and self._tree_bp.get("trees"):
            # Fallback: procedural trees
            tree_count = rng.randint(12, 25)
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

        # Imported rock/plant scatter for non-tree biomes
        if self._model_loader and biome_key not in _TREE_BIOMES:
            self._scatter_imported_models(biome_key, register, rng)

        return self.nodes

    def _scatter_imported_models(self, biome_key, register, rng):
        """Scatter imported Kenney models appropriate for this biome."""
        # Pick models by biome category
        categories = _BIOME_CATEGORIES.get(biome_key, ["geology"])
        model_ids = []
        for cat in categories:
            model_ids.extend(self._model_loader.by_category(cat))

        if not model_ids:
            return

        # Trees for vegetated biomes
        if biome_key in _TREE_BIOMES:
            tree_ids = self._model_loader.by_category("flora")
            tree_ids = [t for t in tree_ids if "tree" in t]
            tree_count = rng.randint(10, 20)
            for _ in range(tree_count):
                tid = rng.choice(tree_ids) if tree_ids else None
                if not tid:
                    continue
                np = self._model_loader.load(tid)
                if not np:
                    continue
                x = rng.uniform(-self.radius * 0.8, self.radius * 0.8)
                y = rng.uniform(-self.radius * 0.8, self.radius * 0.8)
                if abs(x) < 5 and abs(y) < 5:
                    x += 8 * (1 if x >= 0 else -1)
                np.reparentTo(self.render_root)
                np.setPos(x, y, 0)
                np.setH(rng.uniform(0, 360))
                self._model_loader.apply_register(np, register)
                self.nodes.append({
                    "np": np, "role": "tree", "biome": biome_key,
                    "model_id": tid,
                })

        # Ground scatter (rocks, plants, bushes, mushrooms)
        scatter_ids = [m for m in model_ids if "tree" not in m]
        scatter_count = rng.randint(8, 18)
        for _ in range(scatter_count):
            mid = rng.choice(scatter_ids) if scatter_ids else None
            if not mid:
                continue
            np = self._model_loader.load(mid)
            if not np:
                continue
            x = rng.uniform(-self.radius * 0.7, self.radius * 0.7)
            y = rng.uniform(-self.radius * 0.7, self.radius * 0.7)
            if abs(x) < 4 and abs(y) < 4:
                x += 6 * (1 if x >= 0 else -1)
            np.reparentTo(self.render_root)
            np.setPos(x, y, 0)
            np.setH(rng.uniform(0, 360))
            self._model_loader.apply_register(np, register)
            self.nodes.append({
                "np": np, "role": "scatter", "biome": biome_key,
                "model_id": mid,
            })

    def _get_scatter_keys(self, biome_key: str) -> list:
        """Get compound keys appropriate for this biome."""
        categories = _BIOME_CATEGORIES.get(biome_key, ["geology"])
        keys = []
        for key, bp in self._compounds.items():
            if not bp.get("biome_scatter"):
                continue
            if bp.get("category") in categories:
                keys.append(key)
        return keys

    def _spawn_compound(self, key, bp, register, pos):
        """Spawn a compound object at position with register palette."""
        regs = bp.get("registers", {})
        if register not in regs:
            # Fallback to first available register
            if regs:
                register = next(iter(regs))
            else:
                return None

        full_palette = self._factory.resolve_register_full(regs, register)
        parts = self._factory.from_blueprint_full(bp, full_palette)

        root = self.render_root.attachNewNode(f"compound_{key}")
        root.setPos(*pos)

        for p in parts:
            child = root.attachNewNode(p.geom_node)
            child.setPos(p.offset_x, p.offset_y, p.offset_z)
            if p.emission > 0:
                mat = Material(f"emit_{p.role}")
                e = p.emission
                mat.setEmission(Vec4(
                    p.edge_color[0] * e, p.edge_color[1] * e,
                    p.edge_color[2] * e, 1.0
                ))
                child.setMaterial(mat, 1)

        return root

    def clear(self):
        """Remove all scene nodes."""
        for entry in self.nodes:
            np = entry.get("np")
            if np and not np.isEmpty():
                try:
                    np.removeNode()
                except Exception:
                    pass
        self.nodes = []
        self._floor_np = None
