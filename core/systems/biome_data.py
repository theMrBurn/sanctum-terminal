"""
core/systems/biome_data.py

Pure-data biome configuration — zero Panda3D imports.

Single source of truth for density tables, palettes, collision radii,
tile variants, companion recipes, color scales, light affinities,
spectrum profiles, mote presets, and light layer configs.

Both cavern.py (Panda3D) and renderer_bridge.py (wgpu) import from here.
"""


# -- Density tables: (kind, density_per_1000sqm, clearance_radius, margin) -----

BIOME_CAVERN_DEFAULT = [
    # Tartarus-mode cavern: geological bones + organic architecture only.
    # Creatures (rat/beetle/spider/firefly) and clutter (leaf/leaf_pile/
    # twig_scatter/rubble/cave_gravel) stripped — roaming orbs are the
    # only living presence, spawned via core/systems/roaming_pool.py
    # (outside the stamp density table) so they can wander, not be placed.
    ("mega_column",       0.12,    10.0,      20),
    ("column",            0.30,    5.0,       10),
    ("boulder",           1.20,    3.0,       3),
    ("stalagmite",        1.80,    3.0,       2),
    ("giant_fungus",      0.15,    2.5,       3),
    ("crystal_cluster",   1.10,    2.0,       3),
    ("dead_log",          0.70,    1.5,       2),
    ("bone_pile",         0.35,    0,         2),
    ("moss_patch",        0.75,    0,         2),
    ("ceiling_moss",      0.15,    0,         5),
    ("hanging_vine",      0.35,    0,         4),
    ("grass_tuft",        0.60,    0,         1),
    ("horizon_form",      0.12,    10.0,      30),
    ("horizon_mid",       0.08,     8.0,      20),
    ("horizon_near",      0.10,     6.0,      12),
    ("exit_lure",         0.03,   20.0,       35),
]

BIOME_OUTDOOR_FOREST = [
    ("mega_column",       0.08,    12.0,      20),
    ("column",            0.40,     4.0,       8),
    ("boulder",           0.80,     3.0,       3),
    ("stalagmite",        0.60,     1.5,       2),
    ("giant_fungus",      0.15,     2.5,       3),
    ("crystal_cluster",   0.10,     2.0,       3),
    ("dead_log",          0.70,     1.5,       2),
    ("moss_patch",        0.60,     0,         2),
    ("grass_tuft",        1.50,     0,         1),
    ("rubble",            0.40,     0,         1),
    ("leaf_pile",         0.80,     0,         1),
    ("firefly",           0.60,     0,         1),
    ("leaf",              0.50,     0,         1),
    ("beetle",            0.20,     0,         2),
    ("rat",               0.15,     0,         2),
    ("horizon_form",      0.10,    12.0,      30),
    ("horizon_mid",       0.08,     8.0,      20),
    ("horizon_near",      0.10,     6.0,      12),
    ("exit_lure",         0.02,    20.0,      35),
]


# -- Collision radii -----------------------------------------------------------

# HARD_OBJECTS is used for STAMP SPACING — the keep-out margin between
# landmarks during procedural placement. Values are intentionally larger
# than the visual footprint so columns/mega_columns/buttresses create
# walking-margin bubbles around themselves (other anchors respect these
# radii, preserving walkable paths in dense stamps). This is the GENERATION
# radius, not the physics radius.
# Phase 5: HARD_OBJECTS is now derived from kind_config physics.collision_radius.
# Used by world_gen for clearance/spacing during stamp composition. The shim
# pattern matches KIND_PROPS — kind_config is the single source, this is a
# read-only view kept for backwards-compat with importers.
def _build_hard_objects() -> dict:
    from core.systems import kind_config as _kc
    out = {}
    for name, kcfg in _kc.all_kinds().items():
        r = kcfg.get("physics", {}).get("collision_radius")
        if r is not None and r > 0:
            out[name] = float(r)
    return out

HARD_OBJECTS = _build_hard_objects()

# PLAYER_COLLISION_RADII is used for PHYSICS — the radius at which the
# player's _physics_process push-out engages. These are a brain-side
# approximation: one value per kind, scaled at spawn by sv/1.30. The
# "right" fix is to compute collision in Godot from the actual per-
# instance applied transform (it's a deferred refactor). In the meantime,
# values are a compromise between covering max rendered radii for close-
# viewing clip-through AND staying small enough that authored hub
# compositions with tight flanker spacing remain walkable.
#
# buttress raised to 2.3 to cover its ~2.77m max rendered radius (user
# was clipping through at sv 1.50 in a buttress_arch stamp). Other kinds
# left at their original values — the hub's authored arches depend on
# their current radii for walkability (see test_hub_arches_are_walkable).
# Mega_column in particular has ~7m max rendered radius at max sv, but
# bumping its collision that high blocks the hub N arch flankers.
#
# Known tradeoff: large mega_column/column/dead_log variants are still
# clip-throughable in the procedural periphery. Follow-up is the Godot-
# side per-instance collision refactor — scaffolding already designed.
#
# Doorframe is INTENTIONALLY OMITTED — architectural walk-through gate.
# Tissue kinds default to 0 = walk-through.
PLAYER_COLLISION_RADII = {
    "mega_column":      2.5,
    "column":           1.2,
    "buttress":         2.3,   # BUMPED from 1.5 — covers sv_max rendered ~2.77m
    "stalagmite":       0.6,
    "boulder":          0.8,
    "crystal_cluster":  1.2,
    "giant_fungus":     0.9,
    "monolith":         0.4,
    "bone_pile":        0.3,
    "dead_log":         0.5,
    # doorframe: INTENTIONALLY OMITTED — walk-through architectural gate
    # tissue / atmosphere / creatures: 0 (default, walk-through)
}


# -- Formation archetypes (RosterPool source) ----------------------------------
#
# Each formation is a RECIPE that produces one integrated geological mass:
# buttress arms + a central column that reads as a single silhouette.
# The column is the PEAK of the mound, not a separate object with supports.
#
# Scale anchors (FOV 52°, eye height 2.5m):
#   - buttress arm length: 3-6m (fits in viewing frustum without dominating)
#   - column peak height:  6-10m (tall enough to read as landmark, short enough to fit under dome height 30m)
#   - formation footprint: 8-14m wide (sits within the 10-13m honeycomb spacing)
#
# Fields:
#   - "column": {"kind", "scale_mult", "z_offset"} — central peak
#   - "arms":   list of {offset_distance, offset_angle, lean_angle, scale_x/y/z}
#
# RosterPool cycles through formations so adjacent buttressed columns differ.

FORMATION_ARCHETYPES = [
    # F0 — tripod mound: 3 stretched slabs merging at center, column as peak tip
    # Lean capped at 45°, scale_z at 2.0, offsets ≤4.0m for cleaner navigation
    {
        "name": "tripod_mound",
        "column": {"kind": "mega_column", "scale_mult": 0.75, "z_offset": 0.0},
        "arms": [
            {"offset_distance": 3.0, "offset_angle": 0.0,
             "lean_angle": 42.0, "scale_x": 1.1, "scale_y": 1.1, "scale_z": 1.8},
            {"offset_distance": 3.0, "offset_angle": 120.0,
             "lean_angle": 42.0, "scale_x": 1.1, "scale_y": 1.1, "scale_z": 1.8},
            {"offset_distance": 3.0, "offset_angle": 240.0,
             "lean_angle": 42.0, "scale_x": 1.1, "scale_y": 1.1, "scale_z": 1.8},
        ],
    },
    # F1 — cliff back: one dominant slab, column rises adjacent to slab peak
    {
        "name": "cliff_back",
        "column": {"kind": "mega_column", "scale_mult": 0.85, "z_offset": 0.0,
                   "offset_distance": 2.5, "offset_angle": 0.0},
        "arms": [
            {"offset_distance": 2.0, "offset_angle": 180.0,
             "lean_angle": 45.0, "scale_x": 1.8, "scale_y": 1.5, "scale_z": 2.2},
        ],
    },
    # F2 — wedge pair: 2 slabs forming a V, column in the throat
    {
        "name": "wedge_pair",
        "column": {"kind": "mega_column", "scale_mult": 0.70, "z_offset": 0.0},
        "arms": [
            {"offset_distance": 3.5, "offset_angle": 45.0,
             "lean_angle": 42.0, "scale_x": 1.0, "scale_y": 1.0, "scale_z": 2.0},
            {"offset_distance": 3.5, "offset_angle": 315.0,
             "lean_angle": 42.0, "scale_x": 1.0, "scale_y": 1.0, "scale_z": 2.0},
        ],
    },
    # F3 — ridge line: 3-4 small masses stretched along axis, column at midpoint
    {
        "name": "ridge_line",
        "column": {"kind": "mega_column", "scale_mult": 0.65, "z_offset": 0.0},
        "arms": [
            {"offset_distance": 2.5, "offset_angle": 30.0,
             "lean_angle": 38.0, "scale_x": 0.8, "scale_y": 0.9, "scale_z": 1.6},
            {"offset_distance": 4.0, "offset_angle": 30.0,
             "lean_angle": 35.0, "scale_x": 0.7, "scale_y": 0.8, "scale_z": 1.5},
            {"offset_distance": 2.5, "offset_angle": 210.0,
             "lean_angle": 38.0, "scale_x": 0.8, "scale_y": 0.9, "scale_z": 1.6},
            {"offset_distance": 4.0, "offset_angle": 210.0,
             "lean_angle": 35.0, "scale_x": 0.7, "scale_y": 0.8, "scale_z": 1.5},
        ],
    },
    # F4 — collapsed pile: 2-3 flat slabs at shallow angles, column from center
    {
        "name": "collapsed_pile",
        "column": {"kind": "mega_column", "scale_mult": 0.80, "z_offset": 0.0},
        "arms": [
            {"offset_distance": 2.5, "offset_angle": 60.0,
             "lean_angle": 25.0, "scale_x": 1.3, "scale_y": 1.0, "scale_z": 1.6},
            {"offset_distance": 2.8, "offset_angle": 200.0,
             "lean_angle": 30.0, "scale_x": 1.1, "scale_y": 0.9, "scale_z": 1.8},
            {"offset_distance": 2.5, "offset_angle": 320.0,
             "lean_angle": 22.0, "scale_x": 1.2, "scale_y": 1.1, "scale_z": 1.6},
        ],
    },
]

# Legacy alias — old BUTTRESS_VARIANTS name kept for import compatibility
BUTTRESS_VARIANTS = FORMATION_ARCHETYPES

ANCHOR_WAKE_MULT = {
    "mega_column":      1.8,
    "column":           1.6,
    "crystal_cluster":  1.5,
    "giant_fungus":     1.4,
    "boulder":          1.3,
    "ceiling_moss":     1.5,
}


# -- Palettes ------------------------------------------------------------------

CAVERN_PALETTE = {
    "floor": (0.08, 0.06, 0.05),
    "dirt": (0.044, 0.030, 0.023),
    "stone": (0.12, 0.11, 0.10),
    "dark_stone": (0.08, 0.07, 0.07),
    "dead_organic": (0.09, 0.07, 0.05),
    "bone": (0.14, 0.13, 0.11),
}

OUTDOOR_PALETTE = {
    "floor": (0.12, 0.10, 0.06),
    "dirt": (0.08, 0.06, 0.03),
    "stone": (0.10, 0.07, 0.05),
    "dark_stone": (0.06, 0.05, 0.03),
    "dead_organic": (0.06, 0.10, 0.04),
    "bone": (0.16, 0.14, 0.08),
}

BIOME_PALETTES = {
    "cavern": CAVERN_PALETTE,
    "outdoor": OUTDOOR_PALETTE,
}


# -- Color scales (per-kind overrides applied after build) ---------------------

OUTDOOR_COLOR_SCALES = {
    "boulder":         (0.75, 1.45, 0.55, 1.0),
    "column":          (0.90, 0.75, 0.55, 1.0),
    "mega_column":     (0.82, 0.65, 0.48, 1.0),
    "stalagmite":      (0.82, 0.70, 0.52, 1.0),
    "giant_fungus":    (0.60, 1.10, 0.45, 1.0),
    "crystal_cluster": (1.00, 0.82, 0.55, 1.0),
    "moss_patch":      (0.40, 0.95, 0.25, 1.0),
    "dead_log":        (0.55, 0.78, 0.35, 1.0),
    "grass_tuft":      (0.55, 1.00, 0.35, 1.0),
    "rubble":          (0.82, 0.72, 0.58, 1.0),
    "leaf_pile":       (0.90, 0.70, 0.35, 1.0),
    "twig_scatter":    (0.76, 0.65, 0.42, 1.0),
    "firefly":         (3.0, 2.0, 1.0, 1.0),
    "cave_gravel":     (0.72, 0.65, 0.48, 1.0),
    "horizon_form":    (0.12, 0.16, 0.08, 1.0),
    "horizon_mid":     (0.16, 0.20, 0.12, 1.0),
    "horizon_near":    (0.20, 0.24, 0.16, 1.0),
}


# -- Tile variants (density modifiers per tile) --------------------------------

TILE_VARIANTS = {
    "standard":       {"density_mult": 1.0, "weight": 0.60},
    "sparse":         {"density_mult": 0.4, "weight": 0.15, "desc": "near-empty, sells absence"},
    "crystal_grove":  {"density_mult": 0.6, "weight": 0.08,
                       "boost": {"crystal_cluster": 3.0, "stalagmite": 1.5}},
    "fungus_forest":  {"density_mult": 0.7, "weight": 0.07,
                       "boost": {"giant_fungus": 3.0, "moss_patch": 2.0}},
    "bone_field":     {"density_mult": 0.5, "weight": 0.05,
                       "boost": {"bone_pile": 4.0, "rubble": 2.0}},
    "wet_zone":       {"density_mult": 0.8, "weight": 0.05,
                       "boost": {"moss_patch": 3.0, "ceiling_moss": 2.0},
                       "surface": "wet_stone", "drip_motes": True},
}

OUTDOOR_TILE_VARIANTS = {
    "standard":       {"density_mult": 1.0, "weight": 0.50},
    "clearing":       {"density_mult": 0.3, "weight": 0.15,
                       "boost": {"grass_tuft": 3.0, "firefly": 2.0, "leaf": 2.0},
                       "desc": "open meadow — light, grass, drifting leaves"},
    "dense_canopy":   {"density_mult": 1.2, "weight": 0.12,
                       "boost": {"column": 2.5, "moss_patch": 2.0, "dead_log": 1.5},
                       "desc": "thick forest — more trunks, more moss, darker"},
    "fern_hollow":    {"density_mult": 0.8, "weight": 0.10,
                       "boost": {"boulder": 3.0, "moss_patch": 2.5, "leaf_pile": 2.0},
                       "desc": "sword fern colony — green mounds everywhere"},
    "rocky_outcrop":  {"density_mult": 0.6, "weight": 0.08,
                       "boost": {"stalagmite": 3.0, "rubble": 2.5, "cave_gravel": 2.0},
                       "desc": "exposed rock — stumps and stones"},
    "stream_bed":     {"density_mult": 0.7, "weight": 0.05,
                       "boost": {"moss_patch": 4.0, "grass_tuft": 2.0},
                       "surface": "wet_stone", "desc": "damp gully — moss-on-everything"},
}


# -- Companion spawns (ecosystem clustering) -----------------------------------

COMPANION_SPAWNS = {
    "boulder":      {"grass_tuft": 1, "moss_patch": 1, "radius": 4.0},
    "column":       {"grass_tuft": 1, "moss_patch": 1, "radius": 3.0},
    "mega_column":  {"moss_patch": 1, "radius": 4.0},
    "moss_patch":   {"grass_tuft": 1, "radius": 2.0},
    "dead_log":     {"grass_tuft": 1, "radius": 2.5},
    "stalagmite":   {"grass_tuft": 1, "radius": 3.0},
}

OUTDOOR_COMPANION_SPAWNS = {
    "mega_column": {"moss_patch": 1, "grass_tuft": 1, "radius": 8.0},
    "column":      {"grass_tuft": 1, "radius": 4.0},
    "boulder":     {"grass_tuft": 1, "radius": 4.0},
    "dead_log":    {"moss_patch": 1, "radius": 3.0},
    "giant_fungus": {"grass_tuft": 1, "radius": 3.5},
}


# -- Flourish pools (RosterPool variety for eye-tricking density near anchors) -
#
# Each anchor kind has a POOL of possible flourish kinds. The world generator
# picks 1-3 flourishes per anchor via RosterPool rotation, so adjacent anchors
# get different flourish mixes — creates visual density variation without
# literal "grass ring around every boulder" rules.
#
# Scale anchor: flourishes should sit WITHIN the anchor's footprint silhouette
# so they read as "ground near the rock" not "a separate feature."

CAVERN_FLOURISH_POOLS = {
    "boulder":       ["moss_patch", "rubble", "twig_scatter", "cave_gravel",
                      "grass_tuft", "leaf_pile"],
    "mega_column":   ["rubble", "moss_patch", "cave_gravel", "twig_scatter",
                      "bone_pile", "stalagmite"],
    "column":        ["rubble", "cave_gravel", "moss_patch", "grass_tuft"],
    "buttress":      ["rubble", "cave_gravel", "moss_patch", "twig_scatter"],
    "giant_fungus":  ["moss_patch", "grass_tuft", "leaf_pile", "twig_scatter"],
    "crystal_cluster": ["cave_gravel", "rubble", "moss_patch"],
    "dead_log":      ["moss_patch", "grass_tuft", "leaf_pile", "twig_scatter",
                      "rubble"],
}

OUTDOOR_FLOURISH_POOLS = {
    "boulder":       ["moss_patch", "grass_tuft", "leaf_pile", "rubble",
                      "twig_scatter"],
    "mega_column":   ["moss_patch", "grass_tuft", "dead_log", "leaf_pile",
                      "twig_scatter", "rubble"],
    "column":        ["grass_tuft", "moss_patch", "leaf_pile"],
    "buttress":      ["moss_patch", "rubble", "grass_tuft", "twig_scatter"],
    "giant_fungus":  ["grass_tuft", "leaf_pile", "moss_patch"],
    "dead_log":      ["moss_patch", "grass_tuft", "leaf_pile"],
}

FLOURISH_COUNT_RANGE = (1, 3)  # per anchor
FLOURISH_RADIUS_RANGE = (1.2, 2.8)  # tighter than before (was 1.0-3.5) — stays close to anchor, doesn't block corridors


# -- Cluster archetypes (RosterPool source for room feature clusters) ----------
#
# A cluster is a small group of 2-5 same-kind entities placed as a single
# composition element (like the spore-pod trio in Tag 4). Rooms get 1-2
# cluster placements as scene-setting features that read as ONE thing.
#
# Each cluster: kind + count range + internal spread radius + z_height_offset
# for overhead variants (stalactite-style hanging formations).

# -- Formation beacon pool (RosterPool source for formation column beacons) ---
#
# Every formation column gets one beacon element placed 3m off its base.
# The LRU roster cycles through beacon types so adjacent formations differ.
# (Name kept as ROOM_BEACONS for historical reasons — consumer is formation
# beacon emission in world_gen.py, not the reverted room system.)

CAVERN_ROOM_BEACONS = [
    {"name": "filament_spire",  "kind": "filament",
     "count": 1, "spread": 0.0, "z_offset": 0.0},
    {"name": "crystal_hearth",  "kind": "crystal_cluster",
     "count": 1, "spread": 0.0, "z_offset": 0.0},
    {"name": "crystal_trio",    "kind": "crystal_cluster",
     "count": 3, "spread": 1.5, "z_offset": 0.0},
    {"name": "firefly_swarm",   "kind": "firefly",
     "count": 5, "spread": 2.2, "z_offset": 1.5},
    {"name": "fungus_beacon",   "kind": "giant_fungus",
     "count": 1, "spread": 0.0, "z_offset": 0.0},
    {"name": "filament_trio",   "kind": "filament",
     "count": 3, "spread": 1.8, "z_offset": 0.0},
]

OUTDOOR_ROOM_BEACONS = [
    {"name": "firefly_swarm",   "kind": "firefly",
     "count": 6, "spread": 2.5, "z_offset": 1.5},
    {"name": "fungus_ring",     "kind": "giant_fungus",
     "count": 3, "spread": 2.0, "z_offset": 0.0},
    {"name": "moss_glow",       "kind": "moss_patch",
     "count": 4, "spread": 2.0, "z_offset": 0.0},
    {"name": "crystal_hearth",  "kind": "crystal_cluster",
     "count": 1, "spread": 0.0, "z_offset": 0.0},
]


# -- Stamps (authored compositions placed at honeycomb nodes) ------------------
#
# A stamp is a multi-object composition that replaces the single-anchor roll
# at a honeycomb node. Instead of "one boulder + flourishes", a stamp places
# an integrated scene: "two boulders flanking a gap with a crystal accent."
#
# Fields:
#   name      — unique identifier
#   footprint — radius the stamp claims (no other hard objects inside)
#   members   — list of relative placements:
#       kind       — entity kind name
#       dx, dy     — offset from stamp center (meters)
#       scale_mult — optional scale multiplier (None = 1.0)
#       hard       — whether this member needs collision reservation
#
# Stamps are selected via RosterPool rotation at ~25% of honeycomb nodes.
# The rest stay as single-anchor rolls (preserving existing scatter baseline).

CAVERN_STAMPS = [
    # Creature den — ghost sprite primitive test: rats + chest
    # Weight 4 = ~30% of slots, same as mega stamps. Guaranteed sighting.
    {
        "name": "creature_den",
        "footprint": 5.0,
        "weight": 4,
        "members": [
            {"kind": "rat", "dx": 0.0, "dy": 0.0, "scale_mult": None, "hard": False},
            {"kind": "rat", "dx": 1.5, "dy": 0.8, "scale_mult": None, "hard": False},
            {"kind": "rat", "dx": -1.2, "dy": 1.0, "scale_mult": None, "hard": False},
            {"kind": "rat_ice", "dx": 2.5, "dy": -1.0, "scale_mult": None, "hard": False},
            {"kind": "rat_fire", "dx": -2.0, "dy": -1.5, "scale_mult": None, "hard": False},
            {"kind": "treasure_chest", "dx": 0.0, "dy": -2.5, "scale_mult": None, "hard": True},
            {"kind": "clay_pot", "dx": -3.0, "dy": 0.5, "scale_mult": None, "hard": False},
            {"kind": "clay_pot", "dx": 3.0, "dy": -0.5, "scale_mult": None, "hard": False},
            {"kind": "bone_pile", "dx": 1.0, "dy": 2.0, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": -1.5, "dy": -0.5, "scale_mult": None, "hard": False},
        ],
    },
    # Crystal grotto — emissive focal point, the "room with a light"
    {
        "name": "crystal_grotto",
        "footprint": 6.0,
        "members": [
            {"kind": "crystal_cluster", "dx": 0.0, "dy": 0.0, "scale_mult": 1.3, "hard": True},
            {"kind": "stalagmite", "dx": -3.0, "dy": -1.5, "scale_mult": None, "hard": True},
            {"kind": "stalagmite", "dx": 2.8, "dy": -1.8, "scale_mult": None, "hard": True},
            {"kind": "moss_patch", "dx": -1.0, "dy": 1.5, "scale_mult": None, "hard": False},
            {"kind": "moss_patch", "dx": 1.2, "dy": 2.0, "scale_mult": None, "hard": False},
            {"kind": "filament", "dx": 0.5, "dy": -3.5, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": -2.0, "dy": 0.8, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": 1.8, "dy": 0.5, "scale_mult": None, "hard": False},
        ],
    },
    # Bone shrine — narrative beat, something happened here
    {
        "name": "bone_shrine",
        "footprint": 5.0,
        "members": [
            {"kind": "bone_pile", "dx": 0.0, "dy": 0.0, "scale_mult": 1.2, "hard": True},
            {"kind": "rubble", "dx": -2.0, "dy": -1.0, "scale_mult": None, "hard": False},
            {"kind": "rubble", "dx": 2.2, "dy": -0.8, "scale_mult": None, "hard": False},
            {"kind": "dead_log", "dx": 0.0, "dy": -2.5, "scale_mult": None, "hard": True},
            {"kind": "firefly", "dx": 0.3, "dy": 0.5, "scale_mult": None, "hard": False},
            {"kind": "firefly", "dx": -0.5, "dy": 0.8, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": 1.0, "dy": 1.5, "scale_mult": None, "hard": False},
        ],
    },
    # Fungus hollow — bioluminescent cluster, vertical + ground emissives
    {
        "name": "fungus_hollow",
        "footprint": 6.0,
        "members": [
            {"kind": "giant_fungus", "dx": 0.0, "dy": 0.0, "scale_mult": 1.1, "hard": True},
            {"kind": "giant_fungus", "dx": -2.5, "dy": 1.5, "scale_mult": 0.55, "hard": True},
            {"kind": "giant_fungus", "dx": 2.0, "dy": 2.0, "scale_mult": 0.5, "hard": True},
            {"kind": "moss_patch", "dx": -1.5, "dy": -1.0, "scale_mult": None, "hard": False},
            {"kind": "moss_patch", "dx": 1.0, "dy": -2.0, "scale_mult": None, "hard": False},
            {"kind": "ceiling_moss", "dx": 0.0, "dy": 0.5, "scale_mult": None, "hard": False},
            {"kind": "firefly", "dx": -1.0, "dy": 2.5, "scale_mult": None, "hard": False},
            {"kind": "firefly", "dx": 1.5, "dy": 1.0, "scale_mult": None, "hard": False},
        ],
    },
    # Boulder gate — two rocks framing a walkable gap, invitation to pass through
    {
        "name": "boulder_gate",
        "footprint": 7.0,
        "members": [
            {"kind": "boulder", "dx": -3.5, "dy": 0.0, "scale_mult": 1.0, "hard": True},
            {"kind": "boulder", "dx": 3.5, "dy": 0.0, "scale_mult": 0.85, "hard": True},
            {"kind": "rubble", "dx": -1.0, "dy": -1.5, "scale_mult": None, "hard": False},
            {"kind": "rubble", "dx": 0.8, "dy": -1.2, "scale_mult": None, "hard": False},
            {"kind": "crystal_cluster", "dx": 0.0, "dy": 3.0, "scale_mult": 0.7, "hard": True},
            {"kind": "cave_gravel", "dx": 0.0, "dy": 0.0, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": -0.5, "dy": 0.5, "scale_mult": None, "hard": False},
        ],
    },
    # Pillar alcove — column with flanking spires, reads as a nook
    {
        "name": "pillar_alcove",
        "footprint": 5.5,
        "members": [
            {"kind": "column", "dx": 0.0, "dy": -1.0, "scale_mult": None, "hard": True},
            {"kind": "stalagmite", "dx": -2.5, "dy": 1.0, "scale_mult": 0.9, "hard": True},
            {"kind": "stalagmite", "dx": 2.5, "dy": 0.8, "scale_mult": 0.8, "hard": True},
            {"kind": "moss_patch", "dx": 0.0, "dy": 1.5, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": -1.2, "dy": -0.5, "scale_mult": None, "hard": False},
            {"kind": "grass_tuft", "dx": 1.0, "dy": 1.8, "scale_mult": None, "hard": False},
        ],
    },
    # Spore cluster — partner-type group: one giant_fungus hero (cap-bearing,
    # skyward spore release) with surrounding spore_pod ground partners
    # (boulder-mimic, ground spore receivers). Lore: fungus releases spores
    # from cap, pods catch them at ground level. Both species in one stamp.
    {
        "name": "spore_cluster",
        "footprint": 4.0,
        "members": [
            {"kind": "giant_fungus", "dx": 0.0, "dy": 0.0, "scale_mult": 0.6, "hard": True},
            {"kind": "spore_pod", "dx": -1.5, "dy": 1.2, "scale_mult": None, "hard": False},
            {"kind": "spore_pod", "dx": 1.8, "dy": 0.5, "scale_mult": None, "hard": False},
            {"kind": "spore_pod", "dx": 0.5, "dy": -1.8, "scale_mult": None, "hard": False},
            {"kind": "moss_patch", "dx": -0.5, "dy": -0.5, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": 1.0, "dy": 1.5, "scale_mult": None, "hard": False},
        ],
    },
    # Ruined doorway (existing kinds) — composition experiment C from the
    # 2026-04-09 evening session. Two columns as posts, rubble fall
    # between them, moss/gravel dressing. Tests whether the doorway
    # concept READS before authoring a custom doorframe mesh.
    {
        "name": "ruined_doorway_columns",
        "footprint": 6.0,
        "members": [
            {"kind": "column", "dx": -1.6, "dy": 0.0, "scale_mult": 0.85, "hard": True},
            {"kind": "column", "dx": 1.6, "dy": 0.0, "scale_mult": 0.85, "hard": True},
            {"kind": "rubble", "dx": 0.0, "dy": -0.3, "scale_mult": 1.2, "hard": False},
            {"kind": "rubble", "dx": -0.6, "dy": 0.4, "scale_mult": None, "hard": False},
            {"kind": "rubble", "dx": 0.7, "dy": 0.5, "scale_mult": None, "hard": False},
            {"kind": "rubble", "dx": -2.5, "dy": -1.0, "scale_mult": None, "hard": False},
            {"kind": "rubble", "dx": 2.5, "dy": -0.8, "scale_mult": None, "hard": False},
            {"kind": "moss_patch", "dx": -1.4, "dy": 0.5, "scale_mult": None, "hard": False},
            {"kind": "moss_patch", "dx": 1.4, "dy": 0.6, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": 0.0, "dy": 0.0, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": -1.0, "dy": -1.5, "scale_mult": None, "hard": False},
            {"kind": "grass_tuft", "dx": -2.0, "dy": 1.5, "scale_mult": None, "hard": False},
        ],
    },
    # Ancient threshold (custom doorframe kind) — experiment A from the
    # 2026-04-09 evening session. Uses the new gen_kind_mesh-built
    # doorframe kind (vertex-colored stone post + lintel beam) as the
    # hero, with rubble fall, moss accents, and a guardian monolith
    # standing off to one side as a way-marker.
    {
        "name": "ancient_threshold",
        "footprint": 7.0,
        "members": [
            {"kind": "doorframe", "dx": 0.0, "dy": 0.0, "scale_mult": 1.0, "hard": True},
            {"kind": "monolith", "dx": -3.0, "dy": -1.5, "scale_mult": 1.0, "hard": True},
            {"kind": "rubble", "dx": 0.0, "dy": -0.4, "scale_mult": 1.3, "hard": False},
            {"kind": "rubble", "dx": -1.2, "dy": 0.5, "scale_mult": None, "hard": False},
            {"kind": "rubble", "dx": 1.0, "dy": 0.3, "scale_mult": None, "hard": False},
            {"kind": "moss_patch", "dx": -1.8, "dy": 0.6, "scale_mult": None, "hard": False},
            {"kind": "moss_patch", "dx": 1.8, "dy": 0.5, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": 0.0, "dy": 0.0, "scale_mult": None, "hard": False},
            {"kind": "grass_tuft", "dx": 2.5, "dy": 1.8, "scale_mult": None, "hard": False},
        ],
    },
    # Standing stones (monolith kind) — irregular menhir scatter.
    # NOT a clean triangle — five stones placed asymmetrically across
    # the footprint with rubble fall and moss in between. Each monolith
    # picks its own variant + per-instance scale hash, so no two read
    # alike. Boundary marker / collapsed ritual site language.
    {
        "name": "standing_stones",
        "footprint": 9.0,
        "members": [
            {"kind": "monolith", "dx": -3.5, "dy": -2.0, "scale_mult": 1.0, "hard": True},
            {"kind": "monolith", "dx": 2.8, "dy": -2.5, "scale_mult": 1.0, "hard": True},
            {"kind": "monolith", "dx": -1.0, "dy": 3.2, "scale_mult": 0.85, "hard": True},
            {"kind": "monolith", "dx": 3.5, "dy": 1.5, "scale_mult": 0.9, "hard": True},
            {"kind": "monolith", "dx": -2.5, "dy": 0.8, "scale_mult": 0.75, "hard": False},
            {"kind": "rubble", "dx": -1.8, "dy": -1.0, "scale_mult": None, "hard": False},
            {"kind": "rubble", "dx": 1.5, "dy": -1.5, "scale_mult": None, "hard": False},
            {"kind": "rubble", "dx": 0.5, "dy": 2.5, "scale_mult": None, "hard": False},
            {"kind": "moss_patch", "dx": 0.0, "dy": 0.0, "scale_mult": None, "hard": False},
            {"kind": "moss_patch", "dx": -2.0, "dy": 2.5, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": 0.5, "dy": 1.0, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": -0.5, "dy": -1.0, "scale_mult": None, "hard": False},
            {"kind": "grass_tuft", "dx": -3.0, "dy": 1.5, "scale_mult": None, "hard": False},
            {"kind": "grass_tuft", "dx": 2.5, "dy": 0.5, "scale_mult": None, "hard": False},
        ],
    },
    # Toadstool grove — biome-agnostic landmark fungus (classic Fly Agaric).
    # Hero toadstool centered, partner-type spore_pods flanking (lore: pods
    # catch spores released by toadstool gills), moss ring underneath.
    # Rare stamp = singleton presence when it appears.
    # Authored via tools/gen_kind_mesh.py with baked vertex colors.
    {
        "name": "toadstool_grove",
        "footprint": 6.0,
        "members": [
            {"kind": "toadstool", "dx": 0.0, "dy": 0.0, "scale_mult": 1.0, "hard": True},
            {"kind": "spore_pod", "dx": -2.2, "dy": 1.5, "scale_mult": None, "hard": False},
            {"kind": "spore_pod", "dx": 2.0, "dy": -1.8, "scale_mult": None, "hard": False},
            {"kind": "moss_patch", "dx": -0.8, "dy": 0.6, "scale_mult": None, "hard": False},
            {"kind": "moss_patch", "dx": 0.7, "dy": -0.5, "scale_mult": None, "hard": False},
            {"kind": "grass_tuft", "dx": 1.5, "dy": 1.8, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": -1.5, "dy": -1.8, "scale_mult": None, "hard": False},
        ],
    },
    # Rubble field — collapsed area, wide low scatter, tells a story
    {
        "name": "rubble_field",
        "footprint": 6.0,
        "members": [
            {"kind": "rubble", "dx": 0.0, "dy": 0.0, "scale_mult": 1.3, "hard": False},
            {"kind": "rubble", "dx": -2.5, "dy": 1.0, "scale_mult": None, "hard": False},
            {"kind": "rubble", "dx": 2.0, "dy": -1.5, "scale_mult": None, "hard": False},
            {"kind": "rubble", "dx": -1.0, "dy": -2.5, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": 1.5, "dy": 1.8, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": -2.0, "dy": -1.0, "scale_mult": None, "hard": False},
            {"kind": "bone_pile", "dx": 0.5, "dy": 2.0, "scale_mult": None, "hard": False},
            {"kind": "twig_scatter", "dx": -1.5, "dy": 2.5, "scale_mult": None, "hard": False},
        ],
    },
    # Filament grove — tall emissive stalks in a loose line, wayfinding pull
    {
        "name": "filament_grove",
        "footprint": 5.0,
        "members": [
            {"kind": "filament", "dx": 0.0, "dy": 0.0, "scale_mult": None, "hard": False},
            {"kind": "filament", "dx": -2.0, "dy": 1.5, "scale_mult": None, "hard": False},
            {"kind": "filament", "dx": 2.0, "dy": -1.0, "scale_mult": None, "hard": False},
            {"kind": "moss_patch", "dx": 0.5, "dy": 2.0, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": -1.0, "dy": -1.5, "scale_mult": None, "hard": False},
        ],
    },
    # Stalagmite fence — row of spires creating a natural barrier/corridor wall
    {
        "name": "stalagmite_fence",
        "footprint": 6.0,
        "members": [
            {"kind": "stalagmite", "dx": -3.0, "dy": 0.0, "scale_mult": 1.1, "hard": True},
            {"kind": "stalagmite", "dx": -1.0, "dy": 0.3, "scale_mult": 0.85, "hard": True},
            {"kind": "stalagmite", "dx": 1.0, "dy": -0.2, "scale_mult": 1.0, "hard": True},
            {"kind": "stalagmite", "dx": 3.0, "dy": 0.1, "scale_mult": 0.9, "hard": True},
            {"kind": "rubble", "dx": 0.0, "dy": 1.5, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": -2.0, "dy": -1.0, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": 2.0, "dy": -1.2, "scale_mult": None, "hard": False},
        ],
    },
    # ---- MEGA STAMPS — landmark anchors, walkable interiors ----
    # All mega stamps have weight: 4 — weighted selection in stamp_world
    # pushes their pick rate from 19% (uniform 3/16) to ~48%
    # (3×4 / (13 + 12) = 12/25). Claustrophobic cavern is the intent.
    #
    # Obelisk court — single mega_column landmark, ground stays open around it
    {
        "name": "obelisk_court",
        "weight": 4,
        "footprint": 8.0,
        "members": [
            {"kind": "mega_column", "dx": 0.0, "dy": 0.0, "scale_mult": 1.0, "hard": True},
            {"kind": "rubble", "dx": -3.5, "dy": -3.0, "scale_mult": None, "hard": False},
            {"kind": "rubble", "dx": 3.0, "dy": -3.5, "scale_mult": None, "hard": False},
            {"kind": "moss_patch", "dx": -2.5, "dy": 2.5, "scale_mult": None, "hard": False},
            {"kind": "crystal_cluster", "dx": 3.5, "dy": 3.0, "scale_mult": 0.6, "hard": False},
            {"kind": "cave_gravel", "dx": 0.0, "dy": -2.5, "scale_mult": None, "hard": False},
        ],
    },
    # Column henge — three columns at the perimeter, walkable center
    {
        "name": "column_henge",
        "weight": 4,
        "footprint": 9.0,
        "members": [
            {"kind": "column", "dx": -4.0, "dy": -2.0, "scale_mult": 1.0, "hard": True},
            {"kind": "column", "dx": 4.0, "dy": -2.0, "scale_mult": 1.0, "hard": True},
            {"kind": "column", "dx": 0.0, "dy": 4.0, "scale_mult": 1.1, "hard": True},
            {"kind": "moss_patch", "dx": 0.0, "dy": 0.0, "scale_mult": None, "hard": False},
            {"kind": "firefly", "dx": 0.5, "dy": 0.5, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": -1.5, "dy": 1.5, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": 1.5, "dy": -1.0, "scale_mult": None, "hard": False},
        ],
    },
    # Buttress arch — buttress + mega_column flanking a gap, gateway feel
    {
        "name": "buttress_arch",
        "weight": 4,
        "footprint": 9.0,
        "members": [
            {"kind": "mega_column", "dx": -4.0, "dy": 0.0, "scale_mult": 0.85, "hard": True},
            {"kind": "buttress", "dx": 4.0, "dy": 0.5, "scale_mult": 1.0, "hard": True},
            {"kind": "boulder", "dx": -3.5, "dy": -3.5, "scale_mult": 0.7, "hard": False},
            {"kind": "rubble", "dx": 3.0, "dy": -3.5, "scale_mult": None, "hard": False},
            {"kind": "crystal_cluster", "dx": 0.0, "dy": 3.5, "scale_mult": 0.5, "hard": False},
            {"kind": "moss_patch", "dx": 0.0, "dy": 0.0, "scale_mult": None, "hard": False},
        ],
    },
    # ------------------------------------------------------------------------
    # CAPTURED STAMPS — authored via Shift+Cmd+T in live play, pasted here
    # verbatim. Positions are player-relative from the capture moment. Re-
    # tune footprint / weight / rename as compositions prove themselves out.
    # ------------------------------------------------------------------------

    # Captured grove_mycelial (30 members) — authored from live scene.
    # Captured within 20m radius via Shift+Cmd+T, so footprint must cover it.
    {
        "name": "grove_mycelial",
        "footprint": 20.0,
        "weight": 2,
        "members": [
            {"kind": "filament", "dx": -4.9, "dy": -11.6, "scale_mult": 0.9, "hard": False},
            {"kind": "filament", "dx": -4.1, "dy": -9.3, "scale_mult": 0.93, "hard": False},
            {"kind": "filament", "dx": -5.1, "dy": -13.9, "scale_mult": 0.69, "hard": False},
            {"kind": "moss_patch", "dx": -2.8, "dy": -11.4, "scale_mult": 0.76, "hard": False},
            {"kind": "cave_gravel", "dx": -6.6, "dy": -11.2, "scale_mult": 0.82, "hard": False},
            {"kind": "giant_fungus", "dx": 8.3, "dy": -11.4, "scale_mult": 0.65, "hard": True},
            {"kind": "grass_tuft", "dx": 5.7, "dy": -11.4, "scale_mult": 0.83, "hard": False},
            {"kind": "moss_patch", "dx": 10.0, "dy": -11.0, "scale_mult": 0.59, "hard": False},
            {"kind": "leaf_pile", "dx": 10.3, "dy": -9.7, "scale_mult": 0.65, "hard": False},
            {"kind": "giant_fungus", "dx": 7.9, "dy": -14.6, "scale_mult": 0.79, "hard": True},
            {"kind": "giant_fungus", "dx": 10.9, "dy": -10.0, "scale_mult": 0.8, "hard": True},
            {"kind": "giant_fungus", "dx": 6.8, "dy": -13.8, "scale_mult": 0.69, "hard": True},
            {"kind": "giant_fungus", "dx": 7.5, "dy": -9.7, "scale_mult": 0.75, "hard": True},
            {"kind": "giant_fungus", "dx": 5.8, "dy": -11.6, "scale_mult": 0.77, "hard": True},
            {"kind": "moss_patch", "dx": -17.2, "dy": 3.6, "scale_mult": 0.65, "hard": False},
            {"kind": "moss_patch", "dx": -0.2, "dy": 5.1, "scale_mult": 0.92, "hard": False},
            {"kind": "moss_patch", "dx": 14.7, "dy": 3.7, "scale_mult": 0.74, "hard": False},
            {"kind": "grass_tuft", "dx": -10.4, "dy": 13.3, "scale_mult": 0.69, "hard": False},
            {"kind": "rubble", "dx": -4.7, "dy": 14.7, "scale_mult": 0.63, "hard": False},
            {"kind": "ceiling_moss", "dx": 9.3, "dy": 17.6, "scale_mult": 0.76, "hard": False},
            {"kind": "column", "dx": 14.2, "dy": -8.5, "scale_mult": 0.91, "hard": True},
            {"kind": "column", "dx": -7.1, "dy": -2.1, "scale_mult": 0.65, "hard": True},
            {"kind": "crystal_cluster", "dx": -13.2, "dy": 7.0, "scale_mult": 0.75, "hard": True},
            {"kind": "moss_patch", "dx": -14.7, "dy": 12.1, "scale_mult": 0.85, "hard": False},
            {"kind": "rubble", "dx": -3.4, "dy": 14.1, "scale_mult": 0.6, "hard": False},
            {"kind": "rubble", "dx": -2.9, "dy": 13.6, "scale_mult": 0.82, "hard": False},
            {"kind": "cave_gravel", "dx": -2.1, "dy": 13.1, "scale_mult": 0.79, "hard": False},
            {"kind": "rubble", "dx": 7.7, "dy": 12.1, "scale_mult": 0.73, "hard": False},
            {"kind": "rubble", "dx": 7.8, "dy": 12.4, "scale_mult": 0.67, "hard": False},
            {"kind": "grass_tuft", "dx": 6.3, "dy": -10.8, "scale_mult": 0.77, "hard": False},
        ],
    },

    # Captured grotto_mixed (67 members) — authored from live scene.
    {
        "name": "grotto_mixed",
        "footprint": 20.0,
        "weight": 1,
        "members": [
            {"kind": "crystal_cluster", "dx": -6.7, "dy": -15.4, "scale_mult": 0.87, "hard": True},
            {"kind": "moss_patch", "dx": -8.2, "dy": -13.8, "scale_mult": 0.89, "hard": False},
            {"kind": "rubble", "dx": 9.1, "dy": -14.7, "scale_mult": 0.83, "hard": False},
            {"kind": "crystal_cluster", "dx": 10.6, "dy": -14.3, "scale_mult": 0.62, "hard": True},
            {"kind": "twig_scatter", "dx": -19.5, "dy": -2.0, "scale_mult": 0.71, "hard": False},
            {"kind": "column", "dx": -10.7, "dy": -1.0, "scale_mult": 0.59, "hard": True},
            {"kind": "rubble", "dx": -11.3, "dy": -0.3, "scale_mult": 0.8, "hard": False},
            {"kind": "rubble", "dx": -9.8, "dy": -1.1, "scale_mult": 0.96, "hard": False},
            {"kind": "cave_gravel", "dx": -12.0, "dy": 3.7, "scale_mult": 0.95, "hard": False},
            {"kind": "moss_patch", "dx": -6.4, "dy": -5.3, "scale_mult": 0.73, "hard": False},
            {"kind": "ceiling_moss", "dx": -10.7, "dy": -1.0, "scale_mult": 0.83, "hard": False},
            {"kind": "ceiling_moss", "dx": -9.6, "dy": 0.8, "scale_mult": 0.79, "hard": False},
            {"kind": "ceiling_moss", "dx": -10.6, "dy": 0.7, "scale_mult": 0.8, "hard": False},
            {"kind": "ceiling_moss", "dx": -13.1, "dy": 0.0, "scale_mult": 0.84, "hard": False},
            {"kind": "ceiling_moss", "dx": -10.0, "dy": 2.4, "scale_mult": 0.75, "hard": False},
            {"kind": "ceiling_moss", "dx": -13.2, "dy": -5.2, "scale_mult": 0.84, "hard": False},
            {"kind": "cave_gravel", "dx": -9.3, "dy": -0.4, "scale_mult": 0.59, "hard": False},
            {"kind": "cave_gravel", "dx": -11.0, "dy": -3.0, "scale_mult": 0.59, "hard": False},
            {"kind": "moss_patch", "dx": -10.5, "dy": 0.1, "scale_mult": 0.87, "hard": False},
            {"kind": "moss_patch", "dx": -10.8, "dy": -3.2, "scale_mult": 0.71, "hard": False},
            {"kind": "giant_fungus", "dx": 3.5, "dy": -4.6, "scale_mult": 0.95, "hard": True},
            {"kind": "grass_tuft", "dx": 3.9, "dy": -7.9, "scale_mult": 0.94, "hard": False},
            {"kind": "moss_patch", "dx": 0.6, "dy": -4.9, "scale_mult": 0.66, "hard": False},
            {"kind": "giant_fungus", "dx": 1.1, "dy": -5.2, "scale_mult": 0.71, "hard": True},
            {"kind": "giant_fungus", "dx": 1.1, "dy": -4.6, "scale_mult": 0.71, "hard": True},
            {"kind": "giant_fungus", "dx": 5.2, "dy": -7.0, "scale_mult": 0.84, "hard": True},
            {"kind": "crystal_cluster", "dx": 17.4, "dy": 0.2, "scale_mult": 0.67, "hard": True},
            {"kind": "moss_patch", "dx": 16.8, "dy": -1.9, "scale_mult": 0.95, "hard": False},
            {"kind": "rubble", "dx": 19.1, "dy": 2.6, "scale_mult": 0.6, "hard": False},
            {"kind": "cave_gravel", "dx": -17.0, "dy": 7.1, "scale_mult": 0.68, "hard": False},
            {"kind": "stalagmite", "dx": -13.0, "dy": 15.1, "scale_mult": 0.9, "hard": True},
            {"kind": "giant_fungus", "dx": -4.4, "dy": 10.3, "scale_mult": 0.63, "hard": True},
            {"kind": "moss_patch", "dx": -5.5, "dy": 7.5, "scale_mult": 0.77, "hard": False},
            {"kind": "leaf_pile", "dx": -4.8, "dy": 12.9, "scale_mult": 0.87, "hard": False},
            {"kind": "twig_scatter", "dx": -3.2, "dy": 7.4, "scale_mult": 0.8, "hard": False},
            {"kind": "giant_fungus", "dx": -4.1, "dy": 8.3, "scale_mult": 0.81, "hard": True},
            {"kind": "giant_fungus", "dx": -3.9, "dy": 7.9, "scale_mult": 0.96, "hard": True},
            {"kind": "giant_fungus", "dx": -4.7, "dy": 8.3, "scale_mult": 0.67, "hard": True},
            {"kind": "grass_tuft", "dx": -6.2, "dy": 11.2, "scale_mult": 0.65, "hard": False},
            {"kind": "grass_tuft", "dx": -2.8, "dy": 12.1, "scale_mult": 0.76, "hard": False},
            {"kind": "grass_tuft", "dx": -6.1, "dy": 9.7, "scale_mult": 0.87, "hard": False},
            {"kind": "giant_fungus", "dx": 10.6, "dy": 12.2, "scale_mult": 0.76, "hard": True},
            {"kind": "grass_tuft", "dx": 10.0, "dy": 10.1, "scale_mult": 0.69, "hard": False},
            {"kind": "giant_fungus", "dx": 7.7, "dy": 11.1, "scale_mult": 0.73, "hard": True},
            {"kind": "giant_fungus", "dx": 8.7, "dy": 14.5, "scale_mult": 0.7, "hard": True},
            {"kind": "giant_fungus", "dx": 12.5, "dy": 14.6, "scale_mult": 0.71, "hard": True},
            {"kind": "giant_fungus", "dx": 11.5, "dy": 10.6, "scale_mult": 0.59, "hard": True},
            {"kind": "cave_gravel", "dx": 12.1, "dy": 11.9, "scale_mult": 0.76, "hard": False},
            {"kind": "cave_gravel", "dx": 12.6, "dy": 13.2, "scale_mult": 0.9, "hard": False},
            {"kind": "crystal_cluster", "dx": -8.1, "dy": 3.6, "scale_mult": 0.59, "hard": True},
            {"kind": "moss_patch", "dx": 7.7, "dy": -8.6, "scale_mult": 0.68, "hard": False},
            {"kind": "crystal_cluster", "dx": 18.4, "dy": 6.8, "scale_mult": 0.77, "hard": True},
            {"kind": "boulder", "dx": -4.2, "dy": -6.5, "scale_mult": 0.87, "hard": True},
            {"kind": "rubble", "dx": -4.9, "dy": -6.9, "scale_mult": 0.7, "hard": False},
            {"kind": "rubble", "dx": -3.9, "dy": -5.8, "scale_mult": 0.88, "hard": False},
            {"kind": "cave_gravel", "dx": -4.2, "dy": -5.7, "scale_mult": 0.84, "hard": False},
            {"kind": "stalagmite", "dx": 8.1, "dy": 6.0, "scale_mult": 0.95, "hard": True},
            {"kind": "rubble", "dx": 8.5, "dy": 5.4, "scale_mult": 0.93, "hard": False},
            {"kind": "rubble", "dx": 7.8, "dy": 5.6, "scale_mult": 0.94, "hard": False},
            {"kind": "cave_gravel", "dx": 7.2, "dy": 6.0, "scale_mult": 0.68, "hard": False},
            {"kind": "stalagmite", "dx": 7.4, "dy": -17.0, "scale_mult": 0.75, "hard": True},
            {"kind": "rubble", "dx": 7.8, "dy": -17.5, "scale_mult": 0.8, "hard": False},
            {"kind": "rubble", "dx": 7.3, "dy": -17.4, "scale_mult": 0.91, "hard": False},
            {"kind": "stalagmite", "dx": 2.1, "dy": 13.4, "scale_mult": 0.7, "hard": True},
            {"kind": "rubble", "dx": 3.0, "dy": 13.1, "scale_mult": 0.83, "hard": False},
            {"kind": "rubble", "dx": 2.7, "dy": 14.2, "scale_mult": 0.62, "hard": False},
            {"kind": "rubble", "dx": 16.4, "dy": 8.8, "scale_mult": 0.65, "hard": False},
        ],
    },

    # Captured fallen_arch_field (92 members) — authored from live scene.
    {
        "name": "fallen_arch_field",
        "footprint": 20.0,
        "weight": 1,
        "members": [
            {"kind": "leaf_pile", "dx": -13.7, "dy": -14.0, "scale_mult": 0.87, "hard": False},
            {"kind": "grass_tuft", "dx": -11.8, "dy": -14.9, "scale_mult": 0.76, "hard": False},
            {"kind": "giant_fungus", "dx": 1.7, "dy": -14.8, "scale_mult": 0.76, "hard": True},
            {"kind": "grass_tuft", "dx": 1.0, "dy": -16.9, "scale_mult": 0.69, "hard": False},
            {"kind": "giant_fungus", "dx": -1.3, "dy": -15.9, "scale_mult": 0.73, "hard": True},
            {"kind": "giant_fungus", "dx": -0.2, "dy": -12.5, "scale_mult": 0.7, "hard": True},
            {"kind": "giant_fungus", "dx": 3.5, "dy": -12.4, "scale_mult": 0.71, "hard": True},
            {"kind": "giant_fungus", "dx": 2.6, "dy": -16.4, "scale_mult": 0.59, "hard": True},
            {"kind": "cave_gravel", "dx": 3.2, "dy": -15.1, "scale_mult": 0.76, "hard": False},
            {"kind": "cave_gravel", "dx": 3.7, "dy": -13.8, "scale_mult": 0.9, "hard": False},
            {"kind": "mega_column", "dx": -6.1, "dy": 0.4, "scale_mult": 0.59, "hard": True},
            {"kind": "rubble", "dx": -6.5, "dy": 0.5, "scale_mult": 0.93, "hard": False},
            {"kind": "rubble", "dx": -6.5, "dy": 0.1, "scale_mult": 0.81, "hard": False},
            {"kind": "cave_gravel", "dx": -6.7, "dy": -0.4, "scale_mult": 0.64, "hard": False},
            {"kind": "cave_gravel", "dx": -6.3, "dy": 1.2, "scale_mult": 0.85, "hard": False},
            {"kind": "filament", "dx": -4.8, "dy": -0.4, "scale_mult": 0.9, "hard": False},
            {"kind": "rubble", "dx": -0.3, "dy": 4.4, "scale_mult": 0.61, "hard": False},
            {"kind": "twig_scatter", "dx": -8.7, "dy": 6.0, "scale_mult": 0.66, "hard": False},
            {"kind": "ceiling_moss", "dx": -6.1, "dy": 0.4, "scale_mult": 0.74, "hard": False},
            {"kind": "ceiling_moss", "dx": -8.6, "dy": 0.5, "scale_mult": 0.77, "hard": False},
            {"kind": "ceiling_moss", "dx": -4.7, "dy": 1.5, "scale_mult": 0.93, "hard": False},
            {"kind": "ceiling_moss", "dx": -4.5, "dy": -1.6, "scale_mult": 0.76, "hard": False},
            {"kind": "ceiling_moss", "dx": -4.5, "dy": -3.4, "scale_mult": 0.82, "hard": False},
            {"kind": "ceiling_moss", "dx": -6.4, "dy": 4.9, "scale_mult": 0.85, "hard": False},
            {"kind": "grass_tuft", "dx": -8.0, "dy": -1.8, "scale_mult": 0.6, "hard": False},
            {"kind": "grass_tuft", "dx": -8.0, "dy": -2.6, "scale_mult": 0.68, "hard": False},
            {"kind": "column", "dx": 11.3, "dy": -1.9, "scale_mult": 0.8, "hard": True},
            {"kind": "rubble", "dx": 11.9, "dy": -1.6, "scale_mult": 0.84, "hard": False},
            {"kind": "rubble", "dx": 11.5, "dy": -1.0, "scale_mult": 0.86, "hard": False},
            {"kind": "cave_gravel", "dx": 12.8, "dy": 3.6, "scale_mult": 0.65, "hard": False},
            {"kind": "moss_patch", "dx": 11.6, "dy": -7.0, "scale_mult": 0.81, "hard": False},
            {"kind": "rubble", "dx": 10.0, "dy": -0.8, "scale_mult": 0.67, "hard": False},
            {"kind": "moss_patch", "dx": 13.5, "dy": -0.9, "scale_mult": 0.86, "hard": False},
            {"kind": "giant_fungus", "dx": -13.3, "dy": 13.1, "scale_mult": 0.86, "hard": True},
            {"kind": "moss_patch", "dx": -12.4, "dy": 15.1, "scale_mult": 0.96, "hard": False},
            {"kind": "mega_column", "dx": 0.4, "dy": 13.8, "scale_mult": 0.92, "hard": True},
            {"kind": "rubble", "dx": 0.1, "dy": 14.3, "scale_mult": 0.7, "hard": False},
            {"kind": "rubble", "dx": 0.5, "dy": 14.5, "scale_mult": 0.68, "hard": False},
            {"kind": "cave_gravel", "dx": 0.4, "dy": 13.0, "scale_mult": 0.64, "hard": False},
            {"kind": "cave_gravel", "dx": 0.7, "dy": 13.8, "scale_mult": 0.92, "hard": False},
            {"kind": "filament", "dx": 1.9, "dy": 14.6, "scale_mult": 0.64, "hard": False},
            {"kind": "rubble", "dx": 1.8, "dy": 14.5, "scale_mult": 0.75, "hard": False},
            {"kind": "rubble", "dx": 2.1, "dy": 14.7, "scale_mult": 0.71, "hard": False},
            {"kind": "cave_gravel", "dx": 3.4, "dy": 15.5, "scale_mult": 0.61, "hard": False},
            {"kind": "cave_gravel", "dx": 2.5, "dy": 14.5, "scale_mult": 0.94, "hard": False},
            {"kind": "twig_scatter", "dx": 1.3, "dy": 9.8, "scale_mult": 0.83, "hard": False},
            {"kind": "moss_patch", "dx": 5.3, "dy": 12.1, "scale_mult": 0.61, "hard": False},
            {"kind": "rubble", "dx": 3.5, "dy": 15.8, "scale_mult": 0.89, "hard": False},
            {"kind": "rubble", "dx": 4.5, "dy": 15.6, "scale_mult": 0.83, "hard": False},
            {"kind": "cave_gravel", "dx": 4.2, "dy": 15.3, "scale_mult": 0.75, "hard": False},
            {"kind": "cave_gravel", "dx": 4.0, "dy": 16.4, "scale_mult": 0.8, "hard": False},
            {"kind": "rubble", "dx": 4.3, "dy": 15.9, "scale_mult": 0.87, "hard": False},
            {"kind": "cave_gravel", "dx": 9.0, "dy": 16.5, "scale_mult": 0.95, "hard": False},
            {"kind": "rubble", "dx": -1.6, "dy": 12.3, "scale_mult": 0.79, "hard": False},
            {"kind": "rubble", "dx": -2.0, "dy": 12.8, "scale_mult": 0.73, "hard": False},
            {"kind": "cave_gravel", "dx": -1.3, "dy": 12.7, "scale_mult": 0.65, "hard": False},
            {"kind": "cave_gravel", "dx": -2.5, "dy": 12.4, "scale_mult": 0.96, "hard": False},
            {"kind": "rubble", "dx": 2.5, "dy": 9.9, "scale_mult": 0.58, "hard": False},
            {"kind": "rubble", "dx": -3.0, "dy": 12.1, "scale_mult": 0.66, "hard": False},
            {"kind": "rubble", "dx": -3.6, "dy": 12.1, "scale_mult": 0.76, "hard": False},
            {"kind": "cave_gravel", "dx": -3.0, "dy": 11.0, "scale_mult": 0.87, "hard": False},
            {"kind": "cave_gravel", "dx": -2.6, "dy": 11.6, "scale_mult": 0.95, "hard": False},
            {"kind": "rubble", "dx": -3.7, "dy": 12.0, "scale_mult": 0.77, "hard": False},
            {"kind": "twig_scatter", "dx": -0.8, "dy": 15.5, "scale_mult": 0.77, "hard": False},
            {"kind": "moss_patch", "dx": -0.7, "dy": 14.4, "scale_mult": 0.66, "hard": False},
            {"kind": "bone_pile", "dx": 7.5, "dy": 13.8, "scale_mult": 0.61, "hard": False},
            {"kind": "filament", "dx": -2.6, "dy": 13.8, "scale_mult": 0.92, "hard": False},
            {"kind": "filament", "dx": -3.5, "dy": 15.1, "scale_mult": 0.63, "hard": False},
            {"kind": "filament", "dx": -3.3, "dy": 12.9, "scale_mult": 0.66, "hard": False},
            {"kind": "ceiling_moss", "dx": 0.4, "dy": 13.8, "scale_mult": 0.87, "hard": False},
            {"kind": "ceiling_moss", "dx": 1.9, "dy": 14.0, "scale_mult": 0.85, "hard": False},
            {"kind": "ceiling_moss", "dx": 1.4, "dy": 12.3, "scale_mult": 0.88, "hard": False},
            {"kind": "ceiling_moss", "dx": 2.3, "dy": 12.4, "scale_mult": 0.86, "hard": False},
            {"kind": "ceiling_moss", "dx": 0.2, "dy": 17.8, "scale_mult": 0.86, "hard": False},
            {"kind": "ceiling_moss", "dx": -1.5, "dy": 10.9, "scale_mult": 0.65, "hard": False},
            {"kind": "stalagmite", "dx": 18.6, "dy": 0.5, "scale_mult": 0.8, "hard": True},
            {"kind": "rubble", "dx": 18.4, "dy": 0.1, "scale_mult": 0.83, "hard": False},
            {"kind": "rubble", "dx": 18.1, "dy": 0.6, "scale_mult": 0.64, "hard": False},
            {"kind": "stalagmite", "dx": -6.8, "dy": -13.6, "scale_mult": 0.7, "hard": True},
            {"kind": "rubble", "dx": -5.9, "dy": -13.9, "scale_mult": 0.83, "hard": False},
            {"kind": "rubble", "dx": -6.3, "dy": -12.8, "scale_mult": 0.62, "hard": False},
            {"kind": "stalagmite", "dx": 11.7, "dy": 14.2, "scale_mult": 0.9, "hard": True},
            {"kind": "rubble", "dx": 12.1, "dy": 13.9, "scale_mult": 0.94, "hard": False},
            {"kind": "rubble", "dx": 12.4, "dy": 14.9, "scale_mult": 0.95, "hard": False},
            {"kind": "cave_gravel", "dx": 10.8, "dy": 14.2, "scale_mult": 0.72, "hard": False},
            {"kind": "stalagmite", "dx": 0.9, "dy": -7.1, "scale_mult": 0.88, "hard": True},
            {"kind": "rubble", "dx": 0.9, "dy": -7.4, "scale_mult": 0.68, "hard": False},
            {"kind": "rubble", "dx": 0.3, "dy": -7.4, "scale_mult": 0.84, "hard": False},
            {"kind": "grass_tuft", "dx": -1.4, "dy": 13.2, "scale_mult": 0.77, "hard": False},
            {"kind": "grass_tuft", "dx": 10.6, "dy": 6.3, "scale_mult": 0.7, "hard": False},
            {"kind": "rubble", "dx": 7.5, "dy": -18.2, "scale_mult": 0.65, "hard": False},
            {"kind": "cave_gravel", "dx": -13.9, "dy": 12.3, "scale_mult": 0.76, "hard": False},
        ],
    },
]


# -- Origin hub (authored, fixed) ---------------------------------------------
#
# The starting location. NOT in CAVERN_STAMPS — this stamp is placed
# deterministically at slot (0, 0) by stamp_world.stamp_at(), bypassing the
# weighted selection. World coordinates are centered on (0, 0), not the
# slot center — the hub is the literal origin of the cavern.
#
# Composition philosophy:
#   - Axis mundi at center: the tallest landmark, visible from everywhere
#     inside the hub, readable from outside the hub as "that's where I
#     started." Primitive = mega_column.
#   - Four cardinal arches at distance ~12m — N/E/S/W — each built from
#     DIFFERENT vocabulary so the player learns the language by walking
#     through all four. The gateway grammar:
#       N arch: doorframe (lintel+runes) flanked by two mega_columns
#       E arch: column + two buttresses (the structural brother pair)
#       S arch: doorframe flanked by two monoliths (ancient gate feel)
#       W arch: column pair + mega_column backer (wide threshold)
#   - Four provision quadrants between arches, each with a lore role:
#       NE — toadstool grove        (food / warmth / ringed ritual site)
#       SE — spore_pod + giant_fungus  (forage / fungal partnership)
#       SW — bone_pile + crystal     (relic light / memento mori)
#       NW — boulder alcove + crystal (shelter / stone cache / beacon)
#   - Walkable floor: moss_patch + grass_tuft + cave_gravel filling the
#     inner ring, nothing >0.3m tall inside the central ~8m walking area.
#   - Perimeter stalagmites between the arches, acting as visual walls.
#     Breaks the silhouette so the hub reads as enclosed but not solid.
#
# This hub is the first authored spatial frame in the game. Every piece
# is a composition of existing kinds — no new meshes, no new shaders.
# It proves the stack can absorb an authored starting moment without
# touching any of the render pipeline.
#
# Spawn position (main.gd): player should emerge through the SOUTH arch
# at world (0, -14), facing +y (north), so the walk into the hub is
# through the authored gateway, not a teleport into the center.

ORIGIN_HUB = {
    "name": "origin_hub",
    "footprint": 30.0,
    "members": [
        # --- AXIS MUNDI (tallest landmark, visible from every cardinal) ---
        {"kind": "mega_column", "dx":  0.0, "dy":  0.0, "scale_mult": 1.25, "hard": True},

        # --- N ARCH (doorframe with mega_column flankers) ---
        # Flankers at dx=±5.5 so player can pass between them. With new
        # visual_radius (mega_column=4.5 × scale_mult=0.65 × sv_mean=1.3 ≈ 3.8m
        # hull), the old ±3.2m spacing was blocked once collision matched
        # visual silhouette. 5.5m centerline distance gives ~1m walking gap.
        {"kind": "doorframe",   "dx":  0.0, "dy": 12.0, "scale_mult": 1.15, "hard": True},
        {"kind": "mega_column", "dx": -5.5, "dy": 12.5, "scale_mult": 0.65, "hard": True},
        {"kind": "mega_column", "dx":  5.5, "dy": 12.5, "scale_mult": 0.65, "hard": True},

        # --- E ARCH (column + buttress pair) ---
        {"kind": "column",      "dx": 12.0, "dy":  0.0, "scale_mult": 1.05, "hard": True},
        {"kind": "buttress",    "dx": 12.5, "dy":  3.0, "scale_mult": 0.90, "hard": True},
        {"kind": "buttress",    "dx": 12.5, "dy": -3.0, "scale_mult": 0.90, "hard": True},

        # --- S ARCH (doorframe flanked by monoliths — ancient gate) ---
        {"kind": "doorframe",   "dx":  0.0, "dy":-12.0, "scale_mult": 1.05, "hard": True},
        {"kind": "monolith",    "dx": -3.2, "dy":-12.5, "scale_mult": 1.00, "hard": True},
        {"kind": "monolith",    "dx":  3.2, "dy":-12.5, "scale_mult": 1.00, "hard": True},

        # --- W ARCH (column pair + mega_column backer) ---
        {"kind": "column",      "dx":-12.0, "dy":  2.0, "scale_mult": 1.00, "hard": True},
        {"kind": "column",      "dx":-12.0, "dy": -2.0, "scale_mult": 1.00, "hard": True},
        {"kind": "mega_column", "dx":-14.0, "dy":  0.0, "scale_mult": 0.55, "hard": True},

        # --- NE QUADRANT — toadstool grove (food / warmth) ---
        {"kind": "toadstool",   "dx":  5.5, "dy":  5.5, "scale_mult": 1.00, "hard": False},
        {"kind": "toadstool",   "dx":  7.0, "dy":  4.0, "scale_mult": 0.80, "hard": False},
        {"kind": "toadstool",   "dx":  4.5, "dy":  7.0, "scale_mult": 0.90, "hard": False},
        {"kind": "toadstool",   "dx":  6.5, "dy":  6.5, "scale_mult": 0.75, "hard": False},
        {"kind": "moss_patch",  "dx":  5.5, "dy":  5.5, "scale_mult": None, "hard": False},

        # --- SE QUADRANT — spore_pod cluster + giant_fungus partner ---
        {"kind": "giant_fungus","dx":  7.0, "dy": -6.5, "scale_mult": 0.75, "hard": True},
        {"kind": "spore_pod",   "dx":  5.0, "dy": -5.0, "scale_mult": 1.10, "hard": False},
        {"kind": "spore_pod",   "dx":  6.5, "dy": -3.8, "scale_mult": 0.90, "hard": False},
        {"kind": "spore_pod",   "dx":  4.0, "dy": -6.8, "scale_mult": 0.85, "hard": False},
        {"kind": "moss_patch",  "dx":  5.0, "dy": -5.0, "scale_mult": None, "hard": False},

        # --- SW QUADRANT — bone relic + crystal witness light ---
        {"kind": "bone_pile",   "dx": -5.0, "dy": -5.0, "scale_mult": 1.25, "hard": False},
        {"kind": "rubble",      "dx": -6.5, "dy": -4.0, "scale_mult": None, "hard": False},
        {"kind": "rubble",      "dx": -4.0, "dy": -6.5, "scale_mult": None, "hard": False},
        {"kind": "crystal_cluster", "dx": -7.0, "dy": -3.0, "scale_mult": 0.60, "hard": True},
        {"kind": "moss_patch",  "dx": -5.0, "dy": -5.0, "scale_mult": None, "hard": False},

        # --- NW QUADRANT — boulder alcove + crystal beacon ---
        {"kind": "boulder",     "dx": -5.0, "dy":  5.0, "scale_mult": 1.20, "hard": True},
        {"kind": "boulder",     "dx": -7.0, "dy":  4.0, "scale_mult": 0.90, "hard": True},
        {"kind": "rubble",      "dx": -5.5, "dy":  6.5, "scale_mult": None, "hard": False},
        {"kind": "crystal_cluster", "dx": -4.0, "dy":  7.5, "scale_mult": 0.80, "hard": True},
        {"kind": "moss_patch",  "dx": -5.0, "dy":  5.0, "scale_mult": None, "hard": False},

        # --- CENTRAL BEACON RING (secondary light near axis mundi) ---
        {"kind": "crystal_cluster", "dx":  2.0, "dy":  2.0, "scale_mult": 0.55, "hard": True},
        {"kind": "firefly",     "dx":  0.5, "dy":  0.5, "scale_mult": None, "hard": False},
        {"kind": "firefly",     "dx": -0.5, "dy":  1.0, "scale_mult": None, "hard": False},
        {"kind": "firefly",     "dx":  1.0, "dy": -0.5, "scale_mult": None, "hard": False},

        # --- WALKABLE FLOOR TISSUE (inner 8m ring) ---
        {"kind": "moss_patch",  "dx":  0.0, "dy":  3.5, "scale_mult": None, "hard": False},
        {"kind": "moss_patch",  "dx":  3.5, "dy":  0.0, "scale_mult": None, "hard": False},
        {"kind": "moss_patch",  "dx":  0.0, "dy": -3.5, "scale_mult": None, "hard": False},
        {"kind": "moss_patch",  "dx": -3.5, "dy":  0.0, "scale_mult": None, "hard": False},
        {"kind": "grass_tuft",  "dx":  2.0, "dy":  2.5, "scale_mult": None, "hard": False},
        {"kind": "grass_tuft",  "dx": -2.5, "dy":  1.5, "scale_mult": None, "hard": False},
        {"kind": "grass_tuft",  "dx":  2.5, "dy": -2.0, "scale_mult": None, "hard": False},
        {"kind": "grass_tuft",  "dx": -1.8, "dy": -3.0, "scale_mult": None, "hard": False},
        {"kind": "cave_gravel", "dx":  1.5, "dy":  0.0, "scale_mult": None, "hard": False},
        {"kind": "cave_gravel", "dx":  0.0, "dy":  1.5, "scale_mult": None, "hard": False},
        {"kind": "cave_gravel", "dx": -1.5, "dy":  0.0, "scale_mult": None, "hard": False},
        {"kind": "cave_gravel", "dx":  0.0, "dy": -1.5, "scale_mult": None, "hard": False},

        # --- PERIMETER WALL STALAGMITES (between arches — visual enclosure) ---
        # NE corner
        {"kind": "stalagmite",  "dx":  9.0, "dy":  7.5, "scale_mult": 0.85, "hard": True},
        {"kind": "stalagmite",  "dx":  7.5, "dy":  9.0, "scale_mult": 0.90, "hard": True},
        # SE corner
        {"kind": "stalagmite",  "dx":  9.0, "dy": -7.5, "scale_mult": 0.85, "hard": True},
        {"kind": "stalagmite",  "dx":  7.5, "dy": -9.0, "scale_mult": 0.90, "hard": True},
        # SW corner
        {"kind": "stalagmite",  "dx": -9.0, "dy": -7.5, "scale_mult": 0.85, "hard": True},
        {"kind": "stalagmite",  "dx": -7.5, "dy": -9.0, "scale_mult": 0.90, "hard": True},
        # NW corner
        {"kind": "stalagmite",  "dx": -9.0, "dy":  7.5, "scale_mult": 0.85, "hard": True},
        {"kind": "stalagmite",  "dx": -7.5, "dy":  9.0, "scale_mult": 0.90, "hard": True},

        # --- CREATURES — atom-cluster ghost sprites at the hub ----------
        # Guaranteed visible at spawn. Rats near the bone pile (SW),
        # clay pot near the toadstool grove (NE), chest near the axis.
        {"kind": "rat",          "dx": -4.0, "dy": -3.5, "scale_mult": None, "hard": False},
        {"kind": "rat",          "dx": -5.5, "dy": -3.0, "scale_mult": None, "hard": False},
        {"kind": "rat_ice",      "dx": -3.0, "dy": -6.0, "scale_mult": None, "hard": False},
        {"kind": "clay_pot",     "dx":  6.0, "dy":  3.5, "scale_mult": None, "hard": False},
        {"kind": "clay_pot",     "dx":  4.0, "dy":  8.0, "scale_mult": None, "hard": False},
        {"kind": "treasure_chest","dx":  2.5, "dy":  1.0, "scale_mult": None, "hard": False},
    ],
}


# Second authored anchor — a clear cavern pocket reserved for encounter
# iteration. Minimal ground clutter so bat flight paths read clean,
# four mega_columns as vertical markers to fly between, no tissue/
# scatter/tension props. Reached by walking through the N arch from
# the hub. Occupies slot (0, 2) — 60m north of origin.
ENCOUNTER_TEST = {
    "name": "encounter_test",
    "footprint": 30.0,
    "members": [
        # --- FOUR CARDINAL COLUMNS (ceiling markers, bat flight posts) ---
        {"kind": "mega_column", "dx":  10.0, "dy":  10.0, "scale_mult": 0.75, "hard": True},
        {"kind": "mega_column", "dx": -10.0, "dy":  10.0, "scale_mult": 0.75, "hard": True},
        {"kind": "mega_column", "dx":  10.0, "dy": -10.0, "scale_mult": 0.75, "hard": True},
        {"kind": "mega_column", "dx": -10.0, "dy": -10.0, "scale_mult": 0.75, "hard": True},

        # --- CENTER BEACON (visual anchor for navigation) ---
        {"kind": "crystal_cluster", "dx":  0.0, "dy":  0.0, "scale_mult": 0.8, "hard": True},
        {"kind": "firefly",    "dx":  0.0, "dy":  0.0, "scale_mult": None, "hard": False},

        # --- BAT FLOCK (~6 bats — enough to read as activity, sparse
        # enough to follow individuals) ---
        {"kind": "bat", "dx":  0.0, "dy":  0.0, "scale_mult": None, "hard": False},
        {"kind": "bat", "dx":  4.0, "dy":  2.0, "scale_mult": None, "hard": False},
        {"kind": "bat", "dx": -4.0, "dy":  3.0, "scale_mult": None, "hard": False},
        {"kind": "bat", "dx":  2.0, "dy": -4.0, "scale_mult": None, "hard": False},
        {"kind": "bat", "dx": -3.0, "dy": -2.0, "scale_mult": None, "hard": False},
        {"kind": "bat", "dx":  5.0, "dy":  0.0, "scale_mult": None, "hard": False},
    ],
}


# Shadow lab — third authored anchor. Exists purely to iterate the
# decal_projector primitive. Single orb at center = simplest possible
# fixture. Grid variations come in step 6 (task #6) once the single-spot
# case reads. Occupies slot (-2, 0) — 32m west of origin. Reserved in
# stamp_world.py so procedural selection doesn't overwrite it.
SHADOW_LAB = {
    "name": "shadow_lab",
    "footprint": 30.0,
    "members": [
        {"kind": "shadow_orb", "dx": 0.0, "dy": 0.0,
         "scale_mult": None, "hard": False},
    ],
}


OUTDOOR_STAMPS = [
    # Fern clearing — open circle, green mound, dappled light feeling
    {
        "name": "fern_clearing",
        "footprint": 6.0,
        "members": [
            {"kind": "boulder", "dx": 0.0, "dy": 0.0, "scale_mult": 0.9, "hard": True},
            {"kind": "moss_patch", "dx": -2.0, "dy": 1.5, "scale_mult": None, "hard": False},
            {"kind": "moss_patch", "dx": 2.2, "dy": 1.0, "scale_mult": None, "hard": False},
            {"kind": "moss_patch", "dx": 0.0, "dy": -2.5, "scale_mult": None, "hard": False},
            {"kind": "grass_tuft", "dx": -1.5, "dy": -1.0, "scale_mult": None, "hard": False},
            {"kind": "grass_tuft", "dx": 1.8, "dy": -0.8, "scale_mult": None, "hard": False},
            {"kind": "firefly", "dx": 0.5, "dy": 2.0, "scale_mult": None, "hard": False},
            {"kind": "firefly", "dx": -0.8, "dy": 0.3, "scale_mult": None, "hard": False},
        ],
    },
    # Fallen tree — horizontal log with ecosystem growing on it
    {
        "name": "fallen_tree",
        "footprint": 5.0,
        "members": [
            {"kind": "dead_log", "dx": 0.0, "dy": 0.0, "scale_mult": 1.2, "hard": True},
            {"kind": "moss_patch", "dx": 0.5, "dy": 0.3, "scale_mult": 0.8, "hard": False},
            {"kind": "leaf_pile", "dx": -2.0, "dy": 1.0, "scale_mult": None, "hard": False},
            {"kind": "leaf_pile", "dx": 1.8, "dy": -1.2, "scale_mult": None, "hard": False},
            {"kind": "grass_tuft", "dx": -1.0, "dy": -1.5, "scale_mult": None, "hard": False},
            {"kind": "grass_tuft", "dx": 2.0, "dy": 1.5, "scale_mult": None, "hard": False},
            {"kind": "twig_scatter", "dx": -1.5, "dy": 0.5, "scale_mult": None, "hard": False},
        ],
    },
    # Rocky outcrop — exposed geology, stumps and stones
    {
        "name": "rocky_outcrop",
        "footprint": 7.0,
        "members": [
            {"kind": "boulder", "dx": -2.0, "dy": 0.0, "scale_mult": 1.0, "hard": True},
            {"kind": "boulder", "dx": 2.5, "dy": 1.0, "scale_mult": 0.7, "hard": True},
            {"kind": "stalagmite", "dx": 0.0, "dy": -2.5, "scale_mult": None, "hard": True},
            {"kind": "rubble", "dx": -0.5, "dy": 1.5, "scale_mult": None, "hard": False},
            {"kind": "rubble", "dx": 1.0, "dy": -1.0, "scale_mult": None, "hard": False},
            {"kind": "cave_gravel", "dx": 0.0, "dy": 0.5, "scale_mult": None, "hard": False},
        ],
    },
]


# -- Stamp affinity (tile variant → preferred stamp names) ---------------------
#
# When a tile variant has affinity, stamps matching preferred names are 3x
# more likely to be selected via weighted RosterPool pick. Stamps not in the
# affinity list still appear — just less often. "standard" has no affinity
# (all stamps equal).

# -- Anchor stamps (programmatic compositions around structural anchors) -------
#
# Instead of authored fixed-member stamps, each structural anchor type declares
# SLOTS that fill from pools. The anchor itself is the spine — placed first by
# the normal honeycomb roll — then slots radiate around it.
#
# Variety = pool_picks × count_range × angle × rotation × scale_range.
# 3 base templates × combinatorial slot fills = hundreds of unique compositions.
#
# Slot fields:
#   role     — semantic label (flank, ground, accent) for readability
#   count    — [min, max] members to place in this slot
#   pool     — list of kind names to pick from (uniform random)
#   dist     — [min, max] distance from anchor center (meters)
#   scale    — [min, max] scale_mult or null (no override)
#   hard     — whether placed members need collision reservation

CAVERN_ANCHOR_STAMPS = {
    "mega_column": {
        "frequency": 0.60,  # 60% of mega_columns get a stamp
        "slots": [
            {"role": "flank", "count": [1, 2],
             "pool": ["stalagmite", "boulder"],
             "dist": [3.0, 5.0], "scale": [0.7, 1.0], "hard": True},
            {"role": "ground", "count": [2, 4],
             "pool": ["moss_patch", "rubble", "cave_gravel", "grass_tuft"],
             "dist": [1.5, 3.5], "scale": None, "hard": False},
            {"role": "accent", "count": [0, 1],
             "pool": ["crystal_cluster", "filament"],
             "dist": [2.5, 4.0], "scale": [0.6, 0.8], "hard": True},
        ],
    },
    "column": {
        "frequency": 0.50,
        "slots": [
            {"role": "flank", "count": [0, 2],
             "pool": ["stalagmite"],
             "dist": [2.0, 3.5], "scale": [0.7, 0.9], "hard": True},
            {"role": "ground", "count": [1, 3],
             "pool": ["moss_patch", "rubble", "cave_gravel"],
             "dist": [1.0, 2.5], "scale": None, "hard": False},
            {"role": "accent", "count": [0, 1],
             "pool": ["moss_patch", "giant_fungus"],
             "dist": [2.0, 3.0], "scale": [0.5, 0.7], "hard": False},
        ],
    },
    "boulder": {
        "frequency": 0.45,
        "slots": [
            {"role": "flank", "count": [0, 1],
             "pool": ["stalagmite", "rubble"],
             "dist": [2.0, 3.5], "scale": [0.7, 1.0], "hard": True},
            {"role": "ground", "count": [2, 4],
             "pool": ["cave_gravel", "rubble", "twig_scatter", "grass_tuft"],
             "dist": [1.0, 3.0], "scale": None, "hard": False},
            {"role": "accent", "count": [0, 1],
             "pool": ["moss_patch"],
             "dist": [1.5, 2.5], "scale": None, "hard": False},
        ],
    },
    "stalagmite": {
        "frequency": 0.35,
        "slots": [
            {"role": "ground", "count": [1, 2],
             "pool": ["cave_gravel", "rubble"],
             "dist": [0.8, 2.0], "scale": None, "hard": False},
            {"role": "accent", "count": [0, 1],
             "pool": ["moss_patch", "grass_tuft"],
             "dist": [1.0, 2.0], "scale": None, "hard": False},
        ],
    },
    "crystal_cluster": {
        "frequency": 0.55,
        "slots": [
            {"role": "flank", "count": [0, 2],
             "pool": ["stalagmite"],
             "dist": [2.0, 3.5], "scale": [0.6, 0.8], "hard": True},
            {"role": "ground", "count": [1, 3],
             "pool": ["cave_gravel", "rubble", "moss_patch"],
             "dist": [1.0, 2.5], "scale": None, "hard": False},
        ],
    },
    "giant_fungus": {
        "frequency": 0.50,
        "slots": [
            {"role": "ground", "count": [2, 3],
             "pool": ["moss_patch", "grass_tuft", "cave_gravel"],
             "dist": [1.0, 2.5], "scale": None, "hard": False},
            {"role": "accent", "count": [0, 1],
             "pool": ["filament", "firefly"],
             "dist": [1.5, 3.0], "scale": None, "hard": False},
        ],
    },
}

OUTDOOR_ANCHOR_STAMPS = {
    "mega_column": {
        "frequency": 0.55,
        "slots": [
            {"role": "ground", "count": [2, 4],
             "pool": ["moss_patch", "grass_tuft", "leaf_pile"],
             "dist": [2.0, 4.0], "scale": None, "hard": False},
            {"role": "accent", "count": [0, 1],
             "pool": ["dead_log", "boulder"],
             "dist": [3.0, 5.0], "scale": [0.6, 0.8], "hard": True},
        ],
    },
    "column": {
        "frequency": 0.45,
        "slots": [
            {"role": "ground", "count": [1, 3],
             "pool": ["grass_tuft", "moss_patch", "leaf_pile"],
             "dist": [1.5, 3.0], "scale": None, "hard": False},
        ],
    },
    "boulder": {
        "frequency": 0.50,
        "slots": [
            {"role": "ground", "count": [2, 3],
             "pool": ["moss_patch", "grass_tuft", "rubble"],
             "dist": [1.5, 3.0], "scale": None, "hard": False},
            {"role": "accent", "count": [0, 1],
             "pool": ["firefly"],
             "dist": [1.0, 2.0], "scale": None, "hard": False},
        ],
    },
}


CAVERN_STAMP_AFFINITY = {
    "crystal_grove":  ["crystal_grotto", "pillar_alcove", "filament_grove"],
    "fungus_forest":  ["fungus_hollow", "spore_cluster"],
    "bone_field":     ["bone_shrine", "rubble_field"],
    "wet_zone":       ["fungus_hollow", "crystal_grotto", "spore_cluster"],
}

OUTDOOR_STAMP_AFFINITY = {
    "clearing":       ["fern_clearing"],
    "dense_canopy":   ["fallen_tree"],
    "fern_hollow":    ["fern_clearing", "rocky_outcrop"],
    "rocky_outcrop":  ["rocky_outcrop"],
    "stream_bed":     ["fern_clearing"],
}


# -- Spectrum profiles (hue drift configs) -------------------------------------

SPECTRUM_PROFILES = {
    "fungus": {
        "base_hue": (0.22, 0.06, 0.30),
        "drift_range": 0.18,
        "channels": [
            {"freq": 0.017, "amp": 1.0},
            {"freq": 0.011, "amp": 0.6},
            {"freq": 0.007, "amp": 0.3},
        ],
    },
    "crystal": {
        "base_hue": (0.10, 0.12, 0.35),
        "drift_range": 0.15,
        "channels": [
            {"freq": 0.013, "amp": 1.0},
            {"freq": 0.023, "amp": 0.5},
        ],
        "prismatic": True,
        "facet_spread": 0.10,
    },
    "moss": {
        "base_hue": (0.05, 0.18, 0.03),
        "drift_range": 0.06,
        "channels": [
            {"freq": 0.005, "amp": 1.0},
        ],
    },
}

OUTDOOR_SPECTRUM_PROFILES = {
    "fungus": {
        "base_hue": (0.12, 0.28, 0.08),
        "drift_range": 0.08,
        "channels": [
            {"freq": 0.008, "amp": 1.0},
            {"freq": 0.005, "amp": 0.4},
        ],
    },
    "crystal": {
        "base_hue": (0.35, 0.20, 0.12),
        "drift_range": 0.10,
        "channels": [
            {"freq": 0.010, "amp": 1.0},
            {"freq": 0.006, "amp": 0.5},
        ],
        "prismatic": True,
        "facet_spread": 0.08,
    },
    "moss": {
        "base_hue": (0.06, 0.22, 0.04),
        "drift_range": 0.05,
        "channels": [
            {"freq": 0.004, "amp": 1.0},
        ],
    },
    "sunlight": {
        "base_hue": (0.45, 0.38, 0.15),
        "drift_range": 0.12,
        "channels": [
            {"freq": 0.015, "amp": 1.0},
            {"freq": 0.009, "amp": 0.6},
            {"freq": 0.004, "amp": 0.3},
        ],
    },
}


# -- Mote presets (particle configs) -------------------------------------------

MOTE_PRESETS = {
    "ceiling_moss": {
        "color": (0.8, 0.55, 0.15), "count": 12, "radius": 3.0, "height": 18.0,
        "downward": True, "fall_speed": 0.015,
        "sway_amp": 0.10, "sway_freq": 0.05,
        "float_compression": 0.4,
    },
    "giant_fungus": {
        "color": (0.25, 0.08, 0.35), "count": 8, "radius": 3.0, "height": 4.0,
        "downward": False, "fall_speed": 0.005,
        "sway_amp": 0.25, "sway_freq": 0.10,
        "float_compression": 0.2,
    },
    "moss_patch": {
        "color": (0.1, 0.5, 0.08), "count": 3, "radius": 1.5, "height": 1.0,
        "downward": False, "fall_speed": 0.0,
        "sway_amp": 0.10, "sway_freq": 0.06,
        "float_compression": 0.1,
        "ground_bias": True,
    },
    "crystal_cluster": {
        "color": (0.3, 0.35, 0.6), "count": 10, "radius": 3.0, "height": 3.0,
        "downward": False, "fall_speed": 0.003,
        "sway_amp": 0.12, "sway_freq": 0.08,
        "float_compression": 0.15,
    },
}

OUTDOOR_MOTE_PRESETS = {
    "giant_fungus": {
        "color": (0.35, 0.30, 0.12), "count": 6, "radius": 3.0, "height": 3.0,
        "downward": False, "fall_speed": 0.008,
        "sway_amp": 0.30, "sway_freq": 0.06,
        "float_compression": 0.3,
    },
    "moss_patch": {
        "color": (0.25, 0.20, 0.10), "count": 3, "radius": 1.5, "height": 0.8,
        "downward": False, "fall_speed": 0.0,
        "sway_amp": 0.08, "sway_freq": 0.04,
        "float_compression": 0.1,
        "ground_bias": True,
    },
    "crystal_cluster": {
        "color": (0.40, 0.30, 0.15), "count": 5, "radius": 2.0, "height": 2.0,
        "downward": True, "fall_speed": 0.010,
        "sway_amp": 0.20, "sway_freq": 0.08,
        "float_compression": 0.25,
    },
}


# -- Light layers (glow shell + decal configs) ---------------------------------

LIGHT_LAYERS = {
    "moss": {
        "material": "dry_organic",
        "shell_scale": 1.03,
        "shell_roughness": (0.40, 0.60),
        "decal_radius_mult": 1.5,
        "decal_surface": "wet_stone",
        "inner_darken": (0.45, 0.42, 0.40),
        "hues": [
            {"color": (0.08, 0.35, 0.06), "glow": (2.0, 5.0, 1.5), "decal": (0.15, 0.75, 0.12)},
            {"color": (0.35, 0.20, 0.05), "glow": (4.0, 2.5, 0.8), "decal": (1.5, 0.9, 0.22)},
            {"color": (0.06, 0.10, 0.35), "glow": (1.5, 2.0, 5.0), "decal": (0.12, 0.22, 0.75)},
            {"color": (0.25, 0.06, 0.30), "glow": (3.5, 1.0, 4.0), "decal": (0.75, 0.15, 0.9)},
        ],
        "motes": {
            "count": 6, "radius": 2.0, "height": 1.5,
            "downward": False, "fall_speed": 0.0,
            "sway_amp": 0.15, "sway_freq": 0.12,
            "float_compression": 0.2,
        },
    },
    "crystal": {
        "material": "stone_light",
        "shell_scale": 1.05,
        "decal_radius_mult": 4.0,
        "decal_surface": "smooth",
        "inner_darken": (0.40, 0.40, 0.45),
        "additive_patches": True,
        "double_decal": True,
        "hues": [
            {"color": (0.15, 0.18, 0.35), "glow": (3.0, 3.5, 6.0), "decal": (0.6, 0.75, 1.8)},
            {"color": (0.18, 0.08, 0.30), "glow": (3.0, 1.2, 4.5), "decal": (0.75, 0.27, 1.2)},
        ],
        "motes": {
            "count": 10, "radius": 3.0, "height": 3.0,
            "downward": False, "fall_speed": 0.003,
            "sway_amp": 0.12, "sway_freq": 0.08,
            "float_compression": 0.15,
        },
    },
    "torch": {
        "material": "dry_organic",
        "shell_scale": 1.08,
        "decal_radius_mult": 2.0,
        "decal_surface": "smooth",
        "inner_darken": (0.50, 0.45, 0.40),
        "hues": [
            {"color": (0.40, 0.25, 0.05), "glow": (5.0, 3.0, 0.8), "decal": (1.2, 0.7, 0.15)},
            {"color": (0.35, 0.30, 0.08), "glow": (4.5, 3.5, 1.0), "decal": (1.0, 0.8, 0.20)},
        ],
        "motes": {
            "count": 8, "radius": 1.0, "height": 2.5,
            "downward": False, "fall_speed": 0.008,
            "sway_amp": 0.20, "sway_freq": 0.15,
            "float_compression": 0.5,
            "ground_bias": True,
        },
    },
}

OUTDOOR_LIGHT_LAYERS = {
    "sunlight": {
        "material": "dry_organic",
        "shell_scale": 1.02,
        "shell_roughness": (0.20, 0.40),
        "decal_radius_mult": 3.0,
        "decal_surface": "smooth",
        "inner_darken": (0.55, 0.50, 0.45),
        "hues": [
            {"color": (0.45, 0.38, 0.15), "glow": (3.0, 2.5, 1.0), "decal": (1.0, 0.85, 0.35)},
            {"color": (0.40, 0.35, 0.12), "glow": (2.5, 2.0, 0.8), "decal": (0.90, 0.75, 0.30)},
        ],
        "motes": {
            "count": 6, "radius": 2.5, "height": 4.0,
            "downward": True, "fall_speed": 0.006,
            "sway_amp": 0.18, "sway_freq": 0.10,
            "float_compression": 0.3,
        },
    },
}


# -- Light affinity (which objects get which light layers) ---------------------

LIGHT_AFFINITY = {
    "Cavern_Default": {
        "boulder":    {"moss": 0.35, "crystal": 0.05},
        "dead_log":   {"moss": 0.25},
        "stalagmite": {"crystal": 0.15, "moss": 0.10},
        "column":     {"moss": 0.08},
        "rubble":     {"moss": 0.05},
        "bone_pile":  {"moss": 0.03},
    },
    "Outdoor_Forest": {
        "boulder":    {"sunlight": 0.30, "moss": 0.20},
        "column":     {"sunlight": 0.15, "moss": 0.12},
        "mega_column": {"sunlight": 0.10, "moss": 0.15},
        "dead_log":   {"moss": 0.40, "sunlight": 0.10},
        "stalagmite": {"sunlight": 0.12, "moss": 0.08},
        "moss_patch": {"sunlight": 0.25},
        "rubble":     {"moss": 0.10},
    },
}


# -- Render dome height per biome ----------------------------------------------

DOME_HEIGHT = {
    "cavern": 45.0,   # raised from 30 → ceiling feels vast, hangs decoration at 14-18m
    "outdoor": 55.0,  # raised from 45 → sky reads as open, not lid
}


# -- World grain ---------------------------------------------------------------

WORLD_GRAIN = 0.10

MATERIAL_RATIOS = {
    "stone_heavy":  0.80,
    "stone_light":  1.00,
    "dry_organic":  1.20,
    "bone":         0.90,
}

STONE_MIN_HEIGHT_RATIO = 0.15
OVERLAP_FACTOR = 0.50


# -- Light states (fog/ambient per time-of-day) --------------------------------

OUTDOOR_LIGHT_STATES = {
    "day": {
        "ambient": (0.72, 0.65, 0.58),
        "fog_color": (0.22, 0.24, 0.28),
        "fog_near": 15.0,
        "fog_far": 55.0,
        "bg_color": (0.18, 0.22, 0.30),
        "far_clip": 60.0,
        "sun_color": (1.0, 0.90, 0.65),
        "sun_scale": 4.0,
        "moon_color": (0.0, 0.0, 0.0),
        "moon_scale": 0.0,
    },
    "dusk": {
        "ambient": (0.30, 0.22, 0.15),
        "fog_color": (0.20, 0.14, 0.10),
        "fog_near": 10.0,
        "fog_far": 40.0,
        "bg_color": (0.12, 0.08, 0.12),
        "far_clip": 50.0,
        "sun_color": (1.0, 0.55, 0.20),
        "sun_scale": 5.0,
        "moon_color": (0.0, 0.0, 0.0),
        "moon_scale": 0.0,
    },
    "night": {
        "ambient": (0.06, 0.07, 0.10),
        "fog_color": (0.03, 0.04, 0.06),
        "fog_near": 5.0,
        "fog_far": 25.0,
        "bg_color": (0.02, 0.03, 0.05),
        "far_clip": 35.0,
        "sun_color": (0.0, 0.0, 0.0),
        "sun_scale": 0.0,
        "moon_color": (0.60, 0.65, 0.80),
        "moon_scale": 3.0,
    },
}

CAVERN_LIGHT_STATES = {
    "cave": {
        "ambient": (0.10, 0.08, 0.06),          # near-black — darkness defines, light reveals
        "fog_color": (0.06, 0.05, 0.08),         # dark fog — silhouettes merge into mass
        "fog_near": 8.0,                          # fog starts closer — tight visibility cone
        "fog_far": 35.0,                          # shorter draw — darkness eats distance
        "bg_color": (0.02, 0.02, 0.04),           # deep void
        "far_clip": 52.0,
        "sun_color": (0.0, 0.0, 0.0),
        "sun_scale": 0.0,
        "moon_color": (0.0, 0.0, 0.0),
        "moon_scale": 0.0,
    },
    "daylight": {
        "ambient": (0.8, 0.75, 0.7),
        "fog_color": (0.12, 0.11, 0.18),
        "fog_near": 40.0,
        "fog_far": 120.0,
        "bg_color": (0.06, 0.05, 0.10),
        "far_clip": 130.0,
        "sun_color": (0.0, 0.0, 0.0),
        "sun_scale": 0.0,
        "moon_color": (0.0, 0.0, 0.0),
        "moon_scale": 0.0,
    },
}


# -- Plane-attachment architecture (Design Law #14, Phase 3) -------------------
#
# Each biome declares its own set of rendered planes. A plane is the data
# substrate a rendered primitive binds to — ground, ceiling, sky dome, interior
# wall, etc. The brain emits this list in the manifest; the Godot viewer
# instantiates a MeshInstance3D per entry. New planes are added purely by
# editing this config — no renderer code changes required.
#
# Fields:
#   tag            — unique identifier (used by kinds for attachment lookups)
#   kind           — semantic role (ground, ceiling, sky, wall, …)
#   normal         — plane normal in brain-space (z-up). [0,0,1]=up, [0,0,-1]=down
#   offset         — distance from world origin along world-Y (Godot convention)
#   layer          — Merkabah layer tag (near/mid/far/void) for future fade hooks
#   material       — shader parameters; renderer resolves by kind
#   size           — world-unit edge length of the plane quad
#   follow_camera  — if true, plane X/Z tracks camera so it's always under/over
#
# This list is the canonical answer to "where can things physically attach?"
# for each biome. The ceiling plane in cavern matches the former hardcoded
# CEILING_PLANE_Y=15 in main.gd; stalactites resolve their base_y from it.

BIOME_PLANES = {
    "cavern": [
        # Layer 1: Near-floor — warm hearth, the canvas everything reads against.
        # Clean surface — light pools are the detail, not the texture.
        {
            "tag": "ground_near",
            "kind": "ground",
            "normal": [0.0, 0.0, 1.0],
            "offset": 0.0,
            "layer": "near",
            "material": {
                "shader": "ground",
                "surface": "stone_rough",
                "color_base": [0.58, 0.55, 0.50],  # warm cream canvas — objects pop as silhouettes
                "grain_scale": 0.04,
                "grain_strength": 0.0,
                "normal_strength": 0.0,
                "roughness": 0.85,  # CLEAN ROOM — matte, no reflections
                # Large-scale tonal patches so iso view reads the floor as
                # a place, not a uniform wash. Grid size ≫ mark radius
                # produces rare blotches instead of stippled texture.
                "mark_grid_size": 7.0,
                "mark_chance": 0.35,
                "mark_strength": 0.22,
            },
            "size": 2000.0,
            "follow_camera": True,
        },
        # Layer 2: Near-ceiling — cool overhead, altitude and openness memory.
        # Blue-shifted from neutral: reads as sky-absence, cold stone above.
        {
            "tag": "ceiling_near",
            "kind": "ceiling",
            "normal": [0.0, 0.0, -1.0],
            "offset": 15.0,
            "layer": "near",
            "material": {
                "shader": "ground",
                "surface": "stone_weathered",
                "color_base": [0.12, 0.11, 0.09],  # cavern ceiling — deep overhead, warm not black
                "grain_scale": 0.06,
                "grain_strength": 0.0,
                "normal_strength": 0.0,
                "roughness": 0.85,
            },
            "size": 2000.0,
            "follow_camera": True,
        },
        # Wall planes removed — cavern is endless, entities (spikes/boulders)
        # are the only obstacles. The corridor-perspective feel comes from
        # fog + density falloff, not arbitrary planar boundaries.
    ],
    "outdoor": [
        {
            "tag": "ground_near",
            "kind": "ground",
            "normal": [0.0, 0.0, 1.0],
            "offset": 0.0,
            "layer": "near",
            "material": {
                "shader": "ground",
                "surface": "stone_rough",
                "color_base": [0.22, 0.20, 0.15],
                "grain_scale": 0.06,
                "grain_strength": 0.55,
                "normal_strength": 0.7,
            },
            "size": 2000.0,
            "follow_camera": True,
        },
        # No ceiling plane outdoors — sky is the dome. A future sky_dome plane
        # can be added here without touching any renderer code.
    ],
}


# -- Biome registry (unified lookup) ------------------------------------------

# -- Projection banner (7-layer cylindrical billboard) -------------------------
#
# 7 concentric rings at increasing distances, each projecting a layer of
# atmospheric detail. Replaces 3D geometry beyond ~15m with textured surfaces.
# Factor of 7: 7 layers = 7 depth zones = 7 color channels.
#
# Each layer: distance, height, opacity, color tint, and what it represents.
# The brain populates layer colors from nearby emissive clusters.
# Godot renders each as a camera-following CylinderMesh with a ShaderMaterial.

# Distances: 7m increments (7, 14, 21, 28, 35, 42, 49)
# Heights: 7m × layer_index (7, 14, 21, 28, 35, 42, 49) — capped to dome
# Opacity: 0.07 × layer_index (0.07, 0.14, 0.21...) — deeper = more opaque

CAVERN_BANNER_LAYERS = [
    {"distance":  7.0, "height":  7.0, "opacity": 0.03, "role": "near_haze",
     "tint": [0.08, 0.07, 0.10]},
    {"distance": 14.0, "height": 14.0, "opacity": 0.05, "role": "mid_glow",
     "tint": [0.10, 0.09, 0.12]},
    {"distance": 21.0, "height": 17.0, "opacity": 0.07, "role": "mid_emissive",
     "tint": [0.06, 0.08, 0.10]},
    {"distance": 28.0, "height": 19.0, "opacity": 0.10, "role": "far_glow",
     "tint": [0.05, 0.06, 0.09]},
    {"distance": 35.0, "height": 21.0, "opacity": 0.14, "role": "far_haze",
     "tint": [0.04, 0.05, 0.08]},
    {"distance": 42.0, "height": 21.0, "opacity": 0.18, "role": "fog_edge",
     "tint": [0.04, 0.04, 0.07]},
    {"distance": 49.0, "height": 21.0, "opacity": 0.21, "role": "void",
     "tint": [0.03, 0.03, 0.06]},
]

OUTDOOR_BANNER_LAYERS = [
    {"distance":  7.0, "height": 14.0, "opacity": 0.02, "role": "canopy_near",
     "tint": [0.10, 0.12, 0.06]},
    {"distance": 14.0, "height": 21.0, "opacity": 0.04, "role": "canopy_mid",
     "tint": [0.08, 0.10, 0.05]},
    {"distance": 21.0, "height": 28.0, "opacity": 0.07, "role": "tree_line",
     "tint": [0.06, 0.08, 0.04]},
    {"distance": 28.0, "height": 35.0, "opacity": 0.10, "role": "mid_haze",
     "tint": [0.08, 0.09, 0.07]},
    {"distance": 35.0, "height": 42.0, "opacity": 0.14, "role": "far_haze",
     "tint": [0.10, 0.11, 0.09]},
    {"distance": 42.0, "height": 49.0, "opacity": 0.18, "role": "horizon",
     "tint": [0.12, 0.14, 0.10]},
    {"distance": 49.0, "height": 49.0, "opacity": 0.21, "role": "sky_wash",
     "tint": [0.15, 0.18, 0.22]},
]


# -- Render shell system (Design Law #14 extension) ---------------------------
#
# Seven concentric cylindrical shells at factor-of-7 radii from the observer.
# Entities bind to shells by distance + kind class. Only the innermost shell
# renders full 3D geometry. Outer shells project silhouettes onto the banner
# cylinders. Outermost shells are pure atmosphere — no entities at all.
#
# Biome-agnostic: shells are universal. Banner tint/opacity is biome-specific
# (CAVERN_BANNER_LAYERS / OUTDOOR_BANNER_LAYERS). This config controls WHAT
# renders at each distance; the banner config controls HOW it looks.
#
# Modes:
#   geometry   — full MultiMesh, decals, motes, lights
#   silhouette — flat dark shape projected onto banner cylinder (no 3D geometry)
#   hint       — faint silhouette, reduced opacity
#   atmosphere — banner tint only, no entity rendering
#   void       — pure fog/darkness, nothing renders

RENDER_SHELLS = [
    {"radius":  7, "mode": "geometry",   "kind_classes": ["structural", "emissive", "scatter", "ground_cover", "atmosphere", "life"]},
    {"radius": 14, "mode": "geometry",   "kind_classes": ["structural", "emissive", "scatter", "ground_cover", "atmosphere", "life"]},
    {"radius": 21, "mode": "geometry",   "kind_classes": ["structural", "emissive", "scatter", "ground_cover", "atmosphere"]},
    {"radius": 28, "mode": "geometry",   "kind_classes": ["structural", "emissive", "ground_cover", "atmosphere"]},
    {"radius": 35, "mode": "geometry",   "kind_classes": ["structural", "emissive", "atmosphere"]},
    {"radius": 42, "mode": "geometry",   "kind_classes": ["structural", "emissive"]},
    {"radius": 49, "mode": "geometry",   "kind_classes": ["structural"]},
]

# Every entity kind maps to a render class. The class determines which shells
# the kind can appear in. Universal across biomes — the kind IS the class.
KIND_RENDER_CLASS = {
    # structural — large silhouettes, visible at distance, define the space
    "mega_column":     "structural",
    "column":          "structural",
    "boulder":         "structural",
    "stalagmite":      "structural",
    "buttress":        "structural",
    # emissive — glow visible at distance, need geometry locally for self-emit
    "crystal_cluster": "emissive",
    "giant_fungus":    "emissive",
    "filament":        "emissive",
    "firefly":         "emissive",
    "exit_lure":       "emissive",
    # ground_cover — readable up close, invisible at distance on dark ground
    "moss_patch":      "ground_cover",
    "dead_log":        "ground_cover",
    "bone_pile":       "ground_cover",
    "leaf_pile":       "ground_cover",
    # scatter — tiny objects, local only, no silhouette value
    "rubble":          "scatter",
    "cave_gravel":     "scatter",
    "twig_scatter":    "scatter",
    "grass_tuft":      "scatter",
    # atmosphere — ceiling/wall/horizon elements, mid-distance presence
    "ceiling_moss":    "atmosphere",
    "hanging_vine":    "atmosphere",
    "horizon_near":    "atmosphere",
    "horizon_mid":     "atmosphere",
    "horizon_form":    "atmosphere",
    # life — creatures, close range only
    "beetle":          "life",
    "rat":             "life",
    "rat_ice":         "life",
    "rat_fire":        "life",
    "clay_pot":        "life",
    "treasure_chest":  "life",
    "spider":          "life",
    "leaf":            "life",
    "bat":             "life",
}


# -- Macro stamps (7x7 tile grids) — composition + elevation -----------------
#
# Each macro stamp defines a 7x7 grid over a tile (288m / 7 ≈ 41m per cell).
# elevation: height steps (0=floor, 1=+3m, 2=+6m, -1=-3m pit)
# density: spawn density multiplier for this cell (0.0-1.0)
# allowed: kind class shorthand (S=structural, E=emissive, G=ground_cover,
#          A=atmosphere, L=life, X=scatter, ALL=everything)

MACRO_STAMP_CAVERN_CHAMBER = {
    "name": "cavern_chamber",
    "elevation_step": 3.0,
    # Elevation FLAT for now — density/allowed grids are the active feature.
    # Tile-aware elevation (matching edges between adjacent tiles) is Phase 2.
    # The bowl-shaped grid below is pinned for future use.
    # Boat-in-water effect from this grid = KEEP for coast/water biome.
    "elevation": [
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
    ],
    "density": [
        [0.2, 0.3, 0.4, 0.5, 0.4, 0.3, 0.2],
        [0.3, 0.5, 0.6, 0.7, 0.6, 0.5, 0.3],
        [0.4, 0.6, 0.8, 0.9, 0.8, 0.6, 0.4],
        [0.5, 0.7, 0.9, 0.3, 0.9, 0.7, 0.5],
        [0.4, 0.6, 0.8, 0.9, 0.8, 0.6, 0.4],
        [0.3, 0.5, 0.6, 0.7, 0.6, 0.5, 0.3],
        [0.2, 0.3, 0.4, 0.5, 0.4, 0.3, 0.2],
    ],
    "allowed": [
        ["S",   "S",   "SA",  "SA",  "SA",  "S",   "S"],
        ["S",   "SE",  "SEG", "SEG", "SEG", "SE",  "S"],
        ["SA",  "SEG", "ALL", "ALL", "ALL", "SEG", "SA"],
        ["SA",  "SEG", "ALL", "ALL", "ALL", "SEG", "SA"],
        ["SA",  "SEG", "ALL", "ALL", "ALL", "SEG", "SA"],
        ["S",   "SE",  "SEG", "SEG", "SEG", "SE",  "S"],
        ["S",   "S",   "SA",  "SA",  "SA",  "S",   "S"],
    ],
}

MACRO_STAMP_CAVERN_CORRIDOR = {
    "name": "cavern_corridor",
    "elevation_step": 3.0,
    "elevation": [
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
    ],
    "density": [
        [0.1, 0.2, 0.2, 0.3, 0.2, 0.2, 0.1],
        [0.2, 0.4, 0.5, 0.6, 0.5, 0.4, 0.2],
        [0.3, 0.6, 0.7, 0.8, 0.7, 0.6, 0.3],
        [0.4, 0.7, 0.8, 0.9, 0.8, 0.7, 0.4],
        [0.3, 0.6, 0.7, 0.8, 0.7, 0.6, 0.3],
        [0.2, 0.4, 0.5, 0.6, 0.5, 0.4, 0.2],
        [0.1, 0.2, 0.2, 0.3, 0.2, 0.2, 0.1],
    ],
    "allowed": [
        ["S",  "S",  "S",   "SA",  "S",   "S",  "S"],
        ["S",  "SE", "SE",  "SEG", "SE",  "SE", "S"],
        ["SA", "SEG","ALL", "ALL", "ALL", "SEG","SA"],
        ["SA", "ALL","ALL", "ALL", "ALL", "ALL","SA"],
        ["SA", "SEG","ALL", "ALL", "ALL", "SEG","SA"],
        ["S",  "SE", "SE",  "SEG", "SE",  "SE", "S"],
        ["S",  "S",  "S",   "SA",  "S",   "S",  "S"],
    ],
}

MACRO_STAMP_OUTDOOR_CLEARING = {
    "name": "outdoor_clearing",
    "elevation_step": 2.0,
    "elevation": [
        [1, 1, 1, 0, 1, 1, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 1],
        [1, 0, 0, 0, 0, 1, 1],
        [1, 1, 1, 0, 1, 1, 2],
    ],
    "density": [
        [0.4, 0.5, 0.5, 0.6, 0.5, 0.5, 0.4],
        [0.5, 0.6, 0.7, 0.8, 0.7, 0.6, 0.5],
        [0.5, 0.7, 0.8, 0.9, 0.8, 0.7, 0.5],
        [0.6, 0.8, 0.9, 0.4, 0.9, 0.8, 0.6],
        [0.5, 0.7, 0.8, 0.9, 0.8, 0.7, 0.5],
        [0.5, 0.6, 0.7, 0.8, 0.7, 0.6, 0.5],
        [0.4, 0.5, 0.5, 0.6, 0.5, 0.5, 0.4],
    ],
    "allowed": [
        ["SA",  "SA",  "SEG", "SEG", "SEG", "SA",  "SA"],
        ["SA",  "SEG", "ALL", "ALL", "ALL", "SEG", "SA"],
        ["SEG", "ALL", "ALL", "ALL", "ALL", "ALL", "SEG"],
        ["SEG", "ALL", "ALL", "ALL", "ALL", "ALL", "SEG"],
        ["SEG", "ALL", "ALL", "ALL", "ALL", "ALL", "SEG"],
        ["SA",  "SEG", "ALL", "ALL", "ALL", "SEG", "SA"],
        ["SA",  "SA",  "SEG", "SEG", "SEG", "SA",  "SA"],
    ],
}


BIOME_REGISTRY = {
    "cavern": {
        "palette": CAVERN_PALETTE,
        "color_scales": {},
        "companions": COMPANION_SPAWNS,
        "spectrum": SPECTRUM_PROFILES,
        "motes": MOTE_PRESETS,
        "tile_variants": TILE_VARIANTS,
        "light_states": CAVERN_LIGHT_STATES,
        "density": BIOME_CAVERN_DEFAULT,
        "planes": BIOME_PLANES["cavern"],
        "stamps": CAVERN_STAMPS,
        "banner_layers": CAVERN_BANNER_LAYERS,
        "macro_stamps": [MACRO_STAMP_CAVERN_CHAMBER, MACRO_STAMP_CAVERN_CORRIDOR],
        "tile_prefetch_radius": 2,  # 5x5 grid — entities loaded before wake needs them
        # Playable envelope — set very far so the cavern reads as endless.
        # Procedural tile generation supplies content out to arbitrary
        # distance; only actual entity geometry (spikes, boulders) should
        # ever stop the player. 500m gives the soft pullback a chance to
        # act only at truly-wandered-off distances.
        "playable_radius": 500.0,
        "playable_softness": 0.5,
        "exchange": {
            "delivery_budget": 350,
            "compression_threshold": 500,
            "render_horizon": 49,            # meters — matches outermost shell radius
            "mandatory_kinds": {"mega_column", "column"},
            "scoring_weights": {
                "wake_priority": 1.0,
                "distance_band": 0.8,
                "fov_relevance": 0.6,
                "velocity_bias": 0.4,
                "emissive_boost": -0.35,     # light sources debut early (negative = better score)
                "ground_penalty": 0.25,      # floor scatter debuts last
                "roster_stability": -0.30,   # incumbents stay in lineup
                "newcomer_gate": 0.20,       # newcomers need a reason to debut
            },
            # Per-shell delivery budgets — 7 shells, inner to outer.
            # Each shell gates independently: ground scatter can't starve
            # distant structural. Shells ARE the horizon.
            #   0: 0-7m   all kinds        80
            #   1: 7-14m  all kinds        70
            #   2: 14-21m no life          60
            #   3: 21-28m struct/emis/gc   50
            #   4: 28-35m struct/emis/atm  40
            #   5: 35-42m struct/emis      30
            #   6: 42-49m struct only      20
            "shell_budgets": [80, 70, 60, 50, 40, 30, 20],
            "tiles_per_frame": 2,            # max new tiles generated per response cycle
            "cache_size": 64,
        },
    },
    "outdoor": {
        "palette": OUTDOOR_PALETTE,
        "color_scales": OUTDOOR_COLOR_SCALES,
        "companions": OUTDOOR_COMPANION_SPAWNS,
        "spectrum": OUTDOOR_SPECTRUM_PROFILES,
        "motes": OUTDOOR_MOTE_PRESETS,
        "tile_variants": OUTDOOR_TILE_VARIANTS,
        "light_states": OUTDOOR_LIGHT_STATES,
        "density": BIOME_OUTDOOR_FOREST,
        "planes": BIOME_PLANES["outdoor"],
        "stamps": OUTDOOR_STAMPS,
        "banner_layers": OUTDOOR_BANNER_LAYERS,
        "macro_stamps": [MACRO_STAMP_OUTDOOR_CLEARING],
        "tile_prefetch_radius": 2,  # 5x5 grid — entities loaded before wake needs them
        "playable_radius": 80.0,     # outdoor is wider — more open feel
        "playable_softness": 1.5,
        "exchange": {
            "delivery_budget": 400,
            "compression_threshold": 600,
            "render_horizon": 49,            # meters — matches outermost shell radius
            "mandatory_kinds": {"mega_column", "column"},
            "scoring_weights": {
                "wake_priority": 1.0,
                "distance_band": 0.8,
                "fov_relevance": 0.6,
                "velocity_bias": 0.4,
                "emissive_boost": -0.35,     # light sources debut early
                "ground_penalty": 0.25,      # floor scatter debuts last
                "roster_stability": -0.30,   # incumbents stay in lineup
                "newcomer_gate": 0.20,       # newcomers need a reason to debut
            },
            # Outdoor gets more budget per shell — farther sight lines,
            # but same 7-shell structure.
            "shell_budgets": [90, 80, 70, 55, 45, 35, 25],
            "tiles_per_frame": 2,
            "cache_size": 64,
        },
    },
}
