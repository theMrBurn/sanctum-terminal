"""
core/systems/ambient_life.py

Behavior-loop entity system for environmental flourishes.

Entities are state machines that sleep/wake based on camera proximity.
Geometry built once, behavior ticks transform it. Out of range = hidden + paused.
Back in range = resume from current state.

Usage:
    manager = AmbientManager(render_node, wake_radius=30, sleep_radius=45)
    manager.spawn("rat", pos=(10, 20, 0), heading=45, seed=12345)
    manager.spawn("leaf", pos=(5, 8, 3), seed=99)

    # Each frame:
    manager.tick(dt, camera_pos)
"""

import math
import random

from panda3d.core import (
    Vec3, Vec4, NodePath, TexGenAttrib, TextureStage, Texture, PNMImage,
    SamplerState,
)
from core.systems.geometry import make_box, make_sphere, make_bevel_box, make_pebble_cluster, make_rock
from core.systems.glow_decal import make_glow_decal, get_glow_texture, make_light_shaft, get_shaft_texture, make_glow_halo


# -- Biome state (set by cavern.py at init) ------------------------------------
_active_biome = "cavern"


def set_active_biome(biome):
    """Called by cavern.py to configure biome-dependent builders."""
    global _active_biome
    _active_biome = biome


# -- Behavior definitions -----------------------------------------------------

class Behavior:
    """Base behavior loop. Subclass and override tick()."""

    def __init__(self, entity, seed=0):
        self.entity = entity
        self.rng = random.Random(seed)
        self.elapsed = 0.0
        self.state = "idle"
        self.state_timer = 0.0

    def tick(self, dt):
        """Override in subclass. Called each frame when entity is awake."""
        self.elapsed += dt
        self.state_timer += dt

    def _switch(self, new_state):
        self.state = new_state
        self.state_timer = 0.0


class ScurryBehavior(Behavior):
    """Rat-like: idle → scurry → pause → idle. Small radius, quick darts."""

    def __init__(self, entity, seed=0):
        super().__init__(entity, seed)
        self._pick_idle()
        self._origin = entity.pos
        self._target_h = entity.heading
        self._speed = self.rng.uniform(1.5, 3.0)
        self._roam_radius = self.rng.uniform(1.0, 3.0)

    def _pick_idle(self):
        self._switch("idle")
        self._wait = self.rng.uniform(1.5, 5.0)

    def _pick_scurry(self):
        self._switch("scurry")
        self._wait = self.rng.uniform(0.3, 0.8)
        # Pick a random direction within roam radius
        angle = self.rng.uniform(0, 360)
        self._target_h = angle
        self._move_dx = -math.sin(math.radians(angle)) * self._speed
        self._move_dy = math.cos(math.radians(angle)) * self._speed

    def _pick_pause(self):
        self._switch("pause")
        self._wait = self.rng.uniform(0.5, 2.0)

    def tick(self, dt):
        super().tick(dt)
        node = self.entity.node

        if self.state == "idle":
            if self.state_timer > self._wait:
                self._pick_scurry()

        elif self.state == "scurry":
            # Move
            pos = node.getPos()
            nx = pos.getX() + self._move_dx * dt
            ny = pos.getY() + self._move_dy * dt
            # Clamp to roam radius from origin
            dx = nx - self._origin[0]
            dy = ny - self._origin[1]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist > self._roam_radius:
                # Bounce back toward origin
                nx = self._origin[0] + dx / dist * self._roam_radius * 0.9
                ny = self._origin[1] + dy / dist * self._roam_radius * 0.9
                self._pick_pause()
            else:
                node.setH(self._target_h)
            # Height follows terrain if height_fn available
            nz = pos.getZ()
            if self.entity.height_fn:
                nz = self.entity.height_fn(nx, ny)
            node.setPos(nx, ny, nz)
            if self.state_timer > self._wait:
                self._pick_pause()

        elif self.state == "pause":
            if self.state_timer > self._wait:
                choice = self.rng.random()
                if choice < 0.6:
                    self._pick_scurry()
                else:
                    self._pick_idle()


class DriftBehavior(Behavior):
    """Falling leaf / dust mote: drift down with lateral sway, reset at bottom."""

    def __init__(self, entity, seed=0):
        super().__init__(entity, seed)
        self._origin = entity.pos
        self._fall_speed = self.rng.uniform(0.3, 0.8)
        self._sway_amp = self.rng.uniform(0.2, 0.6)
        self._sway_freq = self.rng.uniform(1.0, 3.0)
        self._spin_speed = self.rng.uniform(30, 120)
        self._floor_z = 0.0

    def tick(self, dt):
        super().tick(dt)
        node = self.entity.node
        pos = node.getPos()

        # Fall
        nz = pos.getZ() - self._fall_speed * dt
        # Sway
        sway = math.sin(self.elapsed * self._sway_freq) * self._sway_amp * dt
        nx = pos.getX() + sway
        # Spin
        node.setH(node.getH() + self._spin_speed * dt)

        # Get floor height
        floor = self._floor_z
        if self.entity.height_fn:
            floor = self.entity.height_fn(nx, pos.getY())

        if nz <= floor + 0.02:
            # Reset to origin height — leaf falls again
            node.setPos(self._origin[0] + self.rng.uniform(-0.5, 0.5),
                        self._origin[1] + self.rng.uniform(-0.5, 0.5),
                        self._origin[2])
            self.elapsed = self.rng.uniform(0, 2)  # phase offset so they're not synced
        else:
            node.setPos(nx, pos.getY(), nz)


class CrawlBehavior(Behavior):
    """Spider / insect: slow creep, pause, change direction. Surface-bound."""

    def __init__(self, entity, seed=0):
        super().__init__(entity, seed)
        self._origin = entity.pos
        self._speed = self.rng.uniform(0.3, 0.8)
        self._roam_radius = self.rng.uniform(0.5, 2.0)
        self._pick_creep()

    def _pick_creep(self):
        self._switch("creep")
        self._wait = self.rng.uniform(1.0, 4.0)
        angle = self.rng.uniform(0, 360)
        self._target_h = angle
        self._move_dx = -math.sin(math.radians(angle)) * self._speed
        self._move_dy = math.cos(math.radians(angle)) * self._speed

    def _pick_still(self):
        self._switch("still")
        self._wait = self.rng.uniform(2.0, 8.0)

    def tick(self, dt):
        super().tick(dt)
        node = self.entity.node

        if self.state == "creep":
            pos = node.getPos()
            nx = pos.getX() + self._move_dx * dt
            ny = pos.getY() + self._move_dy * dt
            dx = nx - self._origin[0]
            dy = ny - self._origin[1]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist > self._roam_radius:
                self._pick_still()
                return
            nz = pos.getZ()
            if self.entity.height_fn:
                nz = self.entity.height_fn(nx, ny)
            node.setPos(nx, ny, nz)
            node.setH(self._target_h)
            if self.state_timer > self._wait:
                self._pick_still()

        elif self.state == "still":
            if self.state_timer > self._wait:
                self._pick_creep()


# -- Behavior registry --------------------------------------------------------

class StaticBehavior(Behavior):
    """No movement — object just exists. Used for boulders, landmarks."""

    def tick(self, dt):
        pass  # intentionally empty — static objects don't move


class SwayBehavior(Behavior):
    """Gentle pendulum sway — hanging filaments, chimes, spider silk."""

    def __init__(self, entity, seed=0):
        super().__init__(entity, seed)
        self._sway_amp = self.rng.uniform(0.8, 2.5)  # degrees
        self._sway_freq = self.rng.uniform(0.3, 0.8)  # Hz
        self._phase = self.rng.uniform(0, 6.28)

    def tick(self, dt):
        super().tick(dt)
        self._phase += dt * self._sway_freq * 6.28
        node = self.entity.node
        node.setR(math.sin(self._phase) * self._sway_amp)
        node.setP(math.cos(self._phase * 0.7) * self._sway_amp * 0.4)


class WanderBehavior(Behavior):
    """Slow 3D drift — fireflies, ambient particles, bioluminescent plankton."""

    def __init__(self, entity, seed=0):
        super().__init__(entity, seed)
        self._origin = entity.pos
        self._radius = self.rng.uniform(3.0, 8.0)
        self._speed = self.rng.uniform(0.15, 0.4)
        self._freq_x = self.rng.uniform(0.1, 0.3)
        self._freq_y = self.rng.uniform(0.08, 0.25)
        self._freq_z = self.rng.uniform(0.05, 0.15)
        self._phase = self.rng.uniform(0, 6.28)
        self._z_band = self.rng.uniform(1.0, 3.0)  # vertical wander range

    def tick(self, dt):
        super().tick(dt)
        self._phase += dt * self._speed
        p = self._phase
        ox, oy, oz = self._origin
        node = self.entity.node
        nx = ox + math.sin(p * self._freq_x * 6.28) * self._radius
        ny = oy + math.cos(p * self._freq_y * 6.28) * self._radius * 0.7
        nz = oz + math.sin(p * self._freq_z * 6.28) * self._z_band
        node.setPos(nx, ny, max(0.3, nz))


BEHAVIORS = {
    "scurry": ScurryBehavior,   # rats, small creatures
    "drift": DriftBehavior,     # leaves, dust, embers
    "crawl": CrawlBehavior,     # spiders, insects
    "static": StaticBehavior,   # boulders, landmarks, ruins
    "sway": SwayBehavior,       # hanging filaments, chimes
    "wander": WanderBehavior,   # fireflies, ambient plankton
}


# -- Creature behavior states --------------------------------------------------
# Reactive states layered on top of base behaviors. Opt-in per encounter.
# Player proximity triggers state transitions. Not active unless scenario enables.
#
# Each creature profile maps base_behavior → {state: {overrides}}.
# The overrides replace speed/roam/pause when active.

# -- Discovery pacing ---------------------------------------------------------
# Tile-level biome variation. Most tiles are "standard" density.
# Some tiles are special — crystal grove, fungus forest, bone field.
# The rarity weight controls how often each variant appears.

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

# -- Outdoor tile variants — PNW forest micro-biomes --------------------------
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


# -- Relational spawn patterns (ecosystem recipes) ----------------------------
# Instead of random density scatter, these define what spawns NEAR what.
# When a "anchor" object spawns, it pulls companions from its recipe.
# Built into the parent node via flattenStrong — zero extra entity overhead.

# -- Collision config ----------------------------------------------------------
# Anchor objects wake at extended range — they're the landmarks you see first.
# Everything else uses the default wake radius.
ANCHOR_WAKE_MULT = {
    "mega_column":      1.8,   # visible from fog distance
    "column":           1.6,
    "crystal_cluster":  1.5,
    "giant_fungus":     1.4,
    "boulder":          1.3,
    "ceiling_moss":     1.5,   # the glow should be visible early
}

# "Hard" objects the player can't walk through. Soft objects (grass, motes,
# leaves) have no collision. Each hard kind has a collision radius derived
# from its typical build size.

HARD_OBJECTS = {
    "boulder":          2.5,   # half-width of typical boulder
    "column":           2.5,   # base radius — wide enough for curtain profile
    "mega_column":      2.5,
    "stalagmite":       0.6,
    "giant_fungus":     1.2,
    "crystal_cluster":  1.0,
    "dead_log":         0.8,
    "bone_pile":        0.4,
    "horizon_form":     3.0,
    "horizon_mid":      2.0,
    "horizon_near":     1.0,
}


# -- Shared cavern palette (derived from stage_floor) -------------------------

# All objects reference these to stay on the same spectrum.
# Updated at spawn time if palette changes.
CAVERN_PALETTE = {
    "floor": (0.08, 0.06, 0.05),       # stage_floor base
    "dirt": (0.044, 0.030, 0.023),      # floor * 0.55/0.50/0.45
    "stone": (0.12, 0.11, 0.10),        # slightly lighter than dirt
    "dark_stone": (0.08, 0.07, 0.07),   # deep shadow stone
    "dead_organic": (0.09, 0.07, 0.05), # dead grass, twigs, logs
    "bone": (0.14, 0.13, 0.11),         # pale but muted
}

# -- PNW outdoor palette — Portland OR reference biome -------------------------
# Douglas fir bark, sword fern green, forest floor earth, moss-on-everything.
OUTDOOR_PALETTE = {
    "floor": (0.12, 0.10, 0.06),       # warm forest earth
    "dirt": (0.08, 0.06, 0.03),         # dark forest dirt
    "stone": (0.10, 0.07, 0.05),        # bark brown (columns, mega_columns)
    "dark_stone": (0.06, 0.05, 0.03),   # deep bark shadow
    "dead_organic": (0.06, 0.10, 0.04), # green-brown (living plant matter)
    "bone": (0.16, 0.14, 0.08),         # pale wood / birch bark
}

# Per-kind colorScale overrides applied after build.
# Cavern uses uniform stone tones. Outdoor differentiates by species.
# NOTE: These MULTIPLY against the builder's baked colorScale (~0.50-0.55).
# Values are ~1.8x brighter than target to compensate for the stacking.
# boulder target green (0.19, 0.33, 0.12) → scale (0.65, 1.20, 0.48) × baked (0.55, 0.50, 0.48)
OUTDOOR_COLOR_SCALES = {
    "boulder":         (0.75, 1.45, 0.55, 1.0),  # sword fern mound — bright green
    "column":          (0.90, 0.75, 0.55, 1.0),  # tree bark — warm brown
    "mega_column":     (0.82, 0.65, 0.48, 1.0),  # old growth bark — rich brown
    "stalagmite":      (0.82, 0.70, 0.52, 1.0),  # dead stump / standing stone
    "giant_fungus":    (0.60, 1.10, 0.45, 1.0),  # large bush — green dominant, suppress magenta
    "crystal_cluster": (1.00, 0.82, 0.55, 1.0),  # flowering shrub — warm
    "moss_patch":      (0.40, 0.95, 0.25, 1.0),  # natural moss — green, not neon
    "dead_log":        (0.55, 0.78, 0.35, 1.0),  # nurse log — mossy green-brown
    "grass_tuft":      (0.55, 1.00, 0.35, 1.0),  # forest grass — visible green
    "rubble":          (0.82, 0.72, 0.58, 1.0),  # scattered stones — earthy
    "leaf_pile":       (0.90, 0.70, 0.35, 1.0),  # fir needles — warm orange-brown
    "twig_scatter":    (0.76, 0.65, 0.42, 1.0),  # fallen branches — wood tone
    "firefly":         (3.0, 2.0, 1.0, 1.0),     # same warm amber — fireflies are fireflies
    "cave_gravel":     (0.72, 0.65, 0.48, 1.0),  # dirt pebbles — warm
    "horizon_form":    (0.12, 0.16, 0.08, 1.0),  # distant tree line — dark green
    "horizon_mid":     (0.16, 0.20, 0.12, 1.0),  # mid-distance trees
    "horizon_near":    (0.20, 0.24, 0.16, 1.0),  # near tree silhouettes
}

# Render dome height per biome — fog hides the rest.
DOME_HEIGHT = {
    "cavern": 30.0,      # fog_far 28m + margin
    "outdoor": 45.0,     # Doug firs feel TALL — fog_far 55m, dome lower for canopy implication
}

BIOME_PALETTES = {
    "cavern": CAVERN_PALETTE,
    "outdoor": OUTDOOR_PALETTE,
}


# -- World grain: visual language root -------------------------------------------
# One number governs the texture density of the entire world.
# Materials are ratios of this root — stone is finer, organic is coarser.
# The ratios ARE the regional dialect. The root IS the world's resolution.
#
# Signal flow: WORLD_GRAIN → material ratio → tex_scale on every surface.
# Ground texture, object textures, light decals all derive from the same root.
# The player reads coherence without knowing why — "this world has rules."
#
# Register variants could override WORLD_GRAIN:
#   survival = 0.10 (gritty, detailed)
#   tron     = 0.06 (sharp, clean)
#   tolkien  = 0.14 (broad, painterly)

WORLD_GRAIN = 0.10  # base texture density for the world

# Minimum height ratio for stone/organic shapes.
# No flat pancakes unless biome declares water_flow.
# height = max(width * STONE_MIN_HEIGHT_RATIO, requested_height)
STONE_MIN_HEIGHT_RATIO = 0.15

# -- Size-class contact system -------------------------------------------------
# "Small touch small, big touch big" — objects of similar scale share edges.
# Each builder pulls its size range from its class. Sub-pieces within a builder
# use overlap_z() to ensure connected geometry — no floating gaps.
#
# Contact rule: child_z = parent_top - child_h * OVERLAP_FACTOR
# This guarantees visual intersection between adjacent sections.

OVERLAP_FACTOR = 0.50  # each section overlaps 50% into the one below it


def overlap_z(parent_h, child_h):
    """Calculate z-position for a child section so it overlaps into the parent.

    Returns the z where the child's center should sit so its bottom
    hemisphere intersects with the parent's top hemisphere.
    """
    return parent_h * (1.0 - OVERLAP_FACTOR) - child_h * 0.1


# Companion spawns — objects that cluster near other objects.
# When a base object spawns, also spawn N companions at random positions around it.
# Grass grows near boulders, columns, moss. Not near crystals (too harsh).
COMPANION_SPAWNS = {
    "boulder":    {"grass_tuft": 1, "radius": 4.0},
    "column":     {"grass_tuft": 1, "radius": 5.0},
    "moss_patch": {"grass_tuft": 1, "radius": 2.0},
    "dead_log":   {"grass_tuft": 1, "radius": 2.5},
    "stalagmite": {"grass_tuft": 1, "radius": 3.0},
}

# Outdoor: anchor objects pull PNW ecosystem companions
# Companion counts reduced — each costs a tick slot. Density table handles volume.
OUTDOOR_COMPANION_SPAWNS = {
    "mega_column": {"moss_patch": 1, "grass_tuft": 1, "radius": 8.0},   # Doug fir base
    "column":      {"grass_tuft": 1, "radius": 4.0},                    # tree trunk base
    "boulder":     {"grass_tuft": 1, "radius": 4.0},                    # fern understory
    "dead_log":    {"moss_patch": 1, "radius": 3.0},                    # nurse log
    "giant_fungus": {"grass_tuft": 1, "radius": 3.5},                   # bush ground cover
}


# -- Spectrum system -----------------------------------------------------------
# Polyrhythmic hue drift + prismatic facet offsets.
# One class handles both: spectrum_drift for the whole entity,
# prismatic_offset for per-shard variation within a cluster.
#
# Config-as-code: swap the frequency table and you get a different biome feel.

SPECTRUM_PROFILES = {
    "fungus": {
        "base_hue": (0.22, 0.06, 0.30),
        "drift_range": 0.18,
        "channels": [
            {"freq": 0.017, "amp": 1.0},    # ~60s full cycle
            {"freq": 0.011, "amp": 0.6},    # ~90s, polyrhythmic offset
            {"freq": 0.007, "amp": 0.3},    # ~140s, deep slow drift
        ],
    },
    "crystal": {
        "base_hue": (0.15, 0.18, 0.35),
        "drift_range": 0.12,
        "channels": [
            {"freq": 0.013, "amp": 1.0},    # ~77s cycle
            {"freq": 0.0087, "amp": 0.5},   # ~115s
            {"freq": 0.0053, "amp": 0.25},  # ~188s
        ],
        "prismatic": True,                   # per-shard facet offsets
        "facet_spread": 0.12,                # ±12% channel offset per shard
    },
    "moss": {
        "base_hue": (0.08, 0.35, 0.06),
        "drift_range": 0.10,
        "channels": [
            {"freq": 0.009, "amp": 1.0},    # ~111s — slowest, most organic
            {"freq": 0.006, "amp": 0.4},    # ~167s
        ],
    },
    "ceiling_moss": {
        "base_hue": (0.80, 0.55, 0.15),
        "drift_range": 0.08,
        "channels": [
            {"freq": 0.012, "amp": 1.0},
            {"freq": 0.0073, "amp": 0.5},
        ],
    },
}

# -- Outdoor spectrum profiles — same drift engine, PNW palette ----------------
# Bioluminescence → natural light. Slower drift = weather/wind, not metabolism.
OUTDOOR_SPECTRUM_PROFILES = {
    "fungus": {  # giant_fungus → large bush / rhododendron
        "base_hue": (0.12, 0.28, 0.08),    # forest green
        "drift_range": 0.08,                 # subtle — wind, not glow
        "channels": [
            {"freq": 0.008, "amp": 1.0},    # ~125s — breeze cycle
            {"freq": 0.005, "amp": 0.4},    # ~200s — slow sway
        ],
    },
    "crystal": {  # crystal_cluster → flowering shrub / wildflower
        "base_hue": (0.35, 0.20, 0.12),    # warm flower
        "drift_range": 0.10,
        "channels": [
            {"freq": 0.010, "amp": 1.0},    # ~100s
            {"freq": 0.006, "amp": 0.5},    # ~167s
        ],
        "prismatic": True,                   # per-petal color variation
        "facet_spread": 0.08,
    },
    "moss": {  # moss_patch → natural ground moss
        "base_hue": (0.06, 0.22, 0.04),    # deep natural green
        "drift_range": 0.05,                 # almost static — moss doesn't move
        "channels": [
            {"freq": 0.004, "amp": 1.0},    # ~250s — moisture cycle
        ],
    },
    "sunlight": {  # outdoor-only — dappled sun on forest floor
        "base_hue": (0.45, 0.38, 0.15),    # warm gold
        "drift_range": 0.12,                 # cloud shadows passing
        "channels": [
            {"freq": 0.015, "amp": 1.0},    # ~67s — cloud drift
            {"freq": 0.009, "amp": 0.6},    # ~111s — canopy sway
            {"freq": 0.004, "amp": 0.3},    # ~250s — time of day
        ],
    },
}


class SpectrumEngine:
    """Polyrhythmic hue drift + prismatic facet offsets.

    Each bio-lit entity gets a phase (from seed) and drifts through
    a color gradient on overlapping sine waves. No two entities sync.

    Prismatic mode (crystals): per-shard offsets on top of the drift,
    so facets shimmer independently while the cluster moves as a family.

    LUT mode: pre-computed 256-entry sine table. Zero trig at runtime.
    Saturn/PS1 trick — index into a table instead of calling sin().
    """
    # Pre-computed sine LUT — 256 entries covering 0..2π
    _SIN_LUT = [math.sin(i * 2.0 * math.pi / 256.0) for i in range(256)]

    @staticmethod
    def phase_for_seed(seed):
        """Deterministic phase offset from entity seed — desynchronizes all entities."""
        return (seed * 0.618033) % (2.0 * math.pi)  # golden ratio scatter

    @staticmethod
    def drift(profile_name, elapsed, seed):
        """Calculate hue shift for an entity at a given time.

        Returns (r_shift, g_shift, b_shift) to ADD to base colorScale.
        Uses LUT lookup instead of math.sin() — zero trig per frame.
        """
        profile = biome_config("spectrum").get(profile_name)
        if not profile:
            return (0, 0, 0)
        phase = SpectrumEngine.phase_for_seed(seed)
        lut = SpectrumEngine._SIN_LUT
        total = 0.0
        for ch in profile["channels"]:
            # LUT index: map continuous angle to 0-255
            idx = int((elapsed * ch["freq"] + phase * 0.15915494) * 256.0) & 0xFF
            total += lut[idx] * ch["amp"]
        # Normalize to [-1, 1] range then scale by drift_range
        max_amp = sum(ch["amp"] for ch in profile["channels"])
        if max_amp > 0:
            total /= max_amp
        dr = profile["drift_range"]
        # Shift each channel differently for organic color movement
        r_shift = total * dr
        g_shift = total * dr * 0.7   # green shifts less — keeps warmth
        b_shift = total * dr * 1.2   # blue shifts more — cool/warm oscillation
        return (r_shift, g_shift, b_shift)

    @staticmethod
    def prismatic_offset(seed, shard_index, profile_name="crystal"):
        """Per-shard color offset for prismatic crystals.

        Shard 0 (king) stays true. Others shift ± on one channel.
        Returns (r_off, g_off, b_off) to ADD to shard colorScale.
        """
        profile = biome_config("spectrum").get(profile_name, {})
        if shard_index == 0 or not profile.get("prismatic"):
            return (0, 0, 0)
        spread = profile.get("facet_spread", 0.10)
        rng = random.Random(seed + shard_index * 73)
        # Pick one dominant channel to shift — reads as prismatic refraction
        channel = rng.randint(0, 2)
        amount = rng.uniform(-spread, spread)
        offsets = [0.0, 0.0, 0.0]
        offsets[channel] = amount
        # Subtle complementary shift on another channel
        other = (channel + 1) % 3
        offsets[other] = -amount * 0.3
        return tuple(offsets)

MATERIAL_RATIOS = {
    "stone_heavy":  0.80,   # finer than base — dense packed mineral
    "stone_light":  1.00,   # matches base — crystalline, medium grain
    "dry_organic":  1.20,   # coarser — fiber/bark is bigger than mineral
    "bone":         0.90,   # between stone and base — smooth, polished
}


def _mat_scale(material):
    """Derive tex_scale from world grain × material ratio.

    Every surface in the world speaks the same visual language.
    """
    ratio = MATERIAL_RATIOS.get(material, 1.0)
    return WORLD_GRAIN * ratio


# -- Light layer composition ---------------------------------------------------
# Config-as-code: base object + light layer = composed entity.
# Any base object can receive any light layer. The affinity table per biome
# controls which combos appear and at what probability.
#
# To add a new light type: add an entry to LIGHT_LAYERS.
# To add a new biome feel: add an entry to LIGHT_AFFINITY.
# To light a new object: add it to the biome's affinity dict.
# Zero new builder functions needed.

LIGHT_LAYERS = {
    "moss": {
        "material": "dry_organic",
        "shell_scale": 1.03,          # barely larger — mold grows ON the surface
        "shell_roughness": (0.40, 0.60),  # high roughness = irregular mold patches
        "decal_radius_mult": 1.5,     # glow pool = 1.5× object width
        "decal_surface": "wet_stone",
        "inner_darken": (0.45, 0.42, 0.40),  # inner form recedes
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
            "float_compression": 0.2,  # near-static shimmer around the blanket
        },
    },
    "crystal": {
        "material": "stone_light",
        "shell_scale": 1.05,
        "decal_radius_mult": 4.0,
        "decal_surface": "smooth",
        "inner_darken": (0.40, 0.40, 0.45),
        "additive_patches": True,     # crystal patches bleed light into scene
        "double_decal": True,         # inner bright + outer dim wash
        "hues": [
            {"color": (0.15, 0.18, 0.35), "glow": (3.0, 3.5, 6.0), "decal": (0.6, 0.75, 1.8)},
            {"color": (0.18, 0.08, 0.30), "glow": (3.0, 1.2, 4.5), "decal": (0.75, 0.27, 1.2)},
        ],
        "motes": {
            "count": 10, "radius": 3.0, "height": 3.0,
            "downward": False, "fall_speed": 0.003,
            "sway_amp": 0.12, "sway_freq": 0.08,
            "float_compression": 0.15,  # slow mineral drift, not frozen
        },
    },
    "torch": {
        "material": "dry_organic",
        "shell_scale": 1.08,
        "decal_radius_mult": 2.0,     # torches cast wider pools
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
            "float_compression": 0.5,  # rising heat shimmer
            "ground_bias": True,
        },
    },
}

# Mote behavior presets for standalone entities (not composed via light layers).
# Same config shape — one tick function reads all of them.
MOTE_PRESETS = {
    "ceiling_moss": {
        "color": (0.8, 0.55, 0.15), "count": 12, "radius": 3.0, "height": 18.0,
        "downward": True, "fall_speed": 0.015,
        "sway_amp": 0.10, "sway_freq": 0.05,
        "float_compression": 0.4,       # gentle rain — floaty, continuous loop
    },
    "giant_fungus": {
        "color": (0.25, 0.08, 0.35), "count": 8, "radius": 3.0, "height": 4.0,
        "downward": False, "fall_speed": 0.005,
        "sway_amp": 0.25, "sway_freq": 0.10,
        "float_compression": 0.2,       # slow pendulum drift — spores in still air
    },
    "moss_patch": {
        "color": (0.1, 0.5, 0.08), "count": 3, "radius": 1.5, "height": 1.0,
        "downward": False, "fall_speed": 0.0,
        "sway_amp": 0.10, "sway_freq": 0.06,
        "float_compression": 0.1,       # near-static ground shimmer
        "ground_bias": True,
    },
    "crystal_cluster": {
        "color": (0.3, 0.35, 0.6), "count": 10, "radius": 3.0, "height": 3.0,
        "downward": False, "fall_speed": 0.003,
        "sway_amp": 0.12, "sway_freq": 0.08,
        "float_compression": 0.15,      # slow mineral drift
    },
}

# -- Outdoor mote presets — pollen, leaf particles, ground dust ----------------
OUTDOOR_MOTE_PRESETS = {
    "giant_fungus": {  # bush → pollen/seed drift
        "color": (0.35, 0.30, 0.12), "count": 6, "radius": 3.0, "height": 3.0,
        "downward": False, "fall_speed": 0.008,
        "sway_amp": 0.30, "sway_freq": 0.06,
        "float_compression": 0.3,       # lazy seed drift on breeze
    },
    "moss_patch": {  # ground moss → dust motes
        "color": (0.25, 0.20, 0.10), "count": 3, "radius": 1.5, "height": 0.8,
        "downward": False, "fall_speed": 0.0,
        "sway_amp": 0.08, "sway_freq": 0.04,
        "float_compression": 0.1,       # near-static ground dust
        "ground_bias": True,
    },
    "crystal_cluster": {  # flowers → petal drift
        "color": (0.40, 0.30, 0.15), "count": 5, "radius": 2.0, "height": 2.0,
        "downward": True, "fall_speed": 0.010,
        "sway_amp": 0.20, "sway_freq": 0.08,
        "float_compression": 0.25,      # falling petals
    },
}

# -- Sunlight light layer — outdoor-only, warm ground dapple ------------------
OUTDOOR_LIGHT_LAYERS = {
    "sunlight": {
        "material": "dry_organic",
        "shell_scale": 1.02,
        "shell_roughness": (0.20, 0.40),
        "decal_radius_mult": 3.0,         # wide sun pools
        "decal_surface": "smooth",
        "inner_darken": (0.55, 0.50, 0.45),  # subtle shadow side
        "hues": [
            {"color": (0.45, 0.38, 0.15), "glow": (3.0, 2.5, 1.0), "decal": (1.0, 0.85, 0.35)},
            {"color": (0.40, 0.35, 0.12), "glow": (2.5, 2.0, 0.8), "decal": (0.90, 0.75, 0.30)},
        ],
        "motes": {
            "count": 6, "radius": 2.5, "height": 4.0,
            "downward": True, "fall_speed": 0.006,
            "sway_amp": 0.18, "sway_freq": 0.10,
            "float_compression": 0.3,     # dust motes in sunbeam
        },
    },
}

# Per-biome affinity: {object_kind: {light_layer: probability}}
# 0.0 = never, 1.0 = always. Roll per spawn instance.
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
        "boulder":    {"sunlight": 0.30, "moss": 0.20},   # ferns catch sun + moss
        "column":     {"sunlight": 0.15, "moss": 0.12},   # sun dapple on trunks
        "mega_column": {"sunlight": 0.10, "moss": 0.15},  # old growth = more moss
        "dead_log":   {"moss": 0.40, "sunlight": 0.10},   # nurse logs are mossy
        "stalagmite": {"sunlight": 0.12, "moss": 0.08},   # stumps in clearings
        "moss_patch": {"sunlight": 0.25},                  # sun on moss
        "rubble":     {"moss": 0.10},                      # mossy stones
    },
}


def _cavern_color(key, rng, variation=0.02, biome=None):
    """Get a color from the biome palette with small random variation."""
    if biome is None:
        biome = _active_biome
    palette = BIOME_PALETTES.get(biome, CAVERN_PALETTE)
    base = palette.get(key, (0.10, 0.10, 0.10))
    sv = rng.uniform(-variation, variation)
    return (base[0] + sv, base[1] + sv * 0.7, base[2] + sv * 0.5)


def apply_light_layer(base_node, layer_name, seed):
    """Wrap any built entity with a self-lit glow shell + ground decal.

    Generic compositor — the base object provides form, the light layer
    provides illumination. Works on any geometry returned by a builder.

    Returns the base_node (modified in-place with additional children).
    """
    cfg = LIGHT_LAYERS.get(layer_name)
    if cfg is None:
        cfg = OUTDOOR_LIGHT_LAYERS.get(layer_name)
    if cfg is None:
        return base_node

    rng = random.Random(seed + hash(layer_name))
    hue = cfg["hues"][seed % len(cfg["hues"])]

    # Measure the base object's bounds for shell sizing
    bounds = base_node.getTightBounds()
    if bounds is None or len(bounds) < 2:
        return base_node
    bmin, bmax = bounds
    w = max(0.5, (bmax.getX() - bmin.getX()) * 0.5)
    h = max(0.3, (bmax.getZ() - bmin.getZ()) * 0.5)
    d = max(0.5, (bmax.getY() - bmin.getY()) * 0.5)
    center_z = (bmin.getZ() + bmax.getZ()) * 0.5

    # Darken existing children so the shell reads as the light source
    # Apply to each pre-existing child — never the root (root colorScale cascades)
    dr, dg, db = cfg["inner_darken"]
    for ci in range(base_node.getNumChildren()):
        child = base_node.getChild(ci)
        cs = child.getColorScale()
        if cs.getX() < 1.5:  # don't darken anything already self-lit
            child.setColorScale(dr, dg, db, 1.0)

    # Glow patches — scattered flat growths on the upper surface, not a cocoon.
    # Mold/lichen/crystal grows in spots. The object shows through between them.
    from core.systems.geometry import make_rock
    patch_count = rng.randint(3, 6)
    gx, gy, gz = hue["glow"]
    tex = get_material_texture(cfg["material"], seed=seed)
    ts_glow = TextureStage("glow_layer")
    ts_glow.setMode(TextureStage.MModulate)
    mat_sc = _mat_scale(cfg["material"])
    for pi in range(patch_count):
        # Each patch is flat, sits on the upper surface
        pw = w * rng.uniform(0.3, 0.7)
        pd = d * rng.uniform(0.3, 0.7)
        ph = h * rng.uniform(0.08, 0.20)  # very flat — growth, not a blob
        patch = base_node.attachNewNode(make_rock(
            pw, ph, pd, hue["color"],
            rings=3, segments=5, seed=seed + 700 + pi * 37,
            roughness=rng.uniform(0.3, 0.5),
        ))
        # Place on upper hemisphere — random angle around top
        angle = rng.uniform(0, 360)
        dist = rng.uniform(0, w * 0.4)
        pz = center_z + h * rng.uniform(0.3, 0.8)
        patch.setPos(
            math.cos(math.radians(angle)) * dist,
            math.sin(math.radians(angle)) * dist,
            pz,
        )
        patch.setH(rng.uniform(0, 360))
        patch.setTwoSided(True)
        patch.setTexGen(ts_glow, TexGenAttrib.MWorldPosition)
        patch.setTexture(ts_glow, tex)
        patch.setTexScale(ts_glow, mat_sc, mat_sc)
        patch.setLightOff()
        patch.setColorScale(gx, gy, gz, 1.0)

    # Crystal special: additive blend on patches so they bleed light into the scene
    if cfg.get("additive_patches"):
        from panda3d.core import ColorBlendAttrib
        for ci in range(base_node.getNumChildren()):
            child = base_node.getChild(ci)
            if child.hasColorScale() and child.getColorScale().getX() > 1.5:
                child.setAttrib(ColorBlendAttrib.make(
                    ColorBlendAttrib.MAdd,
                    ColorBlendAttrib.OOne,
                    ColorBlendAttrib.OOne,
                ))
                child.setDepthWrite(False)

    # Ground glow decal — inner bright pool
    from core.systems.glow_decal import make_glow_decal, get_glow_texture
    glow_tex = get_glow_texture(64, surface=cfg["decal_surface"])
    decal_r = w * cfg["decal_radius_mult"]
    make_glow_decal(base_node, color=hue["decal"], radius=decal_r, tex=glow_tex)

    # Double decal: outer dim wash for crystals/torch (wider ambient glow)
    if cfg.get("double_decal"):
        outer_tex = get_glow_texture(64, surface="smooth")
        dr, dg, db = hue["decal"]
        make_glow_decal(base_node, color=(dr * 0.4, dg * 0.4, db * 0.4),
                        radius=decal_r * 2.0, tex=outer_tex)

    # Tag mote config for wake-time spawning — color from the hue
    mote_cfg = cfg.get("motes")
    if mote_cfg:
        tagged = dict(mote_cfg)
        tagged["color"] = hue["decal"]  # motes match the glow pool color
        base_node.setPythonTag("mote_config", tagged)

    return base_node


def resolve_light_layer(kind, seed, biome="Cavern_Default"):
    """Check affinity table — does this object get a light layer?

    Returns layer_name (str) or None. Deterministic per seed.
    """
    affinity = LIGHT_AFFINITY.get(biome, {}).get(kind, {})
    if not affinity:
        return None
    rng = random.Random(seed + 31337)
    for layer_name, prob in affinity.items():
        if rng.random() < prob:
            return layer_name
    return None


# -- Biome registry: unified lookup for all biome-paired config ----------------
# Third biome = one new entry here. Everything else reads biome_config().
BIOME_REGISTRY = {
    "cavern": {
        "palette": CAVERN_PALETTE,
        "color_scales": {},
        "companions": COMPANION_SPAWNS,
        "spectrum": SPECTRUM_PROFILES,
        "motes": MOTE_PRESETS,
        "tile_variants": TILE_VARIANTS,
    },
    "outdoor": {
        "palette": OUTDOOR_PALETTE,
        "color_scales": OUTDOOR_COLOR_SCALES,
        "companions": OUTDOOR_COMPANION_SPAWNS,
        "spectrum": OUTDOOR_SPECTRUM_PROFILES,
        "motes": OUTDOOR_MOTE_PRESETS,
        "tile_variants": OUTDOOR_TILE_VARIANTS,
    },
}


def biome_config(key):
    """Look up biome-specific config. Falls back to cavern."""
    return BIOME_REGISTRY.get(_active_biome, BIOME_REGISTRY["cavern"])[key]


# -- Entity builders ----------------------------------------------------------

def build_rat(parent, seed=0):
    """Build rat geometry, return NodePath."""
    rng = random.Random(seed)
    root = parent.attachNewNode(f"rat_{seed}")

    scale = rng.uniform(0.7, 1.2)
    body_len = rng.uniform(0.15, 0.22) * scale
    body_w = body_len * rng.uniform(0.35, 0.5)
    body_h = body_len * rng.uniform(0.25, 0.35)
    fur = _cavern_color("dead_organic", rng, 0.02)

    bn = root.attachNewNode(make_box(body_w, body_h, body_len, fur))
    bn.setPos(0, 0, body_h * 0.5)
    hs = body_h * 0.8
    hn = root.attachNewNode(make_box(hs * 1.1, hs, hs * 1.1, fur))
    hn.setPos(0, body_len * 0.5, body_h * 0.55)
    sn = root.attachNewNode(make_box(hs * 0.4, hs * 0.3, hs * 0.6,
                                      (fur[0] + 0.02, fur[1] + 0.02, fur[2] + 0.01)))
    sn.setPos(0, body_len * 0.5 + hs * 0.7, body_h * 0.45)
    for t in range(rng.randint(5, 8)):
        taper = 1.0 - (t / 8) * 0.7
        thick = body_h * 0.12 * taper
        tn = root.attachNewNode(make_box(thick, thick, body_len * 0.12, (0.12, 0.09, 0.08)))
        tn.setPos(0, -body_len * 0.4 - body_len * 0.12 * t, body_h * 0.3)

    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    return root


def build_leaf(parent, seed=0):
    """Tiny leaf — curled organic fragment, drifts down."""
    rng = random.Random(seed)
    root = parent.attachNewNode(f"leaf_{seed}")
    w = rng.uniform(0.03, 0.06)
    lh = max(w * STONE_MIN_HEIGHT_RATIO, w * 0.15)
    color = _cavern_color("dead_organic", rng, 0.02)
    leaf = root.attachNewNode(make_rock(
        w * 0.5, lh, w * 0.35, color,
        rings=3, segments=3, seed=seed, roughness=rng.uniform(0.3, 0.5),
    ))
    leaf.setR(rng.uniform(-30, 30))
    leaf.setTwoSided(True)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    return root


def build_spider(parent, seed=0):
    """Tiny spider — body + legs suggestion."""
    rng = random.Random(seed)
    root = parent.attachNewNode(f"spider_{seed}")
    s = rng.uniform(0.02, 0.04)
    color = _cavern_color("dark_stone", rng, 0.01)
    body = root.attachNewNode(make_box(s, s * 0.6, s, color))
    # Leg hints — 4 thin bars
    for i in range(4):
        leg_len = s * 1.5
        leg = root.attachNewNode(make_box(0.003, 0.003, leg_len, (0.06, 0.05, 0.04)))
        angle = -60 + i * 40
        leg.setPos(math.cos(math.radians(angle)) * s * 0.4,
                    math.sin(math.radians(angle)) * s * 0.3, 0)
        leg.setR(angle)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    return root


# -- Shared material textures (generated once, cached) -------------------------
# Pool of 8 variants per material — pre-baked on first request, then sampled.
# This eliminates per-spawn texture generation (the #1 performance killer).

_MATERIAL_POOL = {}   # material -> [tex0, tex1, ..., tex7]
_POOL_SIZE = 8


def get_material_texture(material, seed=0):
    """Get a cached material texture variant. 8 pre-baked per material type."""
    if material not in _MATERIAL_POOL:
        _MATERIAL_POOL[material] = _prebake_material_pool(material)
    return _MATERIAL_POOL[material][seed % _POOL_SIZE]


def _prebake_material_pool(material):
    """Generate pool of texture variants for a material type."""
    pool = []
    for i in range(_POOL_SIZE):
        s = i * 7919  # spread seeds for visual variety
        if material == "stone_heavy":
            tex = generate_stone_texture(size=64, seed=s,
                                          ground_color=CAVERN_PALETTE["dirt"])
        elif material == "stone_light":
            tex = _generate_material_texture(size=48, seed=s,
                base=CAVERN_PALETTE["stone"],
                lighten=0.04,
                cell_size=0.10,
                mortar_width=0.01,
                ground_color=CAVERN_PALETTE["dirt"])
        elif material == "dry_organic":
            tex = _generate_organic_texture(size=48, seed=s,
                base=CAVERN_PALETTE["dead_organic"],
                ground_color=CAVERN_PALETTE["dirt"])
        else:
            tex = generate_stone_texture(size=48, seed=s)
        pool.append(tex)
    return pool


def _generate_material_texture(size=48, seed=0, base=(0.12, 0.11, 0.10),
                                lighten=0.0, cell_size=0.12, mortar_width=0.015,
                                ground_color=(0.06, 0.05, 0.04)):
    """Voronoi stone texture variant — configurable for different erosion rates."""
    rng = random.Random(seed)
    img = PNMImage(size, size)
    br, bg, bb = base[0] + lighten, base[1] + lighten, base[2] + lighten

    cells = []
    cell_colors = []
    for gx_i in range(int(1.0 / cell_size) + 2):
        for gy_i in range(int(1.0 / cell_size) + 2):
            cx = gx_i * cell_size + rng.uniform(-0.04, 0.04)
            cy = gy_i * cell_size + rng.uniform(-0.04, 0.04)
            cells.append((cx, cy))
            sv = rng.uniform(-0.03, 0.03)
            cell_colors.append((br + sv, bg + sv * 0.7, bb + sv * 0.5))

    gr, gg, gb = ground_color
    for y in range(size):
        v = y / size
        for x in range(size):
            u = x / size
            min_d = 999.0
            min_ci = 0
            for ci, (ccx, ccy) in enumerate(cells):
                d = (u - ccx) ** 2 + (v - ccy) ** 2
                if d < min_d:
                    min_d = d
                    min_ci = ci
            min_d = math.sqrt(min_d)
            cr, cg, cb = cell_colors[min_ci % len(cell_colors)]

            if min_d < mortar_width:
                r, g, b = cr * 0.5, cg * 0.5, cb * 0.5
            else:
                n = rng.uniform(-0.02, 0.02)
                r, g, b = cr + n, cg + n * 0.7, cb + n * 0.5

            # Situ blend at bottom
            if v > 0.65:
                t = ((v - 0.65) / 0.35) ** 2
                r = r * (1 - t) + gr * t
                g = g * (1 - t) + gg * t
                b = b * (1 - t) + gb * t

            img.setXel(x, y, max(0, min(1, r)), max(0, min(1, g)), max(0, min(1, b)))

    tex = Texture(f"mat_{seed}")
    tex.load(img)
    tex.setMagfilter(SamplerState.FT_nearest)
    tex.setMinfilter(SamplerState.FT_nearest)
    return tex


def _generate_organic_texture(size=48, seed=0, base=(0.09, 0.07, 0.05),
                               ground_color=(0.06, 0.05, 0.04)):
    """Streaky fiber grain — dead grass, twigs, bark. Not mineral Voronoi."""
    rng = random.Random(seed)
    img = PNMImage(size, size)
    br, bg, bb = base

    for y in range(size):
        v = y / size
        for x in range(size):
            u = x / size
            # Streaky grain — horizontal bands with noise
            streak = math.sin(v * 40 + rng.uniform(-2, 2)) * 0.03
            fiber = rng.uniform(-0.015, 0.015)
            knot = 0.0
            if rng.random() < 0.02:  # occasional dark knot
                knot = -0.04

            r = br + streak + fiber + knot
            g = bg + streak * 0.7 + fiber * 0.8 + knot
            b = bb + streak * 0.4 + fiber * 0.5 + knot

            # Situ blend
            if v > 0.7:
                t = ((v - 0.7) / 0.3) ** 2
                gr, gg, gb = ground_color
                r = r * (1 - t) + gr * t
                g = g * (1 - t) + gg * t
                b = b * (1 - t) + gb * t

            img.setXel(x, y, max(0, min(1, r)), max(0, min(1, g)), max(0, min(1, b)))

    tex = Texture(f"organic_{seed}")
    tex.load(img)
    tex.setMagfilter(SamplerState.FT_nearest)
    tex.setMinfilter(SamplerState.FT_nearest)
    return tex


def generate_stone_texture(size=64, seed=0, ground_color=(0.06, 0.05, 0.04)):
    """Procedural stone texture with height-based situ blending.

    Top rows: lighter weathered stone (exposed to elements)
    Bottom rows: darker, speckled to match ground (situ blend)
    Middle: stone grain via tight Voronoi cells

    Returns a Texture object ready to apply.
    """
    rng = random.Random(seed)
    img = PNMImage(size, size)

    # Stone base — from shared palette
    sb = CAVERN_PALETTE["stone"]
    base_r = sb[0] + rng.uniform(-0.02, 0.02)
    base_g = sb[1] + rng.uniform(-0.02, 0.02)
    base_b = sb[2] + rng.uniform(-0.02, 0.02)

    # Generate jittered cell centers for Voronoi stone grain
    cell_size = 0.12  # tight cells = fine grain
    cells = []
    cell_colors = []
    for gx_i in range(int(1.0 / cell_size) + 2):
        for gy_i in range(int(1.0 / cell_size) + 2):
            cx = gx_i * cell_size + rng.uniform(-0.04, 0.04)
            cy = gy_i * cell_size + rng.uniform(-0.04, 0.04)
            cells.append((cx, cy))
            sv = rng.uniform(-0.03, 0.03)
            cell_colors.append((base_r + sv, base_g + sv * 0.7, base_b + sv * 0.5))

    gr, gg, gb = ground_color

    for y in range(size):
        v = y / size  # 0=top, 1=bottom
        for x in range(size):
            u = x / size

            # Find nearest Voronoi cell
            min_d = 999.0
            min_ci = 0
            for ci, (cx, cy) in enumerate(cells):
                dx = u - cx
                dy = v - cy
                d = dx * dx + dy * dy
                if d < min_d:
                    min_d = d
                    min_ci = ci

            min_d = math.sqrt(min_d)
            cr, cg, cb = cell_colors[min_ci % len(cell_colors)]

            # Fracture lines (mortar) — very thin for stone
            mortar_width = 0.015 + rng.uniform(0, 0.01)
            edge_d = min_d  # approximate edge distance

            if edge_d < mortar_width:
                # Fracture line — darker
                r = cr * 0.5
                g = cg * 0.5
                b = cb * 0.5
            else:
                # Stone surface with subtle noise
                noise = rng.uniform(-0.02, 0.02)
                r = cr + noise
                g = cg + noise * 0.7
                b = cb + noise * 0.5

            # Height-based layering:
            # v=0 (top) = exposed, slightly lighter
            # v=0.5 (middle) = pure stone
            # v=1 (bottom) = situ blend, darker, ground-matched
            if v < 0.3:
                # Top: weather-lightened
                weather = (0.3 - v) / 0.3 * 0.06
                r += weather
                g += weather * 0.8
                b += weather * 0.6
            elif v > 0.65:
                # Bottom: situ blend — fade toward ground color
                blend = (v - 0.65) / 0.35  # 0 at v=0.65, 1 at v=1.0
                blend = blend * blend  # ease in
                r = r * (1 - blend) + gr * blend
                g = g * (1 - blend) + gg * blend
                b = b * (1 - blend) + gb * blend
                # Add speckle
                if rng.random() < blend * 0.3:
                    speck = rng.uniform(-0.03, 0.03)
                    r += speck
                    g += speck
                    b += speck

            img.setXel(x, y, max(0, min(1, r)), max(0, min(1, g)), max(0, min(1, b)))

    tex = Texture(f"stone_{seed}")
    tex.load(img)
    tex.setMagfilter(SamplerState.FT_nearest)
    tex.setMinfilter(SamplerState.FT_nearest)
    return tex


def build_boulder(parent, seed=0):
    """Boulder — 80% connected geological mass, 20% crumbled slabs.

    Connected: single large rock with surface variation from roughness.
    Reads as eroded monolith. Crumbled: original stacked slabs for variety.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"boulder_{seed}")

    total_height = rng.uniform(2.7, 3.3)
    base_width = rng.uniform(4.5, 7.5)
    base_depth = base_width * rng.uniform(0.6, 0.85)

    crumbled = rng.random() < 0.20  # 20% crumbled, 80% connected

    # make_rock squashes bottom hemisphere to 20%, so we need to pass
    # ~1.6× the desired visible height to compensate
    vis_compensate = 1.6

    if crumbled:
        # Crumbled: 2 chunky blocks, not flat slabs
        slab_count = 2
        z = 0
        for si in range(slab_count):
            sw = base_width * rng.uniform(0.7, 1.0) * (0.9 + si * 0.1)
            sd = base_depth * rng.uniform(0.7, 1.0)
            # Each block must be at least 40% as tall as it is wide — no pancakes
            slab_h_raw = total_height / slab_count
            slab_w = sw * 0.5
            slab_h = max(slab_w * 0.4, slab_h_raw * 0.5 * vis_compensate)
            color = _cavern_color("stone", rng, 0.03)
            slab = root.attachNewNode(make_rock(
                slab_w, slab_h, sd * 0.5, color,
                rings=5, segments=8, seed=seed + si * 31,
                roughness=rng.uniform(0.25, 0.45),
            ))
            slab.setPos(rng.uniform(-0.3, 0.3), rng.uniform(-0.2, 0.2), z)
            slab.setH(rng.uniform(-8, 8))
            slab.setTwoSided(True)
            z += slab_h * 0.8
    else:
        # Connected: single eroded mass — roughness provides surface detail
        color = _cavern_color("stone", rng, 0.03)
        mass = root.attachNewNode(make_rock(
            base_width * 0.5, total_height * 0.5 * vis_compensate, base_depth * 0.5, color,
            rings=6, segments=8, seed=seed,
            roughness=rng.uniform(0.30, 0.50),  # higher roughness = eroded character
        ))
        mass.setPos(0, 0, 0)
        mass.setTwoSided(True)

    stone_tex = get_material_texture("stone_heavy", seed=seed)
    ts = TextureStage("stone")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, stone_tex)
    sc = _mat_scale("stone_heavy")
    root.setTexScale(ts, sc, sc)

    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    root.flattenStrong()

    return root


def build_grass_tuft(parent, seed=0):
    """Cave grass clump — dense cluster of blades from multiple growth points.

    3-4 sub-clumps packed together, each with its own blade fan.
    No gaps — reads as a thick patch of cave sedge, not scattered sticks.
    Similar density pattern to crystal satellites or fungus clusters.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"grass_{seed}")
    # Multiple growth points packed together — no gaps
    clump_count = rng.randint(3, 4)
    for ci in range(clump_count):
        clump_angle = rng.uniform(0, 360)
        clump_dist = rng.uniform(0.0, 0.08)  # tight packing
        cx = math.cos(math.radians(clump_angle)) * clump_dist
        cy = math.sin(math.radians(clump_angle)) * clump_dist
        blade_count = rng.randint(4, 8)
        max_h = rng.uniform(0.15, 0.35)
        for i in range(blade_count):
            rank = i / blade_count
            h = max_h * rng.uniform(0.4, 1.0 - rank * 0.3)
            w = rng.uniform(0.006, 0.014)
            color = _cavern_color("dead_organic", rng, 0.03)
            blade = root.attachNewNode(make_rock(
                w * 0.5, h * 0.4, w * 0.15, color,
                rings=3, segments=3, seed=seed + ci * 100 + i * 19,
                roughness=rng.uniform(0.1, 0.25),
            ))
            angle = rng.uniform(0, 360)
            dist = rng.uniform(0.01, 0.05)
            blade.setPos(cx + math.cos(math.radians(angle)) * dist,
                         cy + math.sin(math.radians(angle)) * dist, h * 0.5)
            blade.setH(angle + rng.uniform(-40, 40))
            blade.setP(rng.uniform(-30, 30))
            blade.setR(rng.uniform(-20, 20))
        blade.setTwoSided(True)
    tex = get_material_texture("dry_organic", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    sc = _mat_scale("dry_organic")
    root.setTexScale(ts, sc, sc)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    root.setScale(5.0)
    root.flattenStrong()
    return root


def build_rubble(parent, seed=0):
    """Rubble field — broken stone chunks, not flat cards.

    Mix of sizes: 1-2 medium chunks + several small fragments.
    Scattered wider, varied heights. Reads as collapsed debris.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"rubble_{seed}")
    # 1-2 medium anchor pieces + smaller scatter
    # No setScale — sizes are world-space directly. Height ratio math works correctly.
    anchor_count = rng.randint(1, 2)
    frag_count = rng.randint(3, 5)
    for i in range(anchor_count):
        s = rng.uniform(0.5, 1.2)  # world-space size, no 5× scale
        color = _cavern_color("stone", rng, 0.03)
        rw = s * rng.uniform(0.8, 1.2)
        rh = max(rw * 0.5, s * rng.uniform(0.5, 0.9))  # chunky — height ≥ half width
        piece = make_rock(
            rw, rh,
            s * rng.uniform(0.7, 1.1),
            color, rings=4, segments=5, seed=seed + i,
            roughness=rng.uniform(0.35, 0.55),
        )
        pn = root.attachNewNode(piece)
        pn.setPos(rng.uniform(-1.0, 1.0), rng.uniform(-1.0, 1.0), 0)
        pn.setH(rng.uniform(0, 360))
        pn.setR(rng.uniform(-20, 20))
        pn.setTwoSided(True)
    for i in range(frag_count):
        s = rng.uniform(0.2, 0.5)  # world-space fragments
        color = _cavern_color("stone", rng, 0.02)
        fw = s * rng.uniform(0.7, 1.2)
        fh = max(fw * 0.5, s * rng.uniform(0.4, 0.8))  # no pancakes
        piece = make_rock(
            fw, fh,
            s * rng.uniform(0.6, 1.0),
            color, rings=3, segments=4, seed=seed + 100 + i,
            roughness=rng.uniform(0.4, 0.7),
        )
        pn = root.attachNewNode(piece)
        pn.setPos(rng.uniform(-2.0, 2.0), rng.uniform(-2.0, 2.0), 0)
        pn.setH(rng.uniform(0, 360))
        pn.setR(rng.uniform(-25, 25))
        pn.setTwoSided(True)
    tex = get_material_texture("stone_heavy", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    sc = _mat_scale("stone_heavy")
    root.setTexScale(ts, sc, sc)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    root.flattenStrong()
    return root


def build_leaf_pile(parent, seed=0):
    """Dead leaf litter — curled organic fragments on the ground.

    Flat make_rock shapes with slight curl (roughness) so they read as
    dried leaves, not playing cards. Stacked loosely at random angles.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"leafpile_{seed}")
    count = rng.randint(5, 12)
    for i in range(count):
        w = rng.uniform(0.03, 0.07)
        color = _cavern_color("dead_organic", rng, 0.02)
        lh = max(w * STONE_MIN_HEIGHT_RATIO, w * 0.15)
        leaf = root.attachNewNode(make_rock(
            w * 0.5, lh, w * rng.uniform(0.3, 0.5), color,
            rings=3, segments=4, seed=seed + i * 11,
            roughness=rng.uniform(0.4, 0.7),  # visible curl
        ))
        leaf.setPos(rng.uniform(-0.15, 0.15), rng.uniform(-0.15, 0.15), rng.uniform(0, 0.04))
        leaf.setH(rng.uniform(0, 360))
        leaf.setR(rng.uniform(-30, 30))
        leaf.setP(rng.uniform(-20, 20))
        leaf.setTwoSided(True)
    tex = get_material_texture("dry_organic", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    sc = _mat_scale("dry_organic")
    root.setTexScale(ts, sc, sc)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    root.setScale(5.0)
    root.flattenStrong()
    return root


def build_dead_log(parent, seed=0):
    """Decaying log segment — short cylinder-ish shape, dark, on its side."""
    rng = random.Random(seed)
    root = parent.attachNewNode(f"log_{seed}")
    length = rng.uniform(0.5, 1.5)
    radius = rng.uniform(0.06, 0.15)
    color = _cavern_color("dead_organic", rng, 0.02)
    # Log body — rock primitive on its side reads as rough cylinder
    log = make_rock(
        length * 0.5, radius, radius, color,
        rings=5, segments=6, seed=seed,
        roughness=rng.uniform(0.15, 0.35),
    )
    ln = root.attachNewNode(log)
    ln.setP(90)  # lay on side
    ln.setPos(0, 0, radius * 0.5)
    ln.setTwoSided(True)
    tex = get_material_texture("dry_organic", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    sc = _mat_scale("dry_organic")
    root.setTexScale(ts, sc, sc)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    root.setScale(5.0)
    root.flattenStrong()
    return root


def build_twig_scatter(parent, seed=0):
    """Cave debris — broken organic fragments on the ground.

    Mix of elongated rock-shapes (snapped stalactite bits, bone-like fragments)
    lying flat, not standing up. Tumbled at random angles like they fell.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"twigs_{seed}")
    count = rng.randint(3, 7)
    for i in range(count):
        length = rng.uniform(0.06, 0.18)
        thick = rng.uniform(0.01, 0.03)
        color = _cavern_color("dead_organic", rng, 0.02)
        # Elongated rock lying on its side — not a flat card
        piece = make_rock(
            length * 0.5, thick, thick * rng.uniform(0.6, 1.0),
            color, rings=3, segments=4, seed=seed + i * 13,
            roughness=rng.uniform(0.3, 0.5),
        )
        pn = root.attachNewNode(piece)
        pn.setPos(rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), thick * 0.5)
        pn.setH(rng.uniform(0, 360))
        pn.setP(90 + rng.uniform(-15, 15))  # lying flat
        pn.setTwoSided(True)
    tex = get_material_texture("dry_organic", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    sc = _mat_scale("dry_organic")
    root.setTexScale(ts, sc, sc)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    root.setScale(5.0)
    root.flattenStrong()
    return root


def build_stalagmite(parent, seed=0):
    """Stalagmite — tall irregular cone rising from floor.

    Uses make_rock with height >> width for the tapered column shape.
    Roughness breaks the cone regularity. Mineral deposit colors.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"stalagmite_{seed}")

    # Wide variety: no stubby pancakes — minimum 2m for visual presence
    height = rng.uniform(2.0, 6.0)
    base_w = height * rng.uniform(0.12, 0.35)  # thin spire to chunky column
    base_d = base_w * rng.uniform(0.6, 1.0)    # round to oval base

    # Mineral deposit spectrum — cooler/wetter than dry stone
    # Calcite/limestone: slightly blue-grey shift vs boulder's warm-grey
    mineral_bases = [
        (0.11, 0.11, 0.13),  # cool blue-grey
        (0.13, 0.12, 0.13),  # neutral mineral
        (0.10, 0.10, 0.12),  # dark slate-blue
        (0.12, 0.11, 0.11),  # warm mineral
        (0.09, 0.10, 0.11),  # deep cool
    ]
    base = rng.choice(mineral_bases)
    sv = rng.uniform(-0.02, 0.02)
    color = (base[0] + sv, base[1] + sv * 0.7, base[2] + sv * 0.5)

    # Tall narrow rock — height compensated for bottom squash (1.6×)
    rock = root.attachNewNode(make_rock(
        base_w, height * 0.5 * 1.6, base_d, color,
        rings=6, segments=7, seed=seed,
        roughness=rng.uniform(0.2, 0.4),
    ))
    rock.setPos(0, 0, 0)
    rock.setTwoSided(True)

    # Sometimes a smaller one beside it
    if rng.random() < 0.4:
        s = rng.uniform(0.3, 0.6)
        small = root.attachNewNode(make_rock(
            base_w * s, height * 0.5 * 1.6 * s, base_d * s, color,
            rings=4, segments=5, seed=seed + 77,
            roughness=rng.uniform(0.25, 0.5),
        ))
        angle = rng.uniform(0, 360)
        dist = base_w * 1.2
        small.setPos(
            math.cos(math.radians(angle)) * dist,
            math.sin(math.radians(angle)) * dist,
            0,
        )
        small.setTwoSided(True)

    tex = get_material_texture("stone_light", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    sc = _mat_scale("stone_light")
    root.setTexScale(ts, sc, sc)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    return root


def build_column(parent, seed=0):
    """Massive cave column — single connected make_rock per profile.

    No multi-section gaps. One tall rock with roughness providing
    the surface variation that reads as geological character.
    Profiles control the width/depth/height ratios.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"column_{seed}")

    profile = rng.choice(["pillar", "pillar", "curtain", "broken"])  # hourglass removed — gap source
    total_height = rng.uniform(12.0, 20.0)
    base_radius = rng.uniform(1.5, 3.0)

    if profile == "pillar":
        w = base_radius
        d = base_radius * rng.uniform(0.7, 1.0)
        roughness = rng.uniform(0.25, 0.45)
    elif profile == "curtain":
        w = base_radius * rng.uniform(1.5, 2.5)
        d = base_radius * 0.3  # thin wall
        roughness = rng.uniform(0.15, 0.30)
    elif profile == "broken":
        total_height *= rng.uniform(0.3, 0.5)
        w = base_radius
        d = base_radius * rng.uniform(0.6, 0.9)
        roughness = rng.uniform(0.35, 0.55)  # jagged top

    mineral_bases = [
        (0.11, 0.11, 0.13),
        (0.13, 0.12, 0.13),
        (0.10, 0.10, 0.12),
    ]
    base_color = rng.choice(mineral_bases)
    sv = rng.uniform(-0.02, 0.02)
    color = (base_color[0] + sv, base_color[1] + sv * 0.7, base_color[2] + sv * 0.5)

    # Single connected rock — height compensated for bottom squash
    col = root.attachNewNode(make_rock(
        w, total_height * 0.5 * 1.6, d, color,
        rings=10, segments=8, seed=seed,
        roughness=roughness,
    ))
    col.setPos(0, 0, 0)
    col.setTwoSided(True)

    # Store actual width for collision scaling (curtains are wider than default)
    root.setPythonTag("base_radius", max(w, d))

    tex = get_material_texture("stone_light", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    sc = _mat_scale("stone_light")
    root.setTexScale(ts, sc, sc)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    return root


def build_mega_column(parent, seed=0):
    """Cathedral-scale column — massive base, darkness implies the rest.

    Only renders bottom ~30m (the render dome). The column feels 80-160m
    because darkness above the fog ceiling IS the ceiling. Oblivion trick:
    the cave geometry fits inside the render distance, everything beyond
    is implied. Saves ~1000 verts per column vs 3-section full height.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"mega_column_{seed}")

    # Full conceptual height drives the base radius — massive columns
    # feel massive because of WIDTH, not rendered height
    conceptual_height = rng.uniform(80.0, 160.0)
    base_radius = rng.uniform(5.0, 12.0)
    profile = rng.choice(["pillar", "hourglass", "curtain"])

    if profile == "hourglass":
        pass  # base_radius stays — waist taper is above the dome anyway
    elif profile == "pillar":
        pass  # uniform width — just the base
    else:  # curtain
        base_radius *= rng.uniform(1.5, 2.5)

    depth_scale = 0.25 if profile == "curtain" else rng.uniform(0.7, 1.0)
    color = _cavern_color("stone", rng, 0.02)

    # Render dome cap: only build what's visible (fog far + headroom)
    # Dome height per biome — cavern 30m, outdoor 45m (Doug firs feel TALL).
    dome_h = DOME_HEIGHT.get(_active_biome, 30.0)
    render_height = min(dome_h, conceptual_height)

    col = root.attachNewNode(make_rock(
        base_radius, render_height * 0.5 * 1.6, base_radius * depth_scale, color,
        rings=8, segments=8, seed=seed, roughness=rng.uniform(0.2, 0.35),
    ))
    col.setPos(0, 0, 0)
    col.setTwoSided(True)

    # Store actual base radius for collision scaling
    root.setPythonTag("base_radius", base_radius)

    tex = get_material_texture("stone_light", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    # Mega columns use 0.5× material ratio — bigger grain for massive stone
    sc = _mat_scale("stone_heavy") * 0.5
    root.setTexScale(ts, sc, sc)
    root.setColorScale(0.50, 0.46, 0.44, 1.0)
    return root


def build_small_fungus(parent, seed=0):
    """Tiny bioluminescent accent — 1-3 small bulbs clustered on ground.

    Companion version of the floppy_crystal fungus profile. Reads as
    organic growth near larger objects. Same visual language as
    giant_fungus but at ground-clutter scale.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"small_fungus_{seed}")

    glow_color = (0.40, 0.08, 0.50)
    bulb_count = rng.randint(1, 3)
    for i in range(bulb_count):
        h = rng.uniform(0.08, 0.25)
        r = h * rng.uniform(0.4, 0.7)
        bulb = root.attachNewNode(make_rock(
            r, h * 0.4, r * rng.uniform(0.6, 0.9), glow_color,
            rings=3, segments=4, seed=seed + i * 29,
            roughness=rng.uniform(0.15, 0.30),
        ))
        if i == 0:
            bulb.setPos(0, 0, 0)
        else:
            angle = rng.uniform(0, 360)
            dist = rng.uniform(0.05, 0.15)
            bulb.setPos(
                math.cos(math.radians(angle)) * dist,
                math.sin(math.radians(angle)) * dist,
                0,
            )
        bulb.setTwoSided(True)
        bulb.setLightOff()
        bulb.setColorScale(1.5, 0.5, 1.8, 1.0)

    tex = get_material_texture("dry_organic", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    sc = _mat_scale("dry_organic")
    root.setTexScale(ts, sc, sc)
    root.setScale(5.0)
    root.flattenStrong()
    return root


def build_giant_fungus(parent, seed=0):
    """Giant bioluminescent growth — mimics column geology but organic.

    Uses the same bottom/waist/top profile structure as build_column,
    but with organic material, bulbous proportions, and purple glow.
    Satellites lean outward from the base, stems touching ground.
    Almost creepy how geological it looks — is it a column or a fungus?

    Profiles: bulged (wide waist), tapered (narrows up), floppy_crystal
    (mimics crystal spires but rounded and drooping).
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"fungus_{seed}")

    total_h = rng.uniform(4.0, 10.0)
    base_r = rng.uniform(0.8, 2.0)
    profile = rng.choice(["bulged", "tapered", "floppy_crystal"])

    stem_color = (0.08, 0.06, 0.10)
    glow_color = (0.22, 0.06, 0.30)  # deep violet, not neon magenta

    tex = get_material_texture("dry_organic", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    sc = _mat_scale("dry_organic")

    if profile == "floppy_crystal":
        # Mimics crystal cluster but rounded, drooping, bulbous
        spire_count = rng.randint(2, 5)
        for si in range(spire_count):
            if si == 0:
                sh = total_h
                sr = base_r * rng.uniform(0.6, 1.0)
                sx, sy = 0, 0
            else:
                sh = total_h * rng.uniform(0.3, 0.7)
                sr = base_r * rng.uniform(0.3, 0.6)
                angle = rng.uniform(0, 360)
                dist = base_r * rng.uniform(0.5, 1.2)
                sx = math.cos(math.radians(angle)) * dist
                sy = math.sin(math.radians(angle)) * dist
            spire = root.attachNewNode(make_rock(
                sr, sh * 0.45, sr * rng.uniform(0.6, 0.9), glow_color,
                rings=5, segments=6, seed=seed + si * 41,
                roughness=rng.uniform(0.20, 0.35),  # bulbous, not sharp
            ))
            spire.setPos(sx, sy, 0)
            spire.setR(rng.uniform(-12, 12))  # slight droop
            spire.setTwoSided(True)
            spire.setTexGen(ts, TexGenAttrib.MWorldPosition)
            spire.setTexture(ts, tex)
            spire.setTexScale(ts, sc, sc)
            spire.setLightOff()
            spire.setColorScale(1.8, 0.6, 2.2, 1.0)
    else:
        # Column-mimicking profiles: bottom + waist + cap
        if profile == "bulged":
            waist_r = base_r * rng.uniform(1.2, 1.6)  # wider middle
            cap_r = base_r * rng.uniform(0.8, 1.2)
        else:  # tapered
            waist_r = base_r * rng.uniform(0.7, 0.9)
            cap_r = base_r * rng.uniform(0.4, 0.6)

        # Bottom — stocky base, grounded
        bottom_h = total_h * 0.4
        bottom = root.attachNewNode(make_rock(
            base_r, bottom_h * 0.45, base_r * 0.85, stem_color,
            rings=5, segments=7, seed=seed, roughness=rng.uniform(0.15, 0.25),
        ))
        bottom.setPos(0, 0, 0)
        bottom.setTwoSided(True)
        bottom.setTexGen(ts, TexGenAttrib.MWorldPosition)
        bottom.setTexture(ts, tex)
        bottom.setTexScale(ts, sc, sc)

        # Waist — overlaps into bottom via contact system
        waist_h = total_h * 0.3
        waist_z = overlap_z(bottom_h, waist_h)
        waist = root.attachNewNode(make_rock(
            waist_r, waist_h * 0.45, waist_r * 0.8, glow_color,
            rings=4, segments=6, seed=seed + 33, roughness=rng.uniform(0.12, 0.22),
        ))
        waist.setPos(0, 0, waist_z)
        waist.setTwoSided(True)
        waist.setTexGen(ts, TexGenAttrib.MWorldPosition)
        waist.setTexture(ts, tex)
        waist.setTexScale(ts, sc, sc)
        waist.setLightOff()
        waist.setColorScale(1.5, 0.5, 2.0, 1.0)

        # Cap — sits directly on top of waist, overlapping into it
        cap_h = total_h * 0.30  # taller cap, less disc-like
        cap_z = waist_z + waist_h * 0.15  # physically inside waist top
        cap = root.attachNewNode(make_rock(
            cap_r, cap_h * 0.5, cap_r * 0.9, glow_color,
            rings=4, segments=6, seed=seed + 99, roughness=rng.uniform(0.08, 0.18),
        ))
        cap.setPos(0, 0, cap_z)
        cap.setTwoSided(True)
        cap.setLightOff()
        cap.setColorScale(2.0, 0.7, 2.5, 1.0)

        # Satellites — lean outward from base, stems touching ground
        for ci in range(rng.randint(2, 5)):
            angle = rng.uniform(0, 360)
            dist = base_r + rng.uniform(0.3, 1.0)
            sat_h = total_h * rng.uniform(0.2, 0.5)
            sat_r = base_r * rng.uniform(0.2, 0.4)
            ax = math.cos(math.radians(angle)) * dist
            ay = math.sin(math.radians(angle)) * dist
            sat = root.attachNewNode(make_rock(
                sat_r, sat_h * 0.4, sat_r * 0.7, glow_color,
                rings=3, segments=5, seed=seed + 300 + ci,
                roughness=rng.uniform(0.15, 0.30),
            ))
            sat.setPos(ax, ay, 0)
            sat.setR(rng.uniform(-15, 15))
            sat.setTwoSided(True)
            sat.setLightOff()
            sat.setColorScale(1.0, 0.35, 1.2, 1.0)

    # Ground glow decal — decals ARE the lighting on Metal
    glow_tex = get_glow_texture(64, surface="wet_stone")
    make_glow_decal(root, color=(0.55, 0.15, 0.75), radius=base_r * 3.0, tex=glow_tex)

    # Light shaft — extends from mid-height to ground
    shaft_tex = get_shaft_texture()
    shaft_h = total_h * 0.5
    make_light_shaft(root, color=(0.35, 0.10, 0.50), shaft_height=shaft_h, shaft_width=base_r * 2.0, tex=shaft_tex)

    return root


def build_moss_patch(parent, seed=0):
    """Phosphorescent moss — neon green glow on the ground. Natural wayfinding.

    Organic blobs, not boxes. Textured. Casts green light like a natural torch.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"moss_{seed}")

    # Cluster of small, irregular, textured glowing organic blobs
    patch_count = rng.randint(4, 10)
    green_v = rng.uniform(0.0, 0.04)
    # Ground-like texture — moss grows ON the surface, shares its grain
    tex = get_material_texture("dry_organic", seed=seed)
    ts = TextureStage("moss_mat")
    ts.setMode(TextureStage.MModulate)
    for i in range(patch_count):
        r = rng.uniform(0.1, 0.35)
        h = max(r * STONE_MIN_HEIGHT_RATIO, rng.uniform(0.06, 0.15))
        color = (0.06, 0.40 + green_v + rng.uniform(-0.03, 0.03), 0.08)
        blob = root.attachNewNode(make_rock(
            r, h, r * rng.uniform(0.7, 1.0), color,
            rings=3, segments=4, seed=seed + i * 17, roughness=0.15,
        ))
        blob.setPos(rng.uniform(-1.0, 1.0), rng.uniform(-1.0, 1.0), rng.uniform(0, 0.03))
        blob.setH(rng.uniform(0, 360))
        blob.setTwoSided(True)
        blob.setTexGen(ts, TexGenAttrib.MWorldPosition)
        blob.setTexture(ts, tex)
        sc = _mat_scale("dry_organic")
        blob.setTexScale(ts, sc, sc)
        blob.setLightOff()  # self-illuminated — glow bleeds through texture
        blob.setColorScale(3.0, 6.0, 2.0, 1.0)  # self-illuminated, point light does the area work

    # Ground glow decal — decals ARE the lighting on Metal
    # Moss doesn't cast light like a lamp — it IS the light, seeping from the surface
    tex = get_glow_texture(64, surface="wet_stone")
    make_glow_decal(root, color=(0.15, 0.75, 0.12), radius=5.0, tex=tex)

    return root


def _build_crystal_spire(root, rng, seed_offset, max_h, lean_r=0, lean_p=0, pos=(0, 0, 0)):
    """Single crystal spire — king shard + subordinates. Reused for compound clusters."""
    shard_count = rng.randint(4, 8)
    bv_base = rng.uniform(-0.02, 0.02)
    color = (0.15 + bv_base, 0.18 + bv_base, 0.25 + bv_base)

    for i in range(shard_count):
        if i == 0:
            h = max_h
            dist = 0.0
            sr, sp = 0.0, 0.0
        else:
            rank = i / shard_count
            h = max_h * rng.uniform(0.35, 0.75 - rank * 0.15)
            angle = rng.uniform(0, 360)
            dist = rng.uniform(0.1, 0.35 + rank * 0.15)
            la = rng.uniform(3, 8)
            sr = math.cos(math.radians(angle)) * la
            sp = math.sin(math.radians(angle)) * la

        w = h * rng.uniform(0.12, 0.22)
        bv = rng.uniform(-0.01, 0.01)
        sc = (color[0] + bv, color[1] + bv, color[2] + bv)

        shard = root.attachNewNode(make_rock(
            w, h * 0.5, w * rng.uniform(0.6, 0.9), sc,
            rings=4, segments=4, seed=seed_offset + i * 31, roughness=0.06,
        ))
        sx = pos[0] + (math.cos(math.radians(angle)) * dist if i > 0 else 0)
        sy = pos[1] + (math.sin(math.radians(angle)) * dist if i > 0 else 0)
        shard.setPos(sx, sy, pos[2])
        shard.setR(lean_r + sr)
        shard.setP(lean_p + sp)
        shard.setH(rng.uniform(0, 360))
        shard.setTwoSided(True)
        shard.setLightOff()
        # Prismatic facets — each shard shifts one color channel
        pr, pg, pb = SpectrumEngine.prismatic_offset(seed_offset, i)
        shard.setColorScale(3.0 + pr * 3.0, 3.5 + pg * 3.5, 5.0 + pb * 5.0, 1.0)


def build_crystal_cluster(parent, seed=0):
    """Compound crystal formation — 3 spires from shared trunk + base clusters.

    Three main spires at different vectors from a common base.
    Smaller satellite clusters around the perimeter.
    Reads as a single geological formation, not scattered shards.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"crystal_{seed}")

    # Shared trunk base — wide, squat rock
    trunk_r = rng.uniform(0.6, 1.2)
    trunk_color = (0.12, 0.14, 0.20)
    trunk = root.attachNewNode(make_rock(
        trunk_r, trunk_r * 0.4, trunk_r * 0.8, trunk_color,
        rings=4, segments=5, seed=seed, roughness=0.1,
    ))
    trunk.setPos(0, 0, 0)
    trunk.setTwoSided(True)
    trunk.setLightOff()
    trunk.setColorScale(2.0, 2.2, 3.0, 1.0)

    # 3 main spires — different heights, different lean vectors
    max_h = rng.uniform(4.0, 8.0)
    tallest_h = 0
    for si in range(3):
        spire_h = max_h * rng.uniform(0.6, 1.0)
        tallest_h = max(tallest_h, spire_h)
        angle = si * 120 + rng.uniform(-25, 25)  # ~120° apart
        lean = rng.uniform(8, 20)  # each spire leans outward
        lr = math.cos(math.radians(angle)) * lean
        lp = math.sin(math.radians(angle)) * lean
        # Offset from trunk center
        ox = math.cos(math.radians(angle)) * trunk_r * 0.3
        oy = math.sin(math.radians(angle)) * trunk_r * 0.3
        _build_crystal_spire(root, rng, seed + si * 100, spire_h,
                             lean_r=lr, lean_p=lp, pos=(ox, oy, trunk_r * 0.3))

    # 3-5 small satellite clusters around the base
    for ci in range(rng.randint(3, 5)):
        angle = rng.uniform(0, 360)
        dist = trunk_r + rng.uniform(0.5, 1.5)
        small_h = max_h * rng.uniform(0.15, 0.35)
        sx = math.cos(math.radians(angle)) * dist
        sy = math.sin(math.radians(angle)) * dist
        _build_crystal_spire(root, rng, seed + 500 + ci * 50, small_h,
                             pos=(sx, sy, 0))

    # Ground glow decal — decals ARE the lighting on Metal. Render at higher bin so blue reads over torch amber.
    # (bin 14 > torch bin 10)
    glow_tex = get_glow_texture(64, surface="wet_stone")
    crystal_decal = make_glow_decal(root, color=(0.6, 0.75, 1.8), radius=trunk_r * 3.0, tex=glow_tex)
    crystal_decal.setBin("transparent", 14)  # above torch (bin 10) so blue reads

    # Radial halo — crystal radiates outward, not upward like a lamp
    halo = make_glow_halo(root, color=(0.2, 0.25, 0.8),
                          halo_radius=trunk_r * 2.5, halo_height=tallest_h * 0.5)
    halo.setPos(0, 0, tallest_h * 0.4)  # sit at mid-crystal height

    return root


def build_bone_pile(parent, seed=0):
    """Scattered bones — pale cream against dark ground. History, danger, passage.

    Pale color breaks the dark palette like a warning sign.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"bones_{seed}")

    bone_count = rng.randint(4, 10)
    for i in range(bone_count):
        # Long, thin, slightly curved
        length = rng.uniform(0.2, 0.8)
        thick = rng.uniform(0.02, 0.06)
        # Pale cream — bone color, stark against dark ground
        bv = rng.uniform(-0.02, 0.02)
        color = (0.22 + bv, 0.20 + bv, 0.16 + bv)
        bone = root.attachNewNode(make_rock(
            thick, length * 0.4, thick * 0.8, color,
            rings=3, segments=3, seed=seed + i * 13, roughness=0.08,
        ))
        bone.setPos(rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6), 0.02)
        bone.setH(rng.uniform(0, 360))
        bone.setR(rng.uniform(-10, 10))
        bone.setTwoSided(True)

    # Optional skull-like lump in the center
    if rng.random() < 0.4:
        skull_r = rng.uniform(0.08, 0.14)
        skull_color = (0.20, 0.18, 0.14)
        skull = root.attachNewNode(make_rock(
            skull_r, skull_r * 0.8, skull_r * 0.9, skull_color,
            rings=4, segments=5, seed=seed + 999, roughness=0.12,
        ))
        skull.setPos(0, 0, skull_r * 0.3)
        skull.setTwoSided(True)

    tex = get_material_texture("dry_organic", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    sc = _mat_scale("bone")
    root.setTexScale(ts, sc, sc)
    root.setColorScale(0.60, 0.55, 0.50, 1.0)  # slightly brighter than stone — stands out
    return root


def build_beetle(parent, seed=0):
    """Cave beetle — dark glossy carapace, catches bioluminescent light."""
    rng = random.Random(seed)
    root = parent.attachNewNode(f"beetle_{seed}")

    s = rng.uniform(0.03, 0.06)
    # Dark with subtle iridescence — catches reflected light
    color = (0.04, 0.03, 0.05)
    # Oval body
    body = root.attachNewNode(make_rock(
        s, s * 0.4, s * 0.7, color,
        rings=3, segments=4, seed=seed, roughness=0.05,
    ))
    body.setTwoSided(True)
    # Slight sheen — not setLightOff, so it catches scene lights
    body.setColorScale(1.2, 1.1, 1.3, 1.0)

    # Tiny legs — 3 per side
    for i in range(6):
        leg = root.attachNewNode(make_box(0.002, 0.002, s * 0.6, (0.03, 0.03, 0.04)))
        side = 1 if i < 3 else -1
        leg.setPos(side * s * 0.4, (i % 3 - 1) * s * 0.4, 0)
        leg.setR(side * 40)
    return root


def build_moss_boulder(parent, seed=0):
    """Bioluminescent moss draped over a boulder — config-driven glow lamp.

    Two layers on the same make_rock() geometry:
    1. Dark inner boulder (stone texture, damped — the solid form)
    2. Slightly larger moss shell (organic texture, self-lit — the glowing blanket)

    The moss shell is ~10% oversized so it reads as a blanket draped over the
    surface, not a painted rock. Ground glow decal underneath sells the light
    it casts. Same pattern works for any color — green, amber, blue, purple.

    Config-as-code: swap glow_color / glow_scale to produce any lamp variant.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"moss_boulder_{seed}")

    # -- Config knobs (swap these for different lamp types) --
    glow_hues = [
        ((0.08, 0.35, 0.06), (2.0, 5.0, 1.5), (0.1, 0.5, 0.08)),   # green
        ((0.35, 0.20, 0.05), (4.0, 2.5, 0.8), (1.0, 0.6, 0.15)),   # amber
        ((0.06, 0.10, 0.35), (1.5, 2.0, 5.0), (0.08, 0.15, 0.5)),  # blue
        ((0.25, 0.06, 0.30), (3.5, 1.0, 4.0), (0.5, 0.1, 0.6)),    # purple
    ]
    hue_idx = seed % len(glow_hues)
    moss_color, glow_scale, decal_color = glow_hues[hue_idx]

    # -- Boulder dimensions --
    height = rng.uniform(1.2, 2.2)
    width = rng.uniform(2.0, 4.0)
    depth = width * rng.uniform(0.6, 0.85)

    # -- 1. Inner boulder — dark stone, gives solid form --
    stone_color = _cavern_color("dark_stone", rng, 0.02)
    inner = root.attachNewNode(make_rock(
        width * 0.5, height * 0.5, depth * 0.5, stone_color,
        rings=6, segments=8, seed=seed, roughness=rng.uniform(0.25, 0.40),
    ))
    inner.setTwoSided(True)
    stone_tex = get_material_texture("stone_heavy", seed=seed)
    ts_stone = TextureStage("stone")
    ts_stone.setMode(TextureStage.MModulate)
    inner.setTexGen(ts_stone, TexGenAttrib.MWorldPosition)
    inner.setTexture(ts_stone, stone_tex)
    sc = _mat_scale("stone_heavy")
    inner.setTexScale(ts_stone, sc, sc)
    inner.setColorScale(0.45, 0.42, 0.40, 1.0)  # dark, recedes

    # -- 2. Moss shell — barely larger, rough = mold patches, not a pillow --
    shell = root.attachNewNode(make_rock(
        width * 0.52, height * 0.52, depth * 0.52, moss_color,
        rings=6, segments=8, seed=seed + 777, roughness=rng.uniform(0.40, 0.60),
    ))
    shell.setTwoSided(True)
    organic_tex = get_material_texture("dry_organic", seed=seed)
    ts_moss = TextureStage("moss")
    ts_moss.setMode(TextureStage.MModulate)
    shell.setTexGen(ts_moss, TexGenAttrib.MWorldPosition)
    shell.setTexture(ts_moss, organic_tex)
    sc = _mat_scale("dry_organic")
    shell.setTexScale(ts_moss, sc, sc)
    shell.setLightOff()
    shell.setColorScale(*glow_scale, 1.0)

    # -- 3. Ground glow decal — the light this lamp casts --
    glow_tex = get_glow_texture(64, surface="wet_stone")
    make_glow_decal(root, color=decal_color, radius=width * 1.5, tex=glow_tex)

    return root


def build_ceiling_moss(parent, seed=0):
    """Amber bioluminescent ceiling moss — ecosystem pattern.

    No shaft billboard. Instead:
    1. Small glowing blob at ceiling height (the source)
    2. Ground moss patch below (the catcher — gold-green)
    3. Ground glow decal (warm amber pool connecting them)
    Motes configured via MOTE_PRESETS["ceiling_moss"] spawn at wake —
    gentle downward rain on loop between source and catcher.
    """
    from core.systems.glow_decal import (
        make_glow_decal, get_glow_texture,
        make_ceiling_blob, get_ceiling_blob_texture,
    )

    rng = random.Random(seed)
    root = parent.attachNewNode(f"ceil_moss_{seed}")

    # Cluster hangs from a height — the "ceiling"
    hang_z = rng.uniform(15.0, 25.0)

    # 1. Billboard blob at ceiling — the SOURCE, small and warm
    blob_tex = get_ceiling_blob_texture(64)
    blob_radius = rng.uniform(1.5, 3.0)  # smaller — less UFO, more organic
    blob = make_ceiling_blob(root, color=(4.0, 2.8, 1.0), blob_radius=blob_radius,
                             height=hang_z, tex=blob_tex)

    # 2. Ground catcher — gold-green moss that "caught" the dripping glow
    #    Small cluster of self-lit blobs at ground level
    tex = get_material_texture("dry_organic", seed=seed)
    ts = TextureStage("catch_mat")
    ts.setMode(TextureStage.MModulate)
    sc = _mat_scale("dry_organic")
    for i in range(rng.randint(3, 6)):
        r = rng.uniform(0.08, 0.25)
        h = max(r * 0.3, rng.uniform(0.04, 0.10))
        color = (0.12, 0.30 + rng.uniform(-0.03, 0.03), 0.06)
        catch = root.attachNewNode(make_rock(
            r, h, r * rng.uniform(0.7, 1.0), color,
            rings=3, segments=4, seed=seed + 500 + i * 13, roughness=0.12,
        ))
        catch.setPos(rng.uniform(-1.5, 1.5), rng.uniform(-1.5, 1.5), 0)
        catch.setH(rng.uniform(0, 360))
        catch.setTwoSided(True)
        catch.setTexGen(ts, TexGenAttrib.MWorldPosition)
        catch.setTexture(ts, tex)
        catch.setTexScale(ts, sc, sc)
        catch.setLightOff()
        catch.setColorScale(2.0, 3.5, 1.2, 1.0)  # gold-green glow

    # 3. Ground glow decal — warm amber pool, the ecosystem's light footprint
    glow_tex = get_glow_texture(128, surface="wet_stone")
    decal = make_glow_decal(root, color=(1.5, 1.0, 0.30), radius=8.0, tex=glow_tex)

    return root


def build_hanging_vine(parent, seed=0):
    """Thin vine draping downward — single tapered rock, not dashed segments.

    Dark organic, barely visible until backlit by bioluminescence.
    Slight lean gives it a natural droop.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"vine_{seed}")

    hang_height = rng.uniform(8.0, 22.0)
    vine_length = rng.uniform(hang_height * 0.4, hang_height * 0.6)
    w = rng.uniform(0.03, 0.08)
    color = (0.05, 0.06, 0.04)

    vine = root.attachNewNode(make_rock(
        w, vine_length * 0.5, w * rng.uniform(0.5, 0.8), color,
        rings=4, segments=4, seed=seed, roughness=rng.uniform(0.15, 0.30),
    ))
    vine.setPos(rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5), hang_height - vine_length * 0.5)
    vine.setR(rng.uniform(-12, 12))
    vine.setP(rng.uniform(-8, 8))
    vine.setTwoSided(True)

    tex = get_material_texture("dry_organic", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    sc = _mat_scale("dry_organic")
    root.setTexScale(ts, sc, sc)
    root.setColorScale(0.45, 0.50, 0.40, 1.0)  # dark but slightly green-shifted
    return root


# -- Dust mote system (config-driven, any light source) -----------------------
# One spawn function, one tick function. Behavior comes from the config dict.
# LIGHT_LAYERS["moss"]["motes"] and MOTE_PRESETS["ceiling_moss"] use the same
# config shape — the tick doesn't know or care where the config came from.

def _spawn_motes(parent_node, cfg, origin):
    """Spawn drifting dust motes around a light source. Returns list of nodes."""
    rng = random.Random(hash(origin) & 0xFFFF)
    motes = []
    color = cfg.get("color", (0.5, 0.5, 0.5))
    count = cfg.get("count", 8)
    radius = cfg.get("radius", 3.0)
    height = cfg.get("height", 3.0)
    compress = cfg.get("float_compression", 1.0)
    sway_amp = cfg.get("sway_amp", 0.15)
    sway_freq = cfg.get("sway_freq", 0.10)
    fall_speed = cfg.get("fall_speed", 0.0)
    downward = cfg.get("downward", False)

    for i in range(count * 5):
        size = rng.uniform(0.004, 0.012)  # tiny sparkling dust
        mote = parent_node.getParent().attachNewNode(
            make_box(size, size, size, color))
        mx = origin[0] + rng.uniform(-radius, radius)
        my = origin[1] + rng.uniform(-radius, radius)
        if cfg.get("ground_bias"):
            mz = origin[2] + rng.uniform(0.05, height) ** 2 / height
        else:
            mz = origin[2] + rng.uniform(0.3, height)
        mote.setPos(mx, my, mz)
        mote.setLightOff()
        mote.setColorScale(color[0] * 15, color[1] * 15, color[2] * 15, 0.85)
        mote.setTwoSided(True)
        mote.setBillboardPointEye()

        # Per-mote variation — seeded from config, not hardcoded ranges
        mote.setPythonTag("mote_drift", {
            "origin": (mx, my, mz),
            "radius": radius,
            "height": height,
            "speed": rng.uniform(0.01, 0.06) * compress,
            "sway_freq": sway_freq * rng.uniform(0.7, 1.3),
            "sway_amp": sway_amp * rng.uniform(0.7, 1.3),
            "phase": rng.uniform(0, 6.28),
            "downward": downward,
            "fall_speed": fall_speed * rng.uniform(0.8, 1.2),
        })
        motes.append(mote)
    return motes


def tick_motes(mote_nodes, dt):
    """Animate all active motes. One function, all behaviors from config.

    Called per-frame for each awake entity's mote list.
    Reads the mote_drift tag set at spawn — no per-type branching.
    """
    for mote in mote_nodes:
        if mote.isEmpty():
            continue
        d = mote.getPythonTag("mote_drift")
        if d is None:
            continue
        d["phase"] += dt * d["sway_freq"] * 6.28

        ox, oy, oz = d["origin"]
        phase = d["phase"]
        amp = d["sway_amp"]

        # Lateral sway — sin/cos gives figure-8 when combined
        nx = ox + math.sin(phase) * amp
        ny = oy + math.cos(phase * 0.7) * amp * 0.6

        if d["downward"]:
            # Falling motes — drift down, reset at bottom
            oz -= d["fall_speed"] * 60 * dt  # 60fps-normalized
            floor_z = d["origin"][2] - d["height"]
            if oz < floor_z:
                oz = d["origin"][2]  # reset to top
            d["origin"] = (d["origin"][0], d["origin"][1], oz)
            nz = oz
        else:
            # Floating motes — gentle vertical bob
            nz = oz + math.sin(phase * 0.5) * amp * 0.3

        mote.setPos(nx, ny, nz)


def build_filament(parent, seed=0):
    """Hanging mineral filament — cave spider silk or calcite thread.

    Thin vertical strand hanging from ceiling height, barely visible
    until backlit by nearby bioluminescence. Sway behavior makes them
    catch the eye through motion, not brightness.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"filament_{seed}")

    hang_z = rng.uniform(10.0, 22.0)
    strand_len = rng.uniform(3.0, 8.0)
    segments = rng.randint(4, 8)
    seg_len = strand_len / segments

    # Near-invisible dark thread — catches glow from nearby sources
    color = (0.06, 0.06, 0.07)
    thickness = rng.uniform(0.003, 0.008)

    for i in range(segments):
        seg = root.attachNewNode(make_box(thickness, thickness, seg_len * 0.45, color))
        z = hang_z - i * seg_len
        seg.setPos(rng.uniform(-0.03, 0.03), rng.uniform(-0.03, 0.03), z)
        seg.setTwoSided(True)

    # Occasional mineral bead — tiny bright point on the strand
    if rng.random() < 0.4:
        bead_z = hang_z - rng.uniform(strand_len * 0.3, strand_len * 0.8)
        bead_size = rng.uniform(0.008, 0.02)
        bead = root.attachNewNode(make_box(bead_size, bead_size, bead_size, (0.12, 0.11, 0.10)))
        bead.setPos(0, 0, bead_z)
        bead.setTwoSided(True)
        # Slight glow on the bead — catches light
        bead.setLightOff()
        bead.setColorScale(2.0, 1.8, 1.5, 1.0)

    root.setColorScale(0.50, 0.50, 0.55, 1.0)
    return root


def build_firefly(parent, seed=0):
    """Bioluminescent air mote — ambient wandering point of light.

    Self-lit tiny box on a WanderBehavior path. Like cave plankton
    or distant fireflies. The motion sells the depth — your eye catches
    movement before the object. Different seeds produce different colors
    cycling through warm amber, cool blue, faint green.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"firefly_{seed}")

    # Color cycles through hues by seed
    hues = [
        (1.0, 0.7, 0.2),    # warm amber
        (0.3, 0.5, 1.0),    # cool blue
        (0.2, 0.8, 0.3),    # faint green
        (0.7, 0.3, 0.9),    # dim purple
    ]
    color = hues[seed % len(hues)]

    size = rng.uniform(0.006, 0.015)
    mote = root.attachNewNode(make_box(size, size, size, color))
    mote.setPos(0, 0, rng.uniform(3.0, 12.0))
    mote.setLightOff()
    # Dim glow — visible but not a lamp
    intensity = rng.uniform(4.0, 8.0)
    mote.setColorScale(color[0] * intensity, color[1] * intensity,
                        color[2] * intensity, 0.7)
    mote.setTwoSided(True)
    mote.setBillboardPointEye()

    return root


def build_cave_gravel(parent, seed=0):
    """Single tiny pebble — floor fill. Extremely cheap, very high density.

    One make_rock per spawn. Fills the empty bands between object clusters.
    The quantity does the work, not the individual piece.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"gravel_{seed}")
    s = rng.uniform(0.015, 0.04)
    color = _cavern_color("stone", rng, 0.03)
    pebble = root.attachNewNode(make_rock(
        s * rng.uniform(0.7, 1.3), s * rng.uniform(0.3, 0.6), s * rng.uniform(0.6, 1.2),
        color, rings=3, segments=3, seed=seed, roughness=rng.uniform(0.3, 0.5),
    ))
    pebble.setH(rng.uniform(0, 360))
    pebble.setTwoSided(True)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    root.setScale(5.0)
    root.flattenStrong()
    return root


def build_horizon_form(parent, seed=0):
    """Distant dark silhouette — sells depth at the fog boundary.

    Large flat billboard shape at 30-40m height, dark, barely visible.
    At fog distance it reads as distant cave formations. The parallax
    as the player walks is what sells the illusion of a larger space.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"horizon_{seed}")

    # Dark shape — barely brighter than the fog
    color = (0.04, 0.035, 0.035)
    w = rng.uniform(4.0, 12.0)
    h = rng.uniform(3.0, 10.0)

    shape = root.attachNewNode(make_rock(
        w * 0.5, h * 0.5, w * rng.uniform(0.2, 0.4), color,
        rings=4, segments=5, seed=seed, roughness=rng.uniform(0.3, 0.5),
    ))
    shape.setPos(0, 0, 0)  # grounded — parallax sells depth, not elevation
    shape.setTwoSided(True)

    # No texture, no lighting — just a dark mass at distance
    root.setLightOff()
    root.setColorScale(0.08, 0.07, 0.07, 1.0)

    return root


def build_horizon_mid(parent, seed=0):
    """Mid-distance silhouette — between torch range and fog boundary.

    Smaller than far horizon forms, more varied shapes. 2-3 dark masses
    clustered to read as distant cave architecture. The gap between
    near and far bands is what sells continuous depth.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"horizon_mid_{seed}")

    color = (0.05, 0.045, 0.045)
    count = rng.randint(1, 3)
    for i in range(count):
        w = rng.uniform(2.0, 6.0)
        h = rng.uniform(2.0, 7.0)
        shape = root.attachNewNode(make_rock(
            w * 0.5, h * 0.5, w * rng.uniform(0.15, 0.35), color,
            rings=3, segments=4, seed=seed + i * 47, roughness=rng.uniform(0.25, 0.45),
        ))
        angle = rng.uniform(0, 360)
        dist = rng.uniform(0, 2.0) if count > 1 else 0
        shape.setPos(
            math.cos(math.radians(angle)) * dist,
            math.sin(math.radians(angle)) * dist,
            h * 0.2 + rng.uniform(0, 3.0),
        )
        shape.setTwoSided(True)

    root.setLightOff()
    root.setColorScale(0.09, 0.08, 0.08, 1.0)
    return root


def build_horizon_near(parent, seed=0):
    """Near-distance silhouette — just past torch range.

    Single small dark form, low to ground. Reads as rubble or low
    formations in the middle distance. Highest parallax of the three
    bands because closest to player.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"horizon_near_{seed}")

    color = (0.06, 0.055, 0.05)
    w = rng.uniform(1.5, 4.0)
    h = rng.uniform(1.0, 3.5)
    shape = root.attachNewNode(make_rock(
        w * 0.5, h * 0.5, w * rng.uniform(0.2, 0.5), color,
        rings=3, segments=4, seed=seed, roughness=rng.uniform(0.3, 0.5),
    ))
    shape.setPos(0, 0, h * 0.15 + rng.uniform(0, 1.0))
    shape.setTwoSided(True)

    root.setLightOff()
    root.setColorScale(0.10, 0.09, 0.09, 1.0)
    return root


def build_exit_lure(parent, seed=0):
    """Faint warm glow at extreme fog distance — the unreachable exit.

    Single tiny self-lit point that reads as distant torchlight or daylight
    leaking in. Always placed high and ahead. The player can never reach it
    but it sells the illusion that the cavern leads somewhere.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"exit_lure_{seed}")

    # Tiny warm point — like a distant torch or crack of daylight
    from core.systems.geometry import make_box
    size = rng.uniform(0.08, 0.15)
    point = root.attachNewNode(make_box(size, size, size, (0.95, 0.75, 0.35)))
    point.setPos(0, 0, rng.uniform(4.0, 10.0))
    point.setLightOff()
    point.setColorScale(3.0, 2.2, 1.0, 0.7)
    point.setBillboardPointEye()
    point.setTwoSided(True)

    # Faint ground kiss — tiny decal below the point
    from core.systems.glow_decal import make_glow_decal, get_glow_texture
    glow_tex = get_glow_texture(32, surface="smooth")
    make_glow_decal(root, color=(0.45, 0.30, 0.12), radius=1.5, tex=glow_tex)

    return root


BUILDERS = {
    "rat": (build_rat, "scurry"),
    "leaf": (build_leaf, "drift"),
    "spider": (build_spider, "crawl"),
    "beetle": (build_beetle, "crawl"),
    "boulder": (build_boulder, "static"),
    "grass_tuft": (build_grass_tuft, "static"),
    "rubble": (build_rubble, "static"),
    "leaf_pile": (build_leaf_pile, "static"),
    "dead_log": (build_dead_log, "static"),
    "twig_scatter": (build_twig_scatter, "static"),
    "bone_pile": (build_bone_pile, "static"),
    "stalagmite": (build_stalagmite, "static"),
    "column": (build_column, "static"),
    "mega_column": (build_mega_column, "static"),
    "giant_fungus": (build_giant_fungus, "static"),
    "small_fungus": (build_small_fungus, "static"),
    "moss_patch": (build_moss_patch, "static"),
    "crystal_cluster": (build_crystal_cluster, "static"),
    "hanging_vine": (build_hanging_vine, "static"),
    "moss_boulder": (build_moss_boulder, "static"),
    "ceiling_moss": (build_ceiling_moss, "static"),
    "filament": (build_filament, "sway"),
    "firefly": (build_firefly, "wander"),
    "cave_gravel": (build_cave_gravel, "static"),
    "horizon_form": (build_horizon_form, "static"),
    "horizon_mid": (build_horizon_mid, "static"),
    "horizon_near": (build_horizon_near, "static"),
    "exit_lure": (build_exit_lure, "static"),
}


# -- Ambient Entity ------------------------------------------------------------

# Map entity kinds to spectrum profiles — only bio-lit entities drift
_KIND_TO_SPECTRUM = {
    "giant_fungus": "fungus",
    "crystal_cluster": "crystal",
    "moss_patch": "moss",
    "moss_boulder": "moss",
    "ceiling_moss": "ceiling_moss",
    "small_fungus": "fungus",
}


class AmbientEntity:
    """A single behavior-driven entity in the world."""

    __slots__ = ("kind", "pos", "heading", "node", "behavior",
                 "awake", "height_fn", "chunk_key", "motes",
                 "seed", "spectrum", "base_color_scale", "fade_alpha",
                 "imposter")

    def __init__(self, kind, node, behavior, pos, heading, height_fn=None,
                 chunk_key=None, seed=0):
        self.kind = kind
        self.pos = pos
        self.motes = []  # dust mote nodes spawned on wake
        self.heading = heading
        self.node = node
        self.behavior = behavior
        self.awake = False
        self.height_fn = height_fn
        self.chunk_key = chunk_key
        self.seed = seed
        self.fade_alpha = 1.0  # 0→1 on wake, smooth pop-in
        self.imposter = None   # cheap dark card shown at distance
        self.spectrum = _KIND_TO_SPECTRUM.get(kind)  # None for non-bio entities
        # Capture the initial colorScale so drift is additive from base
        if self.spectrum and node and not node.isEmpty():
            cs = node.getColorScale()
            self.base_color_scale = (cs.getX(), cs.getY(), cs.getZ())
        else:
            self.base_color_scale = None


# -- Ambient Manager -----------------------------------------------------------

class AmbientManager:
    """Manages all ambient life entities. Tick once per frame."""

    MAX_ENTITIES = 25000  # hard cap — refuse spawns beyond this

    def __init__(self, render_node, wake_radius=40.0, sleep_radius=50.0):
        self._render = render_node
        self._wake_r2 = wake_radius * wake_radius
        self._sleep_r2 = sleep_radius * sleep_radius
        self._imposter_r2 = (sleep_radius + 15.0) ** 2  # imposters visible beyond sleep
        self._entities = []         # all entities
        self._active = set()        # currently ticking (set for O(1) add/remove)
        self._active_hard = set()   # collidable subset — only HARD_OBJECTS entities (set for O(1) remove)
        self._check_cursor = 0      # stagger wake/sleep checks across frames
        self._check_batch = 20      # entities to check per frame
        self._max_lights = 8        # GPU budget: nearest N bio-lights only
        self._active_lights = []    # [(dist2, glow_np, entity), ...] sorted
        self._hibernated_n = 0      # incremental counter — no full scans
        self._mote_frame = 0        # throttle: tick motes every 3rd frame
        # Adaptive tick budget — self-regulating batch size
        self._tick_budget_ms = 8.0  # target: 8ms max per tick (leaves 25ms for render)
        self._last_tick_ms = 0.0
        self._adaptive_batch = 150  # starting scan batch, adjusts per tick

    def spawn(self, kind, pos, heading=0, seed=0, height_fn=None, chunk_key=None,
              biome="Cavern_Default"):
        """Create an entity. It starts asleep until tick() wakes it.

        Light layer composition happens here — the affinity table decides
        whether this instance gets a glow shell + ground decal.
        """
        if kind not in BUILDERS:
            return None
        if len(self._entities) >= self.MAX_ENTITIES:
            return None  # hard cap — refuse spawns, don't queue forever
        builder_fn, behavior_name = BUILDERS[kind]
        node = builder_fn(self._render, seed=seed)

        # Biome color override — same geometry, different palette
        color_scales = biome_config("color_scales")
        if kind in color_scales:
            node.setColorScale(*color_scales[kind])

        # Composition: check if this object gets a light layer
        layer = resolve_light_layer(kind, seed, biome=biome)
        if layer is not None:
            apply_light_layer(node, layer, seed)

        node.setPos(pos[0], pos[1], pos[2])
        node.setH(heading)
        node.hide()  # starts hidden

        behavior_cls = BEHAVIORS[behavior_name]
        entity = AmbientEntity(kind, node, None, pos, heading, height_fn, chunk_key, seed=seed)
        entity.behavior = behavior_cls(entity, seed=seed)

        self._entities.append(entity)
        self._hibernated_n += 1  # spawns asleep

        # Companion spawns — biome-aware ecosystem clustering
        companions = biome_config("companions").get(kind, {})
        if companions:
            comp_rng = random.Random(seed + 55555)
            for comp_kind, comp_count in companions.items():
                if comp_kind == "radius":
                    continue
                r = companions.get("radius", 3.0)
                for ci in range(comp_count):
                    angle = comp_rng.uniform(0, 360)
                    dist = comp_rng.uniform(r * 0.3, r)
                    cx = pos[0] + math.cos(math.radians(angle)) * dist
                    cy = pos[1] + math.sin(math.radians(angle)) * dist
                    cz = pos[2]
                    if height_fn:
                        cz = height_fn(cx, cy)
                    self.spawn(comp_kind, pos=(cx, cy, cz),
                               heading=comp_rng.uniform(0, 360),
                               seed=seed + 60000 + ci,
                               height_fn=height_fn, chunk_key=chunk_key)

        return entity

    def despawn_chunk(self, chunk_key):
        """Remove all entities belonging to a chunk — full destroy."""
        to_remove = [e for e in self._entities if e.chunk_key == chunk_key]
        for e in to_remove:
            self._active.discard(e)
            if e.node and not e.node.isEmpty():
                e.node.removeNode()
            self._entities.remove(e)

    def hibernate_chunk(self, chunk_key):
        """Hide all entities in a chunk — keep in memory for fast re-show."""
        for e in self._entities:
            if e.chunk_key == chunk_key:
                self._active.discard(e)
                e.awake = False
                if e.node and not e.node.isEmpty():
                    e.node.hide()
                for m in e.motes:
                    if not m.isEmpty():
                        m.removeNode()
                e.motes = []

    def wake_chunk(self, chunk_key):
        """Re-show a hibernated chunk — zero rebuild cost."""
        for e in self._entities:
            if e.chunk_key == chunk_key and not e.awake:
                if e.node and not e.node.isEmpty():
                    # Don't force show — let the normal wake/sleep radius handle it
                    pass  # next tick cycle will wake entities within radius

    def hibernate_distant(self, cam_pos, keep_radius=1):
        """Hibernate all chunks beyond keep_radius tiles from camera.

        Used by TensionCycle dump phase — clears the world except
        the immediate surroundings, dropping entity pressure fast.
        """
        cx, cy = cam_pos.getX(), cam_pos.getY()
        tile = 288.0  # match _object_tile_size
        center_tx = int(math.floor(cx / tile))
        center_ty = int(math.floor(cy / tile))
        hibernated = set()
        for e in self._entities:
            if e.chunk_key and isinstance(e.chunk_key, tuple) and len(e.chunk_key) == 3:
                _, tx, ty = e.chunk_key
                if abs(tx - center_tx) > keep_radius or abs(ty - center_ty) > keep_radius:
                    if e.awake:
                        self._active.discard(e)
                        if e.kind in HARD_OBJECTS:
                            self._active_hard.discard(e)
                        e.awake = False
                        self._hibernated_n += 1
                        if e.node and not e.node.isEmpty():
                            e.node.hide()
                        for m in e.motes:
                            if not m.isEmpty():
                                m.removeNode()
                        e.motes = []
                    hibernated.add(e.chunk_key)
        return hibernated

    @property
    def hibernated_count(self):
        """How many entities are alive but sleeping (in purgatory)."""
        return self._hibernated_n

    def _make_imposter(self, entity):
        """Create a cheap dark silhouette card for a distant entity.

        One flat billboard — no texture, no lighting, no tick cost.
        Just a dark shape that fills the visual field at distance.
        Removed when entity wakes or goes beyond imposter range.
        """
        cr = HARD_OBJECTS.get(entity.kind, 1.0)
        from panda3d.core import CardMaker, TransparencyAttrib
        cm = CardMaker("imposter")
        hw = cr * 0.5   # smaller — subtle, not obvious cards
        hh = cr * 1.0
        cm.setFrame(-hw, hw, 0, hh)
        imp = self._render.attachNewNode(cm.generate())
        imp.setPos(entity.pos[0], entity.pos[1], entity.pos[2])
        imp.setBillboardPointEye()
        imp.setColor(0.05, 0.045, 0.045, 0.5)  # darker, more transparent — blends into fog
        imp.setLightOff()
        imp.setDepthWrite(False)
        imp.setBin("transparent", 5)
        imp.setTransparency(TransparencyAttrib.MAlpha)
        entity.imposter = imp

    def collide_point(self, px, py, player_radius=0.4):
        """Check if a point collides with any hard active entity.

        Returns (slide_x, slide_y) — the corrected position after pushing
        out of all colliding objects. If no collision, returns (px, py).

        Uses sphere-vs-sphere: player radius + object collision radius.
        Slide vector = push along the surface normal so movement continues
        tangent to the object rather than stopping dead.

        Only iterates _active_hard (collidable subset), not all active entities.
        Collision radius uses stored base_radius when available (curtain columns,
        mega columns scale with actual geometry width).
        """
        sx, sy = px, py
        for e in self._active_hard:
            # Use stored base_radius if builder tagged it, otherwise HARD_OBJECTS default
            cr = HARD_OBJECTS.get(e.kind, 1.0)
            if e.node and not e.node.isEmpty():
                stored = e.node.getPythonTag("base_radius")
                if stored is not None:
                    cr = max(cr, stored)
            ex, ey = e.pos[0], e.pos[1]
            dx = sx - ex
            dy = sy - ey
            d2 = dx * dx + dy * dy
            min_dist = player_radius + cr
            min_d2 = min_dist * min_dist
            if d2 < min_d2 and d2 > 0.0001:
                # Push out along the normal (player - entity center)
                dist = math.sqrt(d2)
                nx = dx / dist
                ny = dy / dist
                penetration = min_dist - dist
                sx += nx * penetration
                sy += ny * penetration
        return sx, sy

    def tick(self, dt, cam_pos):
        """Per-frame update: staggered wake/sleep, tick active behaviors."""
        cx, cy = cam_pos.getX(), cam_pos.getY()

        # Freeze scan when stationary — skip wake/sleep if player hasn't moved 5m.
        import time as _time
        _tick_start = _time.monotonic()
        moved = True
        if hasattr(self, '_last_scan_pos'):
            lx, ly = self._last_scan_pos
            ddx, ddy = cx - lx, cy - ly
            if ddx * ddx + ddy * ddy < 25.0:  # 5m squared
                moved = False
        if moved:
            self._last_scan_pos = (cx, cy)

        # Adaptive wake/sleep scan — only runs when player is moving.
        n = len(self._entities)
        if n > 0 and moved:
            # Adjust batch based on last tick performance
            if self._last_tick_ms > self._tick_budget_ms * 1.2:
                self._adaptive_batch = max(50, self._adaptive_batch - 30)
            elif self._last_tick_ms < self._tick_budget_ms * 0.6:
                self._adaptive_batch = min(400, self._adaptive_batch + 20)
            batch = self._adaptive_batch
            for _ in range(batch):
                if self._check_cursor >= n:
                    self._check_cursor = 0
                e = self._entities[self._check_cursor]
                self._check_cursor += 1

                dx = e.pos[0] - cx
                dy = e.pos[1] - cy
                d2 = dx * dx + dy * dy

                # Anchors wake at extended range — landmarks visible first
                wake_mult = ANCHOR_WAKE_MULT.get(e.kind, 1.0)
                entity_wake_r2 = self._wake_r2 * (wake_mult * wake_mult)

                if not e.awake and d2 < entity_wake_r2:
                    # Full wake — show real geometry
                    e.awake = True
                    self._hibernated_n -= 1
                    e.fade_alpha = 1.0  # instant show — fog handles the transition
                    e.node.show()
                    e.node.setAlphaScale(1.0)
                    self._active.add(e)
                    if e.kind in HARD_OBJECTS:
                        self._active_hard.add(e)
                    # Hide imposter if it exists
                    if e.imposter and not e.imposter.isEmpty():
                        e.imposter.removeNode()
                        e.imposter = None
                    # Spawn motes on wake
                    if not e.motes:
                        mote_cfg = biome_config("motes").get(e.kind)
                        if mote_cfg is None:
                            mote_cfg = e.node.getPythonTag("mote_config")
                        if mote_cfg:
                            origin = (e.pos[0], e.pos[1], e.pos[2])
                            e.motes = _spawn_motes(e.node, mote_cfg, origin)
                entity_sleep_r2 = self._sleep_r2 * (wake_mult * wake_mult)
                if e.awake and d2 > entity_sleep_r2:
                    # Sleep — hide real geometry, show imposter if in range
                    e.awake = False
                    self._hibernated_n += 1
                    e.node.hide()
                    self._active.discard(e)
                    if e.kind in HARD_OBJECTS:
                        self._active_hard.discard(e)
                    for m in e.motes:
                        if not m.isEmpty():
                            m.removeNode()
                    e.motes = []
                    # Spawn imposter silhouette if within imposter range
                    if d2 < self._imposter_r2 and HARD_OBJECTS.get(e.kind):
                        self._make_imposter(e)
                elif not e.awake and e.imposter is None and d2 < self._imposter_r2:
                    # Not awake, no imposter, but in imposter range — create one
                    if HARD_OBJECTS.get(e.kind):
                        self._make_imposter(e)
                elif e.imposter and d2 > self._imposter_r2:
                    # Beyond imposter range — remove it
                    if not e.imposter.isEmpty():
                        e.imposter.removeNode()
                    e.imposter = None
        # Tick active behaviors + motes (throttled) + spectrum drift
        # Three optimizations:
        # 1. Static entities skip behavior tick entirely (StaticBehavior.tick = pass)
        # 2. Behind-camera entities tick behavior every 6th frame
        # 3. Spectrum drift staggered: each entity drifts every 4th frame
        self._mote_frame += 1
        tick_motes_this_frame = (self._mote_frame % 3 == 0)
        try:
            from panda3d.core import ClockObject
            elapsed = ClockObject.getGlobalClock().getFrameTime()
        except Exception:
            elapsed = 0

        # Camera forward vector for behind-check (passed via cam_pos heading)
        cam_h = getattr(self, '_cam_heading', 0.0)
        fwd_x = -math.sin(math.radians(cam_h))
        fwd_y = math.cos(math.radians(cam_h))
        frame_n = self._mote_frame  # reuse as global frame counter

        # Fog-distance threshold: entities beyond this are 50%+ fog-painted.
        # Skip their tick entirely — visual noise at that distance.
        fog_skip_r2 = 625.0  # 25m squared

        for idx, e in enumerate(self._active):
            dx = e.pos[0] - cx
            dy = e.pos[1] - cy
            d2 = dx * dx + dy * dy

            # Fog-covered: skip everything — behavior, motes, spectrum
            if d2 > fog_skip_r2:
                continue

            # Behind-camera check
            dot = dx * fwd_x + dy * fwd_y
            behind = dot < 0

            # 1. Behavior tick: skip static entirely, throttle behind-camera
            is_static = isinstance(e.behavior, StaticBehavior)
            if not is_static:
                if behind:
                    if frame_n % 6 == idx % 6:
                        e.behavior.tick(dt * 6)
                else:
                    e.behavior.tick(dt)

            # 2. Motes: already throttled to every 3rd frame
            if tick_motes_this_frame and e.motes:
                tick_motes(e.motes, dt * 3)

            # 3. Spectrum drift: stagger every 4th frame per entity
            if e.spectrum and e.base_color_scale and (frame_n % 4 == idx % 4):
                rs, gs, bs = SpectrumEngine.drift(e.spectrum, elapsed, e.seed)
                br, bg, bb = e.base_color_scale
                e.node.setColorScale(br + rs, bg + gs, bb + bs, 1.0)

        # Record tick cost for adaptive budget
        self._last_tick_ms = (_time.monotonic() - _tick_start) * 1000.0

    def reseat_ground(self, old_height_fn, new_height_fn):
        """Reseat all entities when switching ground modes.

        Shifts each entity's Z by the difference between old and new
        ground height at its XY position. Ceiling entities, leaves, etc.
        move correctly because their internal offsets are relative to root Z.
        """
        for e in self._entities:
            if e.node and not e.node.isEmpty():
                x, y = e.pos[0], e.pos[1]
                old_z = old_height_fn(x, y)
                new_z = new_height_fn(x, y)
                delta = new_z - old_z
                cur_z = e.node.getZ()
                e.node.setZ(cur_z + delta)
            e.height_fn = new_height_fn

    @property
    def total_count(self):
        return len(self._entities)

    @property
    def awake_count(self):
        """Entities that are alive and not hibernated — the real memory pressure."""
        return len(self._entities) - self._hibernated_n

    @property
    def active_count(self):
        return len(self._active)

    def kind_census(self):
        """Per-kind entity counts: {kind: (active, total, hibernated)}."""
        from collections import defaultdict
        counts = defaultdict(lambda: [0, 0, 0])  # [active, total, hibernated]
        active_set = set(id(e) for e in self._active)
        for e in self._entities:
            c = counts[e.kind]
            c[1] += 1  # total
            if id(e) in active_set:
                c[0] += 1  # active
            if not e.awake:
                c[2] += 1  # hibernated
        return {k: tuple(v) for k, v in counts.items()}
