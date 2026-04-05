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
    ("mega_column",       0.12,    10.0,      20),
    ("column",            0.30,    5.0,       10),
    ("boulder",           1.20,    3.0,       3),
    ("stalagmite",        1.80,    3.0,       2),
    ("giant_fungus",      0.30,    2.5,       3),
    ("crystal_cluster",   0.25,    2.0,       3),
    ("dead_log",          0.50,    1.5,       2),
    ("bone_pile",         0.25,    0,         2),
    ("moss_patch",        0.40,    0,         2),
    ("ceiling_moss",      0.40,    0,         5),
    ("hanging_vine",      0.35,    0,         4),
    ("filament",          0.50,    4.0,       2),
    ("firefly",           0.40,    0,         1),
    ("grass_tuft",        1.50,    0,         1),
    ("rubble",            1.20,    0,         1),
    ("leaf_pile",         0.80,    0,         1),
    ("twig_scatter",      0.80,    0,         1),
    ("rat",               0.45,    0,         2),
    ("beetle",            0.25,    0,         2),
    ("cave_gravel",       1.00,    0,         0),
    ("horizon_form",      0.12,    10.0,      30),
    ("horizon_mid",       0.08,     8.0,      20),
    ("horizon_near",      0.10,     6.0,      12),
    ("exit_lure",         0.03,   20.0,       35),
    ("leaf",              0.25,    0,         1),
    ("spider",            0.12,    0,         2),
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

HARD_OBJECTS = {
    # Increased for mega_column/column/buttress to create walking margin around
    # landmarks — the visible silhouette becomes a "keep out" zone other anchors
    # respect, preserving walkable paths around every major landmark.
    "boulder":          2.5,
    "column":           4.0,   # was 2.5 — walking margin
    "mega_column":      5.0,   # was 2.5 — walking margin
    "buttress":         3.0,   # was 1.8 — walking margin
    "stalagmite":       1.2,
    "giant_fungus":     1.2,
    "crystal_cluster":  1.0,
    "dead_log":         0.8,
    "bone_pile":        0.4,
    "horizon_form":     3.0,
    "horizon_mid":      2.0,
    "horizon_near":     1.0,
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
    "boulder":    {"grass_tuft": 1, "radius": 4.0},
    "column":     {"grass_tuft": 1, "radius": 5.0},
    "moss_patch": {"grass_tuft": 1, "radius": 2.0},
    "dead_log":   {"grass_tuft": 1, "radius": 2.5},
    "stalagmite": {"grass_tuft": 1, "radius": 3.0},
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
        "ambient": (0.58, 0.54, 0.48),
        "fog_color": (0.06, 0.055, 0.06),
        "fog_near": 12.0,
        "fog_far": 48.0,
        "bg_color": (0.06, 0.06, 0.07),
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
        {
            "tag": "ground_near",
            "kind": "ground",
            "normal": [0.0, 0.0, 1.0],
            "offset": 0.0,
            "layer": "near",
            "material": {
                "shader": "ground",
                "surface": "stone_rough",
                "color_base": [0.18, 0.15, 0.12],
                # grain_scale 0.22 → 0.06 stretches tile repeat from ~4.5m to
                # ~16m, pushing the pattern beyond typical fog distance so the
                # ground reads as textured stone rather than tiled stone.
                # normal_strength 1.3 → 0.7 softens the bump relief that was
                # amplifying the repeat signal. Observed in tag_03 playtest.
                "grain_scale": 0.06,
                "grain_strength": 0.55,
                "normal_strength": 0.7,
            },
            "size": 2000.0,
            "follow_camera": True,
        },
        {
            "tag": "ceiling_near",
            "kind": "ceiling",
            "normal": [0.0, 0.0, -1.0],
            "offset": 15.0,
            "layer": "near",
            "material": {
                "shader": "ground",
                "surface": "stone_weathered",
                "color_base": [0.10, 0.09, 0.08],
                # Same stretch treatment as ground, slightly softer relief
                # because the ceiling is farther from the camera on average.
                "grain_scale": 0.06,
                "grain_strength": 0.50,
                "normal_strength": 0.6,
            },
            "size": 2000.0,
            "follow_camera": True,
        },
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
    },
}
