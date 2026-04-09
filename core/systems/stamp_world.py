"""
core/systems/stamp_world.py

Pure-function world generation from the AUTHORED stamp library.

The world is an infinite grid of slots. Each slot picks one stamp
deterministically from CAVERN_STAMPS or OUTDOOR_STAMPS, instantiates
its members at the slot center with small per-slot rotation/jitter,
and adds tissue scatter (loose grass, gravel, leaf piles) for connector
terrain between authored stamps.

This is the "ASCII braille / QR" model — the world is a grid you can
read like a code. Each glyph is a curated mini-scene the user designed.
Walk anywhere, you see authored content. The seed IS the world.

Save state: just (seed, player_pos). The entire world rebuilds from
those few bytes. v2 will add Wang-tile edge matching for stamp adjacency.

Pure Python. No cache. No state. Recomputed every frame.
"""

from __future__ import annotations

import math
import random
from typing import Dict, List

from core.systems.biome_data import (
    BIOME_REGISTRY,
    CAVERN_STAMPS,
    OUTDOOR_STAMPS,
)
from core.systems.bucket_world import KIND_PROPS


# Slot grid — each cell holds one stamp. 16m matches the visible radius
# (49m / 3 ≈ 16m) so the camera always sees ~3-4 slots in every direction.
SLOT_SIZE = 16.0

# Tissue scatter — connector terrain between authored stamps. Pure noise,
# fills the negative space. Density is per-slot (not per sqm).
TISSUE_KINDS_CAVERN = [
    ("grass_tuft",  3),  # (kind, count)
    ("rubble",      2),
    ("cave_gravel", 4),
]
TISSUE_KINDS_OUTDOOR = [
    ("grass_tuft",  4),
    ("leaf_pile",   2),
    ("twig_scatter", 3),
]


def _slot_seed(gx: int, gy: int, world_seed: int) -> int:
    """Deterministic per-slot seed."""
    return world_seed ^ (gx * 7919) ^ (gy * 6271 << 1)


def _stamps_for(biome_name: str) -> list:
    if biome_name == "outdoor":
        return OUTDOOR_STAMPS
    return CAVERN_STAMPS


def _tissue_for(biome_name: str) -> list:
    if biome_name == "outdoor":
        return TISSUE_KINDS_OUTDOOR
    return TISSUE_KINDS_CAVERN


def _make_entity(kind: str, x: float, y: float, rng: random.Random,
                 scale_mult: float = 1.0) -> Dict | None:
    """Build an entity dict from KIND_PROPS + per-instance jitter."""
    props = KIND_PROPS.get(kind)
    if props is None:
        return None
    sv = rng.uniform(0.75, 1.25) * 1.30 * scale_mult
    sx, sy_s, sz = props["scale"]
    r, g, b = props["color"]
    return {
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


def stamp_at(gx: int, gy: int, seed: int, biome_name: str) -> List[Dict]:
    """Pure function: slot coords → entity list.

    Picks one stamp deterministically, instantiates its members at the
    slot center with random rotation, then adds tissue scatter within
    the slot bounds. Same input always returns the same output.
    """
    stamps = _stamps_for(biome_name)
    if not stamps:
        return []

    rng = random.Random(_slot_seed(gx, gy, seed))
    cx = (gx + 0.5) * SLOT_SIZE
    cy = (gy + 0.5) * SLOT_SIZE

    # Pick one stamp from the library
    stamp = rng.choice(stamps)

    # Slot rotation — rotates the whole stamp by 0/90/180/270 to add variety
    rotation_steps = rng.randint(0, 3)
    cos_r = [1, 0, -1, 0][rotation_steps]
    sin_r = [0, 1, 0, -1][rotation_steps]

    roster = []
    for member in stamp["members"]:
        kind = member["kind"]
        dx_local = member.get("dx", 0.0)
        dy_local = member.get("dy", 0.0)
        # Rotate around stamp center
        dx_world = dx_local * cos_r - dy_local * sin_r
        dy_world = dx_local * sin_r + dy_local * cos_r
        x = cx + dx_world
        y = cy + dy_world
        scale_mult = member.get("scale_mult") or 1.0
        ent = _make_entity(kind, x, y, rng, scale_mult)
        if ent is not None:
            roster.append(ent)

    # Tissue scatter — fills the negative space within the slot bounds.
    # Each tissue kind rolls its count, positions are within the slot square.
    half = SLOT_SIZE / 2.0
    for kind, count in _tissue_for(biome_name):
        for _ in range(count):
            x = cx + rng.uniform(-half, half)
            y = cy + rng.uniform(-half, half)
            ent = _make_entity(kind, x, y, rng)
            if ent is not None:
                roster.append(ent)

    return roster


def get_visible(cam_x: float, cam_y: float, radius: float,
                seed: int, biome_name: str) -> List[Dict]:
    """Collect all entities from slots overlapping the camera circle.

    No cache. Iterates the AABB of slots that could intersect the circle,
    calls stamp_at for each, then filters entities by exact distance.
    """
    radius_sq = radius * radius

    gx_min = int(math.floor((cam_x - radius) / SLOT_SIZE))
    gx_max = int(math.floor((cam_x + radius) / SLOT_SIZE))
    gy_min = int(math.floor((cam_y - radius) / SLOT_SIZE))
    gy_max = int(math.floor((cam_y + radius) / SLOT_SIZE))

    visible = []
    for gx in range(gx_min, gx_max + 1):
        for gy in range(gy_min, gy_max + 1):
            for ent in stamp_at(gx, gy, seed, biome_name):
                dx = ent["x"] - cam_x
                dy = ent["y"] - cam_y
                if dx * dx + dy * dy <= radius_sq:
                    visible.append(ent)

    return visible
