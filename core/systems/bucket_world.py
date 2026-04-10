"""
core/systems/bucket_world.py

Pure-function world generation. The 1984 approach.

The world is a function: spawn_bucket(bx, by, seed, biome) → entities.
Same input, same output. No cache, no state, no shells, no scoring.
Buckets are 16m × 16m. The visible circle (49m radius) covers ~30 buckets.
At ~10 entities per bucket, that's ~300 visible entities computed fresh
every frame. Modern Python does this in milliseconds.

Walking anywhere works. Walking back returns the same entities.
The garbage collector IS the cleanup — entities that aren't asked for
this frame simply don't exist.

This is what Elite, Frontier, and roguelikes have always done.
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Tuple

from core.systems.biome_data import BIOME_REGISTRY


# 16m × 16m buckets — small enough that the visible circle (49m radius)
# covers a manageable count, large enough that per-bucket entity counts
# average out the discrete spawn rolls.
BUCKET_SIZE = 16.0


# Per-kind visual properties — copied from tile_exchange.KIND_PROPS so
# bucket_world is standalone. Same kinds, same scales, same colors.
KIND_PROPS = {
    "mega_column":     {"scale": [3.0, 3.0, 12.0], "color": [0.28, 0.22, 0.16], "emissive": 0.0},
    "column":          {"scale": [2.25, 2.25, 10.0], "color": [0.30, 0.25, 0.18], "emissive": 0.0},
    "buttress":        {"scale": [2.5, 2.5, 6.0],  "color": [0.26, 0.21, 0.16], "emissive": 0.0},
    "boulder":         {"scale": [5.0, 4.4, 3.1],  "color": [0.25, 0.42, 0.16], "emissive": 0.0},
    "stalagmite":      {"scale": [1.0, 1.0, 3.75], "color": [0.28, 0.24, 0.18], "emissive": 0.0},
    "crystal_cluster": {"scale": [2.8, 2.2, 3.5],  "color": [0.50, 0.55, 0.80], "emissive": 1.0},
    "giant_fungus":    {"scale": [2.5, 2.5, 4.4],  "color": [0.30, 0.50, 0.25], "emissive": 0.8},
    "toadstool":       {"scale": [1.2, 1.2, 2.3],  "color": [1.00, 1.00, 1.00], "emissive": 0.0},
    "spore_pod":       {"scale": [1.5, 1.5, 0.9],  "color": [1.00, 1.00, 1.00], "emissive": 0.0},
    "dead_log":        {"scale": [3.75, 1.0, 0.75],"color": [0.19, 0.27, 0.12], "emissive": 0.0},
    "moss_patch":      {"scale": [1.5, 1.5, 0.15], "color": [0.22, 0.45, 0.15], "emissive": 0.9},
    "bone_pile":       {"scale": [0.6, 0.6, 0.3],  "color": [0.14, 0.13, 0.11], "emissive": 0.0},
    "grass_tuft":      {"scale": [0.3, 0.3, 0.25], "color": [0.18, 0.33, 0.11], "emissive": 0.0},
    "rubble":          {"scale": [1.0, 1.0, 0.5],  "color": [0.28, 0.24, 0.19], "emissive": 0.0},
    "leaf_pile":       {"scale": [0.5, 0.5, 0.1],  "color": [0.30, 0.23, 0.12], "emissive": 0.0},
    "twig_scatter":    {"scale": [0.6, 0.4, 0.05], "color": [0.25, 0.21, 0.14], "emissive": 0.0},
    "cave_gravel":     {"scale": [0.2, 0.2, 0.05], "color": [0.24, 0.22, 0.16], "emissive": 0.0},
    "firefly":         {"scale": [0.06, 0.06, 0.06],"color": [0.95, 0.75, 0.30], "emissive": 1.0},
    "leaf":            {"scale": [0.08, 0.06, 0.01],"color": [0.22, 0.30, 0.10], "emissive": 0.0},
    "beetle":          {"scale": [0.04, 0.03, 0.02],"color": [0.10, 0.08, 0.06], "emissive": 0.0},
    "rat":             {"scale": [0.12, 0.06, 0.06],"color": [0.14, 0.11, 0.08], "emissive": 0.0},
    "spider":          {"scale": [0.05, 0.05, 0.03],"color": [0.08, 0.07, 0.06], "emissive": 0.0},
    "ceiling_moss":    {"scale": [3.0, 3.0, 2.5],  "color": [0.35, 0.45, 0.18], "emissive": 0.9},
    "hanging_vine":    {"scale": [0.8, 0.8, 4.0],  "color": [0.10, 0.16, 0.07], "emissive": 0.0},
    "filament":        {"scale": [0.25, 0.25, 3.5], "color": [0.30, 0.40, 0.55], "emissive": 1.0},
    "horizon_form":    {"scale": [6.0, 4.0, 10.0], "color": [0.08, 0.10, 0.05], "emissive": 0.0},
    "horizon_mid":     {"scale": [4.0, 3.0, 7.0],  "color": [0.10, 0.12, 0.06], "emissive": 0.0},
    "horizon_near":    {"scale": [3.0, 2.0, 5.0],  "color": [0.12, 0.14, 0.08], "emissive": 0.0},
    "exit_lure":       {"scale": [1.0, 1.0, 2.0],  "color": [0.60, 0.45, 0.20], "emissive": 1.0},
}


def _bucket_seed(bx: int, by: int, world_seed: int) -> int:
    """Deterministic per-bucket seed. Same coords + world seed → same RNG."""
    return world_seed ^ (bx * 7919) ^ (by * 6271 << 1)


def spawn_bucket(bx: int, by: int, seed: int, biome_name: str) -> List[Dict]:
    """Pure function: bucket coords → entity list. No state. No cache.

    For each kind in the biome's density table, roll dice based on
    density × bucket area. Each entity gets a deterministic position,
    rotation, and color jitter from the bucket's RNG.
    """
    biome_reg = BIOME_REGISTRY.get(biome_name, {})
    density_table = biome_reg.get("density", [])
    if not density_table:
        return []

    rng = random.Random(_bucket_seed(bx, by, seed))
    bucket_area_sqm = BUCKET_SIZE * BUCKET_SIZE
    x_origin = bx * BUCKET_SIZE
    y_origin = by * BUCKET_SIZE

    roster = []
    for entry in density_table:
        kind, density_per_1000sqm, _clearance, _margin = entry
        props = KIND_PROPS.get(kind)
        if props is None:
            continue

        # Expected count in this bucket
        expected = density_per_1000sqm * bucket_area_sqm / 1000.0

        # Roll: integer floor + fractional remainder as probability.
        # E.g. expected=0.31 → 0 entities + 31% chance of 1 more.
        whole = int(expected)
        frac = expected - whole
        count = whole + (1 if rng.random() < frac else 0)

        for _ in range(count):
            x = x_origin + rng.uniform(0.0, BUCKET_SIZE)
            y = y_origin + rng.uniform(0.0, BUCKET_SIZE)
            sv = rng.uniform(0.75, 1.25) * 1.30
            sx, sy_s, sz = props["scale"]
            r, g, b = props["color"]
            ent = {
                "kind": kind,
                "x": round(x, 2),
                "y": round(y, 2),
                "z": 0.0,
                "heading": round(rng.uniform(0.0, 360.0), 1),
                "sv": round(sv, 3),
                "sx": round(sx * sv, 3),
                "sy": round(sy_s * sv, 3),
                "sz": round(sz * rng.uniform(0.80, 1.20), 3),
                "r": round(r * rng.uniform(0.85, 1.15), 3),
                "g": round(g * rng.uniform(0.85, 1.15), 3),
                "b": round(b * rng.uniform(0.85, 1.15), 3),
                "emissive": props["emissive"],
                "light_hue": rng.randint(0, 3),
                "collision_radius": 0.0,
                "tile_variant": "standard",
                "behavior_type": "",
                "decay_stage": 0.0,
                "_chain_index": 0,
            }
            roster.append(ent)

    return roster


def get_visible(cam_x: float, cam_y: float, radius: float,
                seed: int, biome_name: str) -> List[Dict]:
    """Collect all entities from buckets overlapping the visible circle.

    Iterates the AABB of buckets that could intersect the circle, calls
    spawn_bucket for each, then filters entities by exact distance.
    No cache: every call is fresh.
    """
    radius_sq = radius * radius

    bx_min = int(math.floor((cam_x - radius) / BUCKET_SIZE))
    bx_max = int(math.floor((cam_x + radius) / BUCKET_SIZE))
    by_min = int(math.floor((cam_y - radius) / BUCKET_SIZE))
    by_max = int(math.floor((cam_y + radius) / BUCKET_SIZE))

    visible = []
    for bx in range(bx_min, bx_max + 1):
        for by in range(by_min, by_max + 1):
            for ent in spawn_bucket(bx, by, seed, biome_name):
                dx = ent["x"] - cam_x
                dy = ent["y"] - cam_y
                if dx * dx + dy * dy <= radius_sq:
                    visible.append(ent)

    return visible
