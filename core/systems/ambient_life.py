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
    SamplerState, PointLight,
)
from core.systems.geometry import make_box, make_sphere, make_bevel_box, make_pebble_cluster, make_rock


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


BEHAVIORS = {
    "scurry": ScurryBehavior,   # rats, small creatures
    "drift": DriftBehavior,     # leaves, dust, embers
    "crawl": CrawlBehavior,     # spiders, insects
    "static": StaticBehavior,   # boulders, landmarks, ruins
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


def _cavern_color(key, rng, variation=0.02):
    """Get a color from the shared palette with small random variation."""
    base = CAVERN_PALETTE.get(key, (0.10, 0.10, 0.10))
    sv = rng.uniform(-variation, variation)
    return (base[0] + sv, base[1] + sv * 0.7, base[2] + sv * 0.5)


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
    """Tiny leaf — flat box, subtle color."""
    rng = random.Random(seed)
    root = parent.attachNewNode(f"leaf_{seed}")
    w = rng.uniform(0.03, 0.06)
    color = _cavern_color("dead_organic", rng, 0.02)
    leaf = root.attachNewNode(make_box(w, w * 0.15, w * 0.7, color))
    leaf.setR(rng.uniform(-30, 30))
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
    """Boulder — noise-displaced rock with flat base, seated in ground.

    Uses make_rock (irregular displaced sphere) instead of make_sphere.
    Single shape, no decorations. The displacement IS the roughness.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"boulder_{seed}")

    # 1.5× scale from #6 proportions
    height = rng.uniform(2.7, 3.3)
    width = rng.uniform(4.5, 7.5)
    depth = width * rng.uniform(0.6, 0.85)

    color = _cavern_color("stone", rng, 0.03)

    # Single make_rock call — it handles irregularity + flat base internally
    rock = root.attachNewNode(make_rock(
        width * 0.5, height * 0.5, depth * 0.5, color,
        rings=8, segments=10, seed=seed,
        roughness=rng.uniform(0.25, 0.45),
    ))
    rock.setPos(0, 0, 0)
    rock.setTwoSided(True)

    # Stone texture with situ blend — auto-projected via world position
    stone_tex = get_material_texture("stone_heavy", seed=seed)
    ts = TextureStage("stone")
    ts.setMode(TextureStage.MModulate)  # multiply with vertex color
    rock.setTexGen(ts, TexGenAttrib.MWorldPosition)
    rock.setTexture(ts, stone_tex)
    # Scale the texture projection to match boulder size
    rock.setTexScale(ts, 0.15, 0.15)

    # Dampen light response
    root.setColorScale(0.55, 0.50, 0.48, 1.0)

    return root


def build_grass_tuft(parent, seed=0):
    """Small cluster of grass blades — thin fins at slight angles."""
    rng = random.Random(seed)
    root = parent.attachNewNode(f"grass_{seed}")
    blade_count = rng.randint(3, 7)
    for i in range(blade_count):
        h = rng.uniform(0.08, 0.20)
        w = rng.uniform(0.008, 0.015)
        sv = rng.uniform(-0.02, 0.02)
        # Dry, dark grass — derived from shared palette
        color = _cavern_color("dead_organic", rng, 0.02)
        blade = root.attachNewNode(make_box(w, h, w * 0.5, color))
        blade.setPos(rng.uniform(-0.04, 0.04), rng.uniform(-0.04, 0.04), h * 0.5)
        blade.setH(rng.uniform(0, 360))
        blade.setP(rng.uniform(-15, 15))  # slight lean
    tex = get_material_texture("dry_organic", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    root.setTexScale(ts, 0.5, 0.5)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    root.setScale(5.0)  # user-approved scale
    return root


def build_rubble(parent, seed=0):
    """Scattered small rocks — broken stone debris."""
    rng = random.Random(seed)
    root = parent.attachNewNode(f"rubble_{seed}")
    count = rng.randint(3, 8)
    for i in range(count):
        s = rng.uniform(0.04, 0.15)
        color = _cavern_color("stone", rng, 0.02)
        piece = make_rock(
            s * rng.uniform(0.7, 1.3),
            s * rng.uniform(0.4, 0.8),
            s * rng.uniform(0.6, 1.2),
            color, rings=4, segments=5, seed=seed + i,
            roughness=rng.uniform(0.3, 0.6),
        )
        pn = root.attachNewNode(piece)
        pn.setPos(rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), 0)
        pn.setH(rng.uniform(0, 360))
        pn.setTwoSided(True)
    tex = get_material_texture("stone_light", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    root.setTexScale(ts, 0.3, 0.3)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    root.setScale(5.0)  # user-approved scale
    return root


def build_leaf_pile(parent, seed=0):
    """Small pile of dead leaves — flat boxes at random angles."""
    rng = random.Random(seed)
    root = parent.attachNewNode(f"leafpile_{seed}")
    count = rng.randint(5, 12)
    for i in range(count):
        w = rng.uniform(0.03, 0.07)
        color = _cavern_color("dead_organic", rng, 0.02)
        leaf = root.attachNewNode(make_box(w, w * 0.1, w * rng.uniform(0.6, 1.0), color))
        leaf.setPos(rng.uniform(-0.15, 0.15), rng.uniform(-0.15, 0.15), rng.uniform(0, 0.04))
        leaf.setH(rng.uniform(0, 360))
        leaf.setR(rng.uniform(-30, 30))
        leaf.setP(rng.uniform(-20, 20))
    tex = get_material_texture("dry_organic", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    root.setTexScale(ts, 0.4, 0.4)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    root.setScale(5.0)  # user-approved scale
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
    root.setTexScale(ts, 0.3, 0.3)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    root.setScale(5.0)  # user-approved scale
    return root


def build_twig_scatter(parent, seed=0):
    """Tiny sticks on the ground — minimal geometry."""
    rng = random.Random(seed)
    root = parent.attachNewNode(f"twigs_{seed}")
    count = rng.randint(2, 6)
    for i in range(count):
        length = rng.uniform(0.05, 0.15)
        thick = rng.uniform(0.003, 0.008)
        color = _cavern_color("dead_organic", rng, 0.01)
        twig = root.attachNewNode(make_box(thick, thick, length, color))
        twig.setPos(rng.uniform(-0.2, 0.2), rng.uniform(-0.2, 0.2), thick)
        twig.setH(rng.uniform(0, 360))
        twig.setP(rng.uniform(-10, 10))
    tex = get_material_texture("dry_organic", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    root.setTexGen(ts, TexGenAttrib.MWorldPosition)
    root.setTexture(ts, tex)
    root.setTexScale(ts, 0.4, 0.4)
    root.setColorScale(0.55, 0.50, 0.48, 1.0)
    root.setScale(5.0)  # user-approved scale
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
    root.setTexScale(ts, 0.2, 0.2)
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
    root.setTexScale(ts, 0.1, 0.1)
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
    root.setTexScale(ts, 0.06, 0.06)  # larger scale = bigger grain for massive stone
    root.setColorScale(0.50, 0.46, 0.44, 1.0)
    return root


def build_giant_fungus(parent, seed=0):
    """Giant bioluminescent mushroom — purple phosphorescence. Cathedral flora.

    NO stone damping — this is living, glowing biology.
    Cap is self-lit and casts purple light onto surrounding stone.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"fungus_{seed}")

    # Stem — tall, narrow, pale fleshy
    stem_h = rng.uniform(3.0, 8.0)
    stem_r = rng.uniform(0.3, 0.7)
    stem_color = (0.08, 0.06, 0.10)  # pale purple-grey flesh
    stem = root.attachNewNode(make_rock(
        stem_r, stem_h * 0.5, stem_r * 0.8, stem_color,
        rings=5, segments=6, seed=seed, roughness=rng.uniform(0.1, 0.2),
    ))
    stem.setPos(0, 0, 0)
    stem.setTwoSided(True)
    # Stem gets organic texture, not stone
    tex = get_material_texture("dry_organic", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)
    stem.setTexGen(ts, TexGenAttrib.MWorldPosition)
    stem.setTexture(ts, tex)
    stem.setTexScale(ts, 0.3, 0.3)

    # Cap — wide, flat dome, glowing purple, textured
    cap_r = stem_r * rng.uniform(2.5, 5.0)
    cap_h = rng.uniform(0.4, 1.2)
    cap_color = (0.45, 0.08, 0.55)  # rich saturated purple
    cap = root.attachNewNode(make_rock(
        cap_r, cap_h, cap_r * 0.9, cap_color,
        rings=5, segments=8, seed=seed + 99, roughness=rng.uniform(0.05, 0.12),
    ))
    cap.setPos(0, 0, stem_h * 0.8)
    cap.setTwoSided(True)
    cap.setTexGen(ts, TexGenAttrib.MWorldPosition)
    cap.setTexture(ts, tex)
    cap.setTexScale(ts, 0.2, 0.2)
    cap.setLightOff()  # self-illuminated — glow bleeds through texture
    cap.setColorScale(5.0, 1.5, 6.0, 1.0)  # CRANKED phosphorescent purple

    # Gill glow — smaller inverted disc under cap, hottest
    gill_color = (0.55, 0.12, 0.65)
    gill = root.attachNewNode(make_rock(
        cap_r * 0.7, cap_h * 0.3, cap_r * 0.65, gill_color,
        rings=3, segments=6, seed=seed + 200, roughness=0.05,
    ))
    gill.setPos(0, 0, stem_h * 0.75)
    gill.setTwoSided(True)
    gill.setLightOff()
    gill.setColorScale(6.0, 2.0, 7.0, 1.0)  # blazing underside

    # Smaller fungus cluster — arcing out from the base like a colony
    for ci in range(rng.randint(3, 7)):
        angle = rng.uniform(0, 360)
        dist = stem_r + rng.uniform(0.3, 1.5)
        arc_h = rng.uniform(0.8, 3.0)
        arc_r = rng.uniform(0.1, 0.25)
        arc_color = (0.35 + rng.uniform(-0.03, 0.03), 0.06,
                     0.45 + rng.uniform(-0.03, 0.03))
        ax = math.cos(math.radians(angle)) * dist
        ay = math.sin(math.radians(angle)) * dist

        # Small stem leaning outward — textured
        arc_stem = root.attachNewNode(make_rock(
            arc_r, arc_h * 0.4, arc_r * 0.7, stem_color,
            rings=3, segments=4, seed=seed + 300 + ci, roughness=0.12,
        ))
        arc_stem.setPos(ax, ay, 0)
        arc_stem.setR(rng.uniform(-25, 25))
        arc_stem.setTwoSided(True)
        arc_stem.setTexGen(ts, TexGenAttrib.MWorldPosition)
        arc_stem.setTexture(ts, tex)
        arc_stem.setTexScale(ts, 0.4, 0.4)

        # Small glowing cap — textured, glow through grain
        arc_cap_r = arc_r * rng.uniform(2.0, 3.5)
        arc_cap = root.attachNewNode(make_rock(
            arc_cap_r, 0.15, arc_cap_r * 0.8, arc_color,
            rings=3, segments=4, seed=seed + 400 + ci, roughness=0.08,
        ))
        arc_cap.setPos(ax, ay, arc_h * 0.7)
        arc_cap.setTwoSided(True)
        arc_cap.setTexGen(ts, TexGenAttrib.MWorldPosition)
        arc_cap.setTexture(ts, tex)
        arc_cap.setTexScale(ts, 0.3, 0.3)
        arc_cap.setLightOff()
        arc_cap.setColorScale(8.0, 2.5, 10.0, 1.0)  # cranked — visible in the dark

    # Point light — EXAGGERATED, visible light pool edge on the ground
    pl = PointLight(f"fungus_glow_{seed}")
    pl.setColor(Vec4(10.0, 2.0, 14.0, 1))  # 5× previous — see the throw edge
    pl.setAttenuation((0.05, 0.004, 0.001))  # reaches ~25m
    glow_np = root.attachNewNode(pl)
    glow_np.setPos(0, 0, stem_h * 0.75)

    root.setPythonTag("point_light", glow_np)
    root.setPythonTag("mote_config", {
        "color": (0.4, 0.08, 0.55), "count": 12,
        "radius": 4.0, "height": stem_h * 0.9,
    })
    # NO root damping — this is bioluminescent, not stone
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
        h = rng.uniform(0.02, 0.06)
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
        blob.setTexScale(ts, 0.5, 0.5)
        blob.setLightOff()  # self-illuminated — glow bleeds through texture
        blob.setColorScale(8.0, 16.0, 5.0, 1.0)  # 5× CRANKED — SEE IT

    # Point light — EXAGGERATED, visible green pool on the ground
    pl = PointLight(f"moss_glow_{seed}")
    pl.setColor(Vec4(3.0, 12.5, 1.5, 1))  # 5× previous — see the throw edge
    pl.setAttenuation((0.05, 0.004, 0.001))  # reaches ~25m
    glow_np = root.attachNewNode(pl)
    glow_np.setPos(0, 0, 0.5)

    root.setPythonTag("point_light", glow_np)
    root.setPythonTag("mote_config", {
        "color": (0.08, 0.45, 0.06), "count": 15,
        "radius": 3.5, "height": 0.8,
        "ground_bias": True,
        "float_compression": 0.4,  # barely perceptible near surface
    })
    # NO root damping — bioluminescent
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

    # Cold blue point light
    pl = PointLight(f"crystal_glow_{seed}")
    pl.setColor(Vec4(5.0, 6.0, 12.0, 1))  # boosted
    pl.setAttenuation((0.04, 0.003, 0.001))
    glow_np = root.attachNewNode(pl)
    glow_np.setPos(0, 0, tallest_h * 0.7)

    root.setPythonTag("point_light", glow_np)
    root.setPythonTag("mote_config", {
        "color": (0.1, 0.15, 0.45), "count": 12,  # more saturated blue
        "radius": 3.5, "height": tallest_h * 0.8,
        "float_compression": 0.5,
    })
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
    root.setTexScale(ts, 0.4, 0.4)
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


def build_ceiling_moss(parent, seed=0):
    """Amber bioluminescent moss hanging from implied ceiling.

    Spawns at height — dangles down. Motes drift downward.
    Player never sees the ceiling, but the falling light proves it's there.
    Any object with attachment_type='ceiling' gets placed at height.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"ceil_moss_{seed}")

    # Cluster hangs from a height — the "ceiling"
    hang_z = rng.uniform(15.0, 25.0)

    # Dangling organic blobs — amber/gold
    tex = get_material_texture("dry_organic", seed=seed)
    ts = TextureStage("mat")
    ts.setMode(TextureStage.MModulate)

    blob_count = rng.randint(5, 12)
    for i in range(blob_count):
        r = rng.uniform(0.1, 0.4)
        dangle = rng.uniform(0.3, 2.0)  # how far it hangs down
        av = rng.uniform(-0.02, 0.02)
        color = (0.35 + av, 0.25 + av, 0.06)  # warm amber
        blob = root.attachNewNode(make_rock(
            r, dangle * 0.3, r * rng.uniform(0.6, 0.9), color,
            rings=3, segments=4, seed=seed + i * 19, roughness=0.12,
        ))
        blob.setPos(rng.uniform(-1.5, 1.5), rng.uniform(-1.5, 1.5),
                     hang_z - dangle)
        blob.setTwoSided(True)
        blob.setTexGen(ts, TexGenAttrib.MWorldPosition)
        blob.setTexture(ts, tex)
        blob.setTexScale(ts, 0.4, 0.4)
        blob.setLightOff()
        blob.setColorScale(12.0, 8.0, 3.0, 1.0)  # CRANKED warm amber

    # Amber point light — CRANKED, visible warm pool on ground
    pl = PointLight(f"ceil_moss_glow_{seed}")
    pl.setColor(Vec4(25.0, 18.0, 5.0, 1))  # 4× brighter
    pl.setAttenuation((0.02, 0.001, 0.0005))  # reaches ~30m down
    glow_np = root.attachNewNode(pl)
    glow_np.setPos(0, 0, hang_z - 1.0)

    root.setPythonTag("point_light", glow_np)
    root.setPythonTag("mote_config", {
        "color": (0.5, 0.35, 0.1), "count": 20,
        "radius": 4.0, "height": hang_z * 0.9,
        "downward": True,
        "float_compression": 0.3,
    })
    return root


def build_hanging_vine(parent, seed=0):
    """Thin vine draping downward — hangs from column heights, adds vertical softness.

    Dark organic, barely visible until backlit by bioluminescence.
    """
    rng = random.Random(seed)
    root = parent.attachNewNode(f"vine_{seed}")

    # Vine hangs from a random height (as if from a column or ceiling)
    hang_height = rng.uniform(6.0, 20.0)
    vine_length = rng.uniform(3.0, hang_height * 0.7)
    segment_count = rng.randint(4, 8)
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
    root.setTexScale(ts, 0.5, 0.5)
    root.setColorScale(0.45, 0.50, 0.40, 1.0)  # dark but slightly green-shifted
    return root


# -- Dust mote system (config-driven, any light source) -----------------------
# mote_config = {"color": (r,g,b), "count": N, "radius": m, "height": m}
# Tagged on any node with a point_light. AmbientManager spawns on wake.

def _spawn_motes(parent_node, cfg, origin):
    """Spawn drifting dust motes around a light source. Returns list of nodes."""
    rng = random.Random(hash(origin) & 0xFFFF)
    motes = []
    color = cfg.get("color", (0.5, 0.5, 0.5))
    count = cfg.get("count", 8)
    radius = cfg.get("radius", 3.0)
    height = cfg.get("height", 3.0)

    for i in range(count * 5):
        size = rng.uniform(0.006, 0.02)
        mote = parent_node.getParent().attachNewNode(
            make_box(size, size, size, color))
        # Scatter around the light source
        mx = origin[0] + rng.uniform(-radius, radius)
        my = origin[1] + rng.uniform(-radius, radius)
        if cfg.get("ground_bias"):
            # Dense near surface — exponential falloff upward
            mz = origin[2] + rng.uniform(0.05, height) ** 2 / height
        else:
            mz = origin[2] + rng.uniform(0.3, height)
        mote.setPos(mx, my, mz)
        mote.setLightOff()
        # Glow intensity — bright enough to see in the dark
        mote.setColorScale(color[0] * 15, color[1] * 15, color[2] * 15, 0.85)
        mote.setTwoSided(True)
        mote.setBillboardPointEye()  # always faces camera
        # Tag for drift animation
        # Pre-compute velocity — no trig per frame, just v × dt
        compress = cfg.get("float_compression", 1.0)
        downward = cfg.get("downward", False)
        vx = rng.uniform(-0.08, 0.08) * compress
        vy = rng.uniform(-0.08, 0.08) * compress
        if downward:
            vz = -rng.uniform(0.01, 0.05) * compress  # slow fall
        else:
            vz = rng.uniform(-0.03, 0.03) * compress  # gentle bob

        drift_data = {
            "origin": (mx, my, mz),
            "radius": radius,
            "vx": vx, "vy": vy, "vz": vz,
            "downward": downward,
        }
        motes.append((mote, drift_data))  # cached — no getPythonTag needed
    return motes


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
    "ceiling_moss": (build_ceiling_moss, "static"),
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

    MAX_ACTIVE_LIGHTS = 8  # GPU budget — cap simultaneous point lights

    def __init__(self, render_node, wake_radius=40.0, sleep_radius=50.0):
        self._render = render_node
        self._wake_r2 = wake_radius * wake_radius
        self._sleep_r2 = sleep_radius * sleep_radius
        self._entities = []         # all entities
        self._active = set()        # currently ticking (set for O(1) add/remove)
        self._active_lights = []    # (distance², entity, glow_np) — closest N active
        self._check_cursor = 0      # stagger wake/sleep checks across frames
        self._check_batch = 20      # entities to check per frame

    def spawn(self, kind, pos, heading=0, seed=0, height_fn=None, chunk_key=None):
        """Create an entity. It starts asleep until tick() wakes it."""
        if kind not in BUILDERS:
            return None
        builder_fn, behavior_name = BUILDERS[kind]
        node = builder_fn(self._render, seed=seed)
        node.setPos(pos[0], pos[1], pos[2])
        node.setH(heading)
        node.hide()  # starts hidden

        behavior_cls = BEHAVIORS[behavior_name]
        entity = AmbientEntity(kind, node, None, pos, heading, height_fn, chunk_key)
        entity.behavior = behavior_cls(entity, seed=seed)

        self._entities.append(entity)
        return entity

    def despawn_chunk(self, chunk_key):
        """Remove all entities belonging to a chunk."""
        to_remove = [e for e in self._entities if e.chunk_key == chunk_key]
        for e in to_remove:
            self._active.discard(e)
            for m, _d in e.motes:
                if m and not m.isEmpty():
                    m.removeNode()
            e.motes = []
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
                    # Spawn dust motes if configured
                    mcfg = e.node.getPythonTag("mote_config")
                    if mcfg and not e.motes:
                        e.motes = _spawn_motes(e.node, mcfg, e.pos)
                elif e.awake and d2 > self._sleep_r2:
                    e.awake = False
                    e.node.hide()
                    self._active.discard(e)
                    # Remove dust motes
                    for m, _d in e.motes:
                        if m and not m.isEmpty():
                            m.removeNode()
                    e.motes = []

        # Light budget: activate only the closest N point lights
        light_candidates = []
        for e in self._active:
            glow = e.node.getPythonTag("point_light")
            if glow:
                dx = e.pos[0] - cx
                dy = e.pos[1] - cy
                light_candidates.append((dx * dx + dy * dy, e, glow))
        light_candidates.sort()
        # Activate closest, deactivate the rest
        new_lights = set()
        for i, (_, e, glow) in enumerate(light_candidates):
            if i < self.MAX_ACTIVE_LIGHTS:
                new_lights.add(id(glow))
                if not any(id(g) == id(glow) for _, _, g in self._active_lights):
                    self._render.setLight(glow)
            else:
                self._render.clearLight(glow)
        # Clear lights that are no longer in the active set
        for _, _, glow in self._active_lights:
            if id(glow) not in new_lights:
                self._render.clearLight(glow)
        self._active_lights = light_candidates[:self.MAX_ACTIVE_LIGHTS]

        # Tick active behaviors
        t = self._tick_time if hasattr(self, '_tick_time') else 0.0
        self._tick_time = t + dt
        for e in self._active:
            e.behavior.tick(dt)

        # Drift motes — every tick, but cheap: just add velocity × dt
        for e in self._active:
            for m, d in e.motes:
                pos = m.getPos()
                # Tiny velocity nudge — no trig, just linear drift
                vx = d.get("vx", 0)
                vy = d.get("vy", 0)
                vz = d.get("vz", 0)
                nx = pos.getX() + vx * dt
                ny = pos.getY() + vy * dt
                nz = pos.getZ() + vz * dt
                # Soft wrap: when mote drifts too far from origin, nudge back
                ox, oy, oz = d["origin"]
                dx = nx - ox
                dy = ny - oy
                r = d["radius"]
                if dx * dx + dy * dy > r * r:
                    nx = ox + dx * 0.5
                    ny = oy + dy * 0.5
                if d.get("downward"):
                    if nz < oz - r * 2:
                        nz = oz  # reset to top
                else:
                    if abs(nz - oz) > 0.8:
                        d["vz"] = -d["vz"]  # bounce
                m.setPos(nx, ny, nz)

    @property
    def total_count(self):
        return len(self._entities)

    @property
    def active_count(self):
        return len(self._active)
