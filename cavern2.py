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

from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from direct.interval.LerpInterval import LerpColorScaleInterval
from direct.interval.IntervalGlobal import Sequence, Func
from core.systems.config_engine import ConfigEngine
from core.systems.repl import EngineREPL
from panda3d.core import (
    Vec3, Vec4, TextNode, AntialiasAttrib,
    Fog, SamplerState, TransparencyAttrib,
    WindowProperties, NodePath,
    PNMImage, Texture, CardMaker,
    AmbientLight, PointLight, Spotlight,
)
from rich.console import Console

from core.systems.placement_engine import PlacementEngine
from core.systems.entropy_engine import EntropyEngine
from panda3d.core import (
    Geom, GeomNode, GeomTriangles, GeomVertexData,
    GeomVertexFormat, GeomVertexWriter, PerlinNoise2,
    LightRampAttrib,
)
from core.systems.geometry import make_box, make_pebble_cluster
from core.systems.shadowbox_scene import SHADOWBOX_REGISTERS, resolve_palette
from core.systems.ambient_life import AmbientManager
from core.systems.chronometer import Chronometer
from core.systems.membrane import Membrane

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
    ("boulder",           0.55,    4.0,       4),
    ("stalagmite",        0.80,    3.0,       3),
    ("giant_fungus",      0.20,    2.5,       3),
    ("crystal_cluster",   0.15,    2.0,       3),
    ("dead_log",          0.25,    2.0,       3),
    ("bone_pile",         0.10,    0,         3),
    ("moss_patch",        0.40,    0,         2),
    ("ceiling_moss",      0.50,    0,         5),
    ("hanging_vine",      0.20,    0,         5),
    ("grass_tuft",        1.50,    0,         1),
    ("rubble",            1.20,    0,         1),
    ("leaf_pile",         0.80,    0,         1),
    ("twig_scatter",      0.80,    0,         1),
    ("rat",               0.45,    0,         2),
    ("beetle",            0.25,    0,         2),
    ("leaf",              0.30,    0,         1),
    ("spider",            0.08,    0,         2),
]

# Ghost audio seeds — config structure for OSC→Max for Live bridge.
# Each kind maps to an audio profile. Not wired yet — structure only.
# channel: OSC channel/instrument routing
# note_base: MIDI root note (entity pitch center)
# velocity_curve: how approach speed maps to dynamics ("linear", "log", "step")
# band_response: what happens at each LOD band transition
#   1 (far):  ambient layer — reverb-heavy, low velocity, pad/drone
#   2 (mid):  presence layer — moderate dynamics, texture emerges
#   3 (near): detail layer — full velocity, dry signal, percussive elements
# contact: trigger type on collision ("percussive", "sustained", "none")
# decay: note-off behavior ("natural", "gated", "frozen")
AUDIO_GHOST_SEEDS = {
    # -- Architecture (low freq, long sustain, deep reverb) --
    "mega_column":      {"channel": 1,  "note_base": 24, "velocity_curve": "log",
                         "band_response": {1: "drone_low", 2: "resonance", 3: "presence"},
                         "contact": "sustained", "decay": "frozen"},
    "column":           {"channel": 1,  "note_base": 36, "velocity_curve": "log",
                         "band_response": {1: "drone_low", 2: "resonance", 3: "presence"},
                         "contact": "sustained", "decay": "frozen"},
    "boulder":          {"channel": 2,  "note_base": 30, "velocity_curve": "linear",
                         "band_response": {1: "rumble", 2: "mass", 3: "impact_ready"},
                         "contact": "percussive", "decay": "natural"},
    "stalagmite":       {"channel": 2,  "note_base": 48, "velocity_curve": "linear",
                         "band_response": {1: "silence", 2: "tone", 3: "ring"},
                         "contact": "percussive", "decay": "natural"},
    # -- Bioluminescent (mid freq, swells, filter sweeps) --
    "giant_fungus":     {"channel": 3,  "note_base": 55, "velocity_curve": "log",
                         "band_response": {1: "spore_wash", 2: "pulse", 3: "bloom"},
                         "contact": "sustained", "decay": "natural"},
    "crystal_cluster":  {"channel": 3,  "note_base": 72, "velocity_curve": "step",
                         "band_response": {1: "shimmer", 2: "chime", 3: "harmonic"},
                         "contact": "percussive", "decay": "frozen"},
    "moss_patch":       {"channel": 4,  "note_base": 60, "velocity_curve": "log",
                         "band_response": {1: "silence", 2: "breath", 3: "texture"},
                         "contact": "none", "decay": "natural"},
    "ceiling_moss":     {"channel": 4,  "note_base": 65, "velocity_curve": "log",
                         "band_response": {1: "silence", 2: "drip_hint", 3: "drip"},
                         "contact": "none", "decay": "natural"},
    "hanging_vine":     {"channel": 4,  "note_base": 58, "velocity_curve": "linear",
                         "band_response": {1: "silence", 2: "creak", 3: "sway"},
                         "contact": "sustained", "decay": "gated"},
    # -- Organic debris (high freq, transients, texture) --
    "dead_log":         {"channel": 5,  "note_base": 40, "velocity_curve": "linear",
                         "band_response": {1: "silence", 2: "creak", 3: "wood_tone"},
                         "contact": "percussive", "decay": "natural"},
    "bone_pile":        {"channel": 5,  "note_base": 68, "velocity_curve": "step",
                         "band_response": {1: "silence", 2: "rattle_hint", 3: "rattle"},
                         "contact": "percussive", "decay": "gated"},
    "grass_tuft":       {"channel": 6,  "note_base": 76, "velocity_curve": "linear",
                         "band_response": {1: "silence", 2: "silence", 3: "rustle"},
                         "contact": "none", "decay": "gated"},
    "rubble":           {"channel": 6,  "note_base": 44, "velocity_curve": "linear",
                         "band_response": {1: "silence", 2: "scrape_hint", 3: "scrape"},
                         "contact": "percussive", "decay": "natural"},
    "leaf_pile":        {"channel": 6,  "note_base": 80, "velocity_curve": "linear",
                         "band_response": {1: "silence", 2: "silence", 3: "crinkle"},
                         "contact": "none", "decay": "gated"},
    "twig_scatter":     {"channel": 6,  "note_base": 84, "velocity_curve": "step",
                         "band_response": {1: "silence", 2: "silence", 3: "snap"},
                         "contact": "percussive", "decay": "gated"},
    # -- Fauna (dynamic, velocity-sensitive, movement-triggered) --
    "rat":              {"channel": 7,  "note_base": 88, "velocity_curve": "linear",
                         "band_response": {1: "silence", 2: "scurry_distant", 3: "scurry"},
                         "contact": "none", "decay": "gated"},
    "beetle":           {"channel": 7,  "note_base": 92, "velocity_curve": "linear",
                         "band_response": {1: "silence", 2: "silence", 3: "click"},
                         "contact": "none", "decay": "gated"},
    "spider":           {"channel": 7,  "note_base": 96, "velocity_curve": "log",
                         "band_response": {1: "silence", 2: "silence", 3: "creep"},
                         "contact": "none", "decay": "gated"},
    # -- Atmospheric (drift, no contact, pure proximity) --
    "leaf":             {"channel": 8,  "note_base": 70, "velocity_curve": "log",
                         "band_response": {1: "silence", 2: "flutter_hint", 3: "flutter"},
                         "contact": "none", "decay": "natural"},
}


class Cavern(ShowBase):

    def __init__(self):
        super().__init__()

        props = WindowProperties()
        props.setTitle("Sanctum — The Endless Floor")
        props.setSize(960, 540)
        props.setCursorHidden(True)
        props.setFullscreen(True)
        self.win.requestProperties(props)
        self._fullscreen = True

        # -- GC control: manual collection on quiet frames, no random pauses --
        gc.disable()

        # -- Frame rate: disable vsync, cap at 60fps ourselves -----------------
        from panda3d.core import loadPrcFileData, ClockObject
        loadPrcFileData("", "sync-video false")
        globalClock.setMode(ClockObject.MLimited)
        globalClock.setFrameRate(60)

        # -- Config engine (every constant lives in sanctum.toml) ---------------
        self._cfg = ConfigEngine("config/sanctum.toml")

        # -- Rendering setup ---------------------------------------------------
        bg = self._cfg.camera.background
        self.setBackgroundColor(bg[0], bg[1], bg[2], 1)
        self.disableMouse()
        self.camLens.setFov(65.0)
        self.camLens.setNear(0.5)
        self.camLens.setFar(70.0)  # wider than fog — lets you tune fog_far without clipping
        self.render.setAntialias(AntialiasAttrib.MMultisample)
        # Per-pixel lighting with light count limit — cap GPU work
        self.render.setShaderAuto()
        self.render.setAttrib(
            LightRampAttrib.makeDefault())  # default ramp, no HDR overhead

        # -- State -------------------------------------------------------------
        self._register_index = 0
        self._palette = resolve_palette("survival")
        self._keys = {"w": False, "s": False, "a": False, "d": False}
        self._cam_h = 0.0
        self._cam_p = 0.0
        self._chunks = {}           # (cx, cz) -> NodePath
        self._pending_chunks = {}   # (cx, cz) -> texture data being generated in background
        self._ready_chunks = {}     # (cx, cz) -> (tex_data, chunk_seed) ready to build
        self._chunk_cache = {}      # (cx, cz) -> data dict (LRU: despawned chunks kept for fast revisit)
        self._chunk_cache_max = 80  # keep ~80 despawned chunks in memory (~5MB)
        self._chunk_lock = threading.Lock()
        self._chunk_seed = 42
        self._tex_size_override = TEX_SIZE
        self._placer = PlacementEngine(seed=self._chunk_seed)
        self._entropy = EntropyEngine()
        self._membrane = Membrane(self.render)
        self._ambient = AmbientManager(self.render, wake_radius=44.0, sleep_radius=55.0,
                                        membrane=self._membrane)
        self._deferred_spawns = []  # ambient spawns queued across frames
        self._chrono = Chronometer()
        self._chrono_state = self._chrono.read()

        # Native C++ Perlin for texture generation (fast path)
        # Python PlacementEngine Perlin stays for placement/height (still useful)
        self._noise = {}  # keyed by scale for reuse
        for scale_name, sx, sy, seed_offset in [
            ("jitter_x", 1.7, 1.7, 0), ("jitter_y", 1.7, 1.7, 100),
            ("gate", 0.9, 0.9, 500), ("color", 0.4, 0.4, 0),
            ("warm", 0.7, 0.7, 50), ("dirt1", 0.8, 0.8, 0),
            ("dirt2", 2.5, 2.5, 300), ("grit", 1.8, 1.8, 700),
            ("stone", 5.0, 5.0, 0),
            # Normal perturbation — breaks up spotlight reflection on ground
            ("norm_x", 2.2, 2.2, 900), ("norm_y", 2.2, 2.2, 950),
        ]:
            n = PerlinNoise2(sx, sy, 256, self._chunk_seed + seed_offset)
            self._noise[scale_name] = n

        # -- Debug telemetry ---------------------------------------------------
        self._debug_mode = False
        self._probe_data = {}
        self._debug_hud_text = None
        self._debug_tags = []
        self._tag_counter = 0
        self._cmd_path = os.path.join(os.path.dirname(__file__) or ".", "debug_cmd.json")
        self._state_path = os.path.join(os.path.dirname(__file__) or ".", "debug_state.json")

        # -- Tuning potentiometers (number row selects, +/- adjusts) -----------
        self._tuner_channel = 0  # 0 = none selected
        self._tuner_hud = None
        self._tuners = {
            1: {"name": "fog_near",     "val": 25.0,  "min": 0.0,   "max": 60.0, "step": 1.0},
            2: {"name": "fog_far",      "val": 55.0,  "min": 20.0,  "max": 120.0,"step": 2.0},
            3: {"name": "ambient_r",    "val": 0.35,  "min": -0.5,  "max": 1.0,  "step": 0.02},
            4: {"name": "ambient_g",    "val": 0.30,  "min": -0.5,  "max": 1.0,  "step": 0.02},
            5: {"name": "ambient_b",    "val": 0.25,  "min": -0.5,  "max": 1.0,  "step": 0.02},
            6: {"name": "grain_alpha",  "val": 0.18,  "min": -0.3,  "max": 0.5,  "step": 0.02},
            7: {"name": "spot_power",   "val": 4.0,   "min": -2.0,  "max": 10.0, "step": 0.5},
            8: {"name": "decal_scale",  "val": 1.0,   "min": -1.0,  "max": 3.0,  "step": 0.1},
            9: {"name": "fade_entity",  "val": 2.0,   "min": 0.0,   "max": 8.0,  "step": 0.2},
        }

        # Snapshot defaults for reset
        self._tuner_defaults = {k: t["val"] for k, t in self._tuners.items()}

        # -- Lighting ----------------------------------------------------------
        self._build_lighting()

        # -- Fog (linear to black — clean near field, fade to void at distance) -
        self._fog = Fog("cavern_fog")
        self._fog.setColor(Vec4(0, 0, 0, 1))  # fade to darkness, not a color
        self._fog.setLinearRange(self._tuners[1]["val"], self._tuners[2]["val"])
        self.render.setFog(self._fog)

        # -- Camera start ------------------------------------------------------
        self.cam.setPos(0, 0, EYE_Z)
        self._mouse_initialized = False

        # -- Stage the immediate area before player sees anything --
        self._stage_initial_chunks()

        # -- Post-processing: grain + bloom + reduced render resolution ----------
        self._bloom_on = False
        try:
            from direct.filter.CommonFilters import CommonFilters
            self._filters = CommonFilters(self.win, self.cam)
            bloom_int = self._palette.get("bloom_intensity", 0.3)
            self._filters.setBloom(
                blend=(0.3, 0.4, 0.3, 0.0),
                mintrigger=0.6, maxtrigger=1.0,
                desat=0.6, intensity=bloom_int, size="medium",
            )
            self._bloom_on = True
        except Exception:
            self._filters = None

        # Film grain overlay — masks frame hitches + adds atmosphere
        self._setup_grain_shader()

        # -- Controls ----------------------------------------------------------
        self.accept("escape", sys.exit)
        for key in self._keys:
            self.accept(key, self._set_key, [key, True])
            self.accept(f"{key}-up", self._set_key, [key, False])
        # Registers: [ cycles backward, ] cycles forward (replaces fullscreen on ])
        self.accept("[", self._prev_register)
        self.accept("]", self._next_register)
        self.accept("`", self._toggle_debug)
        self.accept("0", self._dump_debug_state)
        self.accept("t", self._place_tag)
        self.accept("shift-t", self._undo_last_tag)
        self.accept("control-t", self._clear_tags)
        self.accept("l", self._toggle_daylight)
        self.accept("shift-]", self._toggle_fullscreen)
        # Tuning: number row selects channel, +/- adjusts
        for i in range(1, 10):
            self.accept(str(i), self._select_tuner, [i])
        self.accept("=", self._adjust_tuner, [1, False])      # coarse +
        self.accept("shift-=", self._adjust_tuner, [1, True])  # fine +
        self.accept("-", self._adjust_tuner, [-1, False])       # coarse -
        self.accept("shift--", self._adjust_tuner, [-1, True])  # fine -
        self.accept("shift-0", self._reset_tuners)  # Shift+0 = reset all to defaults
        self._daylight = False

        # -- REPL (~ to toggle, type Python live) --------------------------------
        self._repl = EngineREPL(self, self._cfg, namespace={
            "fog_obj": self._fog,
            "amb": self._amb_np,
            "spot": self._orb_np,
            "membrane": self._membrane,
            "ambient": self._ambient,
        })
        # Wire config changes to live engine updates
        self._cfg.root.watch("fog", self._on_cfg_fog)
        self._cfg.root.watch("lighting.ambient", self._on_cfg_ambient)

        # -- Layer diagnostic mode ------------------------------------------------
        # Press . to add layers one at a time. Identify which layer causes issues.
        self._diag_layer = 0
        self._diag_labels = [
            "GROUND",       # 1: mesh + texture only
            "FOG",          # 2: fog
            "LIGHTING",     # 3: ambient + torch + fill (all lights at once)
            "ENTITIES",     # 4: ambient life + glow cards (glow is per-entity now)
            "TORCH_DECAL",  # 5: player's warm ground pool
            "GRAIN",        # 6: film grain overlay
            "BLOOM",        # 7: post-process
            "LIVE",         # 8: WASD + full scene
        ]
        # Start with everything hidden
        self._diag_ground_vis = False
        # Hide ground chunks
        for key, np in self._chunks.items():
            np.hide()
        # Disable fog
        self.render.clearFog()
        # Disable all lights
        self.render.clearLight(self._amb_np)
        self.render.clearLight(self._orb_np)
        self.render.clearLight(self._orb_fill)
        # Hide grain
        if self._grain_card:
            self._grain_card.hide()
        # Disable bloom
        if self._bloom_on and self._filters:
            self._filters.delBloom()
            self._bloom_on = False
        # Suppress ambient ticking until entities layer
        self._diag_suppress_ambient = True
        # Suppress membrane updates until membrane layer
        self._diag_suppress_membrane = True
        # (motes are now children of entity nodes — no separate suppression needed)
        # HUD
        self._diag_hud = OnscreenText(
            text="LAYER DIAGNOSTIC\nPress [.] to add next layer\n\n[waiting]",
            pos=(0.0, 0.0), scale=0.06,
            fg=(1.0, 0.9, 0.3, 0.9), align=TextNode.ACenter,
            mayChange=True, shadow=(0, 0, 0, 0.8),
        )
        self.accept(".", self._diag_next_layer)

        self.taskMgr.add(self._loop, "CavernLoop")

        console.log("[bold cyan]THE ENDLESS FLOOR — LAYER DIAGNOSTIC[/bold cyan]")
        console.log("[bold yellow]Press [.] to add each layer[/bold yellow]")
        console.log("[dim]ESC to quit at any point[/dim]")

    # -- Layer diagnostic -------------------------------------------------------

    def _diag_next_layer(self):
        """Press . — enable the next rendering layer."""
        self._diag_layer += 1
        layer = self._diag_layer
        name = self._diag_labels[min(layer - 1, len(self._diag_labels) - 1)]

        if layer == 1:  # GROUND
            for key, np in self._chunks.items():
                np.show()
            self._diag_ground_vis = True

        elif layer == 2:  # FOG
            self.render.setFog(self._fog)

        elif layer == 3:  # LIGHTING (all lights together — ambient + torch + fill)
            self.render.setLight(self._amb_np)
            self.render.setLight(self._orb_np)
            self.render.setLight(self._orb_fill)

        elif layer == 4:  # ENTITIES (glow cards are children, come with them)
            self._diag_suppress_ambient = False

        elif layer == 5:  # TORCH DECAL (player's warm ground pool only)
            self._diag_suppress_membrane = False

        elif layer == 6:  # GRAIN
            if self._grain_card:
                self._grain_card.show()

        elif layer == 7:  # BLOOM
            if self._filters:
                bloom_int = self._palette.get("bloom_intensity", 0.3)
                self._filters.setBloom(
                    blend=(0.3, 0.4, 0.3, 0.0),
                    mintrigger=0.6, maxtrigger=1.0,
                    desat=0.6, intensity=bloom_int, size="medium",
                )
                self._bloom_on = True

        elif layer >= 8:  # LIVE
            self._diag_hud.hide()
            console.log("[bold green]ALL LAYERS ACTIVE — WASD enabled[/bold green]")

        # Update HUD
        if layer < 8:
            active = self._diag_labels[:layer]
            pending = self._diag_labels[layer:]
            lines = ["LAYER DIAGNOSTIC — Press [.] for next\n"]
            for l in active:
                lines.append(f"  [ON]  {l}")
            if pending:
                lines.append(f"\n  next: {pending[0]}")
            self._diag_hud.setText("\n".join(lines))

        console.log(f"[bold yellow]LAYER {layer}: {name}[/bold yellow]")

    # -- Config watchers (REPL changes → live engine) -------------------------

    def _on_cfg_fog(self, path, value):
        """Config change in fog.* → update live fog."""
        try:
            f = self._cfg.fog
            self._fog.setColor(Vec4(f.color[0], f.color[1], f.color[2], 1))
            self._fog.setLinearRange(f.near, f.far)
        except Exception:
            pass

    def _on_cfg_ambient(self, path, value):
        """Config change in lighting.ambient.* → update live ambient."""
        try:
            a = self._cfg.lighting.ambient
            self._amb_np.node().setColor(Vec4(a.color[0], a.color[1], a.color[2], 1))
        except Exception:
            pass

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
        amb = AmbientLight("amb")
        amb.setColor(Vec4(self._tuners[3]["val"], self._tuners[4]["val"], self._tuners[5]["val"], 1))
        self._amb_np = self.render.attachNewNode(amb)
        self.render.setLight(self._amb_np)

        # Light orb — spotlight cone from behind, casting forward like a flashlight
        lc = pal["sconce"]

        # Main cone: spotlight aimed forward — THE player's light, dominant over ambient
        spot = Spotlight("orb_cone")
        spot.setColor(Vec4(lc[0] * 4.0, lc[1] * 3.5, lc[2] * 2.5, 1))  # cranked warm cone
        spot.getLens().setFov(55)  # slightly tighter = more focused beam
        spot.getLens().setNearFar(0.5, 40)
        spot.setAttenuation((0.15, 0.005, 0.001))  # reaches further, falls off slower
        spot.setShadowCaster(True, 512, 512)
        spot.setExponent(12.0)  # tighter hotspot center
        self._orb_np = self.cam.attachNewNode(spot)
        self._orb_np.setPos(0.3, -0.8, 0.6)  # behind right shoulder
        self._orb_np.lookAt(self.cam, Vec3(0, 8, -1))  # aim forward and slightly down
        self.render.setLight(self._orb_np)

        # Fill light: warm halo around the player — you carry warmth into the dark
        fill = PointLight("orb_fill")
        fill.setColor(Vec4(lc[0] * 1.2, lc[1] * 0.9, lc[2] * 0.5, 1))
        fill.setAttenuation((0.3, 0.015, 0.004))
        self._orb_fill = self._orb_np.attachNewNode(fill)
        self.render.setLight(self._orb_fill)

        # Tiny glow marker visible in peripheral vision
        orb_vis = make_box(0.025, 0.025, 0.025, (0.95, 0.8, 0.45))
        self._orb_vis = self._orb_np.attachNewNode(orb_vis)
        self._orb_vis.setLightOff()
        self._orb_vis.setColorScale(4.0, 3.0, 1.8, 1.0)  # bright peripheral torch glow

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
    // Screen-space noise — two octaves for texture
    float n1 = hash(uv * 900.0 + osg_FrameTime * 7.3);
    float n2 = hash(uv * 400.0 + osg_FrameTime * 3.1);

    // Distance from center — drives vignette + fog density feel
    vec2 vc = uv - 0.5;
    float dist = length(vc);
    float vign = 1.0 - dist * dist * 0.8;

    // Fog dither: stronger noise at edges (simulates uneven atmospheric density)
    // Adds particulate breakup to the smooth fog gradient
    float fog_noise = (n1 * 0.7 + n2 * 0.3) * 0.18 - 0.09;
    float edge_boost = smoothstep(0.15, 0.5, dist) * 1.5;  // more noise at fog boundary
    fog_noise *= (1.0 + edge_boost);

    // Film grain — visible everywhere, stronger in dark areas (cave dust)
    float grain = fog_noise * vign;

    // Warm-shift the grain slightly (dust is warm, not neutral gray)
    gl_FragColor = vec4(grain * 1.05, grain, grain * 0.9, 0.18);
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
        # Place ALL initial tiles synchronously (runtime uses 1-per-call drip)
        for _ in range(9):
            self._place_object_tiles()
        # Stage ALL initial objects synchronously — world populated before first frame
        console.log("[dim]Staging objects...[/dim]")
        while self._object_spawn_queue:
            kind, wx, wy, heading, seed, tile_key = \
                self._object_spawn_queue.popleft()
            wz = self._height_at(wx, wy)
            if kind == "leaf":
                wz += 3.0
            self._ambient.spawn(kind, pos=(wx, wy, wz),
                                heading=heading, seed=seed,
                                height_fn=self._height_at,
                                chunk_key=tile_key)
        console.log(f"[bold green]Objects ready. ({self._ambient.total_count} entities)[/bold green]")

    def _generate_object_template(self, seed, biome=None):
        """Generate a tile layout from a biome density config.

        One loop over the config — tile area × density = count.
        Clearance > 0 enforces spacing. Sorted largest-first by config order.
        Swapping biomes = swapping the density table.
        """
        if biome is None:
            biome = BIOME_CAVERN_DEFAULT
        tile = self._object_tile_size
        tile_area = tile * tile
        rng = __import__("random").Random(seed)
        spawns = []
        solid_positions = []  # (x, y, clearance)

        for kind, density, clearance, margin in biome:
            # density is per 1000 sqm — scale to tile area with ±30% variance
            base_count = density * tile_area / 1000.0
            count = max(0, int(rng.uniform(base_count * 0.7, base_count * 1.3)))

            for _ in range(count):
                # Place with spacing check if clearance > 0
                placed = False
                for _attempt in range(5 if clearance > 0 else 1):
                    x = rng.uniform(margin, tile - margin)
                    y = rng.uniform(margin, tile - margin)
                    if clearance > 0:
                        too_close = False
                        for sx, sy, sc in solid_positions:
                            dx, dy = x - sx, y - sy
                            if dx * dx + dy * dy < (clearance + sc) ** 2:
                                too_close = True
                                break
                        if too_close:
                            continue
                        solid_positions.append((x, y, clearance))
                    placed = True
                    break
                if not placed:
                    x = rng.uniform(margin, tile - margin)
                    y = rng.uniform(margin, tile - margin)

                spawns.append((kind, (x, y),
                               rng.uniform(0, 360), rng.randint(0, 99999)))

        return spawns

    def _place_object_tiles(self):
        """Queue object tiles around the camera. Max 1 NEW tile per call — drip the drip."""
        cam_pos = self.cam.getPos()
        tile = self._object_tile_size
        center_tx = int(math.floor(cam_pos.getX() / tile))
        center_ty = int(math.floor(cam_pos.getY() / tile))

        # Sort by distance — center tile + 1 ring (3×3 at 288m = 864m coverage)
        candidates = []
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                tx, ty = center_tx + dx, center_ty + dy
                if (tx, ty) in self._object_tile_placed:
                    continue
                candidates.append((dx * dx + dy * dy, tx, ty))
        if not candidates:
            return
        candidates.sort()

        # Only place ONE tile per call — spreads the queue across multiple frame cycles
        _dist, tx, ty = candidates[0]
        self._object_tile_placed.add((tx, ty))
        offset_x = tx * tile
        offset_y = ty * tile

        template_idx = (tx * 3 + ty * 5 + tx * ty) % len(self._object_templates)
        template = self._object_templates[template_idx]
        entity_key = ("T", tx, ty)

        for kind, (lx, ly), heading, seed in template:
            wx = offset_x + lx
            wy = offset_y + ly
            self._object_spawn_queue.append(
                (kind, wx, wy, heading,
                 seed + tx * 1000 + ty, entity_key))

    def _despawn_distant_tiles(self):
        """Remove object tiles far from camera. Throttled: max 1 per call."""
        cam_pos = self.cam.getPos()
        tile = self._object_tile_size
        center_tx = int(math.floor(cam_pos.getX() / tile))
        center_ty = int(math.floor(cam_pos.getY() / tile))
        for k in list(self._object_tile_placed):
            if abs(k[0] - center_tx) > 3 or abs(k[1] - center_ty) > 3:
                self._ambient.despawn_chunk(("T", k[0], k[1]))
                self._object_tile_placed.discard(k)
                return  # max 1 tile per call — spread the cost

    def _drip_spawn_objects(self):
        """Spawn queued objects across frames. Adaptive rate — faster when queue is deep."""
        # Base: 8/frame. If queue > 500, ramp up to drain faster (still smooth)
        q = len(self._object_spawn_queue)
        rate = 8 if q < 500 else min(24, 8 + q // 200)
        for _ in range(rate):
            if not self._object_spawn_queue:
                return
            kind, wx, wy, heading, seed, tile_key = \
                self._object_spawn_queue.popleft()
            wz = self._height_at(wx, wy)
            if kind == "leaf":
                wz += 3.0
            self._ambient.spawn(kind, pos=(wx, wy, wz),
                                heading=heading, seed=seed,
                                height_fn=self._height_at,
                                chunk_key=tile_key)

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
            # Fast path: cached chunk data from previous visit — skip thread entirely
            if key in self._chunk_cache:
                with self._chunk_lock:
                    self._ready_chunks[key] = self._chunk_cache.pop(key)
                continue
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

        data = {
            "tex_bytes": tex_bytes, "tex_size": tex_size,
            "verts": verts, "norms": norms, "uvs": uvs,
            "subdivs": subdivs, "seed": chunk_seed,
            "spawns": ambient_spawns,
        }
        with self._chunk_lock:
            self._ready_chunks[key] = data
            # LRU cache — keep data for fast revisit after despawn
            if len(self._chunk_cache) >= self._chunk_cache_max:
                self._chunk_cache.pop(next(iter(self._chunk_cache)))
            self._chunk_cache[key] = data  # shared ref, cheap
            self._pending_chunks.pop(key, None)

    def _build_chunk_OLD(self, cx, cz):
        """REPLACED — kept for reference."""
        chunk_root = self.render.attachNewNode(f"chunk_{cx}_{cz}")
        world_x = cx * CHUNK_SIZE
        world_y = cz * CHUNK_SIZE
        pal = self._palette
        chunk_seed = hash((self._chunk_seed, cx, cz)) & 0xFFFFFFFF

        # -- Procedural ground texture via PNMImage ----------------------------
        tex = self._generate_ground_texture(cx, cz, chunk_seed)

        # -- Ground quad -------------------------------------------------------
        cm = CardMaker(f"ground_{cx}_{cz}")
        cm.setFrame(0, CHUNK_SIZE, 0, CHUNK_SIZE)
        ground = chunk_root.attachNewNode(cm.generate())
        ground.setP(-90)  # lay flat (CardMaker makes vertical cards)
        ground.setPos(world_x, world_y, 0)
        ground.setTexture(tex)
        ground.setTwoSided(True)

        # -- Scatter geometry (rocks, pebbles) ---------------------------------
        rng = __import__("random").Random(chunk_seed)
        placer = PlacementEngine(seed=chunk_seed)
        entropy = self._entropy

        # Cobblestone layer — dense small pebble clusters covering the ground
        cobble_count = max(30, int(60 * pal.get("weathering", 0.5)))
        center_x = world_x + CHUNK_SIZE / 2
        center_y = world_y + CHUNK_SIZE / 2
        cobble_pts = placer.golden_spiral(
            cobble_count, CHUNK_SIZE / 2 * 0.95,
            center_x, center_y,
            phase=chunk_seed * 0.1,
        )

        cobble_colors = [
            (0.22, 0.20, 0.18), (0.25, 0.23, 0.20), (0.19, 0.18, 0.16),
            (0.28, 0.26, 0.22), (0.17, 0.16, 0.14), (0.24, 0.22, 0.19),
        ]

        for ci_cob, (px, py) in enumerate(cobble_pts):
            # Perlin field drives size variation — ridges vs flat
            field = self._placer.perlin(px * 0.12, py * 0.12)
            size_weight = entropy.gaussian(field, mu=0.6, sigma=0.35)
            base = 0.06 + size_weight * 0.18  # 0.06-0.24 range

            clr = rng.choice(cobble_colors)
            wv = rng.uniform(-0.02, 0.02)
            clr = (clr[0] + wv, clr[1] + wv * 0.5, clr[2] - wv * 0.3)

            stone = make_pebble_cluster(
                base * rng.uniform(1.2, 2.0),
                base * rng.uniform(0.3, 0.6),
                base * rng.uniform(1.0, 1.8),
                clr, count=max(5, int(10 * size_weight)),
                seed=chunk_seed + ci_cob,
                scatter=rng.uniform(0.0, 0.08),
            )
            sn = chunk_root.attachNewNode(stone)
            sn.setPos(px, py, base * 0.1)
            sn.setH(rng.uniform(0, 360))

        # Occasional larger rocks — fewer, stand out from cobble
        rock_count = rng.randint(1, 4)
        rock_pts = placer.golden_spiral(
            rock_count * 3, CHUNK_SIZE / 3,
            center_x, center_y, phase=chunk_seed * 7.3,
        )
        for ri, (px, py) in enumerate(rock_pts[:rock_count]):
            field = self._placer.perlin(px * 0.05, py * 0.05)
            if field < 0.5:
                continue
            base = 0.2 + field * 0.3
            clr = rng.choice(cobble_colors)
            rock = make_pebble_cluster(
                base * 1.8, base * 0.8, base * 1.5, clr,
                count=max(10, int(18 * field)),
                seed=chunk_seed + 500 + ri,
                scatter=rng.uniform(0.0, 0.1),
            )
            rn = chunk_root.attachNewNode(rock)
            rn.setPos(px, py, base * 0.25)
            rn.setH(rng.uniform(0, 360))

        # Rats — one per chunk on average, sometimes none, sometimes two
        rat_count = rng.choices([0, 1, 1, 2], weights=[2, 5, 5, 1])[0]
        for ri in range(rat_count):
            rx = world_x + rng.uniform(2, CHUNK_SIZE - 2)
            ry = world_y + rng.uniform(2, CHUNK_SIZE - 2)
            facing = rng.uniform(0, 360)
            rat_root = chunk_root.attachNewNode(f"rat_{cx}_{cz}_{ri}")
            rat_root.setPos(rx, ry, 0)
            rat_root.setH(facing)

            scale = rng.uniform(0.7, 1.2)
            body_len = rng.uniform(0.15, 0.22) * scale
            body_w = body_len * rng.uniform(0.35, 0.5)
            body_h = body_len * rng.uniform(0.25, 0.35)
            fur_shade = rng.uniform(-0.02, 0.02)
            fur = (0.08 + fur_shade, 0.06 + fur_shade, 0.05 + fur_shade)

            # Body
            body = make_box(body_w, body_h, body_len, fur)
            bn = rat_root.attachNewNode(body)
            bn.setPos(0, 0, body_h * 0.5)

            # Head
            head_s = body_h * 0.8
            head = make_box(head_s * 1.1, head_s, head_s * 1.1, fur)
            hn = rat_root.attachNewNode(head)
            hn.setPos(0, body_len * 0.5, body_h * 0.55)

            # Snout
            snout = make_box(head_s * 0.4, head_s * 0.3, head_s * 0.6,
                             (fur[0] + 0.02, fur[1] + 0.02, fur[2] + 0.01))
            snn = rat_root.attachNewNode(snout)
            snn.setPos(0, body_len * 0.5 + head_s * 0.7, body_h * 0.45)

            # Tail
            tail_segs = rng.randint(5, 8)
            seg_len = body_len * 0.12
            for t in range(tail_segs):
                taper = 1.0 - (t / tail_segs) * 0.7
                thick = body_h * 0.12 * taper
                seg = make_box(thick, thick, seg_len, (0.12, 0.09, 0.08))
                tn = rat_root.attachNewNode(seg)
                tn.setPos(0, -body_len * 0.4 - seg_len * t, body_h * 0.3)

        return chunk_root

    def _generate_ground_texture_OLD(self, cx, cz, seed):
        """REPLACED."""
        img = PNMImage(TEX_SIZE, TEX_SIZE)
        pal = self._palette

        base_r, base_g, base_b = pal.get("stage_floor", (0.08, 0.06, 0.05))

        for y in range(TEX_SIZE):
            for x in range(TEX_SIZE):
                # World-space coords — continuous across all chunks, no seams
                wx = (cx * CHUNK_SIZE + x / TEX_SIZE * CHUNK_SIZE) * 0.15
                wy = (cz * CHUNK_SIZE + y / TEX_SIZE * CHUNK_SIZE) * 0.15

                n = self._placer.perlin(wx, wy, octaves=2, persistence=0.5)
                variation = (n - 0.5) * 0.14
                r = max(0, min(1, base_r + variation + 0.02))
                g = max(0, min(1, base_g + variation))
                b = max(0, min(1, base_b + variation - 0.01))

                if n < 0.35:
                    r *= 0.65
                    g *= 0.65
                    b *= 0.65

                img.setXel(x, y, r, g, b)

        tex = Texture(f"ground_{cx}_{cz}")
        tex.load(img)
        tex.setMagfilter(SamplerState.FT_nearest)
        tex.setMinfilter(SamplerState.FT_nearest)
        tex.setWrapU(SamplerState.WM_clamp)
        tex.setWrapV(SamplerState.WM_clamp)
        return tex

    # -- New chunk builder (heightmap + cobblestone + boulders) ----------------

    def _build_chunk(self, cx, cz):
        """Heightmap mesh + cobblestone texture + boulders + rats."""
        chunk_root = self.render.attachNewNode(f"chunk_{cx}_{cz}")
        world_x = cx * CHUNK_SIZE
        world_y = cz * CHUNK_SIZE
        chunk_seed = hash((self._chunk_seed, cx, cz)) & 0xFFFFFFFF
        rng = __import__("random").Random(chunk_seed)

        # -- Subdivided ground mesh following height function --
        # 21×21 = enough normals to scatter the spotlight like rough stone
        subdivs = 21
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
        # Overlap: extend mesh half a step past each edge so adjacent chunks
        # overlap and the seam is hidden under the depth buffer
        overhang = step * 0.5
        # UV inset: don't sample right at the clamp boundary
        uv_margin = 0.5 / getattr(self, '_tex_size_override', TEX_SIZE)
        n_nx = self._noise["norm_x"]
        n_ny = self._noise["norm_y"]
        for gy in range(subdivs + 1):
            for gx in range(subdivs + 1):
                # Geometry extends past chunk boundary by overhang
                wx = world_x - overhang + gx * (CHUNK_SIZE + overhang * 2) / subdivs
                wy = world_y - overhang + gy * (CHUNK_SIZE + overhang * 2) / subdivs
                wz = self._height_at(wx, wy)
                vw.addData3(wx, wy, wz)
                dx_h = self._height_at(wx + 0.5, wy) - self._height_at(wx - 0.5, wy)
                dy_h = self._height_at(wx, wy + 0.5) - self._height_at(wx, wy - 0.5)
                # Perturb normals with Perlin — rough stone scatters light
                # instead of reflecting it uniformly (kills wet-floor look)
                perturb = 0.35  # perturbation strength
                dx_h += n_nx(wx, wy) * perturb
                dy_h += n_ny(wx, wy) * perturb
                nmag = math.sqrt(dx_h * dx_h + dy_h * dy_h + 1.0)
                nw.addData3(-dx_h / nmag, -dy_h / nmag, 1.0 / nmag)
                # UV: inset slightly from 0/1 to avoid clamp-edge artifacts
                u = uv_margin + (gx / subdivs) * (1.0 - 2 * uv_margin)
                v = uv_margin + (gy / subdivs) * (1.0 - 2 * uv_margin)
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
                                chunk_key=chunk_key)

        # Occasional leaf drift from above
        leaf_count = rng.choices([0, 0, 1, 2], weights=[4, 3, 2, 1])[0]
        for li in range(leaf_count):
            lx = world_x + rng.uniform(1, CHUNK_SIZE - 1)
            ly = world_y + rng.uniform(1, CHUNK_SIZE - 1)
            lz = self._height_at(lx, ly) + rng.uniform(2.0, 5.0)
            self._ambient.spawn("leaf", pos=(lx, ly, lz),
                                seed=chunk_seed + 3000 + li,
                                height_fn=self._height_at,
                                chunk_key=chunk_key)

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
        # Kill specular on ground — cave floor is matte, not wet
        from panda3d.core import Material
        mat = Material()
        mat.setSpecular((0, 0, 0, 1))
        mat.setShininess(0)
        ground_np.setMaterial(mat)

        # Fade in ground — C++ interval, prevents hard pop-in
        # Clear transparency after fade so ground returns to opaque pipeline
        chunk_root.setTransparency(TransparencyAttrib.MAlpha)
        chunk_root.setColorScale(1, 1, 1, 0)
        def _finish_fade(np=chunk_root):
            if np and not np.isEmpty():
                np.setTransparency(TransparencyAttrib.MNone)
                np.clearColorScale()
        fade = Sequence(
            LerpColorScaleInterval(chunk_root, 2.5, Vec4(1, 1, 1, 1), Vec4(1, 1, 1, 0)),
            Func(_finish_fade),
        )
        fade.start()

        # Ambient spawns — inside time budget with the mesh
        chunk_key = (cx, cz)
        for kind, pos, heading, seed in data["spawns"]:
            self._ambient.spawn(kind, pos=pos, heading=heading, seed=seed,
                                height_fn=self._height_at, chunk_key=chunk_key)

        return chunk_root

    def _bytes_to_texture(self, flat_bytes, tex_size, name):
        """Bulk texture load — single C++ copy, no pixel loop."""
        tex = Texture(name)
        tex.setup2dTexture(tex_size, tex_size, Texture.T_unsigned_byte, Texture.F_rgb8)
        tex.setRamImage(bytes(flat_bytes))
        tex.setMagfilter(SamplerState.FT_linear)   # smooth at close range
        tex.setMinfilter(SamplerState.FT_linear)    # smooth at distance — hides chunk seams
        tex.setWrapU(SamplerState.WM_clamp)
        tex.setWrapV(SamplerState.WM_clamp)
        return tex

    def _compute_cobblestone_pixels(self, cx, cz):
        """Dirt-dominant ground — native C++ Perlin, returns flat bytearray."""
        tex_size = getattr(self, '_tex_size_override', TEX_SIZE)
        pal = self._palette
        noise = self._noise

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

    def _next_register(self):
        self._cycle_register((self._register_index + 1) % len(REGISTERS))

    def _prev_register(self):
        self._cycle_register((self._register_index - 1) % len(REGISTERS))

    def _cycle_register(self, index):
        self._register_index = index % len(REGISTERS)
        reg = REGISTERS[self._register_index]
        self._palette = resolve_palette(reg)

        # Update lighting
        lc = self._palette["sconce"]
        self._orb_np.node().setColor(Vec4(lc[0] * 4.0, lc[1] * 3.5, lc[2] * 2.5, 1))
        fc = self._palette["fog"]
        self._fog.setColor(Vec4(fc[0], fc[1], fc[2], 1))
        bg = self._palette["backdrop"]
        self.setBackgroundColor(bg[0], bg[1], bg[2], 1)

        # Rebuild all chunks with new palette — clear rendered + cached, dispatch fresh
        for key, np in list(self._chunks.items()):
            np.removeNode()
        self._chunks.clear()
        self._chunk_cache.clear()
        self._dispatch_chunks()

        console.log(f"[bold magenta]REGISTER[/bold magenta]  {reg}")

    # -- Debug telemetry (carried from dungeon) --------------------------------

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        props = WindowProperties()
        props.setFullscreen(self._fullscreen)
        if not self._fullscreen:
            props.setSize(960, 540)
        self.win.requestProperties(props)

    def _toggle_daylight(self):
        """Toggle between cave darkness and daylight inspection mode.
        Fog stays — dampness is permanent. Ambient cranks up."""
        self._daylight = not self._daylight
        if self._daylight:
            # Daylight: bright ambient, fog becomes atmospheric haze
            self._amb_np.node().setColor(Vec4(0.8, 0.75, 0.7, 1))
            self._fog.setColor(Vec4(0.35, 0.33, 0.30, 1))  # warm grey haze
            self._fog.setLinearRange(40.0, 120.0)  # push fog way out
            self.camLens.setFar(130.0)
            self.setBackgroundColor(0.30, 0.28, 0.26, 1)  # overcast sky
            console.log("[bold]DAYLIGHT[/bold] — inspection mode")
        else:
            # Cave: restore darkness
            fc = self._palette["fog"]
            self._amb_np.node().setColor(Vec4(0.10, 0.08, 0.06, 1))
            self._fog.setColor(Vec4(fc[0], fc[1], fc[2], 1))
            self._fog.setLinearRange(15.0, 42.0)
            self.camLens.setFar(45.0)
            self.setBackgroundColor(0.02, 0.02, 0.03, 1)
            console.log("[bold]CAVE[/bold] — darkness restored")

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

    # -- Tuning potentiometers ---------------------------------------------------

    def _select_tuner(self, ch):
        """Number row: select which parameter to tune."""
        if self._tuner_channel == ch:
            self._tuner_channel = 0  # toggle off
        else:
            self._tuner_channel = ch
        self._update_tuner_hud()

    def _adjust_tuner(self, direction, fine=False):
        """+ or - key: adjust selected parameter. Exponential taper near default.
        Shift = fine mode (1/5 step). Normal = coarse with curve."""
        ch = self._tuner_channel
        if ch == 0 or ch not in self._tuners:
            return
        t = self._tuners[ch]
        base_step = t["step"]
        if fine:
            # Fine mode: 1/5 step — precision dialing
            step = base_step * 0.2
        else:
            # Exponential taper: small steps near default, larger at extremes
            # Distance from default as fraction of range
            default = self._tuner_defaults[ch]
            full_range = t["max"] - t["min"]
            dist = abs(t["val"] - default) / max(0.001, full_range)
            # Curve: 0.3× at center, ramps to 2× at extremes
            curve = 0.3 + dist * 1.7
            step = base_step * curve
        t["val"] = max(t["min"], min(t["max"], t["val"] + step * direction))
        self._apply_tuner(ch)
        self._update_tuner_hud()

    def _apply_tuner(self, ch):
        """Push tuned value into the live engine."""
        t = self._tuners[ch]
        name = t["name"]
        v = t["val"]

        if name == "fog_near":
            fog_far = self._tuners[2]["val"]
            self._fog.setLinearRange(v, fog_far)
        elif name == "fog_far":
            fog_near = self._tuners[1]["val"]
            self._fog.setLinearRange(fog_near, v)
        elif name in ("ambient_r", "ambient_g", "ambient_b"):
            r = self._tuners[3]["val"]
            g = self._tuners[4]["val"]
            b = self._tuners[5]["val"]
            self._amb_np.getNode(0).setColor(Vec4(r, g, b, 1))
        elif name == "grain_alpha":
            if self._grain_card:
                self._grain_card.setAlphaScale(v / 0.18)  # relative to base
        elif name == "spot_power":
            pal = self._palette["sconce"]
            self._orb_np.getNode(0).setColor(
                Vec4(pal[0] * v, pal[1] * (v * 0.875), pal[2] * (v * 0.625), 1))
        elif name == "decal_scale":
            pass  # applied on next membrane wake — live preview on new entities
        elif name == "fade_entity":
            pass  # applied on next entity wake

    def _reset_tuners(self):
        """Shift+0: reset all pots to defaults."""
        for ch, default_val in self._tuner_defaults.items():
            self._tuners[ch]["val"] = default_val
            self._apply_tuner(ch)
        self._update_tuner_hud()
        console.log("[bold yellow]TUNERS RESET[/bold yellow]")

    def _update_tuner_hud(self):
        """Show/hide the tuning overlay."""
        if self._tuner_channel == 0:
            if self._tuner_hud:
                self._tuner_hud.hide()
            return
        if not self._tuner_hud:
            self._tuner_hud = OnscreenText(
                text="", pos=(0.0, 0.85), scale=0.04,
                fg=(1.0, 0.9, 0.3, 0.9), align=TextNode.ACenter,
                mayChange=True, shadow=(0, 0, 0, 0.7),
            )
        lines = []
        for ch in range(1, 10):
            t = self._tuners[ch]
            marker = ">" if ch == self._tuner_channel else " "
            bar_pct = (t["val"] - t["min"]) / max(0.001, t["max"] - t["min"])
            bar_len = int(bar_pct * 20)
            bar = "|" * bar_len + "." * (20 - bar_len)
            lines.append(f"{marker}{ch} {t['name']:>12s}  [{bar}] {t['val']:.2f}")
        self._tuner_hud.setText("\n".join(lines))
        self._tuner_hud.show()

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
        queue_depth = len(self._object_spawn_queue)
        entities_total = self._ambient.total_count
        entities_active = self._ambient.active_count
        chunks_loaded = len(self._chunks)
        import time as _time
        wall_time = round(_time.time(), 3)

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
                "spawn_queue": queue_depth,
                "entities_total": entities_total,
                "entities_active": entities_active,
                "chunks_loaded": chunks_loaded,
                "wall_time": wall_time,
            },
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

    def _dump_debug_state(self):
        import traceback
        try:
            self._probe_data = self._calc_probe()
            cam = self.cam.getPos()
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
                "palette": {k: list(v) if isinstance(v, tuple) else v
                            for k, v in self._palette.items()},
            }
            with open(self._state_path, "w") as f:
                json.dump(state, f, indent=2, default=str)
            console.log(f"[bold green]STATE DUMPED[/bold green]  "
                         f"chunks={len(self._chunks)}  tags={len(self._debug_tags)}")
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
        lines = [
            f"pos=({cam.getX():.1f}, {cam.getY():.1f}, {cam.getZ():.1f}) "
            f"h={self._cam_h:.0f} p={self._cam_p:.0f}",
            f"chunk=({chunk[0]}, {chunk[1]})  loaded={len(self._chunks)}",
            f"probe: {p.get('surface', '?')}  d={p.get('distance', '?')}",
            f"reg={REGISTERS[self._register_index]}  tags={len(self._debug_tags)}  tex={self._tex_size_override}",
            f"ambient: {self._ambient.active_count}/{self._ambient.total_count} awake",
            f"chrono: {self._chrono_state['day_phase']}  night={self._chrono_state['night_weight']:.2f}  moon={self._chrono_state['moon_approx']:.2f}",
        ]
        self._debug_hud_text.setText("\n".join(lines))

    # -- Main loop -------------------------------------------------------------

    def _loop(self, task):
        dt = globalClock.getDt()

        # Mouse look
        if not hasattr(self, '_win_cx'):
            self._center_mouse()
        dx, dy = self._read_mouse()
        if not self._mouse_initialized:
            self._mouse_initialized = True
            dx, dy = 0, 0

        self._cam_h -= dx * MOUSE_SENS
        self._cam_p = max(-PITCH_LIMIT, min(PITCH_LIMIT, self._cam_p - dy * MOUSE_SENS))

        # WASD — gated by layer diagnostic (layer 10 = LIVE)
        heading_rad = math.radians(self._cam_h)
        forward_x = -math.sin(heading_rad)
        forward_y = math.cos(heading_rad)
        right_x = math.cos(heading_rad)
        right_y = math.sin(heading_rad)

        move_x, move_y = 0.0, 0.0
        if getattr(self, '_diag_layer', 8) >= 8:
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
        terrain_z = self._height_at(new_x, new_y)
        self.cam.setPos(new_x, new_y, terrain_z + EYE_Z)
        self.cam.setHpr(self._cam_h, self._cam_p, 0)

        # 60-frame cycle — spread all subsystems across the cycle
        if not hasattr(self, '_frame_counter'):
            self._frame_counter = 0
        self._frame_counter = (self._frame_counter + 1) % 60

        fc = self._frame_counter

        # Chunk scan + dispatch: frames 0, 15, 30, 45 (4× per cycle)
        if fc % 15 == 0:
            self._dispatch_chunks()

        # Chunk build: frames 10, 20, 40, 50 (4× per cycle — half rate, smoother)
        if fc % 10 == 0 and fc % 30 != 0:
            self._build_ready_chunk()

        # Ambient life: frames 3, 9, 21, 27, 33, 39, 51, 57 (8× per cycle)
        if fc % 6 == 3 and not getattr(self, '_diag_suppress_ambient', False):
            self._ambient.tick(dt * 6, self.cam.getPos(), self._cam_h)

        # Despawn check: frame 47 only (1× per cycle)
        if fc == 47 and not getattr(self, '_diag_suppress_ambient', False):
            self._despawn_distant()

        # Object tile scan: 4× per cycle (1 tile per call, spread the load)
        if fc in (7, 22, 37, 52) and not getattr(self, '_diag_suppress_ambient', False):
            self._place_object_tiles()
        if fc == 53 and not getattr(self, '_diag_suppress_ambient', False):
            self._despawn_distant_tiles()

        # Drip-spawn queued objects: every frame (8 per frame, ~1ms budget)
        if not getattr(self, '_diag_suppress_ambient', False):
            self._drip_spawn_objects()

        # Player torch decal — warm ground pool follows camera
        if not getattr(self, '_diag_suppress_membrane', False):
            self._membrane.update_torch(self.cam.getPos(), self._height_at)

        # Manual GC: gen-0 only during gameplay — lightweight, ~0.1ms
        # Gen-1/2 were causing 50-75ms spikes with 3000+ entity node trees
        if fc == 37:
            gc.collect(0)

        # Chronometer: frame 59 (1× per cycle, ~1 read per second)
        if fc == 59:
            self._chrono_state = self._chrono.read()
            # Fog density shifts with time — denser at night
            nw = self._chrono_state["night_weight"]
            fog_near = 25.0 - nw * 6.0   # 25→19 at night
            fog_far = 55.0 - nw * 12.0   # 55→43 at night
            self._fog.setLinearRange(fog_near, fog_far)
            # Ambient light dims at night
            amb_scale = 1.0 - nw * 0.3   # 30% dimmer at deep night
            self._amb_np.node().setColor(Vec4(
                0.10 * amb_scale, 0.08 * amb_scale, 0.06 * amb_scale, 1))

        # Orb animation: gentle bob + flicker
        t = globalClock.getFrameTime()
        fi = self._palette.get("flicker_intensity", 0.15)
        lc = self._palette["sconce"]
        flicker = 1.0 + fi * 0.4 * math.sin(t * 5.3) * math.sin(t * 7.7)
        self._orb_np.node().setColor(Vec4(
            lc[0] * 1.8 * flicker, lc[1] * 1.6 * flicker,
            lc[2] * 1.4 * flicker, 1,
        ))
        # Gentle drift behind shoulder
        bob_x = 0.3 + math.sin(t * 1.1) * 0.06
        bob_y = -0.8 + math.cos(t * 0.9) * 0.04
        bob_z = 0.6 + math.sin(t * 1.7) * 0.08
        self._orb_np.setPos(bob_x, bob_y, bob_z)
        self._orb_np.lookAt(self.cam, Vec3(0, 8, -1))  # always aim forward+down

        # Debug
        self._check_debug_commands()
        if self._debug_mode:
            self._probe_data = self._calc_probe()
            self._update_debug_hud()

        return task.cont


if __name__ == "__main__":
    Cavern().run()
