"""
renderer_bridge.py

Brain bridge: biome engine → frame manifest → wgpu renderer.

Imports the real brain (biome_data, PlacementEngine, FrameComposer,
SpatialHash, WakeChain) and feeds manifests to NativeRenderer each frame.

Usage:
    python renderer_bridge.py [outdoor|cavern]
    make outdoor
"""

import sys
import random

from core.systems.biome_data import (
    OUTDOOR_LIGHT_STATES, CAVERN_LIGHT_STATES,
)
from core.systems.spatial_wake import SpatialHash, WakeChain, WAKE_CHAINS
from core.systems.world_gen import generate_tile
from native_renderer import NativeRenderer, GROUND_INSTANCE


# -- Kind properties: entity kind → (sx, sy, sz, r, g, b) for cube rendering --
# Scale = cube dimensions. Color = base RGB before lighting.
# Derived from ambient_life.py builder sizes + palettes.

KIND_PROPS = {
    # Skeleton — the landmark geometry you navigate by
    "mega_column":     {"scale": (3.0, 3.0, 12.0), "color": (0.28, 0.22, 0.16), "emissive": 0.0},
    "column":          {"scale": (1.8, 1.8, 8.0),  "color": (0.30, 0.25, 0.18), "emissive": 0.0},

    # Landmarks — mid-size objects that define spaces
    "boulder":         {"scale": (4.0, 3.5, 2.5),  "color": (0.25, 0.42, 0.16), "emissive": 0.0},
    "stalagmite":      {"scale": (0.8, 0.8, 3.0),  "color": (0.28, 0.24, 0.18), "emissive": 0.0},
    "crystal_cluster": {"scale": (1.5, 1.2, 2.0),  "color": (0.35, 0.29, 0.19), "emissive": 1.0},
    "giant_fungus":    {"scale": (2.0, 2.0, 3.5),  "color": (0.20, 0.36, 0.15), "emissive": 0.8},

    # Ecosystem — medium detail
    "dead_log":        {"scale": (3.0, 0.8, 0.6),  "color": (0.19, 0.27, 0.12), "emissive": 0.0},
    "moss_patch":      {"scale": (1.5, 1.5, 0.15), "color": (0.14, 0.33, 0.09), "emissive": 0.9},
    "bone_pile":       {"scale": (0.6, 0.6, 0.3),  "color": (0.14, 0.13, 0.11), "emissive": 0.0},

    # Ground cover
    "grass_tuft":      {"scale": (0.3, 0.3, 0.25), "color": (0.18, 0.33, 0.11), "emissive": 0.0},
    "rubble":          {"scale": (0.8, 0.8, 0.4),  "color": (0.28, 0.24, 0.19), "emissive": 0.0},
    "leaf_pile":       {"scale": (0.5, 0.5, 0.1),  "color": (0.30, 0.23, 0.12), "emissive": 0.0},
    "twig_scatter":    {"scale": (0.6, 0.4, 0.05), "color": (0.25, 0.21, 0.14), "emissive": 0.0},
    "cave_gravel":     {"scale": (0.2, 0.2, 0.05), "color": (0.24, 0.22, 0.16), "emissive": 0.0},

    # Life
    "firefly":         {"scale": (0.06, 0.06, 0.06), "color": (0.95, 0.75, 0.30), "emissive": 1.0},
    "leaf":            {"scale": (0.08, 0.06, 0.01), "color": (0.22, 0.30, 0.10), "emissive": 0.0},
    "beetle":          {"scale": (0.04, 0.03, 0.02), "color": (0.10, 0.08, 0.06), "emissive": 0.0},
    "rat":             {"scale": (0.12, 0.06, 0.06), "color": (0.14, 0.11, 0.08), "emissive": 0.0},
    "spider":          {"scale": (0.05, 0.05, 0.03), "color": (0.08, 0.07, 0.06), "emissive": 0.0},

    # Atmosphere (cavern-only)
    "ceiling_moss":    {"scale": (1.0, 1.0, 0.8),  "color": (0.12, 0.18, 0.08), "emissive": 0.9},
    "hanging_vine":    {"scale": (0.3, 0.3, 2.5),  "color": (0.10, 0.16, 0.07), "emissive": 0.0},
    "filament":        {"scale": (0.05, 0.05, 3.0), "color": (0.30, 0.40, 0.55), "emissive": 1.0},

    # Horizon
    "horizon_form":    {"scale": (6.0, 4.0, 10.0), "color": (0.08, 0.10, 0.05), "emissive": 0.0},
    "horizon_mid":     {"scale": (4.0, 3.0, 7.0),  "color": (0.10, 0.12, 0.06), "emissive": 0.0},
    "horizon_near":    {"scale": (3.0, 2.0, 5.0),  "color": (0.12, 0.14, 0.08), "emissive": 0.0},
    "exit_lure":       {"scale": (1.0, 1.0, 2.0),  "color": (0.60, 0.45, 0.20), "emissive": 1.0},
}

KIND_IDS = {k: i for i, k in enumerate(KIND_PROPS.keys())}


# -- World generation using real brain -----------------------------------------

def generate_world(biome_name, seed=42, tile_size=288.0):
    """Generate entity placements. Thin wrapper around shared world_gen.generate_tile.

    Converts tile-local (kind, (x,y), heading, seed) output to
    world-space (kind, x, y, z, heading, seed) with z offsets for floating kinds.
    """
    rng = random.Random(seed)
    tile_spawns = generate_tile(seed=seed, biome_name=biome_name, tile_size=tile_size)

    # Convert to world-space with z offsets
    half = tile_size / 2.0
    spawns = []
    for kind, (tx, ty), heading, kseed in tile_spawns:
        # Center tile around origin
        x = tx - half
        y = ty - half
        z = 0.0
        if kind == "leaf":
            z = 3.0
        elif kind == "ceiling_moss":
            z = rng.uniform(5.0, 8.0)
        elif kind == "hanging_vine":
            z = rng.uniform(4.0, 7.0)
        elif kind == "filament":
            z = rng.uniform(1.0, 4.0)
        elif kind == "firefly":
            z = rng.uniform(0.5, 2.5)
        spawns.append((kind, x, y, z, heading, kseed))

    return spawns


def spawns_to_entities(spawns, mesh_bounds=None):
    """Convert spawn list to manifest entity tuples.

    Each spawn (kind, x, y, z, heading, seed) becomes
    (kind_id, x, y, z, heading, sx, sy, sz, r, g, b, emissive).

    If mesh_bounds is provided (from mesh library), scale comes from
    actual mesh dimensions and color tint is (1,1,1) — vertex colors
    already carry the builder's baked color.
    """
    entities = []
    for kind, x, y, z, heading, seed in spawns:
        props = KIND_PROPS.get(kind)
        if not props:
            continue
        kid = KIND_IDS.get(kind, 0)
        emissive = props.get("emissive", 0.0)
        srng = random.Random(seed)
        sv = srng.uniform(0.75, 1.25)

        if mesh_bounds and kind in mesh_bounds:
            bounds = mesh_bounds[kind]
            sx = bounds["width"] * sv
            sy = bounds["depth"] * sv
            sz = bounds["height"] * srng.uniform(0.80, 1.20)
            r = srng.uniform(0.90, 1.10)
            g = srng.uniform(0.90, 1.10)
            b = srng.uniform(0.90, 1.10)
        else:
            sx, sy, sz = props["scale"]
            r, g, b = props["color"]
            sx *= sv
            sy *= sv
            sz *= srng.uniform(0.80, 1.20)
            r *= srng.uniform(0.85, 1.15)
            g *= srng.uniform(0.85, 1.15)
            b *= srng.uniform(0.85, 1.15)

        entities.append((kid, x, y, z, heading, sx, sy, sz, r, g, b, emissive))
    return entities


# -- Main ----------------------------------------------------------------------

def main():
    biome_name = sys.argv[1] if len(sys.argv) > 1 else "outdoor"
    seed = 42

    print(f"Generating {biome_name} world (seed={seed})...", flush=True)

    # Load mesh bounds for proper scaling
    from native_renderer import load_mesh_library
    mesh_lib = load_mesh_library()
    mesh_bounds = {k: b for k, (_, b) in mesh_lib.items()}

    # Generate world using real brain
    spawns = generate_world(biome_name, seed=seed)
    all_entities = spawns_to_entities(spawns, mesh_bounds=mesh_bounds)
    print(f"  {len(spawns)} placements → {len(all_entities)} entities", flush=True)

    # Build spatial hash + wake chain
    chain_key = biome_name if biome_name in WAKE_CHAINS else "outdoor"
    wake_chain = WakeChain(WAKE_CHAINS[chain_key])
    spatial = SpatialHash(cell_size=20.0)

    entity_map = {}
    for i, (kind, x, y, z, heading, seed) in enumerate(spawns):
        chain_idx = wake_chain.chain_index(kind)
        spatial.insert(i, x, y, chain_index=chain_idx)
        entity_map[i] = all_entities[i] if i < len(all_entities) else None

    # Light state — use dusk for outdoor (moody, matches reference feel)
    light_states = OUTDOOR_LIGHT_STATES if biome_name == "outdoor" else CAVERN_LIGHT_STATES
    default_state = "dusk" if biome_name == "outdoor" else "cave"
    ls = light_states[default_state]
    fog_manifest = {
        "near": ls["fog_near"],
        "far": ls["fog_far"],
        "color": ls["fog_color"],
    }

    last_wake_ids = [set()]
    cached_manifest = [None]
    wake_check_timer = [0.0]

    def frame_callback(cam, dt):
        """Called each frame by the renderer. Return manifest or None."""
        wake_check_timer[0] += dt

        if wake_check_timer[0] < 0.1 and cached_manifest[0] is not None:
            return None
        wake_check_timer[0] = 0.0

        wake_set = wake_chain.compute_wake_set(spatial, cam["x"], cam["y"])
        wake_ids = {eid for eid, _ in wake_set}

        if wake_ids == last_wake_ids[0] and cached_manifest[0] is not None:
            return None

        last_wake_ids[0] = wake_ids

        visible = [GROUND_INSTANCE]
        for eid, _ in wake_set:
            e = entity_map.get(eid)
            if e is not None:
                visible.append(e)

        cached_manifest[0] = {
            "camera": (cam["x"], cam["y"], cam["z"], cam["h"], cam["p"]),
            "fog": fog_manifest,
            "ambient": ls["ambient"],
            "entities": visible,
        }
        return cached_manifest[0]

    label = "PNW Forest" if biome_name == "outdoor" else "Cavern"
    kind_names = list(KIND_IDS.keys())
    renderer = NativeRenderer(
        title=f"Sanctum — {label} ({len(all_entities)} entities)",
        kind_names=kind_names)
    renderer.cam["z"] = 2.5
    renderer.cam["y"] = -10.0
    renderer.run(frame_callback)


if __name__ == "__main__":
    main()
