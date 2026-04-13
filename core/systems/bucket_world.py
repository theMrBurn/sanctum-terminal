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


# Phase 3: KIND_PROPS now derives from kind_config.json (config/kind_config.json).
# This dict is a SHIM kept for backwards-compat with stamp_world and other
# importers; the literal definitions below are the FALLBACK for any kind
# missing render.scale/color/emissive in kind_config. New kinds should be
# added to kind_config first, not here.
from core.systems import kind_config as _kc


def _build_kind_props_from_config() -> dict:
    """Derive KIND_PROPS shape (scale/color/emissive) from kind_config.
    Falls back to the literal table below for any kind missing render fields."""
    out = {}
    for name, kcfg in _kc.all_kinds().items():
        render = kcfg.get("render", {})
        if "scale" in render and "color" in render and "emissive" in render:
            out[name] = {
                "scale": list(render["scale"]),
                "color": list(render["color"]),
                "emissive": float(render["emissive"]),
            }
    return out


# Live KIND_PROPS = derived from kind_config (single source of truth, Phase 5).
# All 35 kinds have render.scale/color/emissive in kind_config. The literal
# fallback dict was deleted in Phase 5 — kind_config is now load-bearing.
# If a future kind appears here without a render block in kind_config, it
# silently won't be in KIND_PROPS — add to kind_config first.
KIND_PROPS = _build_kind_props_from_config()


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
