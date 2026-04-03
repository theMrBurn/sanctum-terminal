"""
cavern.py

Procedural infinite floor — layer 1 of the cavern system.
Walk forward. Ground generates ahead, despawns behind.
Each chunk gets a unique procedural texture + scattered geometry.

Controls:
    Mouse       Look around
    W/S         Walk forward/back
    A/D         Strafe left/right
    `           Debug overlay
    0           Dump state
    T           Drop tag
    Shift+T     Undo tag
    Ctrl+T      Clear tags
    F1-F4       Registers
    ESC         Quit

Usage:
    make cavern
"""

import sys
import os
import math
import json
import time
import threading
import gc
from collections import deque

from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    Vec3, Vec4, TextNode, AntialiasAttrib,
    Fog, SamplerState, TransparencyAttrib,
    WindowProperties, NodePath,
    PNMImage, Texture, CardMaker,
    AmbientLight,
)
from rich.console import Console

from core.systems.placement_engine import PlacementEngine
from core.systems.entropy_engine import EntropyEngine
from panda3d.core import (
    Geom, GeomNode, GeomTriangles, GeomVertexData,
    GeomVertexFormat, GeomVertexWriter, PerlinNoise2,
)
from core.systems.geometry import make_box, make_pebble_cluster, make_sphere
from core.systems.shadowbox_scene import SHADOWBOX_REGISTERS, resolve_palette
from core.systems.ambient_life import (
    AmbientManager, set_active_biome, OUTDOOR_COLOR_SCALES, OUTDOOR_LIGHT_LAYERS,
    LIGHT_LAYERS,
)
from core.systems.chronometer import Chronometer

console = Console()

# -- World constants -----------------------------------------------------------

CHUNK_SIZE = 16.0       # meters per chunk edge
CHUNK_RADIUS = 2        # chunks visible in each direction (5x5 = 25 chunks)
PREGEN_RADIUS = 3       # pre-generate this far out (fog hides at 42m = ~2.6 chunks)
DESPAWN_RADIUS = 4      # tighter cleanup — fewer chunks in scene graph
TEX_SIZE = 120          # 2×60, base-60 aligned — divides by everything, no alignment artifacts
MOVE_SPEED = 5.0
MOUSE_SENS = 0.3
PITCH_LIMIT = 60.0
EYE_Z = 2.5

REGISTERS = ["survival", "tron", "tolkien", "sanrio"]

# -- Biome density configs -----------------------------------------------------
# (density_per_1000sqm, clearance_radius, margin)
# density × tile_area / 1000 = count.  clearance > 0 = spacing enforced.

BIOME_CAVERN_DEFAULT = [
    # kind               density  clearance  margin  — placed largest-first
    ("mega_column",       0.12,    10.0,      20),
    ("column",            0.30,    5.0,       10),
    ("boulder",           1.20,    3.0,       3),
    ("stalagmite",        1.80,    2.0,       2),
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
    ("horizon_form",      0.12,    10.0,      30),   # far band — fog boundary silhouettes
    ("horizon_mid",       0.08,     8.0,      20),   # mid band — closer, smaller, more detail
    ("horizon_near",      0.10,     6.0,      12),   # near band — just past torch range, sells depth
    ("exit_lure",         0.03,   20.0,       35),   # rare distant glow — unreachable, sells exit illusion
    ("leaf",              0.25,    0,         1),
    ("spider",            0.12,    0,         2),
]

# -- Outdoor biome stub --------------------------------------------------------
# Same engine, different config. Reuses existing builders where possible.
# mega_column → "big tree" (tall, wide, landmark). column → "tree trunk".
# boulder stays boulder. stalagmite → tall rock or dead tree stump.
# crystal/fungus → flowering bush or berry cluster (reuse glow decal).
# Fog: longer range, blue-grey. Ambient: warmer, brighter.
# Clearings = honeycomb chambers. Tree trunks = chamber walls.
#
# ACTIVE_BIOME controls which table + palette is loaded at init.

BIOME_OUTDOOR_FOREST = [
    # kind               density  clearance  margin
    # Trees as structure — same role as columns (chamber walls)
    ("mega_column",       0.08,    12.0,      20),   # Doug fir / old growth
    ("column",            0.40,     4.0,       8),   # second growth / mixed species
    ("boulder",           0.80,     3.0,       3),   # sword fern mounds (color override → green)
    ("stalagmite",        0.60,     1.5,       2),   # dead stumps / standing stones
    ("giant_fungus",      0.15,     2.5,       3),   # large bush / rhododendron
    ("crystal_cluster",   0.10,     2.0,       3),   # flowering shrub / wildflower
    ("dead_log",          0.70,     1.5,       2),   # nurse logs — more common outdoors
    ("moss_patch",        0.60,     0,         2),   # ground moss — PNW essential
    ("grass_tuft",        1.50,     0,         1),   # understory grass (was 2.50 — ground tex handles density)
    ("rubble",            0.40,     0,         1),   # scattered stones
    ("leaf_pile",         0.80,     0,         1),   # fir needles (was 1.20 — less clutter)
    ("firefly",           0.60,     0,         1),   # dusk fireflies
    ("leaf",              0.50,     0,         1),   # drifting leaves / fir needles
    ("beetle",            0.20,     0,         2),   # forest insects
    ("rat",               0.15,     0,         2),   # squirrel / chipmunk
    # cave_gravel + twig_scatter REMOVED — imperceptible at walking speed through fog.
    # Saves ~1000 entity slots for things that matter.
    ("horizon_form",      0.10,    12.0,      30),   # distant tree line silhouettes
    ("horizon_mid",       0.08,     8.0,      20),
    ("horizon_near",      0.10,     6.0,      12),
    ("exit_lure",         0.02,    20.0,      35),   # distant light through trees — campfire, cabin
]

# Palette overrides for outdoor biome (layered onto base register palette)
OUTDOOR_PALETTE = {
    "fog_color": (0.18, 0.20, 0.25),    # blue-grey mist, not cave black
    "fog_near": 15.0,                     # longer visibility
    "fog_far": 55.0,                      # wide open feel
    "far_clip": 60.0,
    "ambient_color": (0.55, 0.50, 0.45),  # warm daylight ambient
    "bg_color": (0.15, 0.18, 0.25),       # twilight sky
}

# -- Outdoor L-key cycle: day → dusk → night → day ----------------------------
# Each state is a complete rendering snapshot. Chrono modulates passively within.
OUTDOOR_LIGHT_STATES = {
    "day": {
        "ambient": (0.72, 0.65, 0.58),    # bright overcast daylight (was 0.55 — too dark)
        "fog_color": (0.22, 0.24, 0.28),  # lighter blue-grey haze
        "fog_near": 15.0,
        "fog_far": 55.0,
        "bg_color": (0.18, 0.22, 0.30),   # brighter daytime sky
        "far_clip": 60.0,
        "sun_color": (1.0, 0.90, 0.65),   # warm disc
        "sun_scale": 4.0,
        "moon_color": (0.0, 0.0, 0.0),    # invisible
        "moon_scale": 0.0,
    },
    "dusk": {
        "ambient": (0.30, 0.22, 0.15),    # golden hour amber
        "fog_color": (0.20, 0.14, 0.10),  # warm golden mist
        "fog_near": 10.0,
        "fog_far": 40.0,
        "bg_color": (0.12, 0.08, 0.12),   # deep violet-blue
        "far_clip": 50.0,
        "sun_color": (1.0, 0.55, 0.20),   # orange disc low on horizon
        "sun_scale": 5.0,                  # bigger at horizon
        "moon_color": (0.0, 0.0, 0.0),
        "moon_scale": 0.0,
    },
    "night": {
        "ambient": (0.06, 0.07, 0.10),    # cool blue moonlight
        "fog_color": (0.03, 0.04, 0.06),  # deep blue mist
        "fog_near": 5.0,
        "fog_far": 25.0,
        "bg_color": (0.02, 0.03, 0.05),   # near-black sky
        "far_clip": 35.0,
        "sun_color": (0.0, 0.0, 0.0),     # invisible
        "sun_scale": 0.0,
        "moon_color": (0.60, 0.65, 0.80), # cool blue-white disc
        "moon_scale": 3.0,
    },
}

OUTDOOR_LIGHT_ORDER = ["day", "dusk", "night"]

# -- Cavern light states — mirror outdoor shape for symmetry -------------------
CAVERN_LIGHT_STATES = {
    "cave": {
        "ambient": (0.38, 0.34, 0.32),
        "fog_color": (0.06, 0.055, 0.06),
        "fog_near": 8.0,
        "fog_far": 28.0,
        "bg_color": (0.06, 0.06, 0.07),
        "far_clip": 30.0,
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

CAVERN_LIGHT_ORDER = ["cave", "daylight"]

# Toggle: "cavern" or "outdoor"
ACTIVE_BIOME = "outdoor"


class Cavern(ShowBase):

    def __init__(self):
        super().__init__()

        props = WindowProperties()
        props.setTitle("Sanctum — The Endless Floor")
        props.setSize(960, 540)  # 75% render resolution — natural softness + GPU savings
        props.setCursorHidden(True)
        self.win.requestProperties(props)

        # -- GC control: manual collection on quiet frames, no random pauses --
        gc.disable()

        # -- Rendering setup ---------------------------------------------------
        self._biome = ACTIVE_BIOME
        set_active_biome(self._biome)  # tell ambient_life which palette to use
        self._light_states = OUTDOOR_LIGHT_STATES if self._biome == "outdoor" else CAVERN_LIGHT_STATES
        self._light_order = OUTDOOR_LIGHT_ORDER if self._biome == "outdoor" else CAVERN_LIGHT_ORDER
        self._light_index = 0
        self._light_state = self._light_order[0]  # "day" or "cave"
        self._daylight = (self._biome == "outdoor")
        ls = self._light_states[self._light_state]
        self.disableMouse()
        self.camLens.setFov(65.0)
        self.camLens.setNear(0.5)
        self.camLens.setFar(ls["far_clip"])
        self.setBackgroundColor(*ls["bg_color"], 1)
        self.render.setAntialias(AntialiasAttrib.MMultisample)
        # setShaderAuto() REMOVED — causes GPU stalls on Apple Silicon Metal.
        # All lighting is via single AmbientLight + decals (no per-pixel shading).
        # Color grade + grain use explicit GLSL shaders on render2d cards.

        # -- State -------------------------------------------------------------
        self._register_index = 0
        self._palette = resolve_palette("survival")
        self._keys = {"w": False, "s": False, "a": False, "d": False}
        self._cam_h = 0.0
        self._cam_p = 0.0
        self._chunks = {}           # (cx, cz) -> NodePath
        self._pending_chunks = {}   # (cx, cz) -> texture data being generated in background
        self._ready_chunks = {}     # (cx, cz) -> (tex_data, chunk_seed) ready to build
        self._chunk_lock = threading.Lock()
        self._chunk_seed = 42
        self._tex_size_override = TEX_SIZE
        self._deferred_entity_spawns = deque()  # drip-spawned across frames
        self._flat_height = lambda x, y: 0.0  # fake ground height — zero Perlin
        self._use_fake_ground = True  # G-mode default — flat plane, zero Perlin, max perf
        self._ground_blend_z = 0.0    # lerp offset to prevent pop on G toggle
        self._placer = PlacementEngine(seed=self._chunk_seed)
        self._entropy = EntropyEngine()
        if self._biome == "outdoor":
            self._ambient = AmbientManager(self.render, wake_radius=40.0, sleep_radius=50.0)
        else:
            self._ambient = AmbientManager(self.render, wake_radius=30.0, sleep_radius=38.0)
        self._deferred_spawns = []  # ambient spawns queued across frames
        self._biome_key = "Outdoor_Forest" if self._biome == "outdoor" else "Cavern_Default"
        self._chrono = Chronometer()
        self._chrono_state = self._chrono.read()

        # -- Tension Cycle (The Train) ----------------------------------------
        from core.systems.tension_cycle import TensionCycle, CAVERN_CYCLE, OUTDOOR_CYCLE
        _cycle_config = OUTDOOR_CYCLE if self._biome == "outdoor" else CAVERN_CYCLE
        self._tension = TensionCycle(config=_cycle_config)
        self._tension.on_state_change = self._on_tension_state
        self._tension.on_dump = self._on_tension_dump
        self._tension.on_rebirth = self._on_tension_rebirth
        self._tension.board()  # always on by default — B toggles off for cozy

        # Native C++ Perlin for texture generation (fast path)
        # Python PlacementEngine Perlin stays for placement/height (still useful)
        self._noise = {}  # keyed by scale for reuse
        for scale_name, sx, sy, seed_offset in [
            ("jitter_x", 1.7, 1.7, 0), ("jitter_y", 1.7, 1.7, 100),
            ("gate", 0.9, 0.9, 500), ("color", 0.4, 0.4, 0),
            ("warm", 0.7, 0.7, 50), ("dirt1", 0.8, 0.8, 0),
            ("dirt2", 2.5, 2.5, 300), ("grit", 1.8, 1.8, 700),
            ("stone", 5.0, 5.0, 0),
        ]:
            n = PerlinNoise2(sx, sy, 256, self._chunk_seed + seed_offset)
            self._noise[scale_name] = n

        # -- Debug telemetry ---------------------------------------------------
        self._debug_mode = False
        self._probe_data = {}
        self._debug_hud_text = None
        self._debug_tags = []
        self._tag_counter = 0
        self._frame_times = deque(maxlen=60)  # rolling 60-frame window
        self._drip_this_frame = 0  # entities spawned this frame via drip
        self._cmd_path = os.path.join(os.path.dirname(__file__) or ".", "debug_cmd.json")
        self._state_path = os.path.join(os.path.dirname(__file__) or ".", "debug_state.json")

        # -- Lighting ----------------------------------------------------------
        self._build_lighting()

        # -- Fog ---------------------------------------------------------------
        self._fog = Fog("cavern_fog")
        ls = self._light_states[self._light_state]
        self._fog.setColor(Vec4(*ls["fog_color"], 1))
        self._fog.setLinearRange(ls["fog_near"], ls["fog_far"])
        self.render.setFog(self._fog)

        # -- Camera start ------------------------------------------------------
        self.cam.setPos(0, 0, EYE_Z)
        self.cam.setHpr(0, 0, 0)  # heading 0 (north), pitch 0 (horizon), roll 0
        self._mouse_initialized = False

        # -- Stage the immediate area before player sees anything --
        self._stage_initial_chunks()

        # -- Fake ground (WorldRunner cheat) — toggle with G key ----------------
        from core.systems.fake_ground import FakeGround
        self._fake_ground = FakeGround(self.render, self._palette, self._chunk_seed)
        self._fake_ground.show()  # G-mode is default — performance ground active
        # Stash real chunks — they exist from _stage_initial_chunks but are hidden
        for key, node in self._chunks.items():
            node.stash()

        # -- Post-processing -------------------------------------------------------
        self._setup_postprocess()
        self._setup_grain_shader()

        # -- Controls ----------------------------------------------------------
        self.accept("escape", sys.exit)
        for key in self._keys:
            self.accept(key, self._set_key, [key, True])
            self.accept(f"{key}-up", self._set_key, [key, False])
        for i in range(len(REGISTERS)):
            self.accept(f"f{i + 1}", self._cycle_register, [i])
        self.accept("`", self._toggle_debug)
        self.accept("0", self._dump_debug_state)
        self.accept("t", self._place_tag)
        self.accept("shift-t", self._undo_last_tag)
        self.accept("control-t", self._clear_tags)
        self.accept("l", self._toggle_daylight)
        self.accept("g", self._toggle_fake_ground)
        self.accept("9", self._showcase_light_layers)
        self.accept("b", self._toggle_tension)  # B = Board/disembark the train
        # Sky bodies disabled — billboard rendering produces vertical line artifacts.
        # Ambient light + fog color communicate time of day without geometry.
        # TODO: Fix billboard rendering or use textured card approach.
        self._sun_np = None
        self._moon_np = None

        self.taskMgr.add(self._loop, "CavernLoop")

        console.log("[bold cyan]THE ENDLESS FLOOR[/bold cyan]")
        console.log("[WASD] move  [Mouse] look  [F1-F4] registers  [L] daylight  [ESC] quit")
        console.log("[dim][`] debug  [0] dump  [T] tag  [Shift+T] undo  [Ctrl+T] clear  [9] showcase  [B] train[/dim]")

    # -- Helpers ---------------------------------------------------------------

    def _set_key(self, key, value):
        self._keys[key] = value

    def _center_mouse(self):
        wp = self.win.getProperties()
        self._win_cx = wp.getXSize() // 2
        self._win_cy = wp.getYSize() // 2
        self.win.movePointer(0, self._win_cx, self._win_cy)

    def _read_mouse(self):
        if not self.mouseWatcherNode.hasMouse():
            return 0.0, 0.0
        md = self.win.getPointer(0)
        dx = md.getX() - self._win_cx
        dy = md.getY() - self._win_cy
        if dx != 0 or dy != 0:
            self.win.movePointer(0, self._win_cx, self._win_cy)
        return dx, dy

    # -- Lighting --------------------------------------------------------------

    def _build_lighting(self):
        pal = self._palette

        # Ambient only — the sole pipeline light. Everything else is decals.
        amb = AmbientLight("amb")
        ls = self._light_states[self._light_state]
        amb.setColor(Vec4(*ls["ambient"], 1))
        self._amb_np = self.render.attachNewNode(amb)
        self.render.setLight(self._amb_np)

        # NO Spotlight, NO PointLight — Metal can't render them.
        # Decals ARE the lighting on this hardware.

        # Torch: cone-shaped ground decal + faint beam billboard + peripheral glow marker
        from core.systems.glow_decal import (
            make_glow_decal, get_glow_texture, make_light_shaft, get_shaft_texture,
        )

        # Main torch pool — elongated warm cone ahead of player
        glow_tex = get_glow_texture(128, surface="wet_stone")
        self._torch_decal = make_glow_decal(
            self.render, color=(1.4, 0.95, 0.45), radius=6.0, tex=glow_tex)

        # Outer ambient wash — wider, dimmer, sells the cone spread
        outer_tex = get_glow_texture(64, surface="smooth")
        self._torch_outer = make_glow_decal(
            self.render, color=(0.5, 0.35, 0.15), radius=10.0, tex=outer_tex)

        # Faint beam billboard — shoulder to ground, reads as light in dusty air
        shaft_tex = get_shaft_texture(32, 64)
        self._torch_beam = make_light_shaft(
            self.render, color=(0.8, 0.55, 0.2),
            shaft_height=2.0, shaft_width=1.5, tex=shaft_tex)

        # Torch disabled — refine during avatar rendering pass
        self._torch_decal.hide()
        self._torch_outer.hide()
        self._torch_beam.hide()

        # Tiny glow marker in peripheral vision
        self._orb_np = self.cam.attachNewNode("torch_mount")
        self._orb_np.setPos(0.3, -0.8, 0.6)
        orb_vis = make_box(0.025, 0.025, 0.025, (0.95, 0.8, 0.45))
        self._orb_vis = self._orb_np.attachNewNode(orb_vis)
        self._orb_vis.setLightOff()
        self._orb_vis.setColorScale(2.5, 2.0, 1.2, 1.0)
        self._orb_vis.hide()

    def _setup_sky_bodies(self):
        """Create sun + moon as self-lit billboard quads.

        No lights — Apple Silicon Metal. These are visual markers that
        track the chronometer's time_of_day on a semicircular arc.
        The ambient light is the REAL lighting; these explain it visually.
        """
        from core.systems.geometry import make_sphere

        # Sun — warm bright disc
        sun_geo = make_sphere(1.0, 1.0, 1.0, (1.0, 0.92, 0.65), rings=8, segments=8)
        self._sun_np = self.render.attachNewNode(sun_geo)
        self._sun_np.setLightOff()
        self._sun_np.setFogOff()
        self._sun_np.setBin("fixed", 0)
        self._sun_np.setDepthTest(False)
        self._sun_np.setDepthWrite(False)
        self._sun_np.setBillboardPointEye()

        # Moon — cool blue-white disc
        moon_geo = make_sphere(1.0, 1.0, 1.0, (0.65, 0.70, 0.85), rings=8, segments=8)
        self._moon_np = self.render.attachNewNode(moon_geo)
        self._moon_np.setLightOff()
        self._moon_np.setFogOff()
        self._moon_np.setBin("fixed", 0)
        self._moon_np.setDepthTest(False)
        self._moon_np.setDepthWrite(False)
        self._moon_np.setBillboardPointEye()

        # Initial state from current L-key mode
        self._apply_light_state()

    def _update_sky_bodies(self, dt):
        """Position sun/moon on arc relative to camera. Called each frame."""
        if self._sun_np is None:
            return

        cs = self._chrono_state
        tod = cs.get("time_of_day", 0.5)  # 0=midnight, 0.5=noon

        # Sun arc: rises east (0.25), peaks overhead (0.5), sets west (0.75)
        # Angle 0=horizon east, π=horizon west, π/2=zenith
        sun_angle = (tod - 0.25) * math.pi / 0.5  # maps 0.25→0, 0.5→π/2, 0.75→π
        sun_visible = 0.25 <= tod <= 0.75

        # Moon arc: opposite — rises 0.75, peaks 0.0/1.0, sets 0.25
        moon_tod = (tod + 0.5) % 1.0
        moon_angle = (moon_tod - 0.25) * math.pi / 0.5
        moon_visible = 0.25 <= moon_tod <= 0.75

        cam_pos = self.cam.getPos()
        cam_h = self._cam_h  # compass heading in degrees
        sky_dist = 45.0  # place at fog boundary

        if sun_visible and self._light_state != "night":
            elevation = math.sin(sun_angle) * 35.0 + 10.0  # 10-45m above ground
            # Sun sits roughly south (fixed heading offset from camera)
            sx = cam_pos.getX() + math.sin(math.radians(cam_h + 30)) * sky_dist
            sy = cam_pos.getY() + math.cos(math.radians(cam_h + 30)) * sky_dist
            sz = cam_pos.getZ() + elevation
            self._sun_np.setPos(sx, sy, sz)
            ls = self._light_states[self._light_state]
            sc = ls["sun_scale"]
            self._sun_np.setScale(sc)
            self._sun_np.setColorScale(*ls["sun_color"], 1.0)
            self._sun_np.show() if sc > 0 else self._sun_np.hide()
        else:
            self._sun_np.hide()

        if moon_visible and self._light_state == "night":
            elevation = math.sin(moon_angle) * 30.0 + 8.0
            mx = cam_pos.getX() + math.sin(math.radians(cam_h - 30)) * sky_dist
            my = cam_pos.getY() + math.cos(math.radians(cam_h - 30)) * sky_dist
            mz = cam_pos.getZ() + elevation
            self._moon_np.setPos(mx, my, mz)
            ls = self._light_states[self._light_state]
            mc = ls["moon_scale"]
            self._moon_np.setScale(mc)
            self._moon_np.setColorScale(*ls["moon_color"], 1.0)
            self._moon_np.show() if mc > 0 else self._moon_np.hide()
        else:
            self._moon_np.hide()

    def _apply_light_state(self):
        """Apply the current light state to all rendering parameters."""
        ls = self._light_states[self._light_state]
        self._amb_np.node().setColor(Vec4(*ls["ambient"], 1))
        self._fog.setColor(Vec4(*ls["fog_color"], 1))
        self._fog.setLinearRange(ls["fog_near"], ls["fog_far"])
        self.camLens.setFar(ls["far_clip"])
        self.setBackgroundColor(*ls["bg_color"], 1)

    def _setup_postprocess(self):
        """Wire bloom (CommonFilters) + color grading (fullscreen card).

        Bloom: Panda3D CommonFilters — proven on this hardware via shadowbox.
        Color grade: fullscreen GLSL card composited over scene (same as grain).
        Both use GLSL 1.20 (Metal-safe).
        """
        from core.systems.postprocess import (
            PostProcessPipeline, PostProcessConfig, BloomConfig,
            ColorGradeConfig, VignetteConfig,
        )

        # Biome-specific post-process tuning
        if self._biome == "outdoor":
            pp_config = PostProcessConfig(
                bloom=BloomConfig(threshold=0.55, intensity=0.35),
                vignette=VignetteConfig(radius=0.95, softness=0.50),  # was 0.90/0.45 — less crush
                color_grade=ColorGradeConfig(
                    warmth=0.10, contrast=1.05, saturation=0.98,  # subtler grade
                    shadow_lift=0.025, highlight_compress=0.92,   # lift shadows more
                ),
            )
        else:
            pp_config = PostProcessConfig(
                bloom=BloomConfig(threshold=0.65, intensity=0.25),
                vignette=VignetteConfig(radius=0.82, softness=0.40),
                color_grade=ColorGradeConfig(
                    warmth=0.05, contrast=1.12, saturation=0.88,
                    shadow_lift=0.015, highlight_compress=0.92,
                ),
            )

        self._pp = PostProcessPipeline(pp_config)
        self._bloom_on = False
        self._filters = None

        # CommonFilters bloom DISABLED — causes 600-1200ms GPU stalls on
        # Apple Silicon Metal. FBO render-to-texture pipeline creates driver
        # synchronization stalls every 3-4 frames. Keeping color grade + grain
        # (render2d cards, no FBO) which are stall-free.
        # TODO: Implement bloom as additive render2d card (emissive bright-pass
        # extracted from scene, blurred on CPU, composited as billboard).
        self._bloom_on = False
        self._filters = None

        # Color grading fullscreen card — same technique as grain shader
        from panda3d.core import Shader
        from core.systems.postprocess import FULLSCREEN_VERT
        grade_frag = """
#version 120
varying vec2 texcoord;

uniform float warmth;
uniform float contrast;
uniform float saturation;
uniform float shadow_lift;
uniform float highlight_compress;
uniform float vignette_radius;
uniform float vignette_softness;

void main() {
    // Color grade operates on the framebuffer via alpha blend
    // Base = mid-gray, modifications shift from there
    vec2 uv = texcoord;

    // Film curves
    float lift = shadow_lift;
    float compress = highlight_compress;

    // Warmth tint
    float r_shift = warmth * 0.08;
    float b_shift = -warmth * 0.04;

    // Vignette
    vec2 vc = uv * 2.0 - 1.0;
    float dist = length(vc);
    float vig = smoothstep(vignette_radius, vignette_radius - vignette_softness, dist);
    float darken = 1.0 - (1.0 - vig) * 0.4;

    // Composite as additive color shift
    gl_FragColor = vec4(
        r_shift * darken + lift,
        lift * darken,
        b_shift * darken + lift,
        0.15 * darken
    );
}
"""
        try:
            grade_shader = Shader.make(Shader.SL_GLSL, FULLSCREEN_VERT, grade_frag)
            cm = CardMaker("color_grade")
            cm.setFrameFullscreenQuad()
            self._grade_card = self.render2d.attachNewNode(cm.generate())
            self._grade_card.setShader(grade_shader)
            self._grade_card.setTransparency(TransparencyAttrib.MAlpha)
            self._grade_card.setBin("fixed", 90)  # before grain (100)
            # Set uniforms
            u = self._pp.get_composite_uniforms()
            self._grade_card.setShaderInput("warmth", u["warmth"])
            self._grade_card.setShaderInput("contrast", u["contrast"])
            self._grade_card.setShaderInput("saturation", u["saturation"])
            self._grade_card.setShaderInput("shadow_lift", u["shadow_lift"])
            self._grade_card.setShaderInput("highlight_compress", u["highlight_compress"])
            self._grade_card.setShaderInput("vignette_radius", u["vignette_radius"])
            self._grade_card.setShaderInput("vignette_softness", u["vignette_softness"])
            console.log(f"[green]Color grade ON[/green] warmth={pp_config.color_grade.warmth} "
                        f"vignette={pp_config.vignette.radius}")
        except Exception as e:
            console.log(f"[yellow]Color grade unavailable:[/yellow] {e}")
            self._grade_card = None

    def _setup_grain_shader(self):
        """Screen-space film grain — constant visual motion masks frame hitches."""
        from panda3d.core import Shader, CardMaker
        grain_glsl_vert = """
#version 120
attribute vec4 p3d_Vertex;
attribute vec2 p3d_MultiTexCoord0;
varying vec2 uv;
uniform mat4 p3d_ModelViewProjectionMatrix;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    uv = p3d_MultiTexCoord0;
}
"""
        grain_glsl_frag = """
#version 120
varying vec2 uv;
uniform float osg_FrameTime;

float hash(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

void main() {
    float grain = hash(uv * 800.0 + osg_FrameTime * 7.3) * 0.08 - 0.04;
    vec2 vc = uv - 0.5;
    float vign = 1.0 - dot(vc, vc) * 0.6;
    gl_FragColor = vec4(grain * vign, grain * vign, grain * vign * 0.9, 0.12);
}
"""
        try:
            shader = Shader.make(Shader.SL_GLSL, grain_glsl_vert, grain_glsl_frag)
            cm = CardMaker("grain_overlay")
            cm.setFrameFullscreenQuad()
            self._grain_card = self.render2d.attachNewNode(cm.generate())
            self._grain_card.setShader(shader)
            self._grain_card.setTransparency(TransparencyAttrib.MAlpha)
            self._grain_card.setBin("fixed", 100)  # render on top
        except Exception as e:
            console.log(f"[dim]Grain shader skipped: {e}[/dim]")
            self._grain_card = None

    # -- Terrain height --------------------------------------------------------

    def _height_at(self, x, y):
        """Global height function — mounds every ~10m, gentle rolling."""
        # Low-frequency rolling hills
        h1 = self._placer.perlin(x * 0.06, y * 0.06, octaves=2, persistence=0.5)
        # Mid-frequency mounds (~10m wavelength)
        h2 = self._placer.perlin(x * 0.1 + 50, y * 0.1 + 50, octaves=2, persistence=0.4)
        return h1 * 1.2 + h2 * 0.8  # 0-2m range

    # -- Chunk generation ------------------------------------------------------

    def _chunk_key(self, world_x, world_y):
        """World position -> chunk grid coords."""
        return (int(math.floor(world_x / CHUNK_SIZE)),
                int(math.floor(world_y / CHUNK_SIZE)))

    def _stage_initial_chunks(self):
        """Build the immediate area synchronously before the player sees anything."""
        cam_pos = self.cam.getPos()
        cx, cz = self._chunk_key(cam_pos.getX(), cam_pos.getY())
        console.log("[dim]Staging ground...[/dim]")

        # Build inner ring (3×3 = 9 chunks) — the player's immediate surroundings
        for dx in range(-1, 2):
            for dz in range(-1, 2):
                key = (cx + dx, cz + dz)
                self._generate_chunk_data(key)
                with self._chunk_lock:
                    data = self._ready_chunks.pop(key)
                self._chunks[key] = self._build_chunk_from_data(key[0], key[1], data)

        # Dispatch the rest to background threads — they'll stream in
        for dx in range(-PREGEN_RADIUS, PREGEN_RADIUS + 1):
            for dz in range(-PREGEN_RADIUS, PREGEN_RADIUS + 1):
                key = (cx + dx, cz + dz)
                if key not in self._chunks and key not in self._pending_chunks:
                    self._pending_chunks[key] = True
                    t = threading.Thread(
                        target=self._generate_chunk_data, args=(key,), daemon=True,
                    )
                    t.start()

        # Flush deferred entity spawns for initial chunks — player shouldn't start empty
        h_fn = self._flat_height if self._use_fake_ground else self._height_at
        while self._deferred_entity_spawns:
            kind, pos, heading, seed, chunk_key = self._deferred_entity_spawns.popleft()
            self._ambient.spawn(kind, pos=pos, heading=heading, seed=seed,
                                height_fn=h_fn, chunk_key=chunk_key,
                                biome=self._biome_key)
        console.log("[bold green]Ground ready.[/bold green]")

        # Pre-bake object field — baseball lineup of unique tiles
        self._object_tile_size = CHUNK_SIZE * 18  # ~288m per tile — 3× larger grid
        self._object_tile_placed = set()
        self._object_spawn_queue = __import__("collections").deque()  # drip-feed queue
        # Generate 7 unique templates — no two adjacent tiles use the same one
        self._object_templates = [
            self._generate_object_template(self._chunk_seed + i * 777)
            for i in range(7)
        ]
        self._place_object_tiles()
        # Stage initial objects — cap at 3000 sync, drip the rest across first frames
        console.log("[dim]Staging objects...[/dim]")
        h_fn = self._flat_height if self._use_fake_ground else self._height_at
        staged = 0
        while self._object_spawn_queue and staged < 3000:
            kind, wx, wy, heading, seed, tile_key = \
                self._object_spawn_queue.popleft()
            wz = h_fn(wx, wy)
            if kind == "leaf":
                wz += 3.0
            self._ambient.spawn(kind, pos=(wx, wy, wz),
                                heading=heading, seed=seed,
                                height_fn=h_fn,
                                chunk_key=tile_key,
                                biome=self._biome_key)
            staged += 1
        remaining = len(self._object_spawn_queue)
        console.log(f"[bold green]Objects ready. ({self._ambient.total_count} staged, {remaining} dripping)[/bold green]")

    def _generate_object_template(self, seed, biome=None):
        """Generate a tile layout with honeycomb path network.

        Scatter node points across the tile — these are walkable clearings.
        Hard objects cluster BETWEEN nodes (forming walls/dividers).
        Soft objects cluster NEAR nodes (visible as you walk through).
        Result: organic branching paths like a beehive, not one corridor.
        Mix of fungus, crystals, boulders at varying distances = natural
        choices about which way to go.
        """
        if biome is None:
            biome = BIOME_OUTDOOR_FOREST if self._biome == "outdoor" else BIOME_CAVERN_DEFAULT
        tile = self._object_tile_size
        tile_area = tile * tile
        rng = __import__("random").Random(seed)
        spawns = []
        solid_positions = []

        from core.systems.ambient_life import HARD_OBJECTS, biome_config

        # Tile variant roll — weighted random per tile seed
        variants = biome_config("tile_variants")
        variant_names = list(variants.keys())
        variant_weights = [variants[v]["weight"] for v in variant_names]
        variant_name = rng.choices(variant_names, weights=variant_weights, k=1)[0]
        variant = variants[variant_name]
        density_mult = variant.get("density_mult", 1.0)
        density_boost = variant.get("boost", {})

        # Honeycomb nodes = mega_column positions. Columns ARE the lattice.
        # First pass: place mega_columns on hex grid. These anchor every chamber.
        # All other objects fill around them.
        node_spacing = rng.uniform(14.0, 18.0)  # tight chambers — enclosed but won't choke staging
        nodes = []
        ny = node_spacing * 0.5
        row = 0
        while ny < tile:
            nx = node_spacing * 0.5 + (node_spacing * 0.5 if row % 2 else 0)
            while nx < tile:
                jx = nx + rng.uniform(-node_spacing * 0.15, node_spacing * 0.15)
                jy = ny + rng.uniform(-node_spacing * 0.15, node_spacing * 0.15)
                nodes.append((jx, jy))
                # 30% get a column anchor, 70% get a bio-lit landmark
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
                    anchor = "moss_patch"  # pure light source, no collision
                spawns.append((anchor, (jx, jy),
                               rng.uniform(0, 360), rng.randint(0, 99999)))
                nx += node_spacing
            ny += node_spacing * 0.87
            row += 1

        # Front-load spawn area — guarantee dense cluster near (0, 0)
        # Player should see a room, not a field, on first frame
        nodes.append((0.0, 0.0))  # spawn node
        for si in range(6):  # ring of 6 chambers around spawn
            angle = si * 60 + rng.uniform(-10, 10)
            dist = node_spacing * rng.uniform(0.8, 1.1)
            nodes.append((
                math.cos(math.radians(angle)) * dist,
                math.sin(math.radians(angle)) * dist,
            ))

        path_radius = rng.uniform(6.0, 10.0)  # clearance around each node

        # FrameComposer pass — compose directed views between selected hex node pairs.
        # Only compose ~30% of adjacent pairs to keep staging fast.
        from core.systems.frame_composer import FrameComposer, FRAMING_CONFIG
        frame_cfg = FRAMING_CONFIG.get(self._biome, FRAMING_CONFIG.get("cavern"))
        composer = FrameComposer(seed=seed)
        max_neighbor_dist = node_spacing * 2.0
        frame_rng = __import__("random").Random(seed + 777)
        for i in range(len(nodes)):
            if frame_rng.random() > 0.3:  # only 30% of nodes compose
                continue
            n1x, n1y = nodes[i]
            # Find nearest neighbor
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

        for kind, density, clearance, margin in biome:
            # Anchor objects placed at honeycomb nodes — skip from density pass
            if kind in ("mega_column", "column", "crystal_cluster", "giant_fungus"):
                continue
            # Tile variant modifies density: mult scales everything, boost scales specific kinds
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
                        # Hard objects: BETWEEN chambers (form walls)
                        if d < path_radius:
                            continue
                        # Dense near chamber edges — the walls
                        if d > path_radius * 2.5 and rng.random() < 0.6:
                            continue
                    else:
                        # Soft objects: PACKED into chambers (crowded, lived-in)
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
                    # Fallback: midpoint between two random nodes (on a path edge)
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

    def _place_object_tiles(self):
        """Queue object tiles around the camera. 5×5 scan, drip-spawned."""
        cam_pos = self.cam.getPos()
        tile = self._object_tile_size
        center_tx = int(math.floor(cam_pos.getX() / tile))
        center_ty = int(math.floor(cam_pos.getY() / tile))

        # Sort by distance — center tile + 1 ring (3×3 at 288m = 864m coverage)
        candidates = []
        if not hasattr(self, '_hibernated_tiles'):
            self._hibernated_tiles = set()

        for dx in range(-1, 2):
            for dy in range(-1, 2):
                tx, ty = center_tx + dx, center_ty + dy
                # Wake hibernated tiles instead of re-spawning
                if (tx, ty) in self._hibernated_tiles:
                    self._ambient.wake_chunk(("T", tx, ty))
                    self._hibernated_tiles.discard((tx, ty))
                    continue
                if (tx, ty) in self._object_tile_placed:
                    continue
                candidates.append((dx * dx + dy * dy, tx, ty))
        candidates.sort()

        for _dist, tx, ty in candidates:
            self._object_tile_placed.add((tx, ty))
            offset_x = tx * tile
            offset_y = ty * tile
            tile_key = (tx, ty)

            template_idx = (tx * 3 + ty * 5 + tx * ty) % len(self._object_templates)
            template = self._object_templates[template_idx]

            # Prefix tile keys with "T" so they never collide with chunk keys
            entity_key = ("T", tx, ty)

            for kind, (lx, ly), heading, seed in template:
                wx = offset_x + lx
                wy = offset_y + ly
                # Height deferred to drip time — keep this scan light
                self._object_spawn_queue.append(
                    (kind, wx, wy, heading,
                     seed + tx * 1000 + ty, entity_key))

    def _despawn_distant_tiles(self):
        """Hibernate distant tiles — keep in memory for return trips.

        Tiles beyond radius 3 hibernate (hide, not destroy). Tiles beyond
        radius 6 (50+ tiles visited) get fully destroyed to cap memory.
        The player can turn around and find the same cave they left.
        """
        cam_pos = self.cam.getPos()
        tile = self._object_tile_size
        center_tx = int(math.floor(cam_pos.getX() / tile))
        center_ty = int(math.floor(cam_pos.getY() / tile))

        # Track path — breadcrumb of visited tiles
        current_tile = (center_tx, center_ty)
        if not hasattr(self, '_path_trail'):
            self._path_trail = []
            self._hibernated_tiles = set()
        if not self._path_trail or self._path_trail[-1] != current_tile:
            self._path_trail.append(current_tile)

        # Hibernate tiles beyond radius 3 (keep in memory)
        to_hibernate = [k for k in self._object_tile_placed
                        if abs(k[0] - center_tx) > 3 or abs(k[1] - center_ty) > 3]
        for k in to_hibernate:
            chunk_key = ("T", k[0], k[1])
            if k not in self._hibernated_tiles:
                self._ambient.hibernate_chunk(chunk_key)
                self._hibernated_tiles.add(k)

        # Hard destroy tiles beyond radius 4 — free entity budget for tiles ahead
        # Was radius 6, but 25K cap fills before player reaches new tiles.
        # Tighter destroy = faster budget recycling = continuous world generation.
        to_destroy = [k for k in self._hibernated_tiles
                      if abs(k[0] - center_tx) > 4 or abs(k[1] - center_ty) > 4]
        for k in to_destroy:
            self._ambient.despawn_chunk(("T", k[0], k[1]))
            self._object_tile_placed.discard(k)
            self._hibernated_tiles.discard(k)

    def _drip_spawn_objects(self):
        """Spawn queued objects across frames. 16 per frame — smooth drip."""
        # Hard cap reached — flush queue, don't accumulate forever
        if self._ambient.total_count >= self._ambient.MAX_ENTITIES:
            self._object_spawn_queue.clear()
            self._drip_this_frame = 0
            return
        h_fn = self._flat_height if self._use_fake_ground else self._height_at
        spawned = 0
        for _ in range(16):  # 16 per frame — clear queue faster
            if not self._object_spawn_queue:
                break
            kind, wx, wy, heading, seed, tile_key = \
                self._object_spawn_queue.popleft()
            wz = h_fn(wx, wy)
            if kind == "leaf":
                wz += 3.0
            self._ambient.spawn(kind, pos=(wx, wy, wz),
                                heading=heading, seed=seed,
                                height_fn=h_fn,
                                chunk_key=tile_key,
                                biome=self._biome_key)
            spawned += 1
        self._drip_this_frame = spawned

    # -- Chunk subsystems (split for 60-frame cycle) ----------------------------

    def _dispatch_chunks(self):
        """Scan for needed chunks, dispatch background threads. Light."""
        cam_pos = self.cam.getPos()
        center_cx, center_cz = self._chunk_key(cam_pos.getX(), cam_pos.getY())

        h_rad = math.radians(self._cam_h)
        fwd_x = -math.sin(h_rad)
        fwd_y = math.cos(h_rad)

        max_concurrent = 6
        active_threads = len(self._pending_chunks)

        needed = []
        for dx in range(-PREGEN_RADIUS, PREGEN_RADIUS + 1):
            for dz in range(-PREGEN_RADIUS, PREGEN_RADIUS + 1):
                key = (center_cx + dx, center_cz + dz)
                if key not in self._chunks and key not in self._pending_chunks:
                    with self._chunk_lock:
                        if key not in self._ready_chunks:
                            needed.append(key)

        def chunk_priority(k):
            dx, dz = k[0] - center_cx, k[1] - center_cz
            dist2 = dx * dx + dz * dz
            dot = dx * fwd_x + dz * fwd_y
            return dist2 - dot * 3.0
        needed.sort(key=chunk_priority)

        for key in needed:
            if active_threads >= max_concurrent:
                break
            self._pending_chunks[key] = True
            t = threading.Thread(
                target=self._generate_chunk_data, args=(key,), daemon=True,
            )
            t.start()
            active_threads += 1

    def _build_ready_chunk(self):
        """Build exactly ONE ready chunk. Minimal frame impact."""
        cam_pos = self.cam.getPos()
        center_cx, center_cz = self._chunk_key(cam_pos.getX(), cam_pos.getY())

        with self._chunk_lock:
            ready_keys = [k for k in self._ready_chunks if k not in self._chunks]
            if not ready_keys:
                # Clean stale
                for key in list(self._ready_chunks.keys()):
                    if key in self._chunks:
                        self._ready_chunks.pop(key)
                return
            ready_keys.sort(key=lambda k: (k[0] - center_cx) ** 2 + (k[1] - center_cz) ** 2)
            key = ready_keys[0]
            data = self._ready_chunks.pop(key)

        self._chunks[key] = self._build_chunk_from_data(key[0], key[1], data)

    def _despawn_distant(self):
        """Remove chunks far from camera. Throttled: max 3 per call."""
        cam_pos = self.cam.getPos()
        center_cx, center_cz = self._chunk_key(cam_pos.getX(), cam_pos.getY())
        removed = 0
        for key in list(self._chunks):
            if removed >= 3:
                break
            if (abs(key[0] - center_cx) > DESPAWN_RADIUS or
                    abs(key[1] - center_cz) > DESPAWN_RADIUS):
                self._chunks[key].removeNode()
                del self._chunks[key]
                removed += 1

    def _generate_chunk_data(self, key):
        """Background thread: compute ALL chunk data (texture + mesh + spawns)."""
        cx, cz = key
        chunk_seed = hash((self._chunk_seed, cx, cz)) & 0xFFFFFFFF
        tex_size = getattr(self, '_tex_size_override', TEX_SIZE)
        world_x = cx * CHUNK_SIZE
        world_y = cz * CHUNK_SIZE

        # Texture bytes (native Perlin)
        tex_bytes = self._compute_cobblestone_pixels(cx, cz)

        # Mesh data — pre-compute all vertices, normals, UVs
        subdivs = 7
        step = CHUNK_SIZE / subdivs
        verts = []   # (x, y, z) tuples
        norms = []   # (nx, ny, nz) tuples
        uvs = []     # (u, v) tuples
        for gy in range(subdivs + 1):
            for gx in range(subdivs + 1):
                wx = world_x + gx * step
                wy = world_y + gy * step
                wz = self._height_at(wx, wy)
                verts.append((wx, wy, wz))
                dx_h = self._height_at(wx + 0.5, wy) - self._height_at(wx - 0.5, wy)
                dy_h = self._height_at(wx, wy + 0.5) - self._height_at(wx, wy - 0.5)
                nmag = math.sqrt(dx_h * dx_h + dy_h * dy_h + 1.0)
                norms.append((-dx_h / nmag, -dy_h / nmag, 1.0 / nmag))
                uvs.append((gx / subdivs, gy / subdivs))

        # Objects are handled by the tile system now — not per-chunk
        ambient_spawns = []

        with self._chunk_lock:
            self._ready_chunks[key] = {
                "tex_bytes": tex_bytes, "tex_size": tex_size,
                "verts": verts, "norms": norms, "uvs": uvs,
                "subdivs": subdivs, "seed": chunk_seed,
                "spawns": ambient_spawns,
            }
            self._pending_chunks.pop(key, None)

    # -- Chunk builder (heightmap + cobblestone + entities) ---------------------

    def _build_chunk(self, cx, cz):
        """Heightmap mesh + cobblestone texture + boulders + rats."""
        chunk_root = self.render.attachNewNode(f"chunk_{cx}_{cz}")
        world_x = cx * CHUNK_SIZE
        world_y = cz * CHUNK_SIZE
        chunk_seed = hash((self._chunk_seed, cx, cz)) & 0xFFFFFFFF
        rng = __import__("random").Random(chunk_seed)

        # -- Subdivided ground mesh following height function --
        subdivs = 7
        if hasattr(self, '_prebuilt_tex') and self._prebuilt_tex is not None:
            tex = self._prebuilt_tex
        else:
            pixels = self._compute_cobblestone_pixels(cx, cz)
            tex = self._pixels_to_texture(pixels, f"cobble_{cx}_{cz}")

        fmt = GeomVertexFormat.getV3n3t2()
        vdata = GeomVertexData(f"terrain_{cx}_{cz}", fmt, Geom.UHStatic)
        vdata.setNumRows((subdivs + 1) ** 2)
        vw = GeomVertexWriter(vdata, "vertex")
        nw = GeomVertexWriter(vdata, "normal")
        tw = GeomVertexWriter(vdata, "texcoord")

        step = CHUNK_SIZE / subdivs
        for gy in range(subdivs + 1):
            for gx in range(subdivs + 1):
                wx = world_x + gx * step
                wy = world_y + gy * step
                wz = self._height_at(wx, wy)
                vw.addData3(wx, wy, wz)
                dx_h = self._height_at(wx + 0.5, wy) - self._height_at(wx - 0.5, wy)
                dy_h = self._height_at(wx, wy + 0.5) - self._height_at(wx, wy - 0.5)
                nmag = math.sqrt(dx_h * dx_h + dy_h * dy_h + 1.0)
                nw.addData3(-dx_h / nmag, -dy_h / nmag, 1.0 / nmag)
                tw.addData2(gx / subdivs, gy / subdivs)

        tris = GeomTriangles(Geom.UHStatic)
        for gy in range(subdivs):
            for gx in range(subdivs):
                i = gy * (subdivs + 1) + gx
                tris.addVertices(i, i + 1, i + subdivs + 2)
                tris.addVertices(i, i + subdivs + 2, i + subdivs + 1)

        geom = Geom(vdata)
        geom.addPrimitive(tris)
        gn = GeomNode(f"ground_{cx}_{cz}")
        gn.addGeom(geom)
        ground_np = chunk_root.attachNewNode(gn)
        ground_np.setTexture(tex)
        ground_np.setTwoSided(True)

        # -- Ambient life (behavior-driven, sleep/wake by proximity) --
        chunk_key = (cx, cz)
        rat_count = rng.choices([0, 1, 1, 2], weights=[2, 5, 5, 1])[0]
        for ri in range(rat_count):
            rx = world_x + rng.uniform(2, CHUNK_SIZE - 2)
            ry = world_y + rng.uniform(2, CHUNK_SIZE - 2)
            rz = self._height_at(rx, ry)
            self._ambient.spawn("rat", pos=(rx, ry, rz),
                                heading=rng.uniform(0, 360),
                                seed=chunk_seed + 2000 + ri,
                                height_fn=self._height_at,
                                chunk_key=chunk_key,
                                biome=self._biome_key)

        # Occasional leaf drift from above
        leaf_count = rng.choices([0, 0, 1, 2], weights=[4, 3, 2, 1])[0]
        for li in range(leaf_count):
            lx = world_x + rng.uniform(1, CHUNK_SIZE - 1)
            ly = world_y + rng.uniform(1, CHUNK_SIZE - 1)
            lz = self._height_at(lx, ly) + rng.uniform(2.0, 5.0)
            self._ambient.spawn("leaf", pos=(lx, ly, lz),
                                seed=chunk_seed + 3000 + li,
                                height_fn=self._height_at,
                                chunk_key=chunk_key,
                                biome=self._biome_key)

        return chunk_root

    def _build_chunk_from_data(self, cx, cz, data):
        """Main thread: load pre-computed arrays into Panda3D. No math here."""
        chunk_root = self.render.attachNewNode(f"chunk_{cx}_{cz}")

        # Texture — bulk load (single C++ call)
        tex = self._bytes_to_texture(data["tex_bytes"], data["tex_size"], f"cobble_{cx}_{cz}")

        # Mesh — load pre-computed verts/norms/uvs
        subdivs = data["subdivs"]
        verts, norms, uvs = data["verts"], data["norms"], data["uvs"]

        fmt = GeomVertexFormat.getV3n3t2()
        vdata = GeomVertexData(f"terrain_{cx}_{cz}", fmt, Geom.UHStatic)
        vdata.setNumRows(len(verts))
        vw = GeomVertexWriter(vdata, "vertex")
        nw = GeomVertexWriter(vdata, "normal")
        tw = GeomVertexWriter(vdata, "texcoord")
        for (vx, vy, vz), (nx, ny, nz), (u, v) in zip(verts, norms, uvs):
            vw.addData3(vx, vy, vz)
            nw.addData3(nx, ny, nz)
            tw.addData2(u, v)

        tris = GeomTriangles(Geom.UHStatic)
        for gy in range(subdivs):
            for gx in range(subdivs):
                i = gy * (subdivs + 1) + gx
                tris.addVertices(i, i + 1, i + subdivs + 2)
                tris.addVertices(i, i + subdivs + 2, i + subdivs + 1)

        geom = Geom(vdata)
        geom.addPrimitive(tris)
        gn = GeomNode(f"ground_{cx}_{cz}")
        gn.addGeom(geom)
        ground_np = chunk_root.attachNewNode(gn)
        ground_np.setTexture(tex)
        ground_np.setTwoSided(True)

        # Defer entity spawns — drip them across frames instead of all at once.
        # This is what turns 121ms spikes into smooth 8ms frames.
        chunk_key = (cx, cz)
        for kind, pos, heading, seed in data["spawns"]:
            self._deferred_entity_spawns.append((kind, pos, heading, seed, chunk_key))

        # Ensure ground receives per-pixel lighting from auto shader
        # ground_np.setShaderAuto()  # REMOVED — Metal GPU stalls

        # If fake ground is active, stash new chunks immediately
        if self._use_fake_ground:
            chunk_root.stash()

        return chunk_root

    def _bytes_to_texture(self, flat_bytes, tex_size, name):
        """Bulk texture load — single C++ copy, no pixel loop."""
        tex = Texture(name)
        tex.setup2dTexture(tex_size, tex_size, Texture.T_unsigned_byte, Texture.F_rgb8)
        tex.setRamImage(bytes(flat_bytes))
        tex.setMagfilter(SamplerState.FT_nearest)
        tex.setMinfilter(SamplerState.FT_nearest)
        tex.setWrapU(SamplerState.WM_clamp)
        tex.setWrapV(SamplerState.WM_clamp)
        return tex

    def _compute_cobblestone_pixels(self, cx, cz):
        """Ground texture — dirt+pebble Voronoi. Biome-aware colors."""
        tex_size = getattr(self, '_tex_size_override', TEX_SIZE)
        pal = self._palette
        noise = self._noise

        if self._biome == "outdoor":
            # PNW forest floor: green-brown grass with bare earth between
            dirt_r, dirt_g, dirt_b = 0.09, 0.11, 0.05   # forest earth (brighter)
            stone_size = 0.65
            jitter_amt = 0.95
            overscan = 2.5
            pebble_chance = 0.60  # more cells visible = denser grass clumps
        else:
            floor = pal.get("stage_floor", (0.08, 0.06, 0.05))
            dirt_r, dirt_g, dirt_b = floor[0] * 0.55, floor[1] * 0.50, floor[2] * 0.45
            stone_size = 0.65
            jitter_amt = 0.95
            overscan = 2.5
            pebble_chance = 0.55

        cells = []
        cell_colors = []
        cell_visible = []
        x_start = cx * CHUNK_SIZE - overscan
        y_start = cz * CHUNK_SIZE - overscan
        x_end = (cx + 1) * CHUNK_SIZE + overscan
        y_end = (cz + 1) * CHUNK_SIZE + overscan

        # Native Perlin for cell jitter + color (C++ speed)
        n_jx, n_jy = noise["jitter_x"], noise["jitter_y"]
        n_gate = noise["gate"]
        n_color, n_warm = noise["color"], noise["warm"]

        gx = x_start
        while gx < x_end:
            gy = y_start
            while gy < y_end:
                jx = n_jx(gx, gy) * 0.5  # native returns -1..1, scale to -0.5..0.5
                jy = n_jy(gx + 100, gy + 100) * 0.5
                wx = gx + jx * stone_size * jitter_amt
                wy = gy + jy * stone_size * jitter_amt
                cells.append((wx, wy))

                gate = (n_gate(wx, wy) + 1.0) * 0.5  # normalize to 0..1
                cell_visible.append(gate > (1.0 - pebble_chance))

                n = (n_color(wx, wy) + 1.0) * 0.5
                v = (n - 0.5) * 0.10
                w = (n_warm(wx, wy) + 1.0) * 0.5
                warm = (w - 0.5) * 0.06
                if self._biome == "outdoor":
                    # Grass clumps: green dominant, warm variation = yellowed grass
                    cell_colors.append((
                        max(0, min(1, 0.09 + v * 0.5 + warm)),       # slightly warm
                        max(0, min(1, 0.16 + v + warm * 0.3)),       # visible green
                        max(0, min(1, 0.05 + v * 0.3 - warm * 0.2)),  # low blue
                    ))
                else:
                    cell_colors.append((
                        max(0, min(1, dirt_r + 0.08 + v + warm)),
                        max(0, min(1, dirt_g + 0.06 + v)),
                        max(0, min(1, dirt_b + 0.05 + v - warm * 0.3)),
                    ))
                gy += stone_size
            gx += stone_size

        # Spatial hash
        bucket_size = stone_size * 1.5
        buckets = {}
        for ci, (ccx, ccy) in enumerate(cells):
            bx = int(math.floor(ccx / bucket_size))
            by = int(math.floor(ccy / bucket_size))
            key = (bx, by)
            if key not in buckets:
                buckets[key] = []
            buckets[key].append(ci)

        # Per-pixel — native Perlin for dirt/grit/stone noise
        n_dirt1, n_dirt2 = noise["dirt1"], noise["dirt2"]
        n_grit, n_stone = noise["grit"], noise["stone"]
        pebble_radius = stone_size * 0.28

        flat = bytearray(tex_size * tex_size * 3)
        idx = 0
        for y in range(tex_size):
            for x in range(tex_size):
                px = cx * CHUNK_SIZE + (x / tex_size) * CHUNK_SIZE
                py = cz * CHUNK_SIZE + (y / tex_size) * CHUNK_SIZE

                bx = int(math.floor(px / bucket_size))
                by = int(math.floor(py / bucket_size))
                min_d1, min_d2 = 999.0, 999.0
                min_ci = 0
                for dbx in range(-1, 2):
                    for dby in range(-1, 2):
                        for ci in buckets.get((bx + dbx, by + dby), ()):
                            ccx, ccy = cells[ci]
                            ddx = px - ccx
                            ddy = py - ccy
                            d = ddx * ddx + ddy * ddy
                            if d < min_d1:
                                min_d2 = min_d1
                                min_d1 = d
                                min_ci = ci
                            elif d < min_d2:
                                min_d2 = d

                min_d1 = math.sqrt(min_d1)

                # Dirt + grit (native Perlin — fast)
                dn1 = (n_dirt1(px, py) + 1.0) * 0.5
                dn2 = (n_dirt2(px, py) + 1.0) * 0.5
                dirt_var = (dn1 - 0.5) * 0.08 + (dn2 - 0.5) * 0.03
                grit = (n_grit(px, py) + 1.0) * 0.5
                grit_boost = max(0, (grit - 0.35)) * 0.12

                dr = max(0.0, min(1.0, dirt_r + dirt_var + grit_boost + 0.01))
                dg = max(0.0, min(1.0, dirt_g + dirt_var + grit_boost * 0.8))
                db = max(0.0, min(1.0, dirt_b + dirt_var + grit_boost * 0.5 - 0.005))

                is_pebble = cell_visible[min_ci % len(cell_visible)] and min_d1 < pebble_radius

                if is_pebble:
                    cr, cg, cb = cell_colors[min_ci % len(cell_colors)]
                    center_dist = min_d1 / pebble_radius
                    edge_blend = min(1.0, center_dist * 1.4)
                    shade = 1.0 - center_dist * center_dist * center_dist * 0.65
                    sv = n_stone(px, py) * 0.04
                    pr = max(0.0, min(1.0, cr * shade + sv))
                    pg = max(0.0, min(1.0, cg * shade + sv))
                    pb = max(0.0, min(1.0, cb * shade + sv))
                    pr = pr * 0.75 + dr * 0.25
                    pg = pg * 0.75 + dg * 0.25
                    pb = pb * 0.75 + db * 0.25
                    if edge_blend > 0.6:
                        t = (edge_blend - 0.6) / 0.4
                        pr = pr * (1 - t) + dr * t
                        pg = pg * (1 - t) + dg * t
                        pb = pb * (1 - t) + db * t
                    flat[idx] = min(255, int(pr * 255))
                    flat[idx + 1] = min(255, int(pg * 255))
                    flat[idx + 2] = min(255, int(pb * 255))
                else:
                    flat[idx] = min(255, int(dr * 255))
                    flat[idx + 1] = min(255, int(dg * 255))
                    flat[idx + 2] = min(255, int(db * 255))
                idx += 3
        return flat

    def _pixels_to_texture(self, pixels, name):
        """Main thread: convert pixel rows to Panda3D Texture."""
        tex_size = len(pixels)  # matches whatever _tex_size_override was used
        img = PNMImage(tex_size, tex_size)
        for y, row in enumerate(pixels):
            for x, (r, g, b) in enumerate(row):
                img.setXel(x, y, r, g, b)
        tex = Texture(name)
        tex.load(img)
        tex.setMagfilter(SamplerState.FT_nearest)
        tex.setMinfilter(SamplerState.FT_nearest)
        tex.setWrapU(SamplerState.WM_clamp)
        tex.setWrapV(SamplerState.WM_clamp)
        return tex

    # -- Register switching ----------------------------------------------------

    def _cycle_register(self, index):
        self._register_index = index % len(REGISTERS)
        reg = REGISTERS[self._register_index]
        self._palette = resolve_palette(reg)

        # Update lighting — outdoor preserves light-state fog/ambient,
        # register tints the ground texture palette only
        lc = self._palette["sconce"]
        if hasattr(self, "_player_light") and self._player_light:
            self._player_light.node().setColor(Vec4(lc[0] * 0.8, lc[1] * 0.7, lc[2] * 0.4, 1))

        if self._biome == "outdoor":
            # Outdoor: register changes ground texture palette but fog/ambient
            # stay anchored to the current light state (day/dusk/night)
            self._apply_light_state()
        else:
            # Cavern: register drives everything
            fc = self._palette["fog"]
            self._fog.setColor(Vec4(fc[0], fc[1], fc[2], 1))
            bg = self._palette["backdrop"]
            self.setBackgroundColor(bg[0], bg[1], bg[2], 1)

        # Rebuild all chunks with new palette
        for key, np in list(self._chunks.items()):
            np.removeNode()
        self._chunks.clear()
        self._dispatch_chunks()

        console.log(f"[bold magenta]REGISTER[/bold magenta]  {reg}")

    # -- Debug telemetry (carried from dungeon) --------------------------------

    def _toggle_fake_ground(self):
        """G key — A/B test: real chunked ground vs WorldRunner cheat ground."""
        self._use_fake_ground = not self._use_fake_ground
        if self._use_fake_ground:
            # Capture current terrain height so camera doesn't jump
            pos = self.cam.getPos()
            self._ground_blend_z = self._height_at(pos.getX(), pos.getY())
            # Stash real chunks off the scene graph entirely — not just hidden
            for key, node in self._chunks.items():
                node.stash()
            self._fake_ground.show()
            # Reseat ALL entities from Perlin heights to Z=0
            self._ambient.reseat_ground(self._height_at, self._flat_height)
            console.log("[bold green]FAKE GROUND[/bold green] — one plane, one texture, zero Perlin")
        else:
            # Capture flat→terrain offset so camera doesn't jump
            pos = self.cam.getPos()
            self._ground_blend_z = -(self._height_at(pos.getX(), pos.getY()))
            # Unstash real chunks back into the scene
            for key, node in self._chunks.items():
                node.unstash()
            self._fake_ground.hide()
            # Reseat ALL entities from Z=0 back to Perlin heights
            self._ambient.reseat_ground(self._flat_height, self._height_at)
            console.log("[bold green]REAL GROUND[/bold green] — chunked Perlin geometry")

    def _toggle_daylight(self):
        """L key — cycle through light states. Both biomes use the same pattern."""
        self._light_index = (self._light_index + 1) % len(self._light_order)
        self._light_state = self._light_order[self._light_index]
        self._daylight = (self._light_state != self._light_order[0])  # legacy compat
        self._apply_light_state()
        # Imposters: hide in bright states (visible as boxes), show in dark
        is_dark = self._light_state in ("night", "cave")
        for e in self._ambient._entities:
            if e.imposter and not e.imposter.isEmpty():
                e.imposter.show() if is_dark else e.imposter.hide()
        console.log(f"[bold]{self._light_state.upper()}[/bold]")

    def _toggle_debug(self):
        self._debug_mode = not self._debug_mode
        if self._debug_mode:
            if not self._debug_hud_text:
                self._debug_hud_text = OnscreenText(
                    text="", pos=(-1.55, -0.65), scale=0.030,
                    fg=(0.4, 1.0, 0.4, 0.75), align=TextNode.ALeft,
                    mayChange=True,
                )
            self._debug_hud_text.show()
        else:
            if self._debug_hud_text:
                self._debug_hud_text.hide()

    def _calc_probe(self):
        h_rad = math.radians(self._cam_h)
        p_rad = math.radians(self._cam_p)
        cos_p = math.cos(p_rad)
        dx = -math.sin(h_rad) * cos_p
        dy = math.cos(h_rad) * cos_p
        dz = math.sin(p_rad)
        cx, cy, cz = self.cam.getX(), self.cam.getY(), self.cam.getZ()

        # Floor hit
        if dz < -0.001:
            t = -cz / dz
            hx, hy = cx + dx * t, cy + dy * t
            return {"surface": "floor", "distance": round(t, 2),
                    "hit": [round(hx, 2), round(hy, 2), 0.0],
                    "chunk": list(self._chunk_key(hx, hy))}
        return {"surface": "sky", "distance": -1, "hit": [0, 0, 0]}

    def _place_tag(self, label=None):
        """Drop a breadcrumb at the player's feet — visible behind you as you walk."""
        self._tag_counter += 1
        tag_id = self._tag_counter
        cx, cy, cz = self.cam.getX(), self.cam.getY(), self.cam.getZ()
        # Ground level at player position
        gz = self._height_at(cx, cy)
        pos = [round(cx, 2), round(cy, 2), round(gz, 2)]
        text = label or f"#{tag_id}"

        tn = TextNode(f"tag_{tag_id}")
        tn.setText(text)
        tn.setAlign(TextNode.ACenter)
        tn.setTextColor(1.0, 0.85, 0.2, 0.9)
        tn.setCardColor(0.0, 0.0, 0.0, 0.5)
        tn.setCardAsMargin(0.15, 0.15, 0.08, 0.08)
        tn.setCardDecal(True)
        node = self.render.attachNewNode(tn)
        node.setPos(pos[0], pos[1], pos[2] + 0.5)
        node.setScale(0.25)
        node.setBillboardPointEye()
        node.setLightOff()  # always visible, ignores scene lighting

        chunk = list(self._chunk_key(cx, cy))
        tile = self._object_tile_size
        tile_key = (int(math.floor(cx / tile)), int(math.floor(cy / tile)))

        # Performance telemetry at moment of drop
        dt = globalClock.getDt()
        frame_ms = round(dt * 1000, 1)
        ft = self._frame_times
        avg_ms = round(sum(ft) / len(ft), 1) if ft else frame_ms
        queue_depth = len(self._object_spawn_queue)
        entities_total = self._ambient.total_count
        entities_active = self._ambient.active_count
        entities_hibernated = self._ambient.hibernated_count
        chunks_loaded = len(self._chunks)
        import time as _time
        wall_time = round(_time.time(), 3)
        census = self._ambient.kind_census()

        tag = {
            "id": tag_id, "label": text,
            "surface": "feet", "distance": 0,
            "pos": pos, "chunk": chunk, "tile": list(tile_key),
            "camera": {
                "x": round(cx, 2), "y": round(cy, 2),
                "z": round(cz, 2),
                "h": round(self._cam_h, 1), "p": round(self._cam_p, 1),
            },
            "perf": {
                "frame_ms": frame_ms,
                "avg_ms": avg_ms,
                "drip_per_frame": self._drip_this_frame,
                "spawn_queue": queue_depth,
                "entities_total": entities_total,
                "entities_active": entities_active,
                "entities_hibernated": entities_hibernated,
                "chunks_loaded": chunks_loaded,
                "wall_time": wall_time,
            },
            "tension": {
                "active": self._tension.active,
                "state": self._tension.state,
                "budget": round(self._tension.budget, 3),
            },
            "census": {k: {"active": a, "total": t, "hibernated": h}
                       for k, (a, t, h) in census.items()},
            "_node": node,
        }
        self._debug_tags.append(tag)
        console.log(f"[bold yellow]TAG #{tag_id}[/bold yellow]  "
                     f"chunk={chunk}  tile={list(tile_key)}  "
                     f"frame={frame_ms}ms  queue={queue_depth}  "
                     f"ent={entities_active}/{entities_total}  @ {pos}")

    def _undo_last_tag(self):
        if not self._debug_tags:
            return
        tag = self._debug_tags.pop()
        try:
            if tag.get("_node") and not tag["_node"].isEmpty():
                tag["_node"].removeNode()
        except Exception:
            pass

    def _clear_tags(self):
        for tag in self._debug_tags:
            try:
                if tag.get("_node") and not tag["_node"].isEmpty():
                    tag["_node"].removeNode()
            except Exception:
                pass
        self._debug_tags.clear()
        self._tag_counter = 0

    def _showcase_light_layers(self):
        """Spawn a museum arc of every base×light combo in front of the camera.

        Two-row arc: front row = smaller objects, back row = larger objects.
        Columns = [dark, moss, crystal, torch] with labels overhead.
        All objects at roughly the same viewing distance.
        Press 9 again to clear.
        """
        from panda3d.core import TextNode
        from direct.gui.OnscreenText import OnscreenText
        from core.systems.ambient_life import (
            BUILDERS, LIGHT_LAYERS, apply_light_layer,
        )

        # Toggle — if showcase exists, remove it
        if hasattr(self, "_showcase_root") and self._showcase_root:
            self._showcase_root.removeNode()
            self._showcase_root = None
            for txt in getattr(self, "_showcase_labels", []):
                txt.destroy()
            self._showcase_labels = []
            console.log("[bold cyan]SHOWCASE[/bold cyan]  cleared")
            return

        # Rows: front (small objects) and back (large objects)
        front_row = ["dead_log", "rubble", "bone_pile"]
        back_row = ["boulder", "stalagmite", "column"]
        layers = [None] + list(LIGHT_LAYERS.keys())  # dark, moss, crystal, torch
        layer_labels = ["dark"] + list(LIGHT_LAYERS.keys())

        cam = self.cam.getPos()
        cam_h = self._cam_h
        fwd_x = -math.sin(math.radians(cam_h))
        fwd_y = math.cos(math.radians(cam_h))
        right_x = fwd_y
        right_y = -fwd_x

        col_spacing = 15.0
        front_dist = 15.0   # small objects closer
        back_dist = 28.0    # large objects further back
        self._showcase_root = self.render.attachNewNode("showcase_grid")
        self._showcase_labels = []

        total_w = (len(layers) - 1) * col_spacing
        seed_base = 12345
        h_fn = self._flat_height if self._use_fake_ground else self._height_at

        def _spawn_row(kinds, forward_dist, row_idx):
            for col, layer_name in enumerate(layers):
                cx = col * col_spacing - total_w * 0.5
                wx = cam.getX() + fwd_x * forward_dist + right_x * cx
                wy = cam.getY() + fwd_y * forward_dist + right_y * cx
                wz = h_fn(wx, wy) + 0.3  # slight lift so decals read clearly

                # Cycle through row objects per column for variety
                kind = kinds[col % len(kinds)]
                if kind not in BUILDERS:
                    continue
                builder_fn, _ = BUILDERS[kind]
                seed = seed_base + row_idx * 1000 + col * 100
                node = builder_fn(self._showcase_root, seed=seed)
                if layer_name is not None:
                    apply_light_layer(node, layer_name, seed)
                node.setPos(wx, wy, wz)
                # Face toward camera
                node.setH(cam_h + 180)

        _spawn_row(front_row, front_dist, 0)
        _spawn_row(back_row, back_dist, 1)

        # Column labels — screen-space text at top
        for col, label in enumerate(layer_labels):
            # Evenly spaced across the top of the screen
            x_ndc = -0.6 + col * (1.2 / max(1, len(layer_labels) - 1))
            txt = OnscreenText(
                text=label.upper(),
                pos=(x_ndc, 0.85),
                scale=0.06,
                fg=(1, 1, 1, 0.7),
                shadow=(0, 0, 0, 0.8),
                align=TextNode.ACenter,
            )
            self._showcase_labels.append(txt)

        count = (len(front_row) + len(back_row)) * len(layers)
        console.log(f"[bold cyan]SHOWCASE[/bold cyan]  {len(layers)} columns × 2 rows — "
                    f"look ahead, columns labeled on screen")
        console.log("[dim]Press 9 again to clear[/dim]")

    # -- Tension Cycle hooks ---------------------------------------------------

    def _toggle_tension(self):
        """5 key — board or disembark the train."""
        if self._tension.active:
            self._tension.disembark()
            console.log("[bold yellow]TRAIN: disembarked[/bold yellow]")
        else:
            self._tension.board()
            console.log("[bold red]TRAIN: boarded[/bold red]")

    def _on_tension_state(self, old, new):
        console.log(f"[dim]TRAIN: {old} → {new}  "
                     f"budget={self._tension.budget:.0%}[/dim]")

    def _on_tension_dump(self):
        """Dump phase — hibernate distant, clear spawn queue."""
        console.log("[bold red]TRAIN: DUMP — hibernating distant tiles[/bold red]")

    def _on_tension_rebirth(self):
        """Rebirth phase — world re-emerges from darkness."""
        console.log("[bold green]TRAIN: REBIRTH — world returning[/bold green]")

    # -- Debug -----------------------------------------------------------------

    def _dump_debug_state(self):
        import traceback
        try:
            self._probe_data = self._calc_probe()
            cam = self.cam.getPos()
            ft = self._frame_times
            avg_ms = round(sum(ft) / len(ft), 1) if ft else 0
            census = self._ambient.kind_census()
            state = {
                "camera": {
                    "x": round(cam.getX(), 3), "y": round(cam.getY(), 3),
                    "z": round(cam.getZ(), 3),
                    "h": round(self._cam_h, 1), "p": round(self._cam_p, 1),
                },
                "probe": self._probe_data,
                "tags": [{k: v for k, v in t.items() if k != "_node"}
                         for t in self._debug_tags],
                "register": REGISTERS[self._register_index],
                "chunks_loaded": len(self._chunks),
                "perf": {
                    "avg_ms": avg_ms,
                    "drip_per_frame": self._drip_this_frame,
                    "spawn_queue": len(self._object_spawn_queue),
                    "entities_total": self._ambient.total_count,
                    "entities_active": self._ambient.active_count,
                    "entities_hibernated": self._ambient.hibernated_count,
                },
                "tension": {
                    "active": self._tension.active,
                    "state": self._tension.state,
                    "budget": round(self._tension.budget, 3),
                },
                "census": {k: {"active": a, "total": t, "hibernated": h}
                           for k, (a, t, h) in census.items()},
                "biome": self._biome,
                "light_state": self._light_state,
                "rendering": {
                    "fog_color": [round(self._fog.getColor()[i], 3) for i in range(3)],
                    "ambient": [round(self._amb_np.node().getColor()[i], 3) for i in range(3)],
                    "far_clip": round(self.camLens.getFar(), 1),
                },
                "palette": {k: list(v) if isinstance(v, tuple) else v
                            for k, v in self._palette.items()},
            }
            with open(self._state_path, "w") as f:
                json.dump(state, f, indent=2, default=str)
            console.log(f"[bold green]STATE DUMPED[/bold green]  "
                         f"chunks={len(self._chunks)}  tags={len(self._debug_tags)}  "
                         f"avg={avg_ms}ms  active={self._ambient.active_count}")
        except Exception as e:
            console.log(f"[bold red]DUMP FAILED[/bold red]  {e}")
            traceback.print_exc()

    def _check_debug_commands(self):
        try:
            with open(self._cmd_path, "r") as f:
                cmds = json.load(f)
            os.remove(self._cmd_path)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        pal = self._palette
        applied = []
        for key, value in cmds.items():
            if key == "register" and value in REGISTERS:
                self._cycle_register(REGISTERS.index(value))
                applied.append(f"register={value}")
            elif key == "tag":
                self._place_tag(label=str(value))
                applied.append(f"tag=\"{value}\"")
            elif key == "clear_tags":
                self._clear_tags()
                applied.append("clear_tags")
            elif key == "dump":
                self._dump_debug_state()
                applied.append("dump")
            elif key == "daylight":
                self._toggle_daylight()
                applied.append(f"daylight→{self._light_state}")
            elif key == "train":
                self._toggle_tension()
                applied.append(f"train={'off' if self._tension.active else 'on'}")
            elif key == "tex_size":
                self._tex_size_override = int(value)
                applied.append(f"tex_size={value}")
            elif key == "rebuild":
                # Flush all chunks — regenerate with current settings
                for k, np in list(self._chunks.items()):
                    np.removeNode()
                self._chunks.clear()
                self._pending_chunks.clear()
                with self._chunk_lock:
                    self._ready_chunks.clear()
                self._update_chunks()
                applied.append("rebuild")
            elif key in pal:
                if isinstance(value, list):
                    pal[key] = tuple(value)
                else:
                    pal[key] = value
                applied.append(f"{key}={value}")
        if applied:
            console.log(f"[bold cyan]DEBUG CMD[/bold cyan]  {', '.join(applied)}")

    def _update_debug_hud(self):
        if not self._debug_hud_text:
            return
        p = self._probe_data
        cam = self.cam.getPos()
        chunk = self._chunk_key(cam.getX(), cam.getY())
        # Rolling frame average
        ft = self._frame_times
        avg_ms = sum(ft) / len(ft) if ft else 0
        lines = [
            f"pos=({cam.getX():.1f}, {cam.getY():.1f}, {cam.getZ():.1f}) "
            f"h={self._cam_h:.0f} p={self._cam_p:.0f}",
            f"chunk=({chunk[0]}, {chunk[1]})  loaded={len(self._chunks)}",
            f"frame: {avg_ms:.1f}ms avg60  drip={self._drip_this_frame}/f  queue={len(self._object_spawn_queue)}",
            f"probe: {p.get('surface', '?')}  d={p.get('distance', '?')}",
            f"reg={REGISTERS[self._register_index]}  tags={len(self._debug_tags)}  tex={self._tex_size_override}",
            f"ambient: {self._ambient.active_count}/{self._ambient.total_count} awake  hibernate={self._ambient.hibernated_count}",
            f"TRAIN: {'ON' if self._tension.active else 'off'}  state={self._tension.state}  budget={self._tension.budget:.0%}",
            f"biome={self._biome}  light={self._light_state}  budget_max={self._tension._config.get('budget_max', '?')}",
            f"chrono: {self._chrono_state['day_phase']}  night={self._chrono_state['night_weight']:.2f}  moon={self._chrono_state['moon_approx']:.2f}",
        ]
        # Per-kind census — top 5 by active count
        census = self._ambient.kind_census()
        top5 = sorted(census.items(), key=lambda kv: kv[1][0], reverse=True)[:5]
        kind_str = "  ".join(f"{k}:{a}/{t}" for k, (a, t, _h) in top5)
        lines.append(f"kinds: {kind_str}")
        self._debug_hud_text.setText("\n".join(lines))

    # -- Main loop -------------------------------------------------------------

    def _loop(self, task):
        dt = globalClock.getDt()
        self._frame_times.append(dt * 1000)

        # Mouse look
        if not hasattr(self, '_win_cx'):
            self._center_mouse()
        dx, dy = self._read_mouse()
        if not self._mouse_initialized:
            self._mouse_initialized = True
            dx, dy = 0, 0

        self._cam_h -= dx * MOUSE_SENS
        self._cam_p = max(-PITCH_LIMIT, min(PITCH_LIMIT, self._cam_p - dy * MOUSE_SENS))

        # WASD
        heading_rad = math.radians(self._cam_h)
        forward_x = -math.sin(heading_rad)
        forward_y = math.cos(heading_rad)
        right_x = math.cos(heading_rad)
        right_y = math.sin(heading_rad)

        move_x, move_y = 0.0, 0.0
        if self._keys["w"]:
            move_x += forward_x; move_y += forward_y
        if self._keys["s"]:
            move_x -= forward_x; move_y -= forward_y
        if self._keys["a"]:
            move_x -= right_x; move_y -= right_y
        if self._keys["d"]:
            move_x += right_x; move_y += right_y

        mag = math.sqrt(move_x * move_x + move_y * move_y)
        if mag > 0:
            move_x = move_x / mag * MOVE_SPEED * dt
            move_y = move_y / mag * MOVE_SPEED * dt

        pos = self.cam.getPos()
        new_x = pos.getX() + move_x
        new_y = pos.getY() + move_y

        # Collision — slide along hard object surfaces
        new_x, new_y = self._ambient.collide_point(new_x, new_y)
        moving = mag > 0

        # Decay ground blend offset — prevents camera pop on G toggle
        if abs(self._ground_blend_z) > 0.001:
            self._ground_blend_z *= 0.88  # ~8 frames to settle
        else:
            self._ground_blend_z = 0.0

        if self._use_fake_ground:
            # WorldRunner mode — flat plane, camera bob sells height
            bob = self._fake_ground.update(new_x, new_y, dt, moving)
            self.cam.setPos(new_x, new_y, EYE_Z + bob + self._ground_blend_z)
        else:
            # Real ground — Perlin height query
            terrain_z = self._height_at(new_x, new_y)
            self.cam.setPos(new_x, new_y, terrain_z + EYE_Z + self._ground_blend_z)
            # Still update fake ground position (for seamless toggle)
            self._fake_ground.update(new_x, new_y)

        self.cam.setHpr(self._cam_h, self._cam_p, 0)

        # 60-frame cycle — spread all subsystems across the cycle
        if not hasattr(self, '_frame_counter'):
            self._frame_counter = 0
        self._frame_counter = (self._frame_counter + 1) % 60

        fc = self._frame_counter

        # Chunk system — skip entirely when fake ground is active
        if not self._use_fake_ground:
            # Chunk scan + dispatch: frames 0, 15, 30, 45 (4× per cycle)
            if fc % 15 == 0:
                self._dispatch_chunks()

            # Chunk build: frames 5, 10, 20, 25, 35, 40, 50, 55 (8× per cycle)
            if fc % 5 == 0 and fc % 15 != 0:
                self._build_ready_chunk()

            # Despawn check: frame 47 only (1× per cycle)
            if fc == 47:
                self._despawn_distant()

        # Ambient life: frames 3, 15, 27, 39, 51 (5× per cycle, every 12th frame)
        # Was every 6th (8×). Rats at 5fps indistinguishable from 10fps.
        if fc % 12 == 3:
            self._ambient._cam_heading = self._cam_h
            self._ambient.tick(dt * 12, self.cam.getPos())

        # Object tile scan: frame 29 — queue new tiles; frame 53 — despawn far tiles
        if fc == 29:
            self._place_object_tiles()
        if fc == 53:
            self._despawn_distant_tiles()

        # Drip-spawn queued objects: every frame (8 per frame, ~1ms budget)
        self._drip_spawn_objects()

        # Drip-spawn deferred chunk entities: 4 per frame, O(1) popleft
        h_fn = self._flat_height if self._use_fake_ground else self._height_at
        for _ in range(min(4, len(self._deferred_entity_spawns))):
            kind, pos, heading, seed, chunk_key = self._deferred_entity_spawns.popleft()
            self._ambient.spawn(kind, pos=pos, heading=heading, seed=seed,
                                height_fn=h_fn, chunk_key=chunk_key,
                                biome=self._biome_key)

        # Manual GC: gen-0 only during gameplay — lightweight, ~0.1ms
        # Gen-1/2 were causing 50-75ms spikes with 3000+ entity node trees
        if fc == 37:
            gc.collect(0)

        # Chronometer: frame 59 (1× per cycle, ~1 read per second)
        if fc == 59:
            self._chrono_state = self._chrono.read()

        # Tension Cycle — drives fog/ambient when active, chrono drives when not
        # budget_max lives in cycle config (CAVERN_CYCLE/OUTDOOR_CYCLE)
        env = self._tension.tick(dt, self._ambient.active_count)
        nw = self._chrono_state.get("night_weight", 0)
        if self._biome == "outdoor":
            # Outdoor: L-key state is the base, tension compresses FROM that base
            ls = self._light_states[self._light_state]
            base_near, base_far = ls["fog_near"], ls["fog_far"]
            base_amb = ls["ambient"]
            base_fog_c = ls["fog_color"]
            # Chrono shifts fog color: night → deeper blue, dusk → warmer
            # night_color target is always cooler/darker than base
            night_fog = (base_fog_c[0] * 0.4, base_fog_c[1] * 0.5, base_fog_c[2] * 0.8)
            fog_c = tuple(base_fog_c[i] + (night_fog[i] - base_fog_c[i]) * nw for i in range(3))
            self._fog.setColor(Vec4(*fog_c, 1))
            if self._tension.active:
                # Tension lerps between current light-state base and tension target
                t = env.budget  # 0.0 = no pressure, 1.0 = max pressure
                t_fog = env.fog
                fog_near = base_near + (t_fog[0] - base_near) * t
                fog_far = base_far + (t_fog[1] - base_far) * t
                t_amb = env.ambient
                amb = tuple(base_amb[i] + (t_amb[i] - base_amb[i]) * t for i in range(3))
                self._fog.setLinearRange(fog_near, fog_far)
                self._amb_np.node().setColor(Vec4(*amb, 1))
                if env.should_dump:
                    self._ambient.hibernate_distant(self.cam.getPos(), keep_radius=1)
                    self._object_spawn_queue.clear()
            else:
                # Chrono modulates the current light state
                amb_scale = 1.0 - nw * 0.4
                fog_near = base_near - nw * 3.0
                fog_far = base_far - nw * 10.0
                self._fog.setLinearRange(fog_near, fog_far)
                self._amb_np.node().setColor(Vec4(
                    base_amb[0] * amb_scale, base_amb[1] * amb_scale,
                    base_amb[2] * amb_scale, 1))
        else:
            # Cavern: tension overrides directly, chrono fallback uses cave values
            if self._tension.active:
                self._fog.setLinearRange(*env.fog)
                self._amb_np.node().setColor(Vec4(*env.ambient, 1))
                if env.should_dump:
                    self._ambient.hibernate_distant(self.cam.getPos(), keep_radius=1)
                    self._object_spawn_queue.clear()
            else:
                fog_near = 8.0 - nw * 2.0
                fog_far = 28.0 - nw * 5.0
                self._fog.setLinearRange(fog_near, fog_far)
                amb_scale = 1.0 - nw * 0.3
                self._amb_np.node().setColor(Vec4(
                    0.38 * amb_scale, 0.34 * amb_scale, 0.32 * amb_scale, 1))

        # Sky bodies — sun/moon position update (outdoor only)
        if self._biome == "outdoor":
            self._update_sky_bodies(dt)

        # Torch disabled — skip flicker and positioning
        cam_pos = self.cam.getPos()
        h_fn = self._flat_height if self._use_fake_ground else self._height_at

        # Debug
        self._check_debug_commands()
        if self._debug_mode:
            self._probe_data = self._calc_probe()
            self._update_debug_hud()

        return task.cont


if __name__ == "__main__":
    Cavern().run()
