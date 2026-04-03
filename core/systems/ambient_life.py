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

# Companion spawns — objects that cluster near other objects.
# When a base object spawns, also spawn N companions at random positions around it.
# Grass grows near boulders, columns, moss. Not near crystals (too harsh).
COMPANION_SPAWNS = {
    "boulder":    {"grass_tuft": 3, "radius": 4.0},
    "column":     {"grass_tuft": 4, "radius": 5.0},
    "moss_patch": {"grass_tuft": 2, "radius": 2.0},
    "dead_log":   {"grass_tuft": 2, "radius": 2.5},
    "stalagmite": {"grass_tuft": 2, "radius": 3.0},
}

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
            {"color": (0.08, 0.35, 0.06), "glow": (2.0, 5.0, 1.5), "decal": (0.1, 0.5, 0.08)},
            {"color": (0.35, 0.20, 0.05), "glow": (4.0, 2.5, 0.8), "decal": (1.0, 0.6, 0.15)},
            {"color": (0.06, 0.10, 0.35), "glow": (1.5, 2.0, 5.0), "decal": (0.08, 0.15, 0.5)},
            {"color": (0.25, 0.06, 0.30), "glow": (3.5, 1.0, 4.0), "decal": (0.5, 0.1, 0.6)},
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
            {"color": (0.15, 0.18, 0.35), "glow": (3.0, 3.5, 6.0), "decal": (0.4, 0.5, 1.2)},
            {"color": (0.30, 0.10, 0.35), "glow": (4.0, 1.5, 5.0), "decal": (0.8, 0.25, 1.0)},
        ],
        "motes": {
            "count": 4, "radius": 1.5, "height": 2.0,
            "downward": False, "fall_speed": 0.0,
            "sway_amp": 0.08, "sway_freq": 0.06,
            "float_compression": 0.1,  # near-frozen sparkle
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
        "color": (1.0, 0.7, 0.2), "count": 5, "radius": 2.0, "height": 8.0,
        "downward": True, "fall_speed": 0.02,
        "sway_amp": 0.05, "sway_freq": 0.08,
        "float_compression": 0.3,       # gentle straight fall — dust in a shaft
    },
    "giant_fungus": {
        "color": (0.5, 0.1, 0.7), "count": 8, "radius": 3.0, "height": 4.0,
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
        "color": (0.3, 0.35, 0.6), "count": 4, "radius": 1.5, "height": 2.0,
        "downward": False, "fall_speed": 0.0,
        "sway_amp": 0.06, "sway_freq": 0.04,
        "float_compression": 0.08,      # frozen sparkle
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
}


def _cavern_color(key, rng, variation=0.02):
    """Get a color from the shared palette with small random variation."""
    base = CAVERN_PALETTE.get(key, (0.10, 0.10, 0.10))
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
    """Boulder — stacked sedimentary slabs with angular breaks.

    2-3 layers of flat make_rock slabs at slightly different widths.
    Top slab overhangs bottom. Reads as layered geology, not a blob.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"boulder_{seed}")

    total_height = rng.uniform(2.7, 3.3)
    base_width = rng.uniform(4.5, 7.5)
    base_depth = base_width * rng.uniform(0.6, 0.85)
    slab_count = rng.randint(2, 3)
    slab_h = total_height / slab_count

    z = 0
    for si in range(slab_count):
        # Each slab slightly different width — angular, not smooth
        sw = base_width * rng.uniform(0.85, 1.1) * (1.0 + si * 0.05)
        sd = base_depth * rng.uniform(0.85, 1.1)
        color = _cavern_color("stone", rng, 0.03)
        slab = root.attachNewNode(make_rock(
            sw * 0.5, slab_h * 0.45, sd * 0.5, color,
            rings=5, segments=8, seed=seed + si * 31,
            roughness=rng.uniform(0.15, 0.30),  # lower roughness = flatter faces
        ))
        # Slight offset per slab — overhang effect
        slab.setPos(rng.uniform(-0.3, 0.3), rng.uniform(-0.2, 0.2), z)
        slab.setH(rng.uniform(-8, 8))
        slab.setTwoSided(True)
        z += slab_h * 0.8  # slight overlap

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
    """Cave grass clump — tall dead blades leaning from a central root.

    Varied heights, stronger lean, some blades curving outward.
    Reads as a dried clump of cave sedge, not identical sticks.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"grass_{seed}")
    blade_count = rng.randint(5, 12)
    # Tallest blade sets the character — others subordinate
    max_h = rng.uniform(0.15, 0.35)
    for i in range(blade_count):
        rank = i / blade_count
        h = max_h * rng.uniform(0.4, 1.0 - rank * 0.3)
        w = rng.uniform(0.005, 0.012)
        color = _cavern_color("dead_organic", rng, 0.03)
        blade = root.attachNewNode(make_rock(
            w * 0.5, h * 0.4, w * 0.15, color,
            rings=3, segments=3, seed=seed + i * 19, roughness=rng.uniform(0.1, 0.25),
        ))
        # Spread from center, lean outward
        angle = rng.uniform(0, 360)
        dist = rng.uniform(0.01, 0.06)
        blade.setPos(math.cos(math.radians(angle)) * dist,
                     math.sin(math.radians(angle)) * dist, h * 0.5)
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
    anchor_count = rng.randint(1, 2)
    frag_count = rng.randint(3, 7)
    for i in range(anchor_count):
        s = rng.uniform(0.10, 0.25)
        color = _cavern_color("stone", rng, 0.03)
        piece = make_rock(
            s * rng.uniform(0.8, 1.4),
            s * rng.uniform(0.5, 0.9),
            s * rng.uniform(0.7, 1.3),
            color, rings=5, segments=6, seed=seed + i,
            roughness=rng.uniform(0.35, 0.55),
        )
        pn = root.attachNewNode(piece)
        pn.setPos(rng.uniform(-0.2, 0.2), rng.uniform(-0.2, 0.2), 0)
        pn.setH(rng.uniform(0, 360))
        pn.setR(rng.uniform(-20, 20))  # tumbled angle
        pn.setTwoSided(True)
    for i in range(frag_count):
        s = rng.uniform(0.03, 0.10)
        color = _cavern_color("stone", rng, 0.02)
        piece = make_rock(
            s * rng.uniform(0.6, 1.4),
            s * rng.uniform(0.3, 0.7),
            s * rng.uniform(0.5, 1.2),
            color, rings=3, segments=4, seed=seed + 100 + i,
            roughness=rng.uniform(0.4, 0.7),
        )
        pn = root.attachNewNode(piece)
        pn.setPos(rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5), 0)
        pn.setH(rng.uniform(0, 360))
        pn.setR(rng.uniform(-30, 30))
        pn.setTwoSided(True)
    tex = get_material_texture("stone_heavy", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    sc = _mat_scale("stone_heavy")
    root.setTexScale(ts, sc, sc)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    root.setScale(5.0)
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

    # Wide variety: stubby thick ones to tall thin spires
    height = rng.uniform(1.0, 6.0)
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

    # Tall narrow rock — height dominates
    rock = root.attachNewNode(make_rock(
        base_w, height * 0.5, base_d, color,
        rings=6, segments=7, seed=seed,
        roughness=rng.uniform(0.2, 0.4),
    ))
    rock.setPos(0, 0, 0)
    rock.setTwoSided(True)

    # Sometimes a smaller one beside it
    if rng.random() < 0.4:
        s = rng.uniform(0.3, 0.6)
        small = root.attachNewNode(make_rock(
            base_w * s, height * 0.5 * s, base_d * s, color,
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
    """Massive cave column — 4 profile variants from same make_rock calls.

    Profiles (selected by seed):
        hourglass: wide-narrow-wide (classical)
        pillar:    near-uniform, slight taper (structural)
        curtain:   wide+thin like a wall/drape (flowstone)
        broken:    base only, abrupt end (collapsed)
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"column_{seed}")

    profile = rng.choice(["hourglass", "pillar", "curtain", "broken"])
    total_height = rng.uniform(12.0, 20.0)
    base_radius = rng.uniform(1.5, 3.0)

    if profile == "hourglass":
        waist_radius = base_radius * rng.uniform(0.3, 0.5)
        top_radius = base_radius * rng.uniform(0.8, 1.2)
    elif profile == "pillar":
        waist_radius = base_radius * rng.uniform(0.8, 0.95)  # nearly uniform
        top_radius = base_radius * rng.uniform(0.7, 0.9)     # slight taper
    elif profile == "curtain":
        base_radius *= rng.uniform(1.5, 2.5)  # extra wide
        waist_radius = base_radius * rng.uniform(0.6, 0.8)
        top_radius = base_radius * rng.uniform(0.5, 0.7)
        # Flatten depth for curtain/wall feel
    elif profile == "broken":
        total_height *= rng.uniform(0.3, 0.5)  # much shorter — it broke
        waist_radius = base_radius * rng.uniform(0.7, 0.9)
        top_radius = base_radius * rng.uniform(0.4, 0.6)  # jagged top

    # Mineral color — same cool spectrum as stalagmites
    mineral_bases = [
        (0.11, 0.11, 0.13),
        (0.13, 0.12, 0.13),
        (0.10, 0.10, 0.12),
    ]
    base_color = rng.choice(mineral_bases)
    sv = rng.uniform(-0.02, 0.02)
    color = (base_color[0] + sv, base_color[1] + sv * 0.7, base_color[2] + sv * 0.5)

    # Curtain profile: flatten the depth axis for wall/drape silhouette
    depth_scale = 0.3 if profile == "curtain" else rng.uniform(0.7, 1.0)

    # Bottom section — wide base tapering to waist
    bottom_h = total_height * rng.uniform(0.35, 0.45)
    bottom = root.attachNewNode(make_rock(
        base_radius, bottom_h * 0.5, base_radius * depth_scale, color,
        rings=8, segments=8, seed=seed,
        roughness=rng.uniform(0.2, 0.35),
    ))
    bottom.setPos(0, 0, 0)
    bottom.setTwoSided(True)

    # Waist section — narrow connecting neck
    waist_h = total_height * rng.uniform(0.15, 0.25)
    waist_z = bottom_h * 0.7
    sv2 = rng.uniform(-0.015, 0.015)
    waist_color = (color[0] + sv2, color[1] + sv2, color[2] + sv2)
    waist = root.attachNewNode(make_rock(
        waist_radius, waist_h * 0.5, waist_radius * depth_scale, waist_color,
        rings=5, segments=6, seed=seed + 33,
        roughness=rng.uniform(0.15, 0.3),
    ))
    waist.setPos(0, 0, waist_z + waist_h * 0.3)
    waist.setTwoSided(True)

    # Top section — rises into darkness (skipped for broken profile)
    if profile != "broken":
        top_h = total_height - bottom_h - waist_h
        top_z = waist_z + waist_h * 0.5
        sv3 = rng.uniform(-0.015, 0.015)
        top_color = (color[0] + sv3, color[1] + sv3, color[2] + sv3)
        top = root.attachNewNode(make_rock(
            top_radius, top_h * 0.5, top_radius * depth_scale, top_color,
            rings=8, segments=8, seed=seed + 66,
            roughness=rng.uniform(0.2, 0.35),
        ))
        top.setPos(0, 0, top_z + top_h * 0.3)
        top.setTwoSided(True)

    # Texture + damping
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
    """Cathedral-scale column — 40-80m tall. Makes the cavern feel hundreds of feet deep."""
    rng = random.Random(seed)
    root = parent.attachNewNode(f"mega_column_{seed}")

    total_height = rng.uniform(80.0, 160.0)
    base_radius = rng.uniform(5.0, 12.0)
    profile = rng.choice(["pillar", "hourglass", "curtain"])

    if profile == "hourglass":
        waist_radius = base_radius * rng.uniform(0.25, 0.4)
        top_radius = base_radius * rng.uniform(0.9, 1.3)
    elif profile == "pillar":
        waist_radius = base_radius * rng.uniform(0.8, 0.95)
        top_radius = base_radius * rng.uniform(0.7, 0.9)
    else:  # curtain
        base_radius *= rng.uniform(1.5, 2.5)
        waist_radius = base_radius * rng.uniform(0.5, 0.7)
        top_radius = base_radius * rng.uniform(0.4, 0.6)

    depth_scale = 0.25 if profile == "curtain" else rng.uniform(0.7, 1.0)
    color = _cavern_color("stone", rng, 0.02)

    # Bottom — massive base
    bottom_h = total_height * 0.4
    bottom = root.attachNewNode(make_rock(
        base_radius, bottom_h * 0.5, base_radius * depth_scale, color,
        rings=10, segments=12, seed=seed, roughness=rng.uniform(0.2, 0.35),
    ))
    bottom.setPos(0, 0, 0)
    bottom.setTwoSided(True)

    # Waist
    waist_h = total_height * 0.2
    waist_z = bottom_h * 0.7
    waist = root.attachNewNode(make_rock(
        waist_radius, waist_h * 0.5, waist_radius * depth_scale, color,
        rings=6, segments=8, seed=seed + 33, roughness=rng.uniform(0.15, 0.3),
    ))
    waist.setPos(0, 0, waist_z)
    waist.setTwoSided(True)

    # Top — vanishes into darkness above
    top_h = total_height - bottom_h - waist_h
    top_z = waist_z + waist_h * 0.5
    top = root.attachNewNode(make_rock(
        top_radius, top_h * 0.5, top_radius * depth_scale, color,
        rings=10, segments=12, seed=seed + 66, roughness=rng.uniform(0.2, 0.35),
    ))
    top.setPos(0, 0, top_z + top_h * 0.3)
    top.setTwoSided(True)

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
    glow_color = (0.45, 0.08, 0.55)

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
            spire.setColorScale(2.5, 0.8, 3.0, 1.0)
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

        # Waist — transition zone, starts glowing
        waist_h = total_h * 0.3
        waist_z = bottom_h * 0.7
        waist = root.attachNewNode(make_rock(
            waist_r, waist_h * 0.4, waist_r * 0.8, glow_color,
            rings=4, segments=6, seed=seed + 33, roughness=rng.uniform(0.12, 0.22),
        ))
        waist.setPos(0, 0, waist_z)
        waist.setTwoSided(True)
        waist.setTexGen(ts, TexGenAttrib.MWorldPosition)
        waist.setTexture(ts, tex)
        waist.setTexScale(ts, sc, sc)
        waist.setLightOff()
        waist.setColorScale(1.5, 0.5, 2.0, 1.0)

        # Cap — sits ON TOP of stem, not floating. Glows hot.
        cap_z = waist_z + waist_h * 0.6
        cap_h = total_h * 0.25
        cap = root.attachNewNode(make_rock(
            cap_r, cap_h * 0.3, cap_r * 0.9, glow_color,
            rings=4, segments=6, seed=seed + 99, roughness=rng.uniform(0.08, 0.18),
        ))
        cap.setPos(0, 0, cap_z)
        cap.setTwoSided(True)
        cap.setLightOff()
        cap.setColorScale(3.0, 1.0, 4.0, 1.0)

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
            sat.setColorScale(2.0, 0.7, 2.5, 1.0)

    # Ground glow decal — decals ARE the lighting on Metal
    glow_tex = get_glow_texture(64, surface="wet_stone")
    make_glow_decal(root, color=(0.6, 0.15, 0.8), radius=base_r * 3.0, tex=glow_tex)

    # Light shaft — extends from mid-height to ground
    shaft_tex = get_shaft_texture()
    shaft_h = total_h * 0.5
    make_light_shaft(root, color=(0.6, 0.15, 0.8), shaft_height=shaft_h, shaft_width=base_r * 2.0, tex=shaft_tex)

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
    make_glow_decal(root, color=(0.1, 0.5, 0.08), radius=5.0, tex=tex)

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
        shard.setColorScale(3.0, 3.5, 5.0, 1.0)


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
    crystal_decal = make_glow_decal(root, color=(0.4, 0.5, 1.2), radius=trunk_r * 3.0, tex=glow_tex)
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
    """Amber bioluminescent moss — 4 cards, zero 3D geometry, zero point lights.

    The full illusion:
    1. Billboard blob at ceiling height (impostor for moss cluster)
    2. Mote shaft connecting ceiling to ground (baked particle specks)
    3. Ground glow decal (warm amber pool)

    Player sees: glowing amber above, motes drifting in a light column,
    warm pool on the floor. Total cost: 3 cards + 1 decal.
    """
    from core.systems.glow_decal import (
        make_glow_decal, get_glow_texture,
        make_light_shaft, get_mote_shaft_texture,
        make_ceiling_blob, get_ceiling_blob_texture,
    )

    rng = random.Random(seed)
    root = parent.attachNewNode(f"ceil_moss_{seed}")

    # Cluster hangs from a height — the "ceiling"
    hang_z = rng.uniform(15.0, 25.0)

    # 1. Billboard blob at ceiling — one card replaces 5-12 rock meshes
    #    Cranked brightness — this is the SOURCE, it should glow hot
    blob_tex = get_ceiling_blob_texture(64)
    blob_radius = rng.uniform(2.5, 4.5)
    blob = make_ceiling_blob(root, color=(5.0, 3.5, 1.2), blob_radius=blob_radius,
                             height=hang_z, tex=blob_tex)

    # 2. Mote shaft — directed downlight like a lamp, baked mote specks
    #    Narrow at top, spreads at ground = natural lamp cone
    mote_tex = get_mote_shaft_texture(32, 128, seed=seed)
    shaft = make_light_shaft(root, color=(1.0, 0.7, 0.2),
                             shaft_height=hang_z - 1.0, shaft_width=4.0, tex=mote_tex)

    # 3. Ground glow decal — the actual "lamp pool" on the floor
    #    Large radius, cranked color — this IS the illumination
    glow_tex = get_glow_texture(128, surface="wet_stone")
    decal = make_glow_decal(root, color=(1.2, 0.8, 0.25), radius=10.0, tex=glow_tex)

    return root


def build_hanging_vine(parent, seed=0):
    """Thin vine draping downward — hangs from column heights, adds vertical softness.

    Dark organic, barely visible until backlit by bioluminescence.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"vine_{seed}")

    # Vine hangs from a random height (as if from a column or ceiling)
    hang_height = rng.uniform(8.0, 22.0)
    # Reach half to 2/3 the distance to the ground
    vine_length = rng.uniform(hang_height * 0.5, hang_height * 0.67)
    segment_count = rng.randint(6, 12)
    seg_len = vine_length / segment_count

    color = (0.05, 0.06, 0.04)  # dark green-brown, nearly invisible
    x_drift = 0.0
    y_drift = 0.0

    for i in range(segment_count):
        w = rng.uniform(0.01, 0.025)
        seg = root.attachNewNode(make_box(w, w, seg_len * 0.45, color))
        z = hang_height - i * seg_len
        x_drift += rng.uniform(-0.15, 0.15)
        y_drift += rng.uniform(-0.15, 0.15)
        seg.setPos(x_drift, y_drift, z)
        seg.setR(rng.uniform(-8, 8))
        seg.setTwoSided(True)

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
    shape.setPos(0, 0, h * 0.3 + rng.uniform(0, 5.0))
    shape.setTwoSided(True)

    # No texture, no lighting — just a dark mass at distance
    root.setLightOff()
    root.setColorScale(0.08, 0.07, 0.07, 1.0)

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
    "moss_patch": (build_moss_patch, "static"),
    "crystal_cluster": (build_crystal_cluster, "static"),
    "hanging_vine": (build_hanging_vine, "static"),
    "moss_boulder": (build_moss_boulder, "static"),
    "ceiling_moss": (build_ceiling_moss, "static"),
    "filament": (build_filament, "sway"),
    "firefly": (build_firefly, "wander"),
    "cave_gravel": (build_cave_gravel, "static"),
    "horizon_form": (build_horizon_form, "static"),
}


# -- Ambient Entity ------------------------------------------------------------

class AmbientEntity:
    """A single behavior-driven entity in the world."""

    __slots__ = ("kind", "pos", "heading", "node", "behavior",
                 "awake", "height_fn", "chunk_key", "motes")

    def __init__(self, kind, node, behavior, pos, heading, height_fn=None, chunk_key=None):
        self.kind = kind
        self.pos = pos
        self.motes = []  # dust mote nodes spawned on wake
        self.heading = heading
        self.node = node
        self.behavior = behavior
        self.awake = False
        self.height_fn = height_fn
        self.chunk_key = chunk_key


# -- Ambient Manager -----------------------------------------------------------

class AmbientManager:
    """Manages all ambient life entities. Tick once per frame."""

    def __init__(self, render_node, wake_radius=40.0, sleep_radius=50.0):
        self._render = render_node
        self._wake_r2 = wake_radius * wake_radius
        self._sleep_r2 = sleep_radius * sleep_radius
        self._entities = []         # all entities
        self._active = set()        # currently ticking (set for O(1) add/remove)
        self._check_cursor = 0      # stagger wake/sleep checks across frames
        self._check_batch = 20      # entities to check per frame
        self._max_lights = 8        # GPU budget: nearest N bio-lights only
        self._active_lights = []    # [(dist2, glow_np, entity), ...] sorted

    def spawn(self, kind, pos, heading=0, seed=0, height_fn=None, chunk_key=None,
              biome="Cavern_Default"):
        """Create an entity. It starts asleep until tick() wakes it.

        Light layer composition happens here — the affinity table decides
        whether this instance gets a glow shell + ground decal.
        """
        if kind not in BUILDERS:
            return None
        builder_fn, behavior_name = BUILDERS[kind]
        node = builder_fn(self._render, seed=seed)

        # Composition: check if this object gets a light layer
        layer = resolve_light_layer(kind, seed, biome=biome)
        if layer is not None:
            apply_light_layer(node, layer, seed)

        node.setPos(pos[0], pos[1], pos[2])
        node.setH(heading)
        node.hide()  # starts hidden

        behavior_cls = BEHAVIORS[behavior_name]
        entity = AmbientEntity(kind, node, None, pos, heading, height_fn, chunk_key)
        entity.behavior = behavior_cls(entity, seed=seed)

        self._entities.append(entity)

        # Companion spawns — grass clusters near boulders, columns, etc.
        companions = COMPANION_SPAWNS.get(kind, {})
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
        """Remove all entities belonging to a chunk."""
        to_remove = [e for e in self._entities if e.chunk_key == chunk_key]
        for e in to_remove:
            self._active.discard(e)
            if e.node and not e.node.isEmpty():
                e.node.removeNode()
            self._entities.remove(e)

    def tick(self, dt, cam_pos):
        """Per-frame update: staggered wake/sleep, tick active behaviors."""
        cx, cy = cam_pos.getX(), cam_pos.getY()

        # Staggered wake/sleep — batch scales with entity count
        # Target: full scan in ~3 seconds (8 ticks/sec × 3s = 24 ticks)
        n = len(self._entities)
        if n > 0:
            batch = max(self._check_batch, n // 24)
            for _ in range(batch):
                if self._check_cursor >= n:
                    self._check_cursor = 0
                e = self._entities[self._check_cursor]
                self._check_cursor += 1

                dx = e.pos[0] - cx
                dy = e.pos[1] - cy
                d2 = dx * dx + dy * dy

                if not e.awake and d2 < self._wake_r2:
                    e.awake = True
                    e.node.show()
                    self._active.add(e)
                    # Spawn motes on wake — config from MOTE_PRESETS or light layer
                    if not e.motes:
                        mote_cfg = MOTE_PRESETS.get(e.kind)
                        if mote_cfg is None:
                            mote_cfg = e.node.getPythonTag("mote_config")
                        if mote_cfg:
                            origin = (e.pos[0], e.pos[1], e.pos[2])
                            e.motes = _spawn_motes(e.node, mote_cfg, origin)
                elif e.awake and d2 > self._sleep_r2:
                    e.awake = False
                    e.node.hide()
                    self._active.discard(e)
                    # Clear motes on sleep
                    for m in e.motes:
                        if not m.isEmpty():
                            m.removeNode()
                    e.motes = []
        # Tick active behaviors + motes
        for e in self._active:
            e.behavior.tick(dt)
            if e.motes:
                tick_motes(e.motes, dt)

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
    def active_count(self):
        return len(self._active)
