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
    HARD_OBJECTS, BIOME_REGISTRY, FORMATION_ARCHETYPES,
    CAVERN_FLOURISH_POOLS, OUTDOOR_FLOURISH_POOLS,
    FLOURISH_COUNT_RANGE, FLOURISH_RADIUS_RANGE,
    CAVERN_ROOM_BEACONS, OUTDOOR_ROOM_BEACONS,
)
from core.systems.frame_composer import FrameComposer, FRAMING_CONFIG
from core.systems.roster_pool import RosterPool


# Kinds that get base aprons — populated from kind_config.json at module load.
# Mirrors the "base_apron": true flag in kind config.
_BASE_APRON_KINDS = {"boulder", "mega_column", "column", "buttress",
                     "stalagmite", "bone_pile"}
_BASE_APRON_HEAVY = {"mega_column", "buttress"}  # larger anchors get denser apron


def _emit_landmark_beacon(anchor_x, anchor_y, spawns, rng):
    """Attach a filament (tall emissive stalk) adjacent to an architectural landmark.

    Every mega_column / formation column gets one. Makes each landmark
    function as a waypoint visible from neighboring landmarks through fog.
    Wayfinding reference: Oblivion's distant firelight-through-opening.
    """
    # Offset 1.5-2.5m from landmark center — reads as "growing beside" not "on top of"
    angle = rng.uniform(0, 360)
    offset = rng.uniform(1.5, 2.5)
    fx = anchor_x + math.cos(math.radians(angle)) * offset
    fy = anchor_y + math.sin(math.radians(angle)) * offset
    spawns.append(("filament", (fx, fy),
                   rng.uniform(0, 360), rng.randint(0, 99999), None))


def _emit_breadcrumb_trail(x1, y1, x2, y2, spawns, rng, count=3):
    """Place small fireflies along a line between two landmarks.

    Creates a visible trail the eye follows unconsciously. Subtle enough to
    feel natural (drifting bioluminescence), bright enough to read.
    """
    for i in range(1, count + 1):
        t = i / (count + 1)
        # Slight perpendicular jitter so it's not a dead-straight line
        dx = x2 - x1
        dy = y2 - y1
        perp_x = -dy
        perp_y = dx
        plen = math.sqrt(perp_x * perp_x + perp_y * perp_y)
        if plen > 0.01:
            perp_x /= plen
            perp_y /= plen
        jitter = rng.uniform(-1.2, 1.2)
        fx = x1 + dx * t + perp_x * jitter
        fy = y1 + dy * t + perp_y * jitter
        spawns.append(("firefly", (fx, fy),
                       rng.uniform(0, 360), rng.randint(0, 99999), None))


def _emit_reward_cluster(center_x, center_y, spawns, rng, count=6):
    """Dense firefly burst at the end of a breadcrumb trail — the payoff.

    Placed AT a landmark (mega_column, formation column) after a trail arrives.
    Read as: "you followed the lights and found something." Tag 12 mechanic.
    """
    for _ in range(count):
        angle = rng.uniform(0, 360)
        radius = rng.uniform(1.2, 2.8)
        fx = center_x + math.cos(math.radians(angle)) * radius
        fy = center_y + math.sin(math.radians(angle)) * radius
        spawns.append(("firefly", (fx, fy),
                       rng.uniform(0, 360), rng.randint(0, 99999), None))


def _emit_fungus_satellites(center_x, center_y, spawns, solid_positions, rng):
    """Spawn 3-5 smaller giant_fungus satellites around a main placement.

    Implements the user's fungus sketch: 1 main stalk + surrounding smaller
    fungi. Matches how crystal_cluster reads. Called after each giant_fungus
    density scatter placement.
    """
    count = rng.randint(3, 5)
    for _ in range(count):
        angle = rng.uniform(0, 360)
        dist = rng.uniform(1.8, 3.2)
        fx = center_x + math.cos(math.radians(angle)) * dist
        fy = center_y + math.sin(math.radians(angle)) * dist
        # Satellites are scaled down 0.45-0.65x via meta field
        spawns.append(("giant_fungus", (fx, fy),
                       rng.uniform(0, 360), rng.randint(0, 99999),
                       {"scale_mult": round(rng.uniform(0.45, 0.65), 3)}))


def _stage_spawn_composition(spawns, solid_positions, rng, tile_center_x, tile_center_y):
    """Deliberate spawn composition — non-blocking elements only.

    Previous version placed a mega_column at 8m which violated the 10m spawn
    clearance and caused clipping. Foreground silhouette now comes from the
    NATURAL honeycomb via spawn heading logic (see _compute_spawn_heading).

    This function only places tiny/zero-collision cues visible in the spawn frame:
    - Distant filament beacon (0.08m collision, 28m away — pull cue)
    - Crystal cluster (2m collision, 22m away — color promise via Decal pool)
    - Breadcrumb fireflies (0 collision — path suggestion)
    """
    # Distant pull cue: filament beacon at 28m, offset 18° LEFT from heading 0
    pull_angle_deg = -18.0  # degrees left of north
    pull_dist = 28.0
    pull_x = tile_center_x + math.sin(math.radians(pull_angle_deg)) * pull_dist
    pull_y = tile_center_y + math.cos(math.radians(pull_angle_deg)) * pull_dist
    spawns.append(("filament", (pull_x, pull_y),
                   rng.uniform(0, 360), rng.randint(0, 99999),
                   {"spawn_staging": "distance_pull"}))

    # Color promise: small crystal cluster near the pull cue, slightly closer
    color_angle_deg = -22.0
    color_dist = 22.0
    color_x = tile_center_x + math.sin(math.radians(color_angle_deg)) * color_dist
    color_y = tile_center_y + math.cos(math.radians(color_angle_deg)) * color_dist
    spawns.append(("crystal_cluster", (color_x, color_y),
                   rng.uniform(0, 360), rng.randint(0, 99999),
                   {"spawn_staging": "color_promise"}))
    solid_positions.append((color_x, color_y, 2.0))

    # Breadcrumb fireflies between spawn and the pull cue (non-blocking path hint)
    _emit_breadcrumb_trail(tile_center_x, tile_center_y, pull_x, pull_y,
                           spawns, rng, count=4)


def _emit_base_apron(anchor_kind, anchor_x, anchor_y, spawns, solid_positions, rng):
    """Tight scatter of rubble/gravel at the base of an erosion-eligible anchor.

    Forms a visible skirt connecting rock to ground — cheats the concave flare
    that erosion would produce. Placement radius 0.4-1.2m is tight enough that
    the eye reads it as "the anchor's own eroded debris," not scattered flourish.

    Driven by kind_config.json "base_apron" flag (config-as-code).
    """
    if anchor_kind not in _BASE_APRON_KINDS:
        return
    # Apron counts kept small — the point is to CHEAT the concave base read,
    # not to carpet the ground. Denser flourish was causing path clutter.
    if anchor_kind in _BASE_APRON_HEAVY:
        count = rng.randint(3, 5)
    else:
        count = rng.randint(2, 3)
    # Mix: mostly rubble with some cave_gravel
    kinds_mix = ["rubble", "rubble", "cave_gravel", "cave_gravel", "rubble"]
    for i in range(count):
        flourish_kind = kinds_mix[i % len(kinds_mix)]
        angle = rng.uniform(0, 360)
        # Tight ring 0.3-1.0m — apron hugs anchor base, doesn't spill into walking corridors
        radius = rng.uniform(0.3, 1.0)
        fx = anchor_x + math.cos(math.radians(angle)) * radius
        fy = anchor_y + math.sin(math.radians(angle)) * radius
        # Apron pieces have tiny clearance, skip collision check (they're ground-huggers)
        spawns.append((flourish_kind, (fx, fy),
                       rng.uniform(0, 360), rng.randint(0, 99999), None))


def _emit_cluster(archetype, center_x, center_y, spawns, solid_positions, rng):
    """Place a cluster of same-kind entities around a center point.

    Clusters read as one composition element: spore-pod trio, stalagmite pair,
    boulder pile, etc. Each member places within the spread radius with slight
    angle variation, so they feel grouped but not stacked.
    """
    kind = archetype["kind"]
    count = archetype["count"]
    spread = archetype["spread"]
    z_off = archetype.get("z_offset", 0.0)
    clearance = HARD_OBJECTS.get(kind, 0)
    placed = 0
    # First member at center (or near it if overhead cluster with z_offset)
    angles = [i * (360.0 / count) + rng.uniform(-25, 25) for i in range(count)]
    for i, angle in enumerate(angles):
        # First member close to center, others radiate out
        dist = 0.0 if i == 0 else rng.uniform(spread * 0.5, spread)
        cx = center_x + math.cos(math.radians(angle)) * dist
        cy = center_y + math.sin(math.radians(angle)) * dist
        # Collision check against existing solids
        if clearance > 0:
            too_close = False
            for sx, sy, sc in solid_positions:
                if (cx - sx) ** 2 + (cy - sy) ** 2 < (clearance + sc) ** 2:
                    too_close = True
                    break
            if too_close:
                continue
            solid_positions.append((cx, cy, clearance))
        meta = {"cluster_z_offset": z_off} if z_off > 0 else None
        spawns.append((kind, (cx, cy),
                       rng.uniform(0, 360), rng.randint(0, 99999), meta))
        placed += 1
    return placed


def _emit_flourishes(anchor_kind, anchor_x, anchor_y, spawns, solid_positions,
                     flourish_rosters, rng):
    """Scatter 1-3 flourish entities OUTSIDE the anchor's walking margin.

    Flourish radius auto-scales to the anchor's clearance so decorations
    never land inside the walkable corridor around a landmark. Mega_column
    with 5m clearance gets flourishes at 5.5-7.5m. Boulder with 2.5m gets
    them at 3.0-5.0m. Etc.
    """
    roster = flourish_rosters.get(anchor_kind)
    if not roster:
        return
    count = rng.randint(FLOURISH_COUNT_RANGE[0], FLOURISH_COUNT_RANGE[1])
    anchor_clearance = HARD_OBJECTS.get(anchor_kind, 1.5)
    # Flourishes place just past the walking margin — keep the corridor clear
    min_radius = anchor_clearance + 0.5
    max_radius = anchor_clearance + 2.5
    for _ in range(count):
        flourish_kind = roster.next()
        angle = rng.uniform(0, 360)
        radius = rng.uniform(min_radius, max_radius)
        fx = anchor_x + math.cos(math.radians(angle)) * radius
        fy = anchor_y + math.sin(math.radians(angle)) * radius
        # Light collision check — don't overlap with solid hard objects
        f_clearance = HARD_OBJECTS.get(flourish_kind, 0)
        if f_clearance > 0:
            too_close = False
            for sx, sy, sc in solid_positions:
                ddx, ddy = fx - sx, fy - sy
                if ddx * ddx + ddy * ddy < (f_clearance + sc) ** 2:
                    too_close = True
                    break
            if too_close:
                continue
            solid_positions.append((fx, fy, f_clearance))
        spawns.append((flourish_kind, (fx, fy),
                       rng.uniform(0, 360), rng.randint(0, 99999), None))


def generate_tile(seed, biome_name="cavern", tile_size=288.0, biome=None,
                  is_spawn_tile=False):
    """Generate a tile layout with honeycomb path network.

    Scatter node points across the tile — these are walkable clearings.
    Hard objects cluster BETWEEN nodes (forming walls/dividers).
    Soft objects cluster NEAR nodes (visible as you walk through).

    Returns (variant_name, spawns) where spawns is a list of
    (kind, (x, y), heading, seed, meta) tuples.
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
    # Cavern 16-20m: leaves 6-10m walking corridor after 2.5m anchor radii
    # and 2-3m buttress reach. Previous 10-13m produced −1m corridors when
    # formations were placed, causing clipping through geometry everywhere.
    if biome_name == "outdoor":
        node_spacing = rng.uniform(20.0, 24.0)
    else:
        node_spacing = rng.uniform(16.0, 20.0)
    nodes = []

    # Formation roster — every 3rd mega_column spawns an integrated geological formation
    # (column peak + buttress arms as one silhouette). RosterPool cycles through recipes.
    formation_roster = RosterPool(FORMATION_ARCHETYPES, seed=seed)
    mega_column_count = 0

    # Landmark positions — tracked for post-loop breadcrumb trail emission
    landmark_positions = []

    # Flourish rosters — per-anchor-kind RosterPool for ground density variation
    flourish_source = OUTDOOR_FLOURISH_POOLS if biome_name == "outdoor" else CAVERN_FLOURISH_POOLS
    flourish_rosters = {
        anchor_kind: RosterPool(pool, seed=seed + hash(anchor_kind) % 10000)
        for anchor_kind, pool in flourish_source.items()
    }

    # Beacon roster — feature cluster pools for formation column beacons.
    # LRU-cycled so adjacent formations get different beacon types.
    beacon_source = OUTDOOR_ROOM_BEACONS if biome_name == "outdoor" else CAVERN_ROOM_BEACONS
    beacon_roster = RosterPool(beacon_source, seed=seed + 54321)

    node_index = 0

    ny = node_spacing * 0.5
    row = 0
    while ny < tile:
        nx = node_spacing * 0.5 + (node_spacing * 0.5 if row % 2 else 0)
        while nx < tile:
            jx = nx + rng.uniform(-node_spacing * 0.15, node_spacing * 0.15)
            jy = ny + rng.uniform(-node_spacing * 0.15, node_spacing * 0.15)
            nodes.append((jx, jy))

            node_index += 1
            roll = rng.random()
            if roll < 0.15:
                anchor = "mega_column"
                # Every 3rd mega_column becomes a formation — not a plain column
                if mega_column_count % 3 == 0:
                    formation = formation_roster.next()
                    col_cfg = formation["column"]
                    # Column may be offset from the node center (e.g. cliff_back)
                    col_ox = col_cfg.get("offset_distance", 0.0)
                    col_oa = math.radians(col_cfg.get("offset_angle", 0.0))
                    col_x = jx + math.cos(col_oa) * col_ox
                    col_y = jy + math.sin(col_oa) * col_ox
                    col_scale = col_cfg.get("scale_mult", 1.0)
                    # Spawn the column with formation-specific scale
                    spawns.append((
                        col_cfg["kind"], (col_x, col_y),
                        rng.uniform(0, 360), rng.randint(0, 99999),
                        {"formation_scale_mult": col_scale,
                         "formation": formation["name"]}
                    ))
                    solid_positions.append((col_x, col_y, 5.0 * col_scale))
                    # Base apron at the formation column peak
                    _emit_base_apron(col_cfg["kind"], col_x, col_y, spawns, solid_positions, rng)
                    # Landmark beacon — filament adjacent to column for wayfinding
                    _emit_landmark_beacon(col_x, col_y, spawns, rng)
                    landmark_positions.append((col_x, col_y))
                    # Spawn the arms — but ONLY if the parent column is floor-attached.
                    # Stalactite columns (ceiling) can't have buttresses leaning on them.
                    # Uses the same hash the brain/Godot use for inversion.
                    parent_hash = abs(math.sin(col_x * 2.71 + col_y * 5.43))
                    parent_is_stalactite = parent_hash < 0.40
                    for arm in formation["arms"]:
                        if parent_is_stalactite:
                            continue  # skip — no buttresses on ceiling columns
                        arm_rad = math.radians(arm["offset_angle"])
                        bx = jx + math.cos(arm_rad) * arm["offset_distance"]
                        by = jy + math.sin(arm_rad) * arm["offset_distance"]
                        # Heading points the arm's LEAN direction back at node center
                        lean_heading = (arm["offset_angle"] + 180.0) % 360.0
                        buttress_seed = rng.randint(0, 99999)
                        spawns.append((
                            "buttress", (bx, by), lean_heading, buttress_seed,
                            {
                                "lean_angle": arm["lean_angle"],
                                "scale_x": arm["scale_x"],
                                "scale_y": arm["scale_y"],
                                "scale_z": arm["scale_z"],
                                "parent_column": (jx, jy),
                                "formation": formation["name"],
                            }
                        ))
                        solid_positions.append((bx, by, 2.5))
                        # Base apron at the buttress arm foot
                        _emit_base_apron("buttress", bx, by, spawns, solid_positions, rng)
                        # Flourishes near each buttress arm (ground density variation)
                        _emit_flourishes("buttress", bx, by, spawns, solid_positions,
                                         flourish_rosters, rng)
                    # Flourishes near the formation column peak
                    _emit_flourishes("mega_column", col_x, col_y, spawns, solid_positions,
                                     flourish_rosters, rng)
                    # Beacon at the formation base — one guaranteed light source
                    # per formation creates a visible landmark without walling off space.
                    # Placed 3m off the column center in the direction opposite the main arms.
                    beacon = beacon_roster.next()
                    beacon_x = jx + math.cos(col_oa + math.pi) * 3.0
                    beacon_y = jy + math.sin(col_oa + math.pi) * 3.0
                    _emit_cluster(beacon, beacon_x, beacon_y, spawns, solid_positions, rng)
                    mega_column_count += 1
                    nx += node_spacing
                    continue  # skip the default anchor spawn — formation replaced it
                else:
                    solid_positions.append((jx, jy, 5.0))
                mega_column_count += 1
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
                           rng.uniform(0, 360), rng.randint(0, 99999), None))
            # Base apron — tight erosion debris at anchor foot (concave cheat)
            _emit_base_apron(anchor, jx, jy, spawns, solid_positions, rng)
            # Landmark beacon — every mega_column gets a filament waypoint
            if anchor == "mega_column":
                _emit_landmark_beacon(jx, jy, spawns, rng)
                landmark_positions.append((jx, jy))
            # Flourish emission — eye-tricking density variation near anchors
            _emit_flourishes(anchor, jx, jy, spawns, solid_positions,
                             flourish_rosters, rng)
            # Fungus cluster: main stalk + 3-5 satellites (matches user's sketch)
            if anchor == "giant_fungus":
                _emit_fungus_satellites(jx, jy, spawns, solid_positions, rng)
            nx += node_spacing
        ny += node_spacing * 0.87
        row += 1

    # Spawn corridor — clear the forward view, frame with flanking geometry.
    # NO node at tile center (player spawns here, don't wall them in).
    # Place nodes in a broken ring that opens toward heading 0 (north in
    # brain-space), creating a natural corridor the player looks down.
    # Flanking nodes at ±60-120° create the "something around the corner"
    # silhouettes. Forward nodes pushed to 1.5-2x spacing for depth.
    cx, cy = tile * 0.5, tile * 0.5
    spawn_corridor_angles = [
        # Flanking left/right — close, creates corridor walls
        (-70, 0.9),  (-110, 0.9),
        # Rear — behind the player, not immediately visible
        (150, 0.8), (-150, 0.8), (180, 1.0),
        # Forward — PUSHED BACK for depth perspective
        (-25, 1.8), (25, 1.8),
        # Mid-forward — staggered depth for parallax
        (-40, 1.3), (40, 1.3),
    ]
    for angle_deg, dist_mult in spawn_corridor_angles:
        angle = angle_deg + rng.uniform(-8, 8)
        dist = node_spacing * dist_mult * rng.uniform(0.9, 1.1)
        nodes.append((
            cx + math.cos(math.radians(angle)) * dist,
            cy + math.sin(math.radians(angle)) * dist,
        ))

    path_radius = rng.uniform(6.0, 10.0)

    # Breadcrumb trails between landmarks — wayfinding visual thread.
    # For each landmark, find up to 2 nearest neighbors within a visibility
    # radius and place 3 fireflies along the connecting line. The eye follows
    # the chain of small lights from landmark to landmark.
    BREADCRUMB_MAX_DIST = node_spacing * 1.8  # ~28-36m at new spacing, within fog visibility
    trail_seen = set()  # dedupe (i, j) == (j, i)
    landmarks_with_reward = set()  # only one reward cluster per landmark
    for i, (x1, y1) in enumerate(landmark_positions):
        # Find nearest 2 neighbors within max distance
        neighbors = []
        for j, (x2, y2) in enumerate(landmark_positions):
            if i == j:
                continue
            dx, dy = x2 - x1, y2 - y1
            d = math.sqrt(dx * dx + dy * dy)
            if d < BREADCRUMB_MAX_DIST:
                neighbors.append((d, j, x2, y2))
        neighbors.sort(key=lambda n: n[0])
        for _, j, x2, y2 in neighbors[:2]:
            pair = (min(i, j), max(i, j))
            if pair in trail_seen:
                continue
            trail_seen.add(pair)
            _emit_breadcrumb_trail(x1, y1, x2, y2, spawns, rng, count=5)
            # Reward cluster at BOTH endpoints (Tag 12 mechanic) — the payoff
            # for following a breadcrumb trail to a landmark
            if i not in landmarks_with_reward:
                _emit_reward_cluster(x1, y1, spawns, rng, count=rng.randint(6, 9))
                landmarks_with_reward.add(i)
            if j not in landmarks_with_reward:
                _emit_reward_cluster(x2, y2, spawns, rng, count=rng.randint(6, 9))
                landmarks_with_reward.add(j)

    # FrameComposer pass — compose directed views between hex node pairs.
    frame_cfg = FRAMING_CONFIG.get(biome_name, FRAMING_CONFIG.get("cavern"))
    composer = FrameComposer(seed=seed)
    max_neighbor_dist = node_spacing * 2.0
    frame_rng = random.Random(seed + 777)
    for i in range(len(nodes)):
        if frame_rng.random() > 0.30:
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
            spawns.append((kind, (fx, fy), fp["heading"], rng.randint(0, 99999), None))
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

    # Density scatter — skip kinds placed via honeycomb anchor roll
    DENSITY_SKIP = ("mega_column", "column", "crystal_cluster", "giant_fungus")
    for kind, density, clearance, margin in biome:
        if kind in DENSITY_SKIP:
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
                           rng.uniform(0, 360), rng.randint(0, 99999), None))
            # Base apron for hard-anchor density scatter (boulder, stalagmite, etc.)
            if is_hard:
                _emit_base_apron(kind, x, y, spawns, solid_positions, rng)

    # Spawn clearance — world origin (0, 0) becomes (tile/2, tile/2) in local
    # coords after the `- half` transform. Remove any HARD anchor within 10m
    # of tile center so the player spawns in a proper walkable bubble, not
    # right against the first ring of anchors. Soft kinds (rubble, gravel,
    # fireflies, moss) remain — they don't block navigation.
    SPAWN_CLEARANCE_RADIUS = 18.0
    cx_spawn = tile * 0.5
    cy_spawn = tile * 0.5
    # Filter hard anchors AND visually-enclosing landmarks (filaments, fungi, crystals)
    # from the spawn bubble. User framing: "make the dome transparent" — any
    # tall or clustered visible element that would form walls/enclosure at spawn
    # gets filtered so the player's first frame is actually open.
    HARD_KIND_SET = set(HARD_OBJECTS.keys())
    VISUAL_LANDMARK_KINDS = {"filament", "giant_fungus", "crystal_cluster"}
    FILTER_KINDS = HARD_KIND_SET | VISUAL_LANDMARK_KINDS
    filtered = []
    for spawn in spawns:
        kind = spawn[0]
        sx, sy = spawn[1]
        if kind in FILTER_KINDS:
            dx = sx - cx_spawn
            dy = sy - cy_spawn
            if dx * dx + dy * dy < SPAWN_CLEARANCE_RADIUS * SPAWN_CLEARANCE_RADIUS:
                continue  # drop this landmark — inside spawn safety zone
        filtered.append(spawn)

    # Spawn staging — deliberate composition at world origin, placed AFTER
    # the clearance filter so it doesn't get stripped. Only on the center tile.
    # This is the first concrete instance of the passive pull loop design principle.
    if is_spawn_tile:
        _stage_spawn_composition(filtered, solid_positions, rng, cx_spawn, cy_spawn)

    return variant_name, filtered
