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
import threading

from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
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
    GeomVertexFormat, GeomVertexWriter,
)
from core.systems.geometry import make_box, make_pebble_cluster
from core.systems.shadowbox_scene import SHADOWBOX_REGISTERS, resolve_palette

console = Console()

# -- World constants -----------------------------------------------------------

CHUNK_SIZE = 16.0       # meters per chunk edge
CHUNK_RADIUS = 2        # chunks visible in each direction (5x5 = 25 chunks)
DESPAWN_RADIUS = 3      # chunks beyond this get cleaned up
TEX_SIZE = 96           # procedural texture resolution per chunk
MOVE_SPEED = 5.0
MOUSE_SENS = 0.3
PITCH_LIMIT = 60.0
EYE_Z = 2.5

REGISTERS = ["survival", "tron", "tolkien", "sanrio"]


class Cavern(ShowBase):

    def __init__(self):
        super().__init__()

        props = WindowProperties()
        props.setTitle("Sanctum — The Endless Floor")
        props.setSize(1280, 720)
        props.setCursorHidden(True)
        self.win.requestProperties(props)

        # -- Rendering setup ---------------------------------------------------
        self.setBackgroundColor(0.02, 0.02, 0.03, 1)
        self.disableMouse()
        self.camLens.setFov(65.0)
        self.camLens.setNear(0.5)
        self.camLens.setFar(200.0)
        self.render.setAntialias(AntialiasAttrib.MMultisample)
        self.render.setShaderAuto()

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
        self._placer = PlacementEngine(seed=self._chunk_seed)
        self._entropy = EntropyEngine()

        # -- Debug telemetry ---------------------------------------------------
        self._debug_mode = False
        self._probe_data = {}
        self._debug_hud_text = None
        self._debug_tags = []
        self._tag_counter = 0
        self._cmd_path = os.path.join(os.path.dirname(__file__) or ".", "debug_cmd.json")
        self._state_path = os.path.join(os.path.dirname(__file__) or ".", "debug_state.json")

        # -- Lighting ----------------------------------------------------------
        self._build_lighting()

        # -- Fog ---------------------------------------------------------------
        self._fog = Fog("cavern_fog")
        fc = self._palette["fog"]
        self._fog.setColor(Vec4(fc[0], fc[1], fc[2], 1))
        self._fog.setLinearRange(20.0, 60.0)
        self.render.setFog(self._fog)

        # -- Camera start ------------------------------------------------------
        self.cam.setPos(0, 0, EYE_Z)
        self._mouse_initialized = False

        # -- Generate initial chunks -------------------------------------------
        self._update_chunks()

        # -- Post-processing ---------------------------------------------------
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

        self.taskMgr.add(self._loop, "CavernLoop")

        console.log("[bold cyan]THE ENDLESS FLOOR[/bold cyan]")
        console.log("[WASD] move  [Mouse] look  [F1-F4] registers  [ESC] quit")
        console.log("[dim][`] debug  [0] dump  [T] tag  [Shift+T] undo  [Ctrl+T] clear[/dim]")

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
        amb.setColor(Vec4(0.10, 0.08, 0.06, 1))
        self._amb_np = self.render.attachNewNode(amb)
        self.render.setLight(self._amb_np)

        # Light orb — spotlight cone from behind, casting forward like a flashlight
        lc = pal["sconce"]

        # Main cone: spotlight aimed forward from behind the player
        spot = Spotlight("orb_cone")
        spot.setColor(Vec4(lc[0] * 3.0, lc[1] * 2.5, lc[2] * 1.5, 1))
        spot.getLens().setFov(60)
        spot.getLens().setNearFar(0.5, 50)
        spot.setAttenuation((0.2, 0.008, 0.002))
        spot.setShadowCaster(True, 512, 512)
        spot.setExponent(8.0)
        self._orb_np = self.cam.attachNewNode(spot)
        self._orb_np.setPos(0.3, -0.8, 0.6)  # behind right shoulder
        self._orb_np.lookAt(self.cam, Vec3(0, 8, -1))  # aim forward and slightly down
        self.render.setLight(self._orb_np)

        # Fill light: dim point light for ambient spill around the orb
        fill = PointLight("orb_fill")
        fill.setColor(Vec4(lc[0] * 0.4, lc[1] * 0.35, lc[2] * 0.2, 1))
        fill.setAttenuation((0.5, 0.03, 0.008))
        self._orb_fill = self._orb_np.attachNewNode(fill)
        self.render.setLight(self._orb_fill)

        # Tiny glow marker visible in peripheral vision
        orb_vis = make_box(0.025, 0.025, 0.025, (0.95, 0.8, 0.45))
        self._orb_vis = self._orb_np.attachNewNode(orb_vis)
        self._orb_vis.setLightOff()
        self._orb_vis.setColorScale(2.5, 2.0, 1.2, 1.0)

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

    def _update_chunks(self):
        """Generate/despawn chunks. Textures built on background threads."""
        cam_pos = self.cam.getPos()
        center_cx, center_cz = self._chunk_key(cam_pos.getX(), cam_pos.getY())

        # Dispatch missing chunks to background threads
        for dx in range(-CHUNK_RADIUS, CHUNK_RADIUS + 1):
            for dz in range(-CHUNK_RADIUS, CHUNK_RADIUS + 1):
                key = (center_cx + dx, center_cz + dz)
                if key not in self._chunks and key not in self._pending_chunks:
                    with self._chunk_lock:
                        if key not in self._ready_chunks:
                            self._pending_chunks[key] = True
                            t = threading.Thread(
                                target=self._generate_chunk_data, args=(key,), daemon=True,
                            )
                            t.start()

        # Build scene nodes from ready chunks (max 2 per frame to stay smooth)
        built = 0
        with self._chunk_lock:
            for key in list(self._ready_chunks.keys()):
                if built >= 2:
                    break
                if key not in self._chunks:
                    tex_pixels, chunk_seed = self._ready_chunks.pop(key)
                    self._chunks[key] = self._build_chunk_from_data(key[0], key[1], tex_pixels, chunk_seed)
                    built += 1
                else:
                    self._ready_chunks.pop(key)

        # Despawn distant chunks
        to_remove = []
        for key in self._chunks:
            if (abs(key[0] - center_cx) > DESPAWN_RADIUS or
                    abs(key[1] - center_cz) > DESPAWN_RADIUS):
                to_remove.append(key)
        for key in to_remove:
            self._chunks[key].removeNode()
            del self._chunks[key]

    def _generate_chunk_data(self, key):
        """Background thread: generate texture pixel data (no Panda3D calls)."""
        cx, cz = key
        chunk_seed = hash((self._chunk_seed, cx, cz)) & 0xFFFFFFFF
        tex_pixels = self._compute_cobblestone_pixels(cx, cz)
        with self._chunk_lock:
            self._ready_chunks[key] = (tex_pixels, chunk_seed)
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
        subdivs = 12
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

        # -- Boulder groups (egg-shaped, sparse) --
        center_x = world_x + CHUNK_SIZE / 2
        center_y = world_y + CHUNK_SIZE / 2
        boulder_count = rng.choices([0, 0, 1, 1, 2], weights=[3, 3, 4, 4, 1])[0]
        rock_colors = [
            (0.22, 0.20, 0.18), (0.25, 0.23, 0.20), (0.19, 0.18, 0.16),
            (0.28, 0.26, 0.22), (0.20, 0.19, 0.17),
        ]

        if boulder_count > 0:
            b_pts = self._placer.golden_spiral(
                boulder_count * 4, CHUNK_SIZE / 3,
                center_x, center_y, phase=chunk_seed * 3.7,
            )
            placed_b = 0
            for px, py in b_pts:
                if placed_b >= boulder_count:
                    break
                if abs(px - center_x) > CHUNK_SIZE / 2 - 1:
                    continue
                if abs(py - center_y) > CHUNK_SIZE / 2 - 1:
                    continue

                bz = self._height_at(px, py)
                clr = rng.choice(rock_colors)

                # Large egg boulder (taller than wide)
                big_h = rng.uniform(0.5, 1.0)
                big_w = big_h * rng.uniform(0.6, 0.85)
                big_d = big_h * rng.uniform(0.5, 0.75)
                big_rock = make_pebble_cluster(
                    big_w, big_h, big_d, clr,
                    count=max(14, int(24 * big_h)),
                    seed=chunk_seed + 800 + placed_b,
                    scatter=rng.uniform(0.0, 0.05),
                )
                brn = chunk_root.attachNewNode(big_rock)
                brn.setPos(px, py, bz + big_h * 0.25)
                brn.setH(rng.uniform(0, 360))

                # 1-3 smaller boulders leaning against
                for li in range(rng.randint(1, 3)):
                    sm_s = rng.uniform(0.3, 0.6)
                    sm_h = big_h * sm_s
                    sm_w = sm_h * rng.uniform(0.6, 0.9)
                    sm_d = sm_h * rng.uniform(0.5, 0.8)
                    sm_clr = rng.choice(rock_colors)
                    sm_rock = make_pebble_cluster(
                        sm_w, sm_h, sm_d, sm_clr,
                        count=max(8, int(16 * sm_s)),
                        seed=chunk_seed + 900 + placed_b * 10 + li,
                        scatter=rng.uniform(0.0, 0.07),
                    )
                    angle = rng.uniform(0, 360)
                    dist = big_w * 0.5 + sm_w * 0.3
                    sx = px + math.cos(math.radians(angle)) * dist
                    sy = py + math.sin(math.radians(angle)) * dist
                    sz = self._height_at(sx, sy)
                    srn = chunk_root.attachNewNode(sm_rock)
                    srn.setPos(sx, sy, sz + sm_h * 0.15)
                    srn.setH(rng.uniform(0, 360))
                    srn.setR(rng.uniform(-15, 15))

                placed_b += 1

        # -- Rats --
        rat_count = rng.choices([0, 1, 1, 2], weights=[2, 5, 5, 1])[0]
        for ri in range(rat_count):
            rx = world_x + rng.uniform(2, CHUNK_SIZE - 2)
            ry = world_y + rng.uniform(2, CHUNK_SIZE - 2)
            rz = self._height_at(rx, ry)
            rat_root = chunk_root.attachNewNode(f"rat_{cx}_{cz}_{ri}")
            rat_root.setPos(rx, ry, rz)
            rat_root.setH(rng.uniform(0, 360))

            scale = rng.uniform(0.7, 1.2)
            body_len = rng.uniform(0.15, 0.22) * scale
            body_w = body_len * rng.uniform(0.35, 0.5)
            body_h = body_len * rng.uniform(0.25, 0.35)
            fs = rng.uniform(-0.02, 0.02)
            fur = (0.08 + fs, 0.06 + fs, 0.05 + fs)

            bn = rat_root.attachNewNode(make_box(body_w, body_h, body_len, fur))
            bn.setPos(0, 0, body_h * 0.5)
            hs = body_h * 0.8
            hn = rat_root.attachNewNode(make_box(hs * 1.1, hs, hs * 1.1, fur))
            hn.setPos(0, body_len * 0.5, body_h * 0.55)
            sn = rat_root.attachNewNode(make_box(hs * 0.4, hs * 0.3, hs * 0.6,
                                                  (fur[0] + 0.02, fur[1] + 0.02, fur[2] + 0.01)))
            sn.setPos(0, body_len * 0.5 + hs * 0.7, body_h * 0.45)
            for t in range(rng.randint(5, 8)):
                taper = 1.0 - (t / 8) * 0.7
                thick = body_h * 0.12 * taper
                tn = rat_root.attachNewNode(make_box(thick, thick, body_len * 0.12, (0.12, 0.09, 0.08)))
                tn.setPos(0, -body_len * 0.4 - body_len * 0.12 * t, body_h * 0.3)

        return chunk_root

    def _build_chunk_from_data(self, cx, cz, tex_pixels, chunk_seed):
        """Build chunk on main thread from pre-computed texture pixels."""
        tex = self._pixels_to_texture(tex_pixels, f"cobble_{cx}_{cz}")
        # Reuse the main build method but inject the texture
        # Quick approach: save/restore to avoid recomputing pixels
        self._prebuilt_tex = tex
        result = self._build_chunk(cx, cz)
        self._prebuilt_tex = None
        return result

    def _compute_cobblestone_pixels(self, cx, cz):
        """Pure computation — returns pixel rows. Thread-safe, no Panda3D."""
        pixels = []  # list of rows, each row = list of (r,g,b)
        pal = self._palette
        base_r, base_g, base_b = pal.get("stage_floor", (0.08, 0.06, 0.05))
        base_r, base_g, base_b = base_r + 0.10, base_g + 0.08, base_b + 0.06
        mortar_r = base_r * 0.2
        mortar_g = base_g * 0.2
        mortar_b = base_b * 0.2

        # Dense cell grid — world-space for seamless tiling across chunks
        # Use a regular jittered grid instead of spiral for even coverage
        stone_size = 0.5  # ~0.5m per stone — dense pack
        overscan = 2.0  # meters past chunk edge for seamless borders
        cell_rng = __import__("random").Random(self._chunk_seed + 77)

        cells = []
        cell_colors = []
        x_start = cx * CHUNK_SIZE - overscan
        y_start = cz * CHUNK_SIZE - overscan
        x_end = (cx + 1) * CHUNK_SIZE + overscan
        y_end = (cz + 1) * CHUNK_SIZE + overscan

        # Jittered grid: regular spacing + seeded offset per cell
        gx = x_start
        while gx < x_end:
            gy = y_start
            while gy < y_end:
                # Deterministic jitter from world position
                jx = self._placer.perlin(gx * 1.7, gy * 1.7, octaves=1) - 0.5
                jy = self._placer.perlin(gx * 1.7 + 100, gy * 1.7 + 100, octaves=1) - 0.5
                wx = gx + jx * stone_size * 0.7
                wy = gy + jy * stone_size * 0.7
                cells.append((wx, wy))

                # Per-stone color: wide palette — warm ochres, cool slate, mossy hints
                n = self._placer.perlin(wx * 0.4, wy * 0.4, octaves=1)
                v = (n - 0.5) * 0.14  # wider brightness range
                w = self._placer.perlin(wx * 0.7 + 50, wy * 0.7 + 50, octaves=1)
                warm = (w - 0.5) * 0.08  # stronger warm/cool swing
                # Third noise layer for green/moss hints
                m = self._placer.perlin(wx * 0.3 + 200, wy * 0.3 + 200, octaves=1)
                moss = max(0, (m - 0.65) * 0.15)  # sparse green tint
                cell_colors.append((
                    max(0, min(1, base_r + v + warm)),
                    max(0, min(1, base_g + v + moss)),
                    max(0, min(1, base_b + v - warm * 0.5)),
                ))
                gy += stone_size
            gx += stone_size

        # Spatial hash: bucket cells into grid for fast nearest-neighbor lookup
        bucket_size = stone_size * 1.5
        buckets = {}
        for ci, (ccx, ccy) in enumerate(cells):
            bx = int(math.floor(ccx / bucket_size))
            by = int(math.floor(ccy / bucket_size))
            key = (bx, by)
            if key not in buckets:
                buckets[key] = []
            buckets[key].append(ci)

        for y in range(TEX_SIZE):
            row = []
            for x in range(TEX_SIZE):
                px = cx * CHUNK_SIZE + (x / TEX_SIZE) * CHUNK_SIZE
                py = cz * CHUNK_SIZE + (y / TEX_SIZE) * CHUNK_SIZE

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
                min_d2 = math.sqrt(min_d2)
                edge = min_d2 - min_d1

                mortar_noise = self._placer.perlin(px * 1.5, py * 1.5, octaves=1)
                mortar_width = 0.03 + mortar_noise * 0.08

                if edge < mortar_width:
                    dirt_n = self._placer.perlin(px * 3.0 + 300, py * 3.0 + 300, octaves=1)
                    dirt_v = dirt_n * 0.06
                    row.append((max(0, mortar_r + dirt_v + 0.01),
                                max(0, mortar_g + dirt_v + 0.005),
                                max(0, mortar_b + dirt_v)))
                else:
                    cr, cg, cb = cell_colors[min_ci % len(cell_colors)]
                    stone_radius = stone_size * 0.4
                    center_dist = min(1.0, min_d1 / stone_radius)
                    shade = 1.0 - center_dist * center_dist * 0.45
                    sn = self._placer.perlin(px * 4.0, py * 4.0, octaves=1)
                    sv = (sn - 0.5) * 0.05
                    row.append((max(0, min(1, cr * shade + sv)),
                                max(0, min(1, cg * shade + sv)),
                                max(0, min(1, cb * shade + sv))))
            pixels.append(row)
        return pixels

    def _pixels_to_texture(self, pixels, name):
        """Main thread: convert pixel rows to Panda3D Texture."""
        img = PNMImage(TEX_SIZE, TEX_SIZE)
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

        # Update lighting
        lc = self._palette["sconce"]
        self._player_light.node().setColor(Vec4(lc[0] * 0.8, lc[1] * 0.7, lc[2] * 0.4, 1))
        fc = self._palette["fog"]
        self._fog.setColor(Vec4(fc[0], fc[1], fc[2], 1))
        bg = self._palette["backdrop"]
        self.setBackgroundColor(bg[0], bg[1], bg[2], 1)

        # Rebuild all chunks with new palette
        for key, np in list(self._chunks.items()):
            np.removeNode()
        self._chunks.clear()
        self._update_chunks()

        console.log(f"[bold magenta]REGISTER[/bold magenta]  {reg}")

    # -- Debug telemetry (carried from dungeon) --------------------------------

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
        probe = self._calc_probe()
        if probe.get("distance", -1) < 0:
            return
        self._tag_counter += 1
        tag_id = self._tag_counter
        pos = probe["hit"]
        text = label or f"#{tag_id}"

        tn = TextNode(f"tag_{tag_id}")
        tn.setText(text)
        tn.setAlign(TextNode.ACenter)
        tn.setTextColor(1.0, 0.85, 0.2, 0.9)
        tn.setCardColor(0.0, 0.0, 0.0, 0.5)
        tn.setCardAsMargin(0.15, 0.15, 0.08, 0.08)
        tn.setCardDecal(True)
        node = self.render.attachNewNode(tn)
        node.setPos(pos[0], pos[1], pos[2] + 0.3)
        node.setScale(0.18)
        node.setBillboardPointEye()

        tag = {
            "id": tag_id, "label": text,
            "surface": probe["surface"], "distance": probe["distance"],
            "pos": pos, "chunk": probe.get("chunk"),
            "camera": {
                "x": round(self.cam.getX(), 2), "y": round(self.cam.getY(), 2),
                "z": round(self.cam.getZ(), 2),
                "h": round(self._cam_h, 1), "p": round(self._cam_p, 1),
            },
            "_node": node,
        }
        self._debug_tags.append(tag)
        console.log(f"[bold yellow]TAG #{tag_id}[/bold yellow]  {probe['surface']}  "
                     f"d={probe['distance']}  @ {pos}")

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
            f"reg={REGISTERS[self._register_index]}  tags={len(self._debug_tags)}",
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
        terrain_z = self._height_at(new_x, new_y)
        self.cam.setPos(new_x, new_y, terrain_z + EYE_Z)
        self.cam.setHpr(self._cam_h, self._cam_p, 0)

        # Chunk generation
        self._update_chunks()

        # Orb animation: gentle bob + flicker
        t = globalClock.getFrameTime()
        fi = self._palette.get("flicker_intensity", 0.15)
        lc = self._palette["sconce"]
        flicker = 1.0 + fi * 0.4 * math.sin(t * 5.3) * math.sin(t * 7.7)
        self._orb_np.node().setColor(Vec4(
            lc[0] * 3.0 * flicker, lc[1] * 2.5 * flicker,
            lc[2] * 1.5 * flicker, 1,
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
