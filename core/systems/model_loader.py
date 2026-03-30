"""
core/systems/model_loader.py

ModelLoader -- loads reference .glb models and applies register palettes.

Hybrid approach: imported models for professional proportions (nouns),
compound primitives for procedural objects (adjectives).

Register palette applies via setColorScale() on imported models.
Same [R] cycle, different rendering path.

Usage:
    loader = ModelLoader(app_loader)
    node = loader.load("tree_detailed", scale=10.0)
    loader.apply_register(node, "tron", tint=(0.0, 0.6, 0.8))
"""

from __future__ import annotations

import json
from pathlib import Path

from panda3d.core import SamplerState, Vec4


# -- Asset catalog -------------------------------------------------------------
# Maps logical names to .glb files in the Kenney nature kit.
# Scale factor brings Kenney units (~1m models) to game scale.

KENNEY_PATH = Path(__file__).parent.parent.parent / "assets" / "kenney" / "nature-kit" / "Models" / "GLTF format"

ASSET_CATALOG = {
    # Trees
    "tree_oak":         {"file": "tree_oak.glb",          "scale": 12.0, "category": "flora"},
    "tree_detailed":    {"file": "tree_detailed.glb",     "scale": 10.0, "category": "flora"},
    "tree_pine":        {"file": "tree_pineRoundA.glb",   "scale": 11.0, "category": "flora"},
    "tree_simple":      {"file": "tree_simple.glb",       "scale": 9.0,  "category": "flora"},
    "tree_tall":        {"file": "tree_tall.glb",         "scale": 13.0, "category": "flora"},
    "tree_dark":        {"file": "tree_default_dark.glb", "scale": 10.0, "category": "flora"},
    "tree_fall":        {"file": "tree_default_fall.glb", "scale": 10.0, "category": "flora"},
    # Rocks
    "rock_large":       {"file": "rock_largeA.glb",       "scale": 4.0,  "category": "geology"},
    "rock_tall":        {"file": "rock_tallA.glb",        "scale": 5.0,  "category": "geology"},
    "rock_small":       {"file": "rock_smallA.glb",       "scale": 3.0,  "category": "geology"},
    "rock_flat":        {"file": "rock_smallFlatA.glb",   "scale": 3.0,  "category": "geology"},
    # Plants
    "bush_large":       {"file": "plant_bushLarge.glb",   "scale": 4.0,  "category": "flora"},
    "bush_small":       {"file": "plant_bushSmall.glb",   "scale": 3.0,  "category": "flora"},
    "grass":            {"file": "grass_large.glb",       "scale": 2.5,  "category": "flora"},
    "flower_red":       {"file": "flower_redA.glb",       "scale": 2.0,  "category": "flora"},
    "mushroom":         {"file": "mushroom_redTall.glb",  "scale": 3.0,  "category": "flora"},
    # Structures
    "log":              {"file": "log.glb",               "scale": 3.0,  "category": "remnant"},
    "log_stack":        {"file": "log_stack.glb",         "scale": 3.0,  "category": "remnant"},
    "stump":            {"file": "stump_round.glb",       "scale": 3.5,  "category": "flora"},
    "campfire":         {"file": "campfire_stones.glb",   "scale": 3.0,  "category": "remnant"},
    "tent":             {"file": "tent_detailedOpen.glb", "scale": 4.0,  "category": "remnant"},
    "fence":            {"file": "fence_simple.glb",      "scale": 3.0,  "category": "remnant"},
    "bed":              {"file": "bed.glb",               "scale": 3.0,  "category": "remnant"},
    "canoe":            {"file": "canoe.glb",             "scale": 4.0,  "category": "remnant"},
    # Object mappings -- shelf objects from objects.json → Kenney models
    "stripped_branch":  {"file": "log.glb",               "scale": 2.0,  "category": "flora"},
    "canopy_leaf_bundle": {"file": "plant_bushSmall.glb", "scale": 2.5,  "category": "flora"},
    "root_cluster":     {"file": "stump_old.glb",         "scale": 2.0,  "category": "flora"},
    "fallen_log_section": {"file": "log_large.glb",       "scale": 2.5,  "category": "flora"},
    "sap_vessel":       {"file": "mushroom_tan.glb",      "scale": 2.0,  "category": "flora"},
    "river_stone":      {"file": "rock_smallA.glb",       "scale": 2.5,  "category": "geology"},
    "flint_shard":      {"file": "rock_smallFlatA.glb",   "scale": 2.0,  "category": "geology"},
    "clay_deposit":     {"file": "rock_smallFlatB.glb",   "scale": 2.5,  "category": "geology"},
    "chalk_outcrop":    {"file": "rock_smallB.glb",       "scale": 2.5,  "category": "geology"},
    "shed_antler":      {"file": "log.glb",               "scale": 1.5,  "category": "fauna"},
    "small_bone":       {"file": "log.glb",               "scale": 1.0,  "category": "fauna"},
    "creature_hide":    {"file": "plant_flatShort.glb",   "scale": 2.5,  "category": "fauna"},
    "rusted_pipe":      {"file": "fence_simple.glb",      "scale": 2.0,  "category": "remnant"},
    "glass_shard":      {"file": "rock_smallFlatC.glb",   "scale": 2.0,  "category": "remnant"},
    "fuel_canister":    {"file": "campfire_planks.glb",   "scale": 2.0,  "category": "remnant"},
    "concrete_fragment": {"file": "rock_largeB.glb",      "scale": 2.0,  "category": "remnant"},
    "faded_sign_panel": {"file": "fence_planks.glb",      "scale": 2.0,  "category": "remnant"},
}

# Register tints -- applied via setColorScale to shift model colors
REGISTER_TINTS = {
    "survival": Vec4(1.0,  0.95, 0.90, 1.0),    # warm neutral
    "tron":     Vec4(0.15, 0.5,  0.7,  1.0),     # cyan shift
    "tolkien":  Vec4(1.1,  0.9,  0.7,  1.0),     # golden warmth
    "sanrio":   Vec4(1.0,  0.8,  0.9,  1.0),     # pink tint
}


class ModelLoader:
    """
    Loads .glb reference models and applies register palette tints.

    Parameters
    ----------
    panda_loader : Panda3D Loader instance (from ShowBase)
    """

    def __init__(self, panda_loader):
        self._loader = panda_loader

    def load(self, asset_id: str, scale: float = None) -> object:
        """
        Load a model by catalog ID.
        Returns a Panda3D NodePath, scaled to game units.
        Returns None if model not found.
        """
        entry = ASSET_CATALOG.get(asset_id)
        if not entry:
            return None

        file_path = KENNEY_PATH / entry["file"]
        if not file_path.exists():
            return None

        model = self._loader.loadModel(str(file_path))
        if model is None:
            return None

        s = scale or entry.get("scale", 1.0)
        model.setScale(s)
        model.setPythonTag("asset_id", asset_id)
        model.setPythonTag("category", entry.get("category", "misc"))

        # Force nearest-neighbor filtering on all textures for pixel-crisp look
        for tex_stage in model.findAllTextureStages():
            tex = model.findTexture(tex_stage)
            if tex:
                tex.setMagfilter(SamplerState.FT_nearest)
                tex.setMinfilter(SamplerState.FT_nearest)

        return model

    def apply_register(self, node, register: str) -> None:
        """Apply register color tint to an imported model."""
        tint = REGISTER_TINTS.get(register, REGISTER_TINTS["survival"])
        node.setColorScale(tint)

    def available(self) -> list:
        """List all available asset IDs."""
        return list(ASSET_CATALOG.keys())

    def by_category(self, category: str) -> list:
        """List asset IDs for a given category."""
        return [k for k, v in ASSET_CATALOG.items() if v.get("category") == category]
