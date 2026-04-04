"""
core/systems/world_gen.py

Shared world generation — honeycomb placement + density scatter.

Zero Panda3D imports. Called by both cavern.py (Panda3D renderer)
and renderer_bridge.py (wgpu renderer). Single source of truth.

Output: list of (kind, (x, y), heading, seed) tuples per tile.
"""

import math
import random

from core.systems.biome_data import (
    BIOME_CAVERN_DEFAULT, BIOME_OUTDOOR_FOREST,
    HARD_OBJECTS, BIOME_REGISTRY,
)
from core.systems.frame_composer import FrameComposer, FRAMING_CONFIG


def generate_tile(seed, biome_name="cavern", tile_size=288.0, biome=None):
    """Generate a tile layout with honeycomb path network.

    Scatter node points across the tile — these are walkable clearings.
    Hard objects cluster BETWEEN nodes (forming walls/dividers).
    Soft objects cluster NEAR nodes (visible as you walk through).

    Returns list of (kind, (x, y), heading, seed) tuples.
    Coordinate system: (0, 0) to (tile_size, tile_size).
    """
    if biome is None:
        biome = BIOME_OUTDOOR_FOREST if biome_name == "outdoor" else BIOME_CAVERN_DEFAULT
    tile = tile_size
    tile_area = tile * tile
    rng = random.Random(seed)
    spawns = []
    solid_positions = []

    # Tile variant roll
    registry = BIOME_REGISTRY.get(biome_name, BIOME_REGISTRY["cavern"])
    variants = registry["tile_variants"]
    variant_names = list(variants.keys())
    variant_weights = [variants[v]["weight"] for v in variant_names]
    variant_name = rng.choices(variant_names, weights=variant_weights, k=1)[0]
    variant = variants[variant_name]
    density_mult = variant.get("density_mult", 1.0)
    density_boost = variant.get("boost", {})

    # Honeycomb nodes = mega_column positions. Columns ARE the lattice.
    # Cavern: tighter corridors. Outdoor: wider forest spacing.
    if biome_name == "outdoor":
        node_spacing = rng.uniform(14.0, 18.0)
    else:
        node_spacing = rng.uniform(10.0, 13.0)  # tighter = forced through walls
    nodes = []
    ny = node_spacing * 0.5
    row = 0
    while ny < tile:
        nx = node_spacing * 0.5 + (node_spacing * 0.5 if row % 2 else 0)
        while nx < tile:
            jx = nx + rng.uniform(-node_spacing * 0.15, node_spacing * 0.15)
            jy = ny + rng.uniform(-node_spacing * 0.15, node_spacing * 0.15)
            nodes.append((jx, jy))
            roll = rng.random()
            if roll < 0.15:
                anchor = "mega_column"
                solid_positions.append((jx, jy, 5.0))
            elif roll < 0.30:
                anchor = "column"
                solid_positions.append((jx, jy, 3.0))
            elif roll < 0.50:
                anchor = "crystal_cluster"
                solid_positions.append((jx, jy, 2.0))
            elif roll < 0.70:
                anchor = "giant_fungus"
                solid_positions.append((jx, jy, 2.0))
            elif roll < 0.85:
                anchor = "boulder"
                solid_positions.append((jx, jy, 3.0))
            else:
                anchor = "moss_patch"
            spawns.append((anchor, (jx, jy),
                           rng.uniform(0, 360), rng.randint(0, 99999)))
            nx += node_spacing
        ny += node_spacing * 0.87
        row += 1

    # Front-load spawn area — guarantee dense cluster near tile center
    cx, cy = tile * 0.5, tile * 0.5
    nodes.append((cx, cy))
    for si in range(6):
        angle = si * 60 + rng.uniform(-10, 10)
        dist = node_spacing * rng.uniform(0.8, 1.1)
        nodes.append((
            cx + math.cos(math.radians(angle)) * dist,
            cy + math.sin(math.radians(angle)) * dist,
        ))

    path_radius = rng.uniform(6.0, 10.0)

    # FrameComposer pass — compose directed views between hex node pairs
    frame_cfg = FRAMING_CONFIG.get(biome_name, FRAMING_CONFIG.get("cavern"))
    composer = FrameComposer(seed=seed)
    max_neighbor_dist = node_spacing * 2.0
    frame_rng = random.Random(seed + 777)
    for i in range(len(nodes)):
        if frame_rng.random() > 0.3:
            continue
        n1x, n1y = nodes[i]
        best_j, best_d = -1, 9999.0
        for j in range(len(nodes)):
            if j == i:
                continue
            dx, dy = nodes[j][0] - n1x, nodes[j][1] - n1y
            d = math.sqrt(dx * dx + dy * dy)
            if d < best_d and d < max_neighbor_dist:
                best_d = d
                best_j = j
        if best_j < 0:
            continue
        n2x, n2y = nodes[best_j]
        frames = composer.compose_along_path(
            node_a=(n1x, n1y), node_b=(n2x, n2y), config=frame_cfg)
        for fp in frames:
            fx, fy = fp["pos"]
            kind = fp["kind"]
            clearance = HARD_OBJECTS.get(kind, 0)
            too_close = False
            for sx, sy, sc in solid_positions:
                if (fx - sx) ** 2 + (fy - sy) ** 2 < (clearance + sc) ** 2:
                    too_close = True
                    break
            if too_close:
                continue
            spawns.append((kind, (fx, fy), fp["heading"], rng.randint(0, 99999)))
            if clearance > 0:
                solid_positions.append((fx, fy, clearance))

    def _dist_to_nearest_node(x, y):
        min_d = 9999.0
        for nx, ny in nodes:
            dx, dy = x - nx, y - ny
            d = math.sqrt(dx * dx + dy * dy)
            if d < min_d:
                min_d = d
        return min_d

    # Density scatter
    for kind, density, clearance, margin in biome:
        if kind in ("mega_column", "column", "crystal_cluster", "giant_fungus"):
            continue
        effective_density = density * density_mult * density_boost.get(kind, 1.0)
        base_count = effective_density * tile_area / 1000.0
        count = max(0, int(rng.uniform(base_count * 0.7, base_count * 1.3)))
        is_hard = kind in HARD_OBJECTS

        for _ in range(count):
            placed = False
            for _attempt in range(8 if is_hard else 3):
                x = rng.uniform(margin, tile - margin)
                y = rng.uniform(margin, tile - margin)
                d = _dist_to_nearest_node(x, y)

                if is_hard:
                    if d < path_radius:
                        continue
                    if d > path_radius * 2.5 and rng.random() < 0.6:
                        continue
                else:
                    if d > path_radius * 1.5 and rng.random() < 0.7:
                        continue

                if clearance > 0:
                    too_close = False
                    for sx, sy, sc in solid_positions:
                        ddx, ddy = x - sx, y - sy
                        if ddx * ddx + ddy * ddy < (clearance + sc) ** 2:
                            too_close = True
                            break
                    if too_close:
                        continue
                    solid_positions.append((x, y, clearance))
                placed = True
                break
            if not placed:
                if len(nodes) >= 2:
                    n1 = nodes[rng.randint(0, len(nodes) - 1)]
                    n2 = nodes[rng.randint(0, len(nodes) - 1)]
                    x = (n1[0] + n2[0]) * 0.5 + rng.uniform(-3, 3)
                    y = (n1[1] + n2[1]) * 0.5 + rng.uniform(-3, 3)
                else:
                    x = rng.uniform(margin, tile - margin)
                    y = rng.uniform(margin, tile - margin)
                x = max(margin, min(tile - margin, x))
                y = max(margin, min(tile - margin, y))

            spawns.append((kind, (x, y),
                           rng.uniform(0, 360), rng.randint(0, 99999)))

    return spawns
