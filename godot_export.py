"""
godot_export.py

Brain → JSON manifest → disk. Godot reads the file.

Phase 1: prove the pipeline. Python brain generates world,
writes manifest.json, Godot project loads and renders it.

Usage:
    python godot_export.py [outdoor|cavern]
    make godot-export
"""

import json
import os
import sys
import random

from core.systems.biome_data import (
    BIOME_REGISTRY,
    OUTDOOR_LIGHT_STATES, CAVERN_LIGHT_STATES,
    HARD_OBJECTS,
)
from core.systems.spatial_wake import SpatialHash, WakeChain, WAKE_CHAINS
from core.systems.world_gen import generate_tile


# -- Kind properties: scale + color + emissive for each entity kind -----------

KIND_PROPS = {
    "mega_column":     {"scale": [3.0, 3.0, 12.0], "color": [0.28, 0.22, 0.16], "emissive": 0.0},
    "column":          {"scale": [1.8, 1.8, 8.0],  "color": [0.30, 0.25, 0.18], "emissive": 0.0},
    "boulder":         {"scale": [4.0, 3.5, 2.5],  "color": [0.25, 0.42, 0.16], "emissive": 0.0},
    "stalagmite":      {"scale": [0.8, 0.8, 3.0],  "color": [0.28, 0.24, 0.18], "emissive": 0.0},
    "crystal_cluster": {"scale": [1.5, 1.2, 2.0],  "color": [0.35, 0.29, 0.19], "emissive": 1.0},
    "giant_fungus":    {"scale": [2.0, 2.0, 3.5],  "color": [0.20, 0.36, 0.15], "emissive": 0.8},
    "dead_log":        {"scale": [3.0, 0.8, 0.6],  "color": [0.19, 0.27, 0.12], "emissive": 0.0},
    "moss_patch":      {"scale": [1.5, 1.5, 0.15], "color": [0.14, 0.33, 0.09], "emissive": 0.9},
    "bone_pile":       {"scale": [0.6, 0.6, 0.3],  "color": [0.14, 0.13, 0.11], "emissive": 0.0},
    "grass_tuft":      {"scale": [0.3, 0.3, 0.25], "color": [0.18, 0.33, 0.11], "emissive": 0.0},
    "rubble":          {"scale": [0.8, 0.8, 0.4],  "color": [0.28, 0.24, 0.19], "emissive": 0.0},
    "leaf_pile":       {"scale": [0.5, 0.5, 0.1],  "color": [0.30, 0.23, 0.12], "emissive": 0.0},
    "twig_scatter":    {"scale": [0.6, 0.4, 0.05], "color": [0.25, 0.21, 0.14], "emissive": 0.0},
    "cave_gravel":     {"scale": [0.2, 0.2, 0.05], "color": [0.24, 0.22, 0.16], "emissive": 0.0},
    "firefly":         {"scale": [0.06, 0.06, 0.06],"color": [0.95, 0.75, 0.30], "emissive": 1.0},
    "leaf":            {"scale": [0.08, 0.06, 0.01],"color": [0.22, 0.30, 0.10], "emissive": 0.0},
    "beetle":          {"scale": [0.04, 0.03, 0.02],"color": [0.10, 0.08, 0.06], "emissive": 0.0},
    "rat":             {"scale": [0.12, 0.06, 0.06],"color": [0.14, 0.11, 0.08], "emissive": 0.0},
    "spider":          {"scale": [0.05, 0.05, 0.03],"color": [0.08, 0.07, 0.06], "emissive": 0.0},
    "ceiling_moss":    {"scale": [1.0, 1.0, 0.8],  "color": [0.12, 0.18, 0.08], "emissive": 0.9},
    "hanging_vine":    {"scale": [0.3, 0.3, 2.5],  "color": [0.10, 0.16, 0.07], "emissive": 0.0},
    "filament":        {"scale": [0.05, 0.05, 3.0], "color": [0.30, 0.40, 0.55], "emissive": 1.0},
    "horizon_form":    {"scale": [6.0, 4.0, 10.0], "color": [0.08, 0.10, 0.05], "emissive": 0.0},
    "horizon_mid":     {"scale": [4.0, 3.0, 7.0],  "color": [0.10, 0.12, 0.06], "emissive": 0.0},
    "horizon_near":    {"scale": [3.0, 2.0, 5.0],  "color": [0.12, 0.14, 0.08], "emissive": 0.0},
    "exit_lure":       {"scale": [1.0, 1.0, 2.0],  "color": [0.60, 0.45, 0.20], "emissive": 1.0},
}

# Collision radii for Godot static bodies
COLLISION_RADII = {k: v for k, v in HARD_OBJECTS.items()}


def generate_world(biome_name, seed=42, tile_size=288.0):
    """Run brain placement engine. Returns spawn list."""
    rng = random.Random(seed)
    tile_spawns = generate_tile(seed=seed, biome_name=biome_name, tile_size=tile_size)

    half = tile_size / 2.0
    spawns = []
    for kind, (tx, ty), heading, kseed in tile_spawns:
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


def build_manifest(biome_name, seed=42):
    """Generate full manifest dict for Godot consumption."""
    spawns = generate_world(biome_name, seed=seed)

    # Build entities with per-seed variation
    entities = []
    for kind, x, y, z, heading, kseed in spawns:
        props = KIND_PROPS.get(kind)
        if not props:
            continue
        srng = random.Random(kseed)
        sv = srng.uniform(0.75, 1.25)
        sx, sy, sz = props["scale"]
        r, g, b = props["color"]
        entities.append({
            "kind": kind,
            "x": round(x, 2),
            "y": round(y, 2),
            "z": round(z, 2),
            "heading": round(heading, 1),
            "sv": round(sv, 3),
            "sx": round(sx * sv, 3),
            "sy": round(sy * sv, 3),
            "sz": round(sz * srng.uniform(0.80, 1.20), 3),
            "r": round(r * srng.uniform(0.85, 1.15), 3),
            "g": round(g * srng.uniform(0.85, 1.15), 3),
            "b": round(b * srng.uniform(0.85, 1.15), 3),
            "emissive": props["emissive"],
            "collision_radius": COLLISION_RADII.get(kind, 0.0),
        })

    # -- Bake light influence into entity colors --
    # For each entity, find nearby emissives and tint toward their color.
    # This is the PS2 trick: vertex colors carry light memory.
    EMISSIVE_LIGHT_COLORS = {
        "crystal_cluster": (0.25, 0.30, 0.55),
        "giant_fungus":    (0.15, 0.25, 0.08),
        "moss_patch":      (0.08, 0.30, 0.06),
        "firefly":         (0.50, 0.40, 0.15),
        "filament":        (0.20, 0.30, 0.40),
        "ceiling_moss":    (0.40, 0.28, 0.10),
    }
    # Collect emissive positions
    emissive_positions = []
    for e in entities:
        if e["kind"] in EMISSIVE_LIGHT_COLORS:
            emissive_positions.append((
                e["x"], e["y"], e["z"],
                EMISSIVE_LIGHT_COLORS[e["kind"]],
                12.0,  # influence radius
            ))

    # Tint non-emissive entities
    for e in entities:
        if e["emissive"] > 0:
            continue
        ex, ey = e["x"], e["y"]
        lr, lg, lb = 0.0, 0.0, 0.0
        for lx, ly, lz, (cr, cg, cb), radius in emissive_positions:
            dx, dy = ex - lx, ey - ly
            dist = (dx*dx + dy*dy) ** 0.5
            if dist < radius:
                # Inverse distance falloff
                influence = (1.0 - dist / radius) ** 2 * 0.35
                lr += cr * influence
                lg += cg * influence
                lb += cb * influence
        # Apply accumulated light tint
        e["r"] = round(min(1.0, e["r"] + lr), 3)
        e["g"] = round(min(1.0, e["g"] + lg), 3)
        e["b"] = round(min(1.0, e["b"] + lb), 3)

    # Light state
    light_states = OUTDOOR_LIGHT_STATES if biome_name == "outdoor" else CAVERN_LIGHT_STATES
    default_state = "dusk" if biome_name == "outdoor" else "cave"
    ls = light_states[default_state]

    # Spatial hash stats for debugging
    chain_key = biome_name if biome_name in WAKE_CHAINS else "outdoor"
    wake_chain = WakeChain(WAKE_CHAINS[chain_key])
    spatial = SpatialHash(cell_size=20.0)
    for i, (kind, x, y, z, heading, kseed) in enumerate(spawns):
        chain_idx = wake_chain.chain_index(kind)
        spatial.insert(i, x, y, chain_index=chain_idx)

    # Test wake from center
    wake_set = wake_chain.compute_wake_set(spatial, 0.0, 0.0)

    manifest = {
        "biome": biome_name,
        "seed": seed,
        "light_state": default_state,
        "camera": {
            "x": 0.0, "y": 0.0, "z": 2.5,
            "heading": 0.0, "pitch": 0.0,
        },
        "fog": {
            "near": ls["fog_near"],
            "far": ls["fog_far"],
            "color": list(ls["fog_color"]),
        },
        "ambient": list(ls["ambient"]),
        "bg_color": list(ls["bg_color"]),
        "sun": {
            "color": list(ls.get("sun_color", [0, 0, 0])),
            "scale": ls.get("sun_scale", 0.0),
        },
        "moon": {
            "color": list(ls.get("moon_color", [0, 0, 0])),
            "scale": ls.get("moon_scale", 0.0),
        },
        "entities": entities,
        "stats": {
            "total_spawns": len(spawns),
            "total_entities": len(entities),
            "wake_from_center": len(wake_set),
        },
    }
    return manifest


def main():
    biome_name = sys.argv[1] if len(sys.argv) > 1 else "outdoor"
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42

    print(f"Generating {biome_name} biome (seed={seed})...")
    manifest = build_manifest(biome_name, seed=seed)

    out_path = os.path.join(os.path.dirname(__file__), "godot", "manifest.json")
    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2)

    stats = manifest["stats"]
    print(f"  {stats['total_spawns']} spawns → {stats['total_entities']} entities")
    print(f"  {stats['wake_from_center']} visible from center (wake set)")
    print(f"  Written to {out_path}")
    print(f"  Light: {manifest['light_state']}, fog: {manifest['fog']['near']}-{manifest['fog']['far']}m")


if __name__ == "__main__":
    main()
