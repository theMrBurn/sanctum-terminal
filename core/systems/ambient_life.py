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

from panda3d.core import Vec3, NodePath, TexGenAttrib, TextureStage, Texture, PNMImage, SamplerState
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
        self._pick_creep()
        self._origin = entity.pos
        self._speed = self.rng.uniform(0.3, 0.8)
        self._roam_radius = self.rng.uniform(0.5, 2.0)

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


# -- Entity builders ----------------------------------------------------------

def build_rat(parent, seed=0):
    """Build rat geometry, return NodePath."""
    rng = random.Random(seed)
    root = parent.attachNewNode(f"rat_{seed}")

    scale = rng.uniform(0.7, 1.2)
    body_len = rng.uniform(0.15, 0.22) * scale
    body_w = body_len * rng.uniform(0.35, 0.5)
    body_h = body_len * rng.uniform(0.25, 0.35)
    fs = rng.uniform(-0.02, 0.02)
    fur = (0.08 + fs, 0.06 + fs, 0.05 + fs)

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

    return root


def build_leaf(parent, seed=0):
    """Tiny leaf — flat box, subtle color."""
    rng = random.Random(seed)
    root = parent.attachNewNode(f"leaf_{seed}")
    w = rng.uniform(0.03, 0.06)
    shade = rng.uniform(-0.02, 0.02)
    color = (0.12 + shade, 0.10 + shade, 0.06 + shade)
    leaf = root.attachNewNode(make_box(w, w * 0.15, w * 0.7, color))
    leaf.setR(rng.uniform(-30, 30))
    return root


def build_spider(parent, seed=0):
    """Tiny spider — body + legs suggestion."""
    rng = random.Random(seed)
    root = parent.attachNewNode(f"spider_{seed}")
    s = rng.uniform(0.02, 0.04)
    color = (0.05, 0.04, 0.03)
    body = root.attachNewNode(make_box(s, s * 0.6, s, color))
    # Leg hints — 4 thin bars
    for i in range(4):
        leg_len = s * 1.5
        leg = root.attachNewNode(make_box(0.003, 0.003, leg_len, (0.06, 0.05, 0.04)))
        angle = -60 + i * 40
        leg.setPos(math.cos(math.radians(angle)) * s * 0.4,
                    math.sin(math.radians(angle)) * s * 0.3, 0)
        leg.setR(angle)
    return root


def generate_stone_texture(size=64, seed=0, ground_color=(0.06, 0.05, 0.04)):
    """Procedural stone texture with height-based situ blending.

    Top rows: lighter weathered stone (exposed to elements)
    Bottom rows: darker, speckled to match ground (situ blend)
    Middle: stone grain via tight Voronoi cells

    Returns a Texture object ready to apply.
    """
    rng = random.Random(seed)
    img = PNMImage(size, size)

    # Stone base — cooler/darker than ground
    base_r = rng.uniform(0.12, 0.17)
    base_g = rng.uniform(0.11, 0.15)
    base_b = rng.uniform(0.11, 0.15)

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

    color = (
        rng.uniform(0.10, 0.16),
        rng.uniform(0.10, 0.14),
        rng.uniform(0.10, 0.14),
    )

    # Single make_rock call — it handles irregularity + flat base internally
    rock = root.attachNewNode(make_rock(
        width * 0.5, height * 0.5, depth * 0.5, color,
        rings=8, segments=10, seed=seed,
        roughness=rng.uniform(0.25, 0.45),
    ))
    rock.setPos(0, 0, 0)
    rock.setTwoSided(True)

    # Stone texture with situ blend — auto-projected via world position
    stone_tex = generate_stone_texture(size=64, seed=seed, ground_color=(0.06, 0.05, 0.04))
    ts = TextureStage("stone")
    ts.setMode(TextureStage.MModulate)  # multiply with vertex color
    rock.setTexGen(ts, TexGenAttrib.MWorldPosition)
    rock.setTexture(ts, stone_tex)
    # Scale the texture projection to match boulder size
    rock.setTexScale(ts, 0.15, 0.15)

    # Dampen light response
    root.setColorScale(0.55, 0.50, 0.48, 1.0)

    return root


BUILDERS = {
    "rat": (build_rat, "scurry"),
    "leaf": (build_leaf, "drift"),
    "spider": (build_spider, "crawl"),
    "boulder": (build_boulder, "static"),
}


# -- Ambient Entity ------------------------------------------------------------

class AmbientEntity:
    """A single behavior-driven entity in the world."""

    __slots__ = ("kind", "pos", "heading", "node", "behavior",
                 "awake", "height_fn", "chunk_key")

    def __init__(self, kind, node, behavior, pos, heading, height_fn=None, chunk_key=None):
        self.kind = kind
        self.pos = pos
        self.heading = heading
        self.node = node
        self.behavior = behavior
        self.awake = False
        self.height_fn = height_fn
        self.chunk_key = chunk_key


# -- Ambient Manager -----------------------------------------------------------

class AmbientManager:
    """Manages all ambient life entities. Tick once per frame."""

    def __init__(self, render_node, wake_radius=30.0, sleep_radius=45.0):
        self._render = render_node
        self._wake_r2 = wake_radius * wake_radius
        self._sleep_r2 = sleep_radius * sleep_radius
        self._entities = []         # all entities
        self._active = set()        # currently ticking (set for O(1) add/remove)
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
            if e.node and not e.node.isEmpty():
                e.node.removeNode()
            self._entities.remove(e)

    def tick(self, dt, cam_pos):
        """Per-frame update: staggered wake/sleep, tick active behaviors."""
        cx, cy = cam_pos.getX(), cam_pos.getY()

        # Staggered wake/sleep — check a batch per frame, not all
        n = len(self._entities)
        if n > 0:
            batch = min(self._check_batch, n)
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
                elif e.awake and d2 > self._sleep_r2:
                    e.awake = False
                    e.node.hide()
                    self._active.discard(e)

        # Tick active behaviors
        for e in self._active:
            e.behavior.tick(dt)

    @property
    def total_count(self):
        return len(self._entities)

    @property
    def active_count(self):
        return len(self._active)
