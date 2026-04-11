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
    ORIGIN_HUB,
    PLAYER_COLLISION_RADII,
)
from core.systems.bucket_world import KIND_PROPS


# Mega stamps — these get filtered out of the neighborhood around the
# origin hub so the authored hub doesn't get swallowed by adjacent mega
# anchors. The transition from hub → procedural should feel intentional.
_MEGA_STAMP_NAMES = {"obelisk_court", "column_henge", "buttress_arch"}

# Slots where the origin hub owns the space or the mega filter applies.
# (0, 0) = hub itself.
# (-1..1, -1..1) \ (0,0) = 8 adjacent slots where mega stamps are excluded.
_HUB_ORIGIN_SLOT = (0, 0)
_HUB_ADJACENT_SLOTS = {(gx, gy)
                       for gx in (-1, 0, 1)
                       for gy in (-1, 0, 1)
                       if (gx, gy) != _HUB_ORIGIN_SLOT}


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
    """Build an entity dict from KIND_PROPS + per-instance jitter.

    collision_radius is read from PLAYER_COLLISION_RADII (biome_data.py)
    and scaled by the per-instance variant scale so small variants get
    proportionally smaller collision. Kinds not in the table get 0 —
    tissue, tissue-sized scatter, atmospheric kinds, and intentionally-
    walkable structures (doorframe) all walk-through by default.
    """
    props = KIND_PROPS.get(kind)
    if props is None:
        return None
    sv = rng.uniform(0.75, 1.25) * 1.30 * scale_mult
    sx, sy_s, sz = props["scale"]
    r, g, b = props["color"]
    coll_base = PLAYER_COLLISION_RADII.get(kind, 0.0)
    # Scale collision by the same variance multiplier as the visual size
    # (normalized by the 1.30 global boost so radius matches visual footprint).
    coll_radius = coll_base * (sv / 1.30)
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
        "collision_radius": round(coll_radius, 3),
        "tile_variant": "standard",
        "behavior_type": "",
        "decay_stage": 0.0,
        "_chain_index": 0,
    }


def _weighted_pick(stamps: list, rng: random.Random) -> Dict:
    """Pick one stamp using its `weight` field (default 1).

    Mega stamps (obelisk_court, column_henge, buttress_arch) carry
    weight: 4 in biome_data.py so they dominate the selection — a
    claustrophobic cavern needs big anchors in ~half the slots, not
    ~a fifth.
    """
    weights = [float(s.get("weight", 1)) for s in stamps]
    total = sum(weights)
    r = rng.uniform(0.0, total)
    cum = 0.0
    for stamp, w in zip(stamps, weights):
        cum += w
        if r <= cum:
            return stamp
    return stamps[-1]   # numerical safety


def _instantiate_hub(world_cx: float, world_cy: float,
                     seed: int) -> List[Dict]:
    """Emit ORIGIN_HUB members at the given world position.

    Unlike procedural stamps, the hub is NOT placed at a slot center —
    it's placed at world (0, 0), regardless of which slot the origin
    falls in. The hub does not rotate (its arches are cardinal) and
    members skip per-instance scatter. This is the only hand-authored
    scene in the game, and it owns its coordinate frame.
    """
    rng = random.Random(seed ^ 0xBADC0DE)
    roster: list[Dict] = []
    for member in ORIGIN_HUB["members"]:
        kind = member["kind"]
        x = world_cx + member.get("dx", 0.0)
        y = world_cy + member.get("dy", 0.0)
        scale_mult = member.get("scale_mult") or 1.0
        ent = _make_entity(kind, x, y, rng, scale_mult)
        if ent is not None:
            roster.append(ent)
    return roster


def stamp_at(gx: int, gy: int, seed: int, biome_name: str) -> List[Dict]:
    """Pure function: slot coords → entity list.

    For the cavern biome, slot (0, 0) is the origin hub — a hand-authored
    stamp placed at world (0, 0) regardless of slot center offset. All
    other slots pick procedurally via weighted selection. The 8 slots
    immediately adjacent to (0, 0) exclude mega stamps so the transition
    from authored hub to procedural periphery stays legible.
    """
    # Origin hub special case — the only hand-authored scene in the game.
    # Takes full ownership of slot (0, 0) in the cavern biome; skips the
    # weighted pool and skips tissue scatter so the authored composition
    # stays clean.
    if biome_name == "cavern" and (gx, gy) == _HUB_ORIGIN_SLOT:
        return _instantiate_hub(0.0, 0.0, seed)

    stamps = _stamps_for(biome_name)
    if not stamps:
        return []

    # Mega-stamp exclusion zone — keep the neighborhood of the hub calm
    # so the transition from authored hub to procedural periphery is
    # readable and you can see the hub's silhouette from outside.
    if biome_name == "cavern" and (gx, gy) in _HUB_ADJACENT_SLOTS:
        stamps = [s for s in stamps if s.get("name") not in _MEGA_STAMP_NAMES]

    rng = random.Random(_slot_seed(gx, gy, seed))
    cx = (gx + 0.5) * SLOT_SIZE
    cy = (gy + 0.5) * SLOT_SIZE

    # Pick one stamp from the library via weighted selection
    stamp = _weighted_pick(stamps, rng)

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


# Scale-in fade band — entities within fade_band of the visibility edge
# scale up from min_scale to full size as you approach. Symmetric: walking
# away shrinks them before they disappear. No state, no Godot diffing —
# just distance math, recomputed every frame.
SCALE_FADE_BAND = 14.0  # last 14m of visibility (35m → 49m at horizon=49)
SCALE_MIN = 0.05        # smallest visible scale at the very edge


def _scale_factor(dist: float, radius: float) -> float:
    """Distance-driven scale fade. 1.0 inside fade band, lerps to SCALE_MIN at edge."""
    fade_start = radius - SCALE_FADE_BAND
    if dist <= fade_start:
        return 1.0
    if dist >= radius:
        return SCALE_MIN
    # Smooth lerp across the fade band
    t = (radius - dist) / SCALE_FADE_BAND  # 1.0 at fade_start, 0.0 at radius
    return SCALE_MIN + (1.0 - SCALE_MIN) * t


def get_visible(cam_x: float, cam_y: float, radius: float,
                seed: int, biome_name: str) -> List[Dict]:
    """Collect all entities from slots overlapping the camera circle.

    No cache. Iterates the AABB of slots that could intersect the circle,
    calls stamp_at for each, then filters entities by exact distance.
    Applies a distance-driven scale fade so entities grow as you approach
    the visibility edge — no instant pop-in.
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
                d2 = dx * dx + dy * dy
                if d2 > radius_sq:
                    continue
                # Apply scale-in fade based on distance
                dist = math.sqrt(d2)
                fade = _scale_factor(dist, radius)
                if fade < 1.0:
                    # Mutate scale fields — these came from spawn_bucket so it's safe
                    ent["sx"] = round(ent["sx"] * fade, 3)
                    ent["sy"] = round(ent["sy"] * fade, 3)
                    ent["sz"] = round(ent["sz"] * fade, 3)
                visible.append(ent)

    return visible
