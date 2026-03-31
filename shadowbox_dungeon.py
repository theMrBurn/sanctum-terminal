"""
shadowbox_dungeon.py

The Garden of Forking Paths — Tartarus-style procedural dungeon.

Same room, different layout every time. Walk up to doors. Press E.
FPS mouse-look, WASD strafe, RPG HUD, bloom, 4 visual registers.

Controls:
    Mouse       Look around
    W/S         Walk forward/back
    A/D         Strafe left/right
    E           Open nearest door (when close)
    1-8         Examine door (free, works at distance)
    F1-F4       Cycle registers (survival/tron/tolkien/sanrio)
    B           Toggle bloom
    ESC         Quit

Usage:
    make shadowbox
"""

import sys
import math
import json
import os

from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from direct.gui.OnscreenImage import OnscreenImage
from panda3d.core import (
    AmbientLight, DirectionalLight, PointLight,
    Vec4, Vec3, TextNode, AntialiasAttrib,
    Fog, SamplerState, TransparencyAttrib,
    WindowProperties, NodePath, Shader, Texture,
    RigidBodyCombiner,
)
from panda3d.bullet import (
    BulletWorld, BulletRigidBodyNode, BulletBoxShape, BulletPlaneShape,
    BulletDebugNode,
)
from rich.console import Console

from core.systems.shadowbox_scene import (
    ShadowboxScene, ShadowboxConfig, ShadowboxCamera,
)
from core.systems.room_layout import RoomLayout, WallSide
from core.systems.door_animator import DoorAnimator, DoorState
from core.systems.interaction_engine import InteractionEngine
from core.systems.geometry import (
    make_box, make_arch, make_textured_quad, make_textured_wall, make_textured_floor,
    make_pebble_cluster,
)
from core.systems.dungeon_campaign import DungeonCampaign
from core.systems.postprocess import (
    COMPOSITE_FRAG, BRIGHT_PASS_FRAG, BLUR_FRAG, FULLSCREEN_VERT,
)

console = Console()

# -- Room constants ------------------------------------------------------------

ROOM_WIDTH  = 16.0
ROOM_DEPTH  = 24.0
WALL_HEIGHT = 6.0
DOOR_WIDTH  = 2.0
DOOR_HEIGHT = 3.2
MOVE_SPEED  = 5.0
MOUSE_SENS  = 0.3
PITCH_LIMIT = 60.0
EYE_Z       = 2.5
TUCK        = 0.06  # overlap at seams to kill edge artifacts

INTERACT_RADIUS  = 2.0   # walk up to door
DETECT_RADIUS    = 8.0   # see door highlight

REGISTERS = ["survival", "tron", "tolkien", "sanrio"]


class ShadowboxDungeon(ShowBase):

    def __init__(self):
        super().__init__()

        props = WindowProperties()
        props.setTitle("Sanctum — The Garden of Forking Paths")
        props.setSize(1280, 720)
        props.setCursorHidden(True)
        self.win.requestProperties(props)

        # -- Scene manager -----------------------------------------------------
        self._scene = ShadowboxScene(ShadowboxConfig(
            camera=ShadowboxCamera(fov=65.0),
            register="survival",
        ))
        self._register_index = 0

        # -- Panda3D setup -----------------------------------------------------
        self.setBackgroundColor(0.02, 0.02, 0.03, 1)
        self.disableMouse()
        self.camLens.setFov(self._scene.config.camera.fov)
        self.camLens.setNear(self._scene.config.camera.near)
        self.camLens.setFar(self._scene.config.camera.far)
        self.render.setAntialias(AntialiasAttrib.MMultisample)
        self.render.setShaderAuto()

        # -- Game state --------------------------------------------------------
        self._campaign = DungeonCampaign(seed="GARDEN_OF_FORKING_PATHS")
        self._door_animator = DoorAnimator(door_count=8)
        self._keys = {"w": False, "s": False, "a": False, "d": False}
        self._cam_h = 0.0
        self._cam_p = 0.0
        self._pending_advance = False
        self._advance_timer = 0.0
        self._transition_phase = None  # "fade_out" | "fade_in" | None
        self._transition_timer = 0.0
        self._wrong_door_msg = ""

        # -- Node tracking -----------------------------------------------------
        self._layer_roots = {}
        self._scene_nodes = []
        self._door_pivots = []  # NodePath per door (hinge pivot)
        self._door_labels = []
        self._light_nodes = []
        self._room_layout = None
        self._torch_nps = []  # torch quads for rotation

        # -- Pre-render state --------------------------------------------------
        self._filters = None
        self._bloom_on = False
        self._custom_pp = False
        self._pp_final_quad = None
        self._sconce_base = (1.0, 0.7, 0.35)  # current base sconce color (with depth warmth)

        # -- Debug telemetry ---------------------------------------------------
        self._debug_mode = False
        self._probe_data = {}
        self._debug_hud_text = None
        self._debug_tags = []       # [{pos, surface, distance, label, node}]
        self._tag_counter = 0
        self._cmd_path = os.path.join(os.path.dirname(__file__) or ".", "debug_cmd.json")
        self._state_path = os.path.join(os.path.dirname(__file__) or ".", "debug_state.json")

        # -- Textures ----------------------------------------------------------
        self._wall_tex = self._load_texture("assets/sprites/textures/wall_brick.png")
        self._door_tex = self._load_texture("assets/sprites/textures/door_procedural.png")
        self._floor_tex = self._load_texture("assets/sprites/textures/floor_gravel.png")
        self._ceil_tex = self._load_texture("assets/sprites/textures/ceiling_slab.png")
        self._torch_tex = self._load_texture("assets/sprites/textures/wall_torch.png")

        # -- Build scene -------------------------------------------------------
        self._build_layer_roots()
        self._build_lighting()
        self._setup_interaction()
        self._build_room()
        self._apply_register()
        self._setup_postprocess()
        self._build_hud()

        # -- Camera start ------------------------------------------------------
        self._reset_camera()
        self._mouse_initialized = False

        # -- Fade overlay ------------------------------------------------------
        self._fade_overlay = OnscreenImage(
            image="assets/sprites/textures/pixel_white.png",
            pos=(0, 0, 0), scale=(2, 1, 2),
        )
        self._fade_overlay.setTransparency(TransparencyAttrib.MAlpha)
        self._fade_overlay.setColor(0, 0, 0, 0)
        self._fade_overlay.hide()

        # -- Controls ----------------------------------------------------------
        for i in range(8):
            self.accept(str(i + 1), self._examine, [i])
        self.accept("e", self._interact_nearest)
        self.accept("escape", sys.exit)

        for i in range(len(REGISTERS)):
            self.accept(f"f{i + 1}", self._cycle_register, [i])
        self.accept("b", self._toggle_bloom)
        self.accept("]", self._toggle_fullscreen)
        self.accept("`", self._toggle_debug)
        self.accept("0", self._dump_debug_state)
        self.accept("t", self._place_tag)
        self.accept("shift-t", self._undo_last_tag)
        self.accept("control-t", self._clear_tags)

        for key in self._keys:
            self.accept(key, self._set_key, [key, True])
            self.accept(f"{key}-up", self._set_key, [key, False])

        self.taskMgr.add(self._loop, "ShadowboxLoop")

        console.log("[bold cyan]THE GARDEN OF FORKING PATHS[/bold cyan]")
        console.log("Walk to a door. Press E. Find the one that's different.")
        console.log("[WASD] move  [Mouse] look  [E] open door  [1-8] examine  [ESC] quit")
        console.log("[dim][`] debug overlay  [0] dump state  [T] tag  [Shift+T] undo  [Ctrl+T] clear[/dim]")

    # -- Helpers ---------------------------------------------------------------

    def _reset_camera(self):
        self.cam.setPos(0, -ROOM_DEPTH / 2 + 2, EYE_Z)
        self._cam_h = 0.0
        self._cam_p = 0.0

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

    def _load_texture(self, path):
        tex = self.loader.loadTexture(path)
        tex.setMagfilter(SamplerState.FT_nearest)
        tex.setMinfilter(SamplerState.FT_nearest)
        tex.setWrapU(SamplerState.WM_repeat)
        tex.setWrapV(SamplerState.WM_repeat)
        return tex

    def _set_key(self, key, value):
        self._keys[key] = value

    # -- Layer infrastructure --------------------------------------------------

    def _build_layer_roots(self):
        for layer in self._scene.config.layers:
            root = self.render.attachNewNode(f"layer_{layer.name}")
            self._layer_roots[layer.name] = root

    # -- Lighting --------------------------------------------------------------

    def _build_lighting(self):
        pal = self._scene.palette

        # Minimal ambient — just enough to not be pitch black in corners
        amb = AmbientLight("amb")
        amb.setColor(Vec4(0.03, 0.025, 0.02, 1))
        self._amb_np = self.render.attachNewNode(amb)
        self.render.setLight(self._amb_np)

        # No sun — torch-lit only
        self._sun_np = None

        # Wall sconces — the room's only real light source
        hw = ROOM_WIDTH / 2 - 0.5
        sconce_y = [-8, -4, 0, 4, 8]  # 5 positions = 10 torches total
        self._sconce_nps = []
        self._torch_nps = []
        for y in sconce_y:
            for x_side in [-hw, hw]:
                lamp = PointLight(f"sconce_{x_side}_{y}")
                lc = pal["sconce"]
                lamp.setColor(Vec4(lc[0] * 1.4, lc[1] * 1.2, lc[2] * 0.7, 1))
                lamp.setShadowCaster(True, 512, 512)
                lamp.setAttenuation((0.3, 0.05, 0.015))
                ln = self.render.attachNewNode(lamp)
                ln.setPos(x_side, y, WALL_HEIGHT * 0.7)
                self.render.setLight(ln)
                self._sconce_nps.append(ln)
                self._light_nodes.append(ln)

                # Torch mount — fixed to wall, wobbles on vertical axis
                torch_mount = self.render.attachNewNode(f"torch_mount_{x_side}_{y}")
                inset = 0.05 if x_side < 0 else -0.05
                torch_mount.setPos(x_side + inset, y, WALL_HEIGHT * 0.55)
                base_h = 90 if x_side > 0 else -90
                torch_mount.setTag("base_h", str(base_h))

                torch_geom = make_textured_quad(0.8, 1.0, name=f"torch_{x_side}_{y}")
                tn = torch_mount.attachNewNode(torch_geom)
                tn.setTexture(self._torch_tex)
                tn.setTransparency(TransparencyAttrib.MAlpha)

                self._torch_nps.append(torch_mount)
                self._light_nodes.append(torch_mount)

        self._fog = Fog("shadowbox_fog")
        fc = pal["fog"]
        self._fog.setColor(Vec4(fc[0], fc[1], fc[2], 1))
        self._fog.setLinearRange(15.0, 50.0)
        self.render.setFog(self._fog)

    # -- Interaction engine ----------------------------------------------------

    def _setup_interaction(self):
        self._interaction = InteractionEngine(
            camera=self.cam,
            render=self.render,
            reachable_radius=INTERACT_RADIUS,
            detectable_radius=DETECT_RADIUS,
        )

    # -- Room geometry ---------------------------------------------------------

    def _clear_scene(self):
        for np in self._scene_nodes + self._door_pivots + self._door_labels:
            try:
                np.removeNode()
            except Exception:
                pass
        self._scene_nodes = []
        self._door_pivots = []
        self._door_labels = []

        # Tags are parented to stage — detach before they become orphans
        for tag in self._debug_tags:
            try:
                if tag.get("_node") and not tag["_node"].isEmpty():
                    tag["_node"].removeNode()
            except Exception:
                pass
            tag["_node"] = None

        # Unregister doors from interaction engine
        if hasattr(self, '_interaction'):
            for rec_id in list(self._interaction._records.keys()):
                self._interaction._records.pop(rec_id, None)

    def _build_room(self):
        self._clear_scene()
        pal = self._scene.palette
        hw, hd = ROOM_WIDTH / 2, ROOM_DEPTH / 2

        # Room layout — random door positions
        layout_seed = hash(
            f"{self._campaign.seed}_{self._campaign.corridor}_{self._campaign._resets}"
        )
        self._room_layout = RoomLayout(
            ROOM_WIDTH, ROOM_DEPTH, door_count=8, seed=layout_seed
        )

        stage_root = self._layer_roots["stage"]
        tile_x = ROOM_DEPTH / WALL_HEIGHT
        floor_tile = max(ROOM_WIDTH, ROOM_DEPTH) / 4.0

        # -- Stage: floor, ceiling, 4 walls ------------------------------------
        # Surfaces are slightly oversized (TUCK) so edges overlap at seams

        # Floor — extend past walls
        floor_geom = make_textured_floor(
            ROOM_WIDTH + TUCK * 2, ROOM_DEPTH + TUCK * 2,
            tile_x=floor_tile, tile_y=floor_tile, name="floor"
        )
        fn = stage_root.attachNewNode(floor_geom)
        fn.setPos(0, 0, -TUCK)
        fn.setTexture(self._floor_tex)
        fn.setTwoSided(True)
        self._scene_nodes.append(fn)

        # Ceiling — extend past walls, tuck down
        ceil_geom = make_textured_floor(
            ROOM_WIDTH + TUCK * 2, ROOM_DEPTH + TUCK * 2,
            tile_x=floor_tile, tile_y=floor_tile, name="ceiling"
        )
        cn = stage_root.attachNewNode(ceil_geom)
        cn.setPos(0, 0, WALL_HEIGHT + TUCK)
        cn.setP(180)
        cn.setTexture(self._ceil_tex)
        cn.setTwoSided(True)
        self._scene_nodes.append(cn)

        # 4 walls — extend height past floor/ceiling, extend width past corners
        walls = [
            ("north", (0, hd, WALL_HEIGHT / 2), 0, ROOM_WIDTH + TUCK * 2),
            ("south", (0, -hd, WALL_HEIGHT / 2), 180, ROOM_WIDTH + TUCK * 2),
            ("east",  (hw, 0, WALL_HEIGHT / 2), -90, ROOM_DEPTH + TUCK * 2),
            ("west",  (-hw, 0, WALL_HEIGHT / 2), 90, ROOM_DEPTH + TUCK * 2),
        ]
        for name, pos, h, length in walls:
            tucked_height = WALL_HEIGHT + TUCK * 2
            w_tile = length / tucked_height
            wg = make_textured_wall(length, tucked_height, tile_x=w_tile, tile_y=1.0, name=name)
            wn = stage_root.attachNewNode(wg)
            wn.setPos(pos[0], pos[1], WALL_HEIGHT / 2)  # re-center with tucked height
            wn.setH(h)
            wn.setTexture(self._wall_tex)
            wn.setTwoSided(True)
            self._scene_nodes.append(wn)

        # -- Crumbled wall patches (entropy + placement driven) -------------------
        import random as _rnd
        from core.systems.entropy_engine import EntropyEngine
        from core.systems.placement_engine import PlacementEngine

        crumble_rng = _rnd.Random(layout_seed + 999)
        entropy = EntropyEngine()
        placer = PlacementEngine(seed=layout_seed + 999)

        num_crumbles = crumble_rng.randint(3, 7)
        brick_colors = [
            (0.35, 0.32, 0.28), (0.32, 0.30, 0.26), (0.38, 0.35, 0.30),
            (0.30, 0.27, 0.24), (0.33, 0.31, 0.27),
        ]
        dust_color = (0.10, 0.09, 0.07)
        stain_color = (0.07, 0.06, 0.05)

        # Collect physics bodies for Bullet settle
        physics_rubble = []

        # Door exclusion zones
        door_positions = []
        for pl in self._room_layout.doors:
            dwx, dwy, _ = pl.world_pos(ROOM_WIDTH, ROOM_DEPTH)
            door_positions.append((dwx, dwy))

        def _too_close_to_door(px, py, min_dist=2.5):
            for dx, dy in door_positions:
                if math.sqrt((px - dx) ** 2 + (py - dy) ** 2) < min_dist:
                    return True
            return False

        for ci in range(num_crumbles):
            # Pick wall position, avoid doors
            for _attempt in range(10):
                wall_choice = crumble_rng.randint(0, 3)
                if wall_choice == 0:    # north
                    cx, cy = crumble_rng.uniform(-hw + 2, hw - 2), hd - 0.1
                    face_h = 0
                elif wall_choice == 1:  # south
                    cx, cy = crumble_rng.uniform(-hw + 2, hw - 2), -hd + 0.1
                    face_h = 180
                elif wall_choice == 2:  # east
                    cx, cy = hw - 0.1, crumble_rng.uniform(-hd + 2, hd - 2)
                    face_h = -90
                else:                   # west
                    cx, cy = -hw + 0.1, crumble_rng.uniform(-hd + 2, hd - 2)
                    face_h = 90
                if not _too_close_to_door(cx, cy):
                    break
            else:
                continue

            cz = crumble_rng.uniform(0.8, WALL_HEIGHT * 0.65)
            face_rad = math.radians(face_h)
            nx = -math.sin(face_rad)
            ny = math.cos(face_rad)
            tx = abs(ny)
            ty = abs(nx)

            # -- Gaussian attunement: damage "belongs" at mid-wall height --
            # Wide sigma so damage is plausible anywhere, just peaks at sweet spot
            h_norm = cz / WALL_HEIGHT
            damage_weight = max(0.35, entropy.gaussian(h_norm, mu=0.35, sigma=0.45))

            # -- Sigmoid falloff for rubble scatter radius --
            fall_dist = cz
            scatter_weight = entropy.sigmoid_weight(
                entropy.MIDFIELD_DIST - fall_dist * 4.0
            )

            # Scale: 0.6-1.0 range — never vanishingly small
            scale = 0.6 + damage_weight * 0.4
            cone_reach = 0.3 + (1.0 - scatter_weight) * 1.0

            # --- Wall damage: pebble-cluster bricks (intact + partially crumbled) ---
            num_bricks = max(4, int(8 * damage_weight))
            for b in range(num_bricks):
                bw = crumble_rng.uniform(0.15, 0.30) * scale
                bh = crumble_rng.uniform(0.08, 0.16) * scale
                bd = crumble_rng.uniform(0.06, 0.14) * scale
                bc = crumble_rng.choice(brick_colors)
                # Bricks near damage center are more crumbled
                b_scatter = crumble_rng.uniform(0.0, 0.4) * damage_weight
                pebble_count = max(8, int(20 * scale))
                brick = make_pebble_cluster(
                    bw, bh, bd, bc,
                    count=pebble_count,
                    seed=layout_seed + ci * 100 + b,
                    scatter=b_scatter,
                )
                brn = stage_root.attachNewNode(brick)
                bx_off = crumble_rng.uniform(-0.35, 0.35) * scale
                bz_off = crumble_rng.uniform(-0.15, 0.15) * scale
                depth_off = crumble_rng.uniform(-0.04, 0.02) * scale
                brn.setPos(
                    cx + bx_off * tx + nx * depth_off,
                    cy + bx_off * ty + ny * depth_off,
                    cz + bz_off,
                )
                brn.setH(face_h + crumble_rng.uniform(-8, 8))
                self._scene_nodes.append(brn)

            # --- Dust streaks (gravity, always down) ---
            streak_max_h = cz - 0.1
            for s in range(crumble_rng.randint(1, max(2, int(4 * damage_weight)))):
                sw = crumble_rng.uniform(0.02, 0.06) * scale
                sh = crumble_rng.uniform(streak_max_h * 0.3, streak_max_h * 0.8)
                streak = make_box(sw, 0.01, sh, stain_color)
                sn = stage_root.attachNewNode(streak)
                s_off = crumble_rng.uniform(-0.25, 0.25) * scale
                streak_bottom = cz - sh
                sn.setPos(
                    cx + s_off * tx + nx * 0.01,
                    cy + s_off * ty + ny * 0.01,
                    streak_bottom + sh / 2,
                )
                self._scene_nodes.append(sn)

            # --- Floor dust patch (sigmoid-driven spread) ---
            dust_spread = 0.4 + cone_reach * 0.6
            dust_w = crumble_rng.uniform(0.5, 0.8) * dust_spread
            dust_d = crumble_rng.uniform(0.3, 0.5) * dust_spread
            dust_patch = make_box(dust_w, 0.005, dust_d, dust_color)
            dpn = stage_root.attachNewNode(dust_patch)
            dpn.setPos(cx + nx * dust_d * 0.3, cy + ny * dust_d * 0.3, 0.01)
            self._scene_nodes.append(dpn)

            # --- Floor rubble (Bullet physics settle) ---
            rubble_count = max(4, int(8 * damage_weight))
            rubble_bodies = []
            for r in range(rubble_count):
                ps = scale * crumble_rng.uniform(0.5, 1.0)
                rw = crumble_rng.uniform(0.06, 0.14) * ps
                rh = crumble_rng.uniform(0.03, 0.06) * ps
                rd = crumble_rng.uniform(0.06, 0.12) * ps
                rc = crumble_rng.choice(brick_colors)
                rc = (rc[0] * 0.7, rc[1] * 0.7, rc[2] * 0.7)
                # Spawn at damage point with slight outward velocity approximated as offset
                eject = crumble_rng.uniform(0.05, 0.3)
                rubble_bodies.append({
                    "x": cx + nx * eject + crumble_rng.uniform(-0.2, 0.2) * tx,
                    "y": cy + ny * eject + crumble_rng.uniform(-0.2, 0.2) * ty,
                    "z": cz + crumble_rng.uniform(-0.1, 0.1),
                    "w": rw, "h": rh, "d": rd,
                    "color": rc, "mass": 0.05 + ps * 0.1,
                    "pebble_count": max(5, int(10 * ps)),
                    "scatter": crumble_rng.uniform(0.5, 1.0),
                    "seed": layout_seed + ci * 200 + r,
                })
            physics_rubble.extend(rubble_bodies)

            # --- Ceiling cracks if upper wall ---
            if cz > WALL_HEIGHT * 0.5:
                for c in range(crumble_rng.randint(2, 4)):
                    cl = crumble_rng.uniform(0.3, 0.8) * damage_weight
                    crack = make_box(0.025, 0.005, cl, stain_color)
                    ccn = stage_root.attachNewNode(crack)
                    angle = crumble_rng.uniform(-40, 40)
                    ccn.setPos(
                        cx + nx * cl * 0.4 + crumble_rng.uniform(-0.15, 0.15),
                        cy + ny * cl * 0.4 + crumble_rng.uniform(-0.15, 0.15),
                        WALL_HEIGHT - 0.01,
                    )
                    ccn.setH(face_h + angle)
                    self._scene_nodes.append(ccn)

        # -- Bullet physics settle: drop all rubble bodies, read resting positions
        if physics_rubble:
            settled = self._physics_settle(stage_root, physics_rubble)
            for s in settled:
                peb = make_pebble_cluster(
                    s["w"], s["h_size"], s["d"], s["color"],
                    count=s["pebble_count"], seed=s["seed"],
                    scatter=s["scatter"],
                )
                rbn = stage_root.attachNewNode(peb)
                rbn.setPos(s["x"], s["y"], s["z"])
                rbn.setHpr(s["h"], s["p"], s["r"])
                self._scene_nodes.append(rbn)

        # -- Doors (scattered by RoomLayout) -----------------------------------
        correct = self._campaign.scene._correct
        self._door_pivots = []
        self._door_labels = []
        self._door_animator.reset()

        for placement in self._room_layout.doors:
            i = placement.door_index
            wx, wy, wz = placement.world_pos(ROOM_WIDTH, ROOM_DEPTH)

            # Pivot at hinge edge — door swings from here
            pivot = stage_root.attachNewNode(f"door_pivot_{i}")
            hx, hy = placement.hinge_offset()
            pivot.setPos(wx + hx, wy + hy, 0)
            pivot.setH(placement.facing_h)
            self._door_pivots.append(pivot)

            # Door panel — flat textured quad on pivot (swings on E)
            door_geom = make_textured_quad(DOOR_WIDTH, DOOR_HEIGHT, name=f"door_{i}")
            door_np = pivot.attachNewNode(door_geom)
            door_np.setPos(DOOR_WIDTH / 2, 0, DOOR_HEIGHT / 2)
            door_np.setTexture(self._door_tex)
            door_np.setTwoSided(True)

            # Register with interaction engine
            self._interaction.register(
                pivot, "door",
                {"index": i, "placement": placement}
            )

            # Door number label — anchored to actual rendered door center
            tn = TextNode(f"door_num_{i}")
            tn.setText(str(i + 1))
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(0.6, 0.5, 0.4, 0.8)
            label = stage_root.attachNewNode(tn)
            # Get the door panel's actual world-space center from the scene graph
            door_center = door_np.getPos(stage_root)
            label.setPos(door_center.getX(), door_center.getY(), DOOR_HEIGHT + 0.3)
            label.setScale(0.30)
            label.setBillboardPointEye()
            self._door_labels.append(label)

            # Correct door embellishment — subtle warm light only
            if i == correct:
                hint_light = PointLight(f"hint_{i}")
                lc = pal["sconce"]
                hint_light.setColor(Vec4(lc[0] * 0.4, lc[1] * 0.4, lc[2] * 0.3, 1))
                hint_light.setAttenuation((1.0, 0.3, 0.1))
                hln = stage_root.attachNewNode(hint_light)
                hln.setPos(door_center.getX(), door_center.getY(), DOOR_HEIGHT + 0.5)
                self.render.setLight(hln)
                self._scene_nodes.append(hln)

        # -- Weathering pass (age the room — edges, seams, door frames) ---------
        self._build_weathering(stage_root, pal, layout_seed)

        # -- Rats (foreground parallax makes them scurry) ----------------------
        fg_root = self._layer_roots["foreground"]
        import random
        rng = random.Random(layout_seed)
        depth = self._campaign.corridor
        for _ in range(5 + depth):  # more rats as you go deeper
            x = rng.uniform(-hw + 2, hw - 2)
            y = rng.uniform(-hd + 2, hd - 2)
            facing = rng.uniform(0, 360)

            # Unique variant per rat
            scale = rng.uniform(0.7, 1.3)
            body_len = rng.uniform(0.15, 0.25) * scale
            body_w = body_len * rng.uniform(0.35, 0.5)
            body_h = body_len * rng.uniform(0.25, 0.35)
            fur_shade = rng.uniform(-0.02, 0.02)
            fur = (0.08 + fur_shade, 0.06 + fur_shade, 0.05 + fur_shade)
            belly = (fur[0] + 0.02, fur[1] + 0.02, fur[2] + 0.01)

            rat_root = fg_root.attachNewNode(f"rat_{_}")
            rat_root.setPos(x, y, 0)
            rat_root.setH(facing)

            # make_box(w=X, h=Z-up, d=Y-depth)

            # Haunches (rear, slightly wider)
            haunch_w = body_w * 1.15
            haunch_len = body_len * 0.45
            haunch = make_box(haunch_w, body_h * 0.95, haunch_len, fur)
            hcn = rat_root.attachNewNode(haunch)
            hcn.setPos(0, -body_len * 0.2, body_h * 0.48)

            # Torso (main body, tapers forward)
            body_geo = make_box(body_w, body_h, body_len * 0.5, fur)
            bn = rat_root.attachNewNode(body_geo)
            bn.setPos(0, body_len * 0.1, body_h * 0.5)

            # Chest (narrower, forward)
            chest_w = body_w * 0.85
            chest = make_box(chest_w, body_h * 0.9, body_len * 0.3, fur)
            cn = rat_root.attachNewNode(chest)
            cn.setPos(0, body_len * 0.38, body_h * 0.48)

            # Belly (slight bulge underneath)
            belly_geo = make_box(body_w * 0.7, body_h * 0.3, body_len * 0.4, belly)
            bln = rat_root.attachNewNode(belly_geo)
            bln.setPos(0, 0, body_h * 0.15)

            # Head
            head_size = body_h * rng.uniform(0.7, 0.9)
            head = make_box(head_size * 1.1, head_size, head_size * 1.2, fur)
            hn = rat_root.attachNewNode(head)
            hn.setPos(0, body_len * 0.55, body_h * 0.55)

            # Snout (longer, tapered)
            snout = make_box(head_size * 0.45, head_size * 0.35, head_size * 0.7, belly)
            sn = rat_root.attachNewNode(snout)
            sn.setPos(0, body_len * 0.55 + head_size * 0.75, body_h * 0.45)

            # Nose tip — fleshy pink
            nose = make_box(head_size * 0.22, head_size * 0.18, head_size * 0.18, (0.22, 0.12, 0.12))
            nn = rat_root.attachNewNode(nose)
            nn.setPos(0, body_len * 0.55 + head_size * 1.1, body_h * 0.44)

            # Eyes — black ovals, slightly protruding from head sides
            eye_w = head_size * 0.18  # wider than tall = oval
            eye_h = head_size * 0.12
            eye_d = head_size * 0.1
            for ex in [-head_size * 0.42, head_size * 0.42]:
                eye = make_box(eye_w, eye_h, eye_d, (0.01, 0.01, 0.01))
                eyn = rat_root.attachNewNode(eye)
                eyn.setPos(ex, body_len * 0.55 + head_size * 0.4, body_h * 0.62)
                # Tiny white glint
                glint = make_box(eye_w * 0.3, eye_h * 0.3, eye_d * 0.5, (0.6, 0.6, 0.6))
                gn = rat_root.attachNewNode(glint)
                gn.setPos(ex + eye_w * 0.15, body_len * 0.55 + head_size * 0.42, body_h * 0.65)

            # Ears (two small boxes on head)
            ear_size = head_size * rng.uniform(0.3, 0.5)
            for ex in [-head_size * 0.38, head_size * 0.38]:
                ear = make_box(ear_size, ear_size * 0.7, ear_size * 0.3, (0.12, 0.08, 0.07))
                en = rat_root.attachNewNode(ear)
                en.setPos(ex, body_len * 0.52, body_h * 0.55 + head_size * 0.5)

            # Legs (4 stubby legs)
            leg_w = body_w * 0.2
            leg_h = body_h * 0.45
            leg_d = leg_w * 1.2
            leg_color = (fur[0] * 0.85, fur[1] * 0.85, fur[2] * 0.85)
            leg_positions = [
                (-body_w * 0.35, body_len * 0.25, 0),   # front-left
                (body_w * 0.35, body_len * 0.25, 0),     # front-right
                (-haunch_w * 0.35, -body_len * 0.25, 0),  # rear-left
                (haunch_w * 0.35, -body_len * 0.25, 0),   # rear-right
            ]
            for lx, ly, lz in leg_positions:
                leg = make_box(leg_w, leg_h, leg_d, leg_color)
                ln = rat_root.attachNewNode(leg)
                ln.setPos(lx, ly, leg_h * 0.5)

            # Paws (tiny, at leg bottoms)
            paw_color = (belly[0] * 0.9, belly[1] * 0.9, belly[2] * 0.9)
            for lx, ly, lz in leg_positions:
                paw = make_box(leg_w * 1.3, leg_w * 0.4, leg_d * 1.2, paw_color)
                pn = rat_root.attachNewNode(paw)
                pn.setPos(lx, ly + leg_d * 0.15, leg_w * 0.2)

            # Tail — chain of segments, unique length, curves
            tail_segs = rng.randint(6, 12)
            tail_thick = body_h * 0.15
            seg_len = body_len * rng.uniform(0.1, 0.15)
            tail_color = (0.13, 0.10, 0.09)
            curve_x = rng.uniform(-0.3, 0.3)  # unique lateral curve
            for t in range(tail_segs):
                taper = 1.0 - (t / tail_segs) * 0.7
                seg = make_box(
                    tail_thick * taper, tail_thick * taper,
                    seg_len * (1.0 - t * 0.02), tail_color
                )
                tn = rat_root.attachNewNode(seg)
                ty = -body_len * 0.45 - seg_len * t
                tz = body_h * 0.3 + t * 0.015
                tx = curve_x * t * seg_len  # lateral drift
                tn.setPos(tx, ty, tz)

            self._scene_nodes.append(rat_root)

    # -- Weathering pass -------------------------------------------------------

    def _build_weathering(self, stage_root, pal, seed):
        """Age the room: pebble-cluster trim along every edge and seam."""
        from core.systems.placement_engine import PlacementEngine
        from core.systems.entropy_engine import EntropyEngine
        from core.systems.curves import apply_scale, normalize

        w_amount = pal.get("weathering", 0.5)
        if w_amount <= 0:
            return

        rng = __import__("random").Random(seed + 7777)
        placer = PlacementEngine(seed=seed + 7777)
        entropy = EntropyEngine()
        hw, hd = ROOM_WIDTH / 2, ROOM_DEPTH / 2

        # Curve-driven base sizes: enclosure scale maps weathering to spawn params
        w_params = apply_scale("enclosure", w_amount)
        # weight scale maps weathering to impact
        w_impact = apply_scale("weight", w_amount)

        # Palette-matched stone colors (dark, muted)
        edge_colors = [
            (0.18, 0.16, 0.14), (0.15, 0.13, 0.12), (0.20, 0.18, 0.15),
            (0.12, 0.11, 0.10), (0.16, 0.15, 0.13),
        ]
        # Darker grout/mortar debris
        grout_color = (0.08, 0.07, 0.06)

        # -- Wall base trim: accumulated debris strip along floor-wall junction --
        # Base cluster size from impact curve (higher weathering = bigger debris)
        base_size = 0.15 + w_impact["impact_rating"] / 10.0 * 0.45  # 0.15-0.60

        walls = [
            (0, -hd + 0.1, ROOM_WIDTH, 0),      # south
            (0, hd - 0.1, ROOM_WIDTH, 180),      # north
            (-hw + 0.1, 0, ROOM_DEPTH, 90),      # west
            (hw - 0.1, 0, ROOM_DEPTH, -90),      # east
        ]
        clusters_per_wall = max(6, int(16 * w_amount))
        for wall_cx, wall_cy, wall_len, wh in walls:
            pts = placer.golden_spiral(
                clusters_per_wall * 2, wall_len / 2 * 0.85,
                wall_cx, wall_cy, phase=wh,
            )
            placed = 0
            for px, py in pts:
                if placed >= clusters_per_wall:
                    break
                if abs(px) > hw - 0.15 or abs(py) > hd - 0.15:
                    continue
                if wh == 0 or wh == 180:
                    py = wall_cy
                else:
                    px = wall_cx

                # Gaussian: clusters near corners are bigger (debris accumulates)
                dist_to_nearest_corner = min(
                    math.sqrt((px - cx) ** 2 + (py - cy) ** 2)
                    for cx, cy in [(-hw, -hd), (-hw, hd), (hw, -hd), (hw, hd)]
                )
                corner_weight = entropy.gaussian(dist_to_nearest_corner, mu=0.0, sigma=6.0)
                local_size = base_size * (0.6 + corner_weight * 0.8)

                clr = rng.choice(edge_colors)
                peb = make_pebble_cluster(
                    local_size * rng.uniform(1.5, 2.5),
                    local_size * rng.uniform(0.5, 0.9),
                    local_size * rng.uniform(1.0, 1.8),
                    clr,
                    count=max(10, int(20 * w_amount)),
                    seed=seed + placed + wh,
                    scatter=rng.uniform(0.08, 0.25),
                )
                pn = stage_root.attachNewNode(peb)
                pn.setPos(px, py, local_size * 0.3)
                pn.setH(wh + rng.uniform(-10, 10))
                self._scene_nodes.append(pn)
                placed += 1

        # -- Corner accumulation: biggest debris piles at room corners --
        # Corners get the highest impact — debris collects where walls meet
        corner_size = base_size * 1.5
        corners = [
            (-hw + 0.3, -hd + 0.3), (-hw + 0.3, hd - 0.3),
            (hw - 0.3, -hd + 0.3), (hw - 0.3, hd - 0.3),
        ]
        for ci_c, (ccx, ccy) in enumerate(corners):
            pile_count = max(3, int(6 * w_amount))
            for p in range(pile_count):
                clr = rng.choice(edge_colors)
                ps = corner_size * rng.uniform(0.7, 1.3)
                pile = make_pebble_cluster(
                    ps * 2.0, ps * 0.8, ps * 2.0, clr,
                    count=max(12, int(24 * w_amount)),
                    seed=seed + ci_c * 50 + p,
                    scatter=rng.uniform(0.1, 0.3),
                )
                pn = stage_root.attachNewNode(pile)
                pn.setPos(
                    ccx + rng.uniform(-0.2, 0.2),
                    ccy + rng.uniform(-0.2, 0.2),
                    ps * 0.3,
                )
                pn.setH(rng.uniform(0, 360))
                self._scene_nodes.append(pn)

        # -- Door frame weathering: crumbling stone edges around openings --
        # Sigmoid weight: lower parts of frame more weathered than top
        if self._room_layout:
            for pl in self._room_layout.doors:
                dwx, dwy, _ = pl.world_pos(ROOM_WIDTH, ROOM_DEPTH)
                frame_pts = [
                    (dwx - DOOR_WIDTH * 0.45, dwy, DOOR_HEIGHT * 0.15, 0.0),
                    (dwx - DOOR_WIDTH * 0.45, dwy, DOOR_HEIGHT * 0.45, 0.4),
                    (dwx - DOOR_WIDTH * 0.45, dwy, DOOR_HEIGHT * 0.75, 0.7),
                    (dwx + DOOR_WIDTH * 0.45, dwy, DOOR_HEIGHT * 0.15, 0.0),
                    (dwx + DOOR_WIDTH * 0.45, dwy, DOOR_HEIGHT * 0.45, 0.4),
                    (dwx + DOOR_WIDTH * 0.45, dwy, DOOR_HEIGHT * 0.75, 0.7),
                    (dwx, dwy, DOOR_HEIGHT - 0.05, 0.9),  # lintel
                    (dwx - DOOR_WIDTH * 0.3, dwy, 0.05, 0.0),   # threshold
                    (dwx + DOOR_WIDTH * 0.3, dwy, 0.05, 0.0),
                ]
                for fi, (fx, fy, fz, h_norm) in enumerate(frame_pts):
                    # Lower frame = more weathered, sigmoid drives it
                    height_weight = entropy.sigmoid_weight(
                        entropy.MIDFIELD_DIST - h_norm * 20.0
                    )
                    local_sz = base_size * (0.5 + height_weight * 0.8)
                    clr = rng.choice(edge_colors)
                    frame_peb = make_pebble_cluster(
                        local_sz * 1.8, local_sz * 1.2, local_sz * 0.8, clr,
                        count=max(8, int(16 * w_amount)),
                        seed=seed + pl.door_index * 30 + fi,
                        scatter=rng.uniform(0.05, 0.2),
                    )
                    fn = stage_root.attachNewNode(frame_peb)
                    fn.setPos(fx, fy, fz)
                    fn.setH(pl.facing_h)
                    self._scene_nodes.append(fn)

        # -- Ceiling-wall junction: crumbling mortar line --
        ceil_count = max(6, int(12 * w_amount))
        ceil_pts = placer.golden_spiral(
            ceil_count * 3, max(hw, hd) * 0.85, 0, 0, phase=42.0,
        )
        placed = 0
        for px, py in ceil_pts:
            if placed >= ceil_count:
                break
            dists = [
                (abs(px - hw), hw - 0.08, py, -90),
                (abs(px + hw), -hw + 0.08, py, 90),
                (abs(py - hd), px, hd - 0.08, 0),
                (abs(py + hd), px, -hd + 0.08, 180),
            ]
            dists.sort(key=lambda d: d[0])
            _, snap_x, snap_y, snap_h = dists[0]
            if abs(snap_x) > hw or abs(snap_y) > hd:
                continue
            clr = grout_color
            cw = rng.uniform(0.2, 0.4) * w_amount
            ch = rng.uniform(0.06, 0.12) * w_amount
            cd = rng.uniform(0.1, 0.2) * w_amount
            ceil_peb = make_pebble_cluster(
                cw, ch, cd, clr,
                count=max(6, int(10 * w_amount)),
                seed=seed + 9000 + placed,
                scatter=rng.uniform(0.05, 0.15),
            )
            cn = stage_root.attachNewNode(ceil_peb)
            cn.setPos(snap_x, snap_y, WALL_HEIGHT - ch * 0.5)
            cn.setH(snap_h)
            self._scene_nodes.append(cn)
            placed += 1

    # -- Physics settle (Bullet) -----------------------------------------------

    def _physics_settle(self, stage_root, bodies, steps=120):
        """
        Drop rigid bodies into a room-shaped physics world.
        Returns list of (pos, hpr, size, color) for final resting positions.
        Bodies: list of dicts {x, y, z, w, h, d, color, mass}
        """
        world = BulletWorld()
        world.setGravity(Vec3(0, 0, -9.81))

        hw, hd_room = ROOM_WIDTH / 2, ROOM_DEPTH / 2

        # Floor plane (z=0, normal up)
        floor_shape = BulletPlaneShape(Vec3(0, 0, 1), 0)
        floor_node = BulletRigidBodyNode("floor")
        floor_node.addShape(floor_shape)
        floor_np = NodePath(floor_node)
        world.attachRigidBody(floor_node)

        # 4 walls
        for normal, offset in [
            (Vec3(0, 1, 0), -hd_room),   # south wall
            (Vec3(0, -1, 0), -hd_room),   # north wall
            (Vec3(1, 0, 0), -hw),          # west wall
            (Vec3(-1, 0, 0), -hw),         # east wall
        ]:
            wall_shape = BulletPlaneShape(normal, offset)
            wall_node = BulletRigidBodyNode(f"wall_{normal}")
            wall_node.addShape(wall_shape)
            NodePath(wall_node)
            world.attachRigidBody(wall_node)

        # Spawn rigid bodies
        body_nps = []
        for b in bodies:
            shape = BulletBoxShape(Vec3(b["w"] / 2, b["d"] / 2, b["h"] / 2))
            rb = BulletRigidBodyNode(f"debris")
            rb.setMass(b.get("mass", 0.1))
            rb.addShape(shape)
            rb.setFriction(0.8)
            rb.setRestitution(0.15)  # low bounce — stone on stone
            rb_np = NodePath(rb)
            rb_np.setPos(b["x"], b["y"], b["z"])
            # Slight random initial rotation for natural tumble
            rb_np.setHpr(
                __import__("random").uniform(0, 360),
                __import__("random").uniform(-15, 15),
                __import__("random").uniform(-15, 15),
            )
            world.attachRigidBody(rb)
            body_nps.append((rb_np, rb, b))

        # Run simulation
        dt = 1.0 / 60.0
        for _ in range(steps):
            world.doPhysics(dt)

        # Read final positions
        results = []
        for rb_np, rb, b in body_nps:
            pos = rb_np.getPos()
            hpr = rb_np.getHpr()
            results.append({
                "x": pos.getX(), "y": pos.getY(), "z": max(0, pos.getZ()),
                "h": hpr.getX(), "p": hpr.getY(), "r": hpr.getZ(),
                "w": b["w"], "h_size": b["h"], "d": b["d"],
                "color": b["color"],
                "pebble_count": b.get("pebble_count", 12),
                "scatter": b.get("scatter", 0.0),
                "seed": b.get("seed", 0),
            })
            world.removeRigidBody(rb)

        return results

    # -- Post-processing -------------------------------------------------------

    def _setup_postprocess(self):
        """Wire up post-processing: CommonFilters bloom + CPU-side color grading."""
        try:
            from direct.filter.CommonFilters import CommonFilters
            self._filters = CommonFilters(self.win, self.cam)
            pal = self._scene.palette
            bloom_int = pal.get("bloom_intensity", 0.3)
            self._filters.setBloom(
                blend=(0.3, 0.4, 0.3, 0.0),
                mintrigger=0.6, maxtrigger=1.0,
                desat=0.6, intensity=bloom_int, size="medium",
            )
            self._bloom_on = True
            console.log(
                f"[green]Post-processing:[/green] bloom={bloom_int:.1f} "
                f"depth-tint ON  warmth={pal.get('warmth', 0):.2f} "
                f"film-curves=CPU-side"
            )
        except Exception as e:
            console.log(f"[yellow]Post-processing unavailable:[/yellow] {e}")
            self._bloom_on = False

    # -- RPG HUD ---------------------------------------------------------------

    def _build_hud(self):
        """Build persistent HUD elements (updated in-place, not rebuilt)."""
        # -- Crosshair --
        self._hud_crosshair = OnscreenText(
            text="+", pos=(0, 0), scale=0.05,
            fg=(0.8, 0.8, 0.8, 0.4), align=TextNode.ACenter,
        )

        # -- Top-left: Floor + Tier --
        self._hud_floor_bg = OnscreenImage(
            image="assets/sprites/textures/pixel_white.png",
            pos=(-1.25, 0, 0.92), scale=(0.35, 1, 0.045),
        )
        self._hud_floor_bg.setTransparency(TransparencyAttrib.MAlpha)
        self._hud_floor_bg.setColor(0, 0, 0, 0.5)

        self._hud_floor_text = OnscreenText(
            text="B0F  VISUAL", pos=(-1.45, 0.905), scale=0.045,
            fg=(0.9, 0.8, 0.6, 1), align=TextNode.ALeft,
        )

        # -- Top-right: Attempt gauge --
        self._hud_gauge_bg = OnscreenImage(
            image="assets/sprites/textures/pixel_white.png",
            pos=(1.25, 0, 0.92), scale=(0.3, 1, 0.025),
        )
        self._hud_gauge_bg.setTransparency(TransparencyAttrib.MAlpha)
        self._hud_gauge_bg.setColor(0.15, 0.12, 0.1, 0.6)

        self._hud_gauge_fill = OnscreenImage(
            image="assets/sprites/textures/pixel_white.png",
            pos=(1.25, 0, 0.92), scale=(0.3, 1, 0.025),
        )
        self._hud_gauge_fill.setTransparency(TransparencyAttrib.MAlpha)
        self._hud_gauge_fill.setColor(0.8, 0.55, 0.2, 0.8)

        self._hud_gauge_label = OnscreenText(
            text="7/7", pos=(1.55, 0.905), scale=0.035,
            fg=(0.7, 0.6, 0.5, 0.8), align=TextNode.ARight,
        )

        # -- Top-center: Deepest --
        self._hud_deepest = OnscreenText(
            text="", pos=(0, 0.93), scale=0.035,
            fg=(0.5, 0.45, 0.4, 0.6), align=TextNode.ACenter,
        )

        # -- Bottom-center: Interaction prompt --
        self._hud_prompt_bg = OnscreenImage(
            image="assets/sprites/textures/pixel_white.png",
            pos=(0, 0, -0.85), scale=(0.5, 1, 0.035),
        )
        self._hud_prompt_bg.setTransparency(TransparencyAttrib.MAlpha)
        self._hud_prompt_bg.setColor(0, 0, 0, 0.5)
        self._hud_prompt_bg.hide()

        self._hud_prompt_text = OnscreenText(
            text="", pos=(0, -0.865), scale=0.04,
            fg=(0.9, 0.85, 0.7, 1), align=TextNode.ACenter,
        )

        # -- Message overlay (center screen, for events) --
        self._hud_message_bg = OnscreenImage(
            image="assets/sprites/textures/pixel_white.png",
            pos=(0, 0, 0.6), scale=(0.7, 1, 0.04),
        )
        self._hud_message_bg.setTransparency(TransparencyAttrib.MAlpha)
        self._hud_message_bg.setColor(0, 0, 0, 0.6)
        self._hud_message_bg.hide()

        self._hud_message_text = OnscreenText(
            text="", pos=(0, 0.585), scale=0.042,
            fg=(1.0, 0.9, 0.7, 1), align=TextNode.ACenter,
        )
        self._message_timer = 0.0

    def _update_hud(self):
        """Update HUD values in place."""
        r = self._campaign.report()
        tier_names = {1: "VISUAL", 2: "SPATIAL", 3: "TEMPORAL", 4: "BEHAVIORAL"}
        tier = tier_names.get(r['tier'], f"TIER {r['tier']}")

        self._hud_floor_text.setText(f"B{r['corridor']}F  {tier}")

        # Attempt gauge
        fill = r['attempts'] / 7.0
        self._hud_gauge_fill.setScale(0.3 * fill, 1, 0.025)
        # Shift gauge fill position to keep it left-aligned
        base_x = 1.25 - 0.3
        self._hud_gauge_fill.setPos(base_x + 0.3 * fill, 0, 0.92)
        self._hud_gauge_label.setText(f"{r['attempts']}/7")

        # Color gauge by urgency
        if r['attempts'] >= 5:
            self._hud_gauge_fill.setColor(0.8, 0.55, 0.2, 0.8)
        elif r['attempts'] >= 3:
            self._hud_gauge_fill.setColor(0.8, 0.4, 0.1, 0.8)
        else:
            self._hud_gauge_fill.setColor(0.8, 0.2, 0.1, 0.9)

        # Deepest
        if r['deepest'] > 0:
            self._hud_deepest.setText(f"Deepest: B{r['deepest']}F")

        # Interaction prompt
        nearest = self._interaction.nearest("door")
        if nearest and not self._pending_advance:
            idx = nearest["obj"]["index"]
            self._hud_prompt_text.setText(f"[E]  Door {idx + 1}")
            self._hud_prompt_bg.show()
        else:
            detectable = self._interaction.all_detectable("door")
            if detectable and not self._pending_advance:
                # Show nearest detectable door info
                closest = detectable[0]
                idx = closest["obj"]["index"]
                self._hud_prompt_text.setText(f"Door {idx + 1}")
                self._hud_prompt_bg.show()
            else:
                self._hud_prompt_text.setText("")
                self._hud_prompt_bg.hide()

    def _show_message(self, text, duration=3.0):
        self._hud_message_text.setText(text)
        self._hud_message_bg.show()
        self._message_timer = duration

    # -- Register switching ----------------------------------------------------

    def _apply_register(self):
        pal = self._scene.palette

        # Ambient — warm-shifted by register warmth param
        w = pal.get("warmth", 0.0)
        amb_r = 0.03 + w * 0.01
        amb_b = 0.02 - w * 0.005
        self._amb_np.node().setColor(Vec4(amb_r, 0.025, amb_b, 1))

        # Sconces — base color stored for flicker to multiply
        lc = pal["sconce"]
        self._sconce_base = (lc[0] * 1.4, lc[1] * 1.2, lc[2] * 0.7)
        for sn in self._sconce_nps:
            sn.node().setColor(Vec4(self._sconce_base[0], self._sconce_base[1], self._sconce_base[2], 1))

        # Fog — warm-shifted
        fc = pal["fog"]
        self._fog.setColor(Vec4(fc[0] + w * 0.01, fc[1], fc[2] - w * 0.005, 1))

        bg = pal["backdrop"]
        self.setBackgroundColor(bg[0], bg[1], bg[2], 1)

        # Depth color shift — tint far layers toward blue/desaturated
        dt_far = pal.get("depth_tint_far", (1, 1, 1))
        dt_mid = pal.get("depth_tint_mid", (1, 1, 1))
        if "backdrop" in self._layer_roots:
            self._layer_roots["backdrop"].setColorScale(dt_far[0], dt_far[1], dt_far[2], 1.0)
        if "midground" in self._layer_roots:
            self._layer_roots["midground"].setColorScale(dt_mid[0], dt_mid[1], dt_mid[2], 1.0)

        # Bloom intensity per register
        if self._filters and self._bloom_on:
            bloom_int = pal.get("bloom_intensity", 0.3)
            try:
                self._filters.setBloom(
                    blend=(0.3, 0.4, 0.3, 0.0),
                    mintrigger=0.6, maxtrigger=1.0,
                    desat=0.6, intensity=bloom_int, size="medium",
                )
            except (IndexError, AttributeError):
                pass  # CommonFilters not fully initialized yet

    def _apply_depth_atmosphere(self):
        pal = self._scene.palette
        depth = self._campaign.corridor
        base_near = 15.0 - min(depth * 0.5, 8.0)
        base_far = 50.0 - min(depth * 1.0, 20.0)
        self._fog.setLinearRange(max(5.0, base_near), max(15.0, base_far))
        # Deeper = darker ambient
        dim = max(0.3, 1.0 - depth * 0.03)
        self._amb_np.node().setColor(Vec4(0.03 * dim, 0.025 * dim, 0.02 * dim, 1))
        # Deeper = warmer sconces (store as base for flicker to multiply)
        lc = pal["sconce"]
        warm = 1.0 + min(depth * 0.02, 0.3)
        self._sconce_base = (lc[0] * 1.4 * warm, lc[1] * 1.2 * warm * 0.95, lc[2] * 0.7 * warm * 0.85)

    def _cycle_register(self, index):
        self._register_index = index % len(REGISTERS)
        reg = REGISTERS[self._register_index]
        self._scene.set_register(reg)
        self._apply_register()
        self._build_room()
        self._setup_interaction()
        self._register_doors()
        self._show_message(f"Register: {reg.upper()}", 2.0)
        console.log(f"[bold magenta]REGISTER[/bold magenta]  {reg}")

    def _toggle_fullscreen(self):
        wp = WindowProperties()
        wp.setFullscreen(not self.win.getProperties().getFullscreen())
        self.win.requestProperties(wp)
        # Recenter mouse after resize
        self.taskMgr.doMethodLater(0.1, lambda t: self._center_mouse(), "recenter")

    def _toggle_bloom(self):
        self._bloom_on = not self._bloom_on
        if self._filters:
            if self._bloom_on:
                pal = self._scene.palette
                self._filters.setBloom(
                    blend=(0.3, 0.4, 0.3, 0.0),
                    mintrigger=0.6, maxtrigger=1.0,
                    desat=0.6, intensity=pal.get("bloom_intensity", 0.3),
                    size="medium",
                )
            else:
                self._filters.delBloom()
        self._show_message(f"Bloom: {'ON' if self._bloom_on else 'OFF'}", 1.5)

    # -- Debug telemetry -------------------------------------------------------

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
            self._show_message("Debug ON — ` toggle, F5 dump", 2.0)
            console.log("[bold green]DEBUG MODE ON[/bold green]  overlay + command channel active")
        else:
            if self._debug_hud_text:
                self._debug_hud_text.hide()
            self._show_message("Debug OFF", 1.0)
            console.log("[dim]DEBUG MODE OFF[/dim]")

    def _calc_probe(self):
        """Raycast from camera center — what is the crosshair pointing at?"""
        h_rad = math.radians(self._cam_h)
        p_rad = math.radians(self._cam_p)
        cos_p = math.cos(p_rad)
        dx = -math.sin(h_rad) * cos_p
        dy = math.cos(h_rad) * cos_p
        dz = math.sin(p_rad)

        cx, cy, cz = self.cam.getX(), self.cam.getY(), self.cam.getZ()
        hw, hd = ROOM_WIDTH / 2, ROOM_DEPTH / 2

        hits = []
        # North wall (y = hd)
        if dy > 0.001:
            t = (hd - cy) / dy
            hx, hz = cx + dx * t, cz + dz * t
            if -hw <= hx <= hw and 0 <= hz <= WALL_HEIGHT:
                hits.append(("north_wall", t, (hx, hd, hz)))
        # South wall (y = -hd)
        if dy < -0.001:
            t = (-hd - cy) / dy
            hx, hz = cx + dx * t, cz + dz * t
            if -hw <= hx <= hw and 0 <= hz <= WALL_HEIGHT:
                hits.append(("south_wall", t, (hx, -hd, hz)))
        # East wall (x = hw)
        if dx > 0.001:
            t = (hw - cx) / dx
            hy, hz = cy + dy * t, cz + dz * t
            if -hd <= hy <= hd and 0 <= hz <= WALL_HEIGHT:
                hits.append(("east_wall", t, (hw, hy, hz)))
        # West wall (x = -hw)
        if dx < -0.001:
            t = (-hw - cx) / dx
            hy, hz = cy + dy * t, cz + dz * t
            if -hd <= hy <= hd and 0 <= hz <= WALL_HEIGHT:
                hits.append(("west_wall", t, (-hw, hy, hz)))
        # Floor (z = 0)
        if dz < -0.001:
            t = -cz / dz
            hx, hy = cx + dx * t, cy + dy * t
            if -hw <= hx <= hw and -hd <= hy <= hd:
                hits.append(("floor", t, (hx, hy, 0.0)))
        # Ceiling (z = WALL_HEIGHT)
        if dz > 0.001:
            t = (WALL_HEIGHT - cz) / dz
            hx, hy = cx + dx * t, cy + dy * t
            if -hw <= hx <= hw and -hd <= hy <= hd:
                hits.append(("ceiling", t, (hx, hy, WALL_HEIGHT)))

        # Nearest door within probe range
        nearest_door = None
        if self._room_layout:
            for pl in self._room_layout.doors:
                dwx, dwy, _ = pl.world_pos(ROOM_WIDTH, ROOM_DEPTH)
                dd = math.sqrt((cx - dwx) ** 2 + (cy - dwy) ** 2)
                if dd < DETECT_RADIUS:
                    if nearest_door is None or dd < nearest_door[1]:
                        nearest_door = (pl.door_index, round(dd, 2), pl.wall.name)

        if hits:
            hits.sort(key=lambda h: h[1])
            name, dist, pos = hits[0]
            result = {
                "surface": name,
                "distance": round(dist, 2),
                "hit": [round(p, 2) for p in pos],
            }
        else:
            result = {"surface": "sky", "distance": -1, "hit": [0, 0, 0]}

        if nearest_door:
            result["nearest_door"] = {
                "index": nearest_door[0],
                "distance": nearest_door[1],
                "wall": nearest_door[2],
            }
        return result

    def _get_debug_state(self):
        """Build full debug state dict."""
        pal = self._scene.palette

        # Serialize tags safely — strip internal node refs
        tags_out = []
        for t in self._debug_tags:
            tags_out.append({
                "id": t.get("id"),
                "label": t.get("label", ""),
                "surface": t.get("surface", "?"),
                "distance": t.get("distance"),
                "pos": t.get("pos"),
                "camera": t.get("camera"),
            })

        try:
            tier = self._campaign.scene._tier
        except Exception:
            tier = 0

        return {
            "camera": {
                "x": round(self.cam.getX(), 3),
                "y": round(self.cam.getY(), 3),
                "z": round(self.cam.getZ(), 3),
                "h": round(self._cam_h, 1),
                "p": round(self._cam_p, 1),
            },
            "probe": self._probe_data,
            "tags": tags_out,
            "register": REGISTERS[self._register_index],
            "corridor": self._campaign.corridor,
            "tier": tier,
            "room_size": {"w": ROOM_WIDTH, "d": ROOM_DEPTH, "h": WALL_HEIGHT},
            "palette": {
                k: list(v) if isinstance(v, tuple) else v
                for k, v in pal.items()
            },
            "sconce_base": [round(c, 4) for c in self._sconce_base],
            "bloom_on": self._bloom_on,
        }

    def _dump_debug_state(self):
        """0 key — write full scene state to debug_state.json."""
        import traceback
        try:
            self._probe_data = self._calc_probe()
            state = self._get_debug_state()
            with open(self._state_path, "w") as f:
                json.dump(state, f, indent=2, default=str)
            console.log(
                f"[bold green]STATE DUMPED[/bold green]  {self._state_path}  "
                f"probe={state['probe'].get('surface', '?')} "
                f"d={state['probe'].get('distance', '?')}  "
                f"tags={len(self._debug_tags)}"
            )
        except Exception as e:
            console.log(f"[bold red]STATE DUMP FAILED[/bold red]  {e}")
            traceback.print_exc()

    def _check_debug_commands(self):
        """Read debug_cmd.json if it exists, apply commands, delete file."""
        try:
            with open(self._cmd_path, "r") as f:
                cmds = json.load(f)
            os.remove(self._cmd_path)
        except (FileNotFoundError, json.JSONDecodeError):
            return

        pal = self._scene.palette
        applied = []

        for key, value in cmds.items():
            # Special commands
            if key == "register" and value in REGISTERS:
                idx = REGISTERS.index(value)
                self._cycle_register(idx)
                applied.append(f"register={value}")
                continue
            if key == "teleport" and isinstance(value, list) and len(value) == 3:
                self.cam.setPos(value[0], value[1], value[2])
                applied.append(f"teleport={value}")
                continue
            if key == "fog_near" or key == "fog_far":
                try:
                    if key == "fog_near":
                        self._fog.setLinearRange(float(value), 50.0)
                    else:
                        self._fog.setLinearRange(15.0, float(value))
                    applied.append(f"{key}={value}")
                except Exception:
                    pass
                continue

            # Tag commands
            if key == "tag":
                self._place_tag(label=str(value))
                applied.append(f"tag=\"{value}\"")
                continue
            if key == "clear_tags":
                self._clear_tags()
                applied.append("clear_tags")
                continue

            # Palette params — update live
            if key in pal:
                if isinstance(value, list):
                    pal[key] = tuple(value)
                else:
                    pal[key] = value
                applied.append(f"{key}={value}")

        if applied:
            self._apply_register()
            console.log(f"[bold cyan]DEBUG CMD[/bold cyan]  {', '.join(applied)}")

    def _update_debug_hud(self):
        """Refresh the debug overlay text."""
        if not self._debug_hud_text:
            return
        p = self._probe_data
        cam = self.cam.getPos()
        lines = [
            f"pos=({cam.getX():.1f}, {cam.getY():.1f}, {cam.getZ():.1f}) "
            f"h={self._cam_h:.0f} p={self._cam_p:.0f}",
            f"probe: {p.get('surface', '?')}  d={p.get('distance', '?')}  "
            f"@ {p.get('hit', '?')}",
            f"reg={REGISTERS[self._register_index]}  "
            f"B{self._campaign.corridor}F  "
            f"bloom={'ON' if self._bloom_on else 'OFF'}  "
            f"tags={len(self._debug_tags)}",
        ]
        if "nearest_door" in p:
            nd = p["nearest_door"]
            lines.append(f"door #{nd['index']+1}  d={nd['distance']}  {nd['wall']}")
        self._debug_hud_text.setText("\n".join(lines))

    # -- Scene tags (point-and-annotate) ---------------------------------------

    def _place_tag(self, label=None):
        """T key or debug_cmd — drop a numbered pin at the crosshair probe hit."""
        probe = self._calc_probe()
        if probe.get("distance", -1) < 0:
            return

        self._tag_counter += 1
        tag_id = self._tag_counter
        pos = probe["hit"]
        text = label or f"#{tag_id}"

        # 3D billboard marker
        tn = TextNode(f"tag_{tag_id}")
        tn.setText(text)
        tn.setAlign(TextNode.ACenter)
        tn.setTextColor(1.0, 0.85, 0.2, 0.9)
        tn.setCardColor(0.0, 0.0, 0.0, 0.5)
        tn.setCardAsMargin(0.15, 0.15, 0.08, 0.08)
        tn.setCardDecal(True)
        node = self._layer_roots["stage"].attachNewNode(tn)
        node.setPos(pos[0], pos[1], pos[2] + 0.3)
        node.setScale(0.18)
        node.setBillboardPointEye()

        tag = {
            "id": tag_id,
            "label": text,
            "surface": probe["surface"],
            "distance": probe["distance"],
            "pos": pos,
            "camera": {
                "x": round(self.cam.getX(), 2),
                "y": round(self.cam.getY(), 2),
                "z": round(self.cam.getZ(), 2),
                "h": round(self._cam_h, 1),
                "p": round(self._cam_p, 1),
            },
            "_node": node,  # internal, stripped on dump
        }
        self._debug_tags.append(tag)
        console.log(
            f"[bold yellow]TAG #{tag_id}[/bold yellow]  {probe['surface']}  "
            f"d={probe['distance']}  @ {pos}  \"{text}\""
        )

    def _undo_last_tag(self):
        """Shift+T — remove the most recent tag."""
        if not self._debug_tags:
            return
        tag = self._debug_tags.pop()
        try:
            if tag.get("_node") and not tag["_node"].isEmpty():
                tag["_node"].removeNode()
        except Exception:
            pass
        console.log(f"[dim]Removed tag #{tag['id']}[/dim]")

    def _clear_tags(self):
        """Ctrl+T — remove all tags from scene."""
        for tag in self._debug_tags:
            try:
                if tag.get("_node") and not tag["_node"].isEmpty():
                    tag["_node"].removeNode()
            except Exception:
                pass
        self._debug_tags.clear()
        self._tag_counter = 0
        console.log("[dim]Tags cleared[/dim]")

    # -- Door re-registration after rebuild ------------------------------------

    def _register_doors(self):
        """Re-register doors with interaction engine after room rebuild."""
        for placement in self._room_layout.doors:
            i = placement.door_index
            if i < len(self._door_pivots):
                self._interaction.register(
                    self._door_pivots[i], "door",
                    {"index": i, "placement": placement}
                )

    # -- Door interaction ------------------------------------------------------

    def _examine(self, door_index):
        if self._pending_advance or self._transition_phase:
            return
        result = self._campaign.examine_door(door_index)
        if result["has_detail"]:
            self._show_message(f"Door {door_index + 1}: {result['description']}", 4.0)
            console.log(
                f"[bold green]DETAIL[/bold green]  Door {door_index + 1}: "
                f"{result['description']}  [dim]({result['detail_type']})[/dim]"
            )
        else:
            self._show_message(f"Door {door_index + 1}: A door. Like the others.", 2.0)

    def _interact_nearest(self):
        """E key — try the nearest reachable door."""
        if self._pending_advance or self._transition_phase:
            return

        nearest = self._interaction.nearest("door")
        if not nearest:
            return

        door_index = nearest["obj"]["index"]
        result = self._campaign.try_door(door_index)

        if result.get("advanced"):
            # Door opens — start animation
            self._door_animator.begin_open(door_index)
            self._pending_advance = True
            self._advance_timer = 1.5  # wait for swing + pause

            depth = result["corridor"]
            if depth <= 2:
                flavor = "The portal shimmers. The corridor reforms."
            elif depth <= 5:
                flavor = "Deeper. The walls remember you."
            elif depth <= 10:
                flavor = "The garden folds inward. You've been here before."
            else:
                flavor = "The paths converge. Every door leads here."

            self._show_message(f"Depth {depth} — {flavor}", 3.0)
            console.log(f"[bold green]ADVANCE[/bold green]  Depth {depth}  Tier {result['tier']}")

        elif result.get("reset"):
            self._show_message("The garden shifts. The paths rearrange.", 3.0)
            console.log(f"[bold red]RESET[/bold red]  Corridor reshuffled")
            self._transition_phase = "fade_out"
            self._transition_timer = 0.5
            self._fade_overlay.show()

        else:
            remaining = result['attempts_remaining']
            if remaining >= 5:
                msg = f"Door {door_index + 1} holds firm. {remaining} remain."
            elif remaining >= 3:
                msg = f"Nothing. Look closer. {remaining} left."
            else:
                msg = f"Wrong. {remaining} remain. Choose carefully."
            self._show_message(msg, 2.5)
            console.log(f"[yellow]WRONG[/yellow]  Door {door_index + 1}  {remaining} left")

    def _execute_advance(self):
        """Trigger fade transition to next room."""
        self._transition_phase = "fade_out"
        self._transition_timer = 0.5
        self._fade_overlay.show()
        self._pending_advance = False

    # -- Main loop -------------------------------------------------------------

    def _loop(self, task):
        dt = globalClock.getDt()

        # -- Fade transitions --------------------------------------------------
        if self._transition_phase == "fade_out":
            self._transition_timer -= dt
            alpha = 1.0 - max(0, self._transition_timer / 0.5)
            self._fade_overlay.setColor(0, 0, 0, alpha)
            if self._transition_timer <= 0:
                # Rebuild room
                self._build_room()
                self._setup_interaction()
                self._register_doors()
                self._apply_depth_atmosphere()
                self._reset_camera()
                self._transition_phase = "fade_in"
                self._transition_timer = 0.5
            return task.cont

        if self._transition_phase == "fade_in":
            self._transition_timer -= dt
            alpha = max(0, self._transition_timer / 0.5)
            self._fade_overlay.setColor(0, 0, 0, alpha)
            if self._transition_timer <= 0:
                self._fade_overlay.hide()
                self._transition_phase = None
            return task.cont

        # -- Pending door advance (waiting for swing animation) ----------------
        if self._pending_advance:
            self._advance_timer -= dt
            if self._advance_timer <= 0:
                self._execute_advance()

        # -- Door animation ----------------------------------------------------
        self._door_animator.tick(dt)
        for i, pivot in enumerate(self._door_pivots):
            angle = self._door_animator.get_angle(i)
            if angle > 0:
                # Apply swing rotation relative to the door's base facing
                base_h = pivot.getH()
                # The pivot's H is already set to facing_h
                # We add the swing angle to open it inward
                pivot.setH(self._room_layout.doors[i].facing_h + angle)

        # -- Torch wobble + flicker ------------------------------------------------
        t = globalClock.getFrameTime()
        for idx, tm in enumerate(self._torch_nps):
            base_h = float(tm.getTag("base_h"))
            wobble = 15.0 * math.sin(t * 1.2 + idx * 2.3)
            tm.setH(base_h + wobble)

        # Sconce light flicker — each torch has its own phase, intensity from register
        fi = self._scene.palette.get("flicker_intensity", 0.15)
        sb = self._sconce_base
        for idx, sn in enumerate(self._sconce_nps):
            flicker = 1.0 + fi * math.sin(t * 8.7 + idx * 1.7) * math.sin(t * 13.1 + idx * 3.1)
            sn.node().setColor(Vec4(sb[0] * flicker, sb[1] * flicker, sb[2] * flicker, 1))

        # -- Mouse look --------------------------------------------------------
        if not hasattr(self, '_win_cx'):
            self._center_mouse()
        dx, dy = self._read_mouse()
        if not self._mouse_initialized:
            self._mouse_initialized = True
            dx, dy = 0, 0

        self._cam_h -= dx * MOUSE_SENS
        self._cam_p = max(-PITCH_LIMIT, min(PITCH_LIMIT, self._cam_p - dy * MOUSE_SENS))

        # -- WASD movement -----------------------------------------------------
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
        hw = ROOM_WIDTH / 2 - 0.5
        hd = ROOM_DEPTH / 2 - 0.5
        new_x = max(-hw, min(hw, pos.getX() + move_x))
        new_y = max(-hd, min(hd, pos.getY() + move_y))
        self.cam.setPos(new_x, new_y, pos.getZ())
        self.cam.setHpr(self._cam_h, self._cam_p, 0)

        # -- Interaction engine ------------------------------------------------
        self._interaction.tick()

        # -- Parallax ----------------------------------------------------------
        self._scene.move_camera(new_x, new_y, self._cam_h)
        offsets = self._scene.get_layer_offsets()
        for name, (ox, oy) in offsets.items():
            if name in self._layer_roots:
                root = self._layer_roots[name]
                root.setX(ox)
                if name != "stage":
                    root.setY(root.getY() + oy * 0.01)

        # -- HUD ---------------------------------------------------------------
        self._update_hud()

        # -- Debug telemetry ---------------------------------------------------
        self._check_debug_commands()
        if self._debug_mode:
            self._probe_data = self._calc_probe()
            self._update_debug_hud()

        # -- Message timer -----------------------------------------------------
        if self._message_timer > 0:
            self._message_timer -= dt
            if self._message_timer <= 0:
                self._hud_message_text.setText("")
                self._hud_message_bg.hide()

        return task.cont


if __name__ == "__main__":
    ShadowboxDungeon().run()
