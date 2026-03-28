import sys, math, random
from direct.showbase.ShowBase import ShowBase
from panda3d.core import AmbientLight, AntialiasAttrib, DirectionalLight, Vec4, WindowProperties, LVector3
from rich.console import Console
from core.systems.biome_renderer import _make_box_geom, _make_plane_geom, BIOME_PALETTE
from core.systems.terrain_generator import TerrainGenerator
from core.systems.cavern_builder import CavernBuilder, CAVERN_X, CAVERN_Y

console = Console()
MOUSE_SENSITIVITY = 0.15
PITCH_CLAMP       = 80.0
SNAP_THRESHOLD    = 200
WALK_SPEED        = 10.0
RUN_SPEED         = 30.0
JUMP_VELOCITY     = 18.0
GRAVITY           = 40.0
GROUND_Z          = 6.0

class RoomLab(ShowBase):
    WORLD_W   = 3200
    WORLD_D   = 3200
    SEED      = 42
    DENSITY   = 0.5

    def __init__(self):
        super().__init__()
        props = WindowProperties()
        props.setTitle('Sanctum — World Lab')
        props.setSize(1280, 720)
        self.win.requestProperties(props)
        self.setBackgroundColor(0.55, 0.62, 0.72, 1)  # Desaturated slate sky
        self.cam_yaw      = 0.0
        self.cam_pitch    = 0.0
        self.vel_z        = 0.0
        self.on_ground    = True
        self.mouse_look_active = False
        self._last_mx     = None
        self._last_my     = None
        self.key_map = {
            'w':False,'s':False,'a':False,'d':False,
            'shift':False,'space':False,
        }
        self.disableMouse()
        self.camLens.setFov(80)
        self.camLens.setFar(4000)
        # Start inside cavern facing the mouth (south)
        self.cam.setPos(CAVERN_X, CAVERN_Y + 6, GROUND_Z)
        self.cam.setHpr(180, 0, 0)  # facing south toward mouth
        self.cam.setHpr(0, 0, 0)
        self.setup_lighting()
        self.render.setShaderAuto()
        # Atmospheric fog
        from panda3d.core import Fog
        fog = Fog('atm_fog')
        fog.setColor(0.50, 0.55, 0.62)  # Desaturated fog
        fog.setExpDensity(0.0008)
        self.render.setFog(fog)
        self.render.setAntialias(AntialiasAttrib.MMultisample)
        self.setup_controls()
        self._build_world()
        self.taskMgr.add(self.game_loop, 'GameLoop')
        console.log('[bold green]WORLD LAB[/bold green] — WSAD walk | Shift run | Space jump | Click mouse | Shift+ESC quit')
        self.accept('escape',       self.disable_mouse_look)
        self.accept('shift-escape', self.exit_app)
        self.accept('mouse1',       self.enable_mouse_look)

    # ── World builder ─────────────────────────────────────────────────────

    def _build_world(self):
        rng  = random.Random(self.SEED)
        hw   = self.WORLD_W / 2
        hd   = self.WORLD_D / 2
        pal  = BIOME_PALETTE['VERDANT']
        fc   = pal['floor']
        ac   = pal['accent']
        self._terrain = TerrainGenerator(seed=self.SEED)
        terrain = self._terrain

        # ── Ground planes per sector ──────────────────────────────────────
        # Sector 1 NW — verdant
        self._ground_plane(-hw/2, hd/2, hw, hd, fc)
        # Sector 2 NE — verdant→mountain
        mtn_floor = (0.35, 0.32, 0.28)
        self._ground_blend(-hw/2+hw, hd/2, hw, hd, fc, mtn_floor, rng)
        # Sector 3 SW — verdant→desert
        desert_floor = (0.55, 0.48, 0.28)
        self._ground_blend(-hw/2, hd/2-hd, hw, hd, fc, desert_floor, rng)
        # Sector 4 SE — mountain/desert meeting
        self._ground_blend(-hw/2+hw, hd/2-hd, hw, hd, mtn_floor, desert_floor, rng)

        # ── Stream ────────────────────────────────────────────────────────
        self._build_stream(rng, hw, hd)

        # ── Sector 1 — Dense verdant forest ──────────────────────────────
        self._build_forest(rng, -hw, 0, 0, hd,
                           ac, fc, count=200, tree_h=(10,22), density=0.6)
        self._build_grass(rng, -hw, 0, 0, hd, ac, count=400)
        self._build_creatures(rng, -hw*0.5, hw*0.1, -hd*0.1, hd*0.5, count=8)
        self._build_gas_station(-120, 80, rng)

        # ── Sector 2 — Thinning forest → mountain ────────────────────────
        self._build_forest(rng, 0, hw, 0, hd,
                           ac, fc, count=80, tree_h=(6,14), density=0.3)
        self._build_rocks(rng, 0, hw, 0, hd, mtn_floor, count=60)
        self._build_grass(rng, 0, hw, 0, hd, ac, count=100)

        # ── Sector 3 — Sparse forest → desert ────────────────────────────
        self._build_forest(rng, -hw, 0, -hd, 0,
                           ac, fc, count=40, tree_h=(5,10), density=0.2)
        self._build_desert_scatter(rng, -hw, 0, -hd, 0, count=80)
        self._build_rocks(rng, -hw, 0, -hd, 0, desert_floor, count=30)

        # ── Sector 4 — Mountain/desert transition ─────────────────────────
        self._build_rocks(rng, 0, hw, -hd, 0, mtn_floor, count=100)
        self._build_desert_scatter(rng, 0, hw, -hd, 0, count=60)

        # ── Background treeline ───────────────────────────────────────────
        self._build_treeline(rng, hw, hd, ac, fc)

        # Batch all static geometry — massive performance gain
        self.render.flattenStrong()

        # Terrain built AFTER flattenStrong so Z values are preserved
        mtn_floor    = (0.35, 0.32, 0.28)
        node = terrain.build_mesh(
            cx=0, cy=0,
            width=self.WORLD_W,
            depth=self.WORLD_D,
            subdivisions=64,
            color=fc,
            sector='verdant'
        )
        self.render.attachNewNode(node)
        # Build spawn cavern
        cavern = CavernBuilder(self.render, self._terrain)
        self._spawn_pos = cavern.build()
        console.log('[dim]World built — 4 sectors, stream, creatures, transitions[/dim]')

    def _ground_plane(self, cx, cy, w, d, color):
        gn = _make_plane_geom(w, d, color)
        self.render.attachNewNode(gn).setPos(cx, cy, 0)

    def _ground_blend(self, cx, cy, w, d, c1, c2, rng):
        # Blend two ground colors with noise patches
        gn = _make_plane_geom(w, d, c1)
        self.render.attachNewNode(gn).setPos(cx, cy, 0)
        for _ in range(40):
            px = cx + rng.uniform(-w/2, w/2)
            py = cy + rng.uniform(-d/2, d/2)
            ps = rng.uniform(10, 50)
            pn = _make_plane_geom(ps, ps, c2)
            self.render.attachNewNode(pn).setPos(px, py, 0.01)

    def _build_stream(self, rng, hw, hd):
        stream_c  = (0.15, 0.35, 0.55)
        shallow_c = (0.12, 0.28, 0.42)
        bank_c    = (0.1, 0.16, 0.08)
        # Start at random edge of sector 1 (NW)
        sx = rng.uniform(-hw*0.8, -hw*0.2)
        sy = hd * 0.85
        angle = rng.uniform(160, 200)
        seg_len = 40
        for i in range(80):
            angle += rng.uniform(-12, 12)
            dx = math.sin(math.radians(angle)) * seg_len
            dy = math.cos(math.radians(angle)) * seg_len
            # Widen as stream progresses south-east
            width = 8 + (i / 80) * 20
            wn = _make_plane_geom(width, seg_len, stream_c)
            wp = self.render.attachNewNode(wn)
            wp.setPos(sx + dx/2, sy + dy/2, 0.05)
            wp.setHpr(-angle, 0, 0)
            sn = _make_plane_geom(width + 8, seg_len, shallow_c)
            sp = self.render.attachNewNode(sn)
            sp.setPos(sx + dx/2, sy + dy/2, 0.02)
            sp.setHpr(-angle, 0, 0)
            bn = _make_box_geom(width + 12, 0.4, seg_len, bank_c)
            bp = self.render.attachNewNode(bn)
            bp.setPos(sx + dx/2, sy + dy/2, 0.15)
            bp.setHpr(-angle, 0, 0)
            sx += dx
            sy += dy
            if abs(sx) > hw * 0.95 or abs(sy) > hd * 0.95:
                break

    def _build_forest(self, rng, x1, x2, y1, y2, ac, fc, count, tree_h, density):
        for _ in range(count):
            x = rng.uniform(x1, x2)
            y = rng.uniform(y1, y2)
            th = rng.uniform(*tree_h)
            tw = rng.uniform(0.6, 1.8)
            trunk_c = (fc[0]*rng.uniform(0.5,0.8), fc[1]*rng.uniform(0.5,0.85), fc[2]*rng.uniform(0.3,0.55))
            tn = _make_box_geom(tw, th, tw, trunk_c)
            self.render.attachNewNode(tn).setPos(x, y, th/2)
            # Multi-layer canopy for less blocky look
            canopy_c = (ac[0]*rng.uniform(0.7,1.1), ac[1]*rng.uniform(0.85,1.2), ac[2]*rng.uniform(0.5,0.9))
            for layer in range(rng.randint(2, 4)):
                cw = rng.uniform(4, 10) * (1 - layer * 0.2)
                ch = rng.uniform(1.0, 2.5)
                offset_x = rng.uniform(-1.5, 1.5)
                offset_y = rng.uniform(-1.5, 1.5)
                shade = 1.0 - layer * 0.1
                cc = (canopy_c[0]*shade, canopy_c[1]*shade, canopy_c[2]*shade)
                cn = _make_box_geom(cw, ch, cw, cc)
                cp = self.render.attachNewNode(cn)
                cp.setPos(x+offset_x, y+offset_y, th + layer*ch*0.8 + ch/2)
                cp.setHpr(rng.uniform(0,45), 0, 0)
            # Grass climbing base
            for _ in range(rng.randint(3, 8)):
                gw = rng.uniform(0.3, 1.2)
                gh = rng.uniform(0.5, 2.0)
                gox = rng.uniform(-tw, tw)
                goy = rng.uniform(-tw, tw)
                gc = (ac[0]*0.6, ac[1]*0.9, ac[2]*0.5)
                gn = _make_box_geom(gw, gh, gw*0.3, gc)
                gp = self.render.attachNewNode(gn)
                gp.setPos(x+gox, y+goy, gh/2)
                gp.setHpr(rng.uniform(0,360), rng.uniform(-20,20), 0)

    def _build_grass(self, rng, x1, x2, y1, y2, ac, count):
        gc1 = (ac[0]*0.6, ac[1]*0.95, ac[2]*0.4)
        gc2 = (ac[0]*0.5, ac[1]*0.8,  ac[2]*0.35)
        for _ in range(count):
            x = rng.uniform(x1, x2)
            y = rng.uniform(y1, y2)
            # Grass patch — cluster of thin tall flats
            for blade in range(rng.randint(3, 8)):
                bw = rng.uniform(0.1, 0.4)
                bh = rng.uniform(0.4, 1.5)
                bx = x + rng.uniform(-1.5, 1.5)
                by = y + rng.uniform(-1.5, 1.5)
                bc = gc1 if rng.random() > 0.4 else gc2
                bn = _make_box_geom(bw, bh, bw*0.1, bc)
                bp = self.render.attachNewNode(bn)
                gz = self._terrain.height_at(bx, by) if hasattr(self, '_terrain') else 0
                bp.setPos(bx, by, gz + bh/2)
                bp.setHpr(rng.uniform(0,360), rng.uniform(-15,15), 0)

    def _build_rocks(self, rng, x1, x2, y1, y2, base_c, count):
        for _ in range(count):
            x = rng.uniform(x1, x2)
            y = rng.uniform(y1, y2)
            rs = rng.uniform(1, 6)
            rc = (base_c[0]*rng.uniform(0.7,1.1), base_c[1]*rng.uniform(0.7,1.0), base_c[2]*rng.uniform(0.6,0.9))
            rn = _make_box_geom(rs, rs*rng.uniform(0.4,0.9), rs*rng.uniform(0.6,1.2), rc)
            rp = self.render.attachNewNode(rn)
            gz = self._terrain.height_at(x, y) if hasattr(self, '_terrain') else 0
            rp.setPos(x, y, gz + rs*0.3)
            rp.setHpr(rng.uniform(0,360), rng.uniform(-10,10), 0)

    def _build_desert_scatter(self, rng, x1, x2, y1, y2, count):
        cactus_c = (0.25, 0.45, 0.15)
        dead_c   = (0.4, 0.35, 0.2)
        for _ in range(count):
            x = rng.uniform(x1, x2)
            y = rng.uniform(y1, y2)
            if rng.random() > 0.5:
                # Cactus — pillar with arms
                ch = rng.uniform(3, 8)
                cn = _make_box_geom(0.8, ch, 0.8, cactus_c)
                cp = self.render.attachNewNode(cn)
                cp.setPos(x, y, ch/2)
                if rng.random() > 0.4:
                    arm_h = ch * 0.6
                    an = _make_box_geom(0.5, arm_h*0.4, 0.5, cactus_c)
                    ap = self.render.attachNewNode(an)
                    ap.setPos(x + rng.uniform(0.8,1.5), y, arm_h)
            else:
                # Dead scrub
                sw = rng.uniform(1, 3)
                sh = rng.uniform(0.5, 2)
                sn = _make_box_geom(sw, sh, sw*0.3, dead_c)
                sp = self.render.attachNewNode(sn)
                sp.setPos(x, y, sh/2)
                sp.setHpr(rng.uniform(0,360), 0, 0)

    def _build_creatures(self, rng, x1, x2, y1, y2, count):
        # Small static creatures near water/shrubs
        body_c = (0.45, 0.38, 0.28)
        for _ in range(count):
            x = rng.uniform(x1, x2)
            y = rng.uniform(y1, y2)
            size = rng.uniform(0.3, 0.7)
            # Body
            bn = _make_box_geom(size*1.5, size*0.7, size*0.8, body_c)
            bp = self.render.attachNewNode(bn)
            bp.setPos(x, y, size*0.5)
            bp.setHpr(rng.uniform(0,360), 0, 0)
            # Head
            hn = _make_box_geom(size*0.6, size*0.6, size*0.6, body_c)
            hp = self.render.attachNewNode(hn)
            hp.setPos(x + size*0.8, y, size*0.9)
            # Legs x4
            leg_c = (body_c[0]*0.8, body_c[1]*0.8, body_c[2]*0.8)
            for lx, ly in [(-0.4,-0.3),(0.4,-0.3),(-0.4,0.3),(0.4,0.3)]:
                ln = _make_box_geom(size*0.15, size*0.5, size*0.15, leg_c)
                lp = self.render.attachNewNode(ln)
                lp.setPos(x+lx*size, y+ly*size, size*0.25)

    def _build_gas_station(self, x, y, rng):
        """
        Ruined gas station — unnatural object in the verdant biome.
        Primitives: concrete slab roof, pillars, pump islands,
        collapsed wall, overgrown vines.
        """
        rust   = (0.35, 0.28, 0.18)
        concrete=(0.42, 0.40, 0.36)
        dark_c = (0.22, 0.20, 0.18)
        glass_c= (0.3,  0.4,  0.35)
        vine_c = (0.2,  0.45, 0.15)
        metal_c= (0.28, 0.25, 0.22)

        # Canopy roof — large flat slab, tilted slightly (collapsed)
        roof = _make_box_geom(50, 0.8, 32, concrete)
        rp = self.render.attachNewNode(roof)
        rp.setPos(x, y, 17)
        rp.setHpr(0, 3, 1)  # slight tilt

        # Support pillars — 4, one partially collapsed
        for px, py, tilt in [(x-20,y-10,0),(x+20,y-10,0),(x-20,y+10,0),(x+20,y+10,12)]:
            pn = _make_box_geom(1.2, 17, 1.2, metal_c)
            pp = self.render.attachNewNode(pn)
            pp.setPos(px, py, 8.5)
            pp.setHpr(tilt, 0, 0)

        # Main building shell — back wall standing
        wall1 = _make_box_geom(36, 14, 0.6, concrete)
        w1p = self.render.attachNewNode(wall1)
        w1p.setPos(x, y+16, 7)

        # Side wall — partially collapsed
        wall2 = _make_box_geom(0.6, 9, 20, concrete)
        w2p = self.render.attachNewNode(wall2)
        w2p.setPos(x-18, y+8, 4.5)
        w2p.setHpr(0, 0, 8)

        # Collapsed wall rubble
        for i in range(8):
            rx = x + rng.uniform(-8, 8)
            ry = y + rng.uniform(5, 12)
            rs = rng.uniform(0.5, 2.5)
            rn = _make_box_geom(rs, rs*0.4, rs*rng.uniform(0.5,1.5), concrete)
            rp2 = self.render.attachNewNode(rn)
            rp2.setPos(rx, ry, rs*0.2)
            rp2.setHpr(rng.uniform(0,360), rng.uniform(-20,20), rng.uniform(-15,15))

        # Pump islands — 2 concrete islands with pump shapes
        for ix in [-5, 5]:
            island = _make_box_geom(2.5, 0.4, 5, concrete)
            ip = self.render.attachNewNode(island)
            ip.setPos(x+ix, y-4, 0.2)
            # Pump body
            pump = _make_box_geom(0.8, 2.5, 0.5, rust)
            pp2 = self.render.attachNewNode(pump)
            pp2.setPos(x+ix, y-4, 1.5)
            # Pump top — hose connector
            top = _make_box_geom(1.0, 0.3, 0.8, metal_c)
            tp = self.render.attachNewNode(top)
            tp.setPos(x+ix, y-4, 2.8)

        # Broken windows — glass remnants
        for wx, wy in [(x-6,y+8.7),(x,y+8.7),(x+6,y+8.7)]:
            if rng.random() > 0.4:
                gn = _make_box_geom(3.5, 3, 0.1, glass_c)
                gp = self.render.attachNewNode(gn)
                gp.setPos(wx, wy, 4)
                gp.setHpr(0, rng.uniform(-8,8), rng.uniform(-5,5))

        # Overgrown vines crawling up walls
        for _ in range(25):
            vx = x + rng.uniform(-12, 12)
            vy = y + rng.uniform(-2, 10)
            vh = rng.uniform(1, 6)
            vw = rng.uniform(0.2, 0.8)
            vn = _make_box_geom(vw, vh, vw*0.2, vine_c)
            vp = self.render.attachNewNode(vn)
            vp.setPos(vx, vy, vh/2)
            vp.setHpr(rng.uniform(0,360), rng.uniform(-25,25), 0)

        # Cracked concrete forecourt
        fore = _make_plane_geom(54, 36, (0.38, 0.36, 0.32))
        fp = self.render.attachNewNode(fore)
        fp.setPos(x, y-8, 0.02)

        # Weeds pushing through cracks
        for _ in range(30):
            wx2 = x + rng.uniform(-13, 13)
            wy2 = y + rng.uniform(-14, 5)
            wh = rng.uniform(0.3, 1.2)
            wc = (vine_c[0]*rng.uniform(0.6,1.0), vine_c[1]*rng.uniform(0.8,1.1), vine_c[2]*0.5)
            wn = _make_box_geom(rng.uniform(0.1,0.4), wh, rng.uniform(0.05,0.2), wc)
            wp2 = self.render.attachNewNode(wn)
            wp2.setPos(wx2, wy2, wh/2)
            wp2.setHpr(rng.uniform(0,360), rng.uniform(-20,20), 0)

        # Rusted sign — fallen",
        sign = _make_box_geom(6, 2, 0.1, rust)
        sp2 = self.render.attachNewNode(sign)
        sp2.setPos(x+8, y-10, 0.5)
        sp2.setHpr(rng.uniform(20,60), rng.uniform(60,80), 0)

        console.log(f"[dim]Gas station placed at ({x:.0f}, {y:.0f})[/dim]")

    def _build_spawn_marker(self):
        """
        Sanctum Stone -- marks the entry point.
        Dark obelisk, slightly luminous, impossible geometry.
        """
        stone_c  = (0.08, 0.06, 0.12)  # near-black, slight purple
        ring_c   = (0.15, 0.12, 0.25)  # dark ring
        glow_c   = (0.3,  0.25, 0.5)   # subtle glow band

        gz = self._terrain.height_at(0, 0) if hasattr(self, "_terrain") else 0

        # Base ring -- flat wide slab
        bn = _make_box_geom(6, 0.3, 6, ring_c)
        self.render.attachNewNode(bn).setPos(0, 0, gz + 0.15)

        # Obelisk -- tall narrow pillar
        on2 = _make_box_geom(1.2, 18, 1.2, stone_c)
        self.render.attachNewNode(on2).setPos(0, 0, gz + 9)

        # Mid band -- glow stripe
        gn = _make_box_geom(1.4, 0.4, 1.4, glow_c)
        self.render.attachNewNode(gn).setPos(0, 0, gz + 6)

        # Cap -- angled tip
        cn = _make_box_geom(0.8, 2.0, 0.8, ring_c)
        cp = self.render.attachNewNode(cn)
        cp.setPos(0, 0, gz + 18)
        cp.setHpr(45, 0, 0)

        # Four corner stones -- smaller obelisks
        for ox, oy in [(-4,0),(4,0),(0,-4),(0,4)]:
            sn = _make_box_geom(0.4, 4, 0.4, stone_c)
            self.render.attachNewNode(sn).setPos(ox, oy, gz + 2)

        console.log("[bold magenta]SANCTUM STONE[/bold magenta] — spawn marker placed")

    def _build_treeline(self, rng, hw, hd, ac, fc):
        dark_t = (fc[0]*0.3, fc[1]*0.35, fc[2]*0.25)
        dark_c = (ac[0]*0.3, ac[1]*0.45, ac[2]*0.3)
        for i in range(200):
            angle = (i / 200) * 6.28
            rx = math.cos(angle) * hw * 0.95 + rng.uniform(-30,30)
            ry = math.sin(angle) * hd * 0.95 + rng.uniform(-30,30)
            th = rng.uniform(25, 50)
            tw = rng.uniform(1.5, 4)
            tn = _make_box_geom(tw, th, tw, dark_t)
            self.render.attachNewNode(tn).setPos(rx, ry, th/2)
            cw = rng.uniform(10, 25)
            cn = _make_box_geom(cw, rng.uniform(4,8), cw, dark_c)
            cp = self.render.attachNewNode(cn)
            cp.setPos(rx, ry, th+3)
            cp.setHpr(rng.uniform(0,45), 0, 0)

    # ── Lighting ──────────────────────────────────────────────────────────

    def setup_lighting(self):
        sun = DirectionalLight('sun')
        sun.setColor(Vec4(0.95, 0.90, 0.85, 1))  # Cool cinematic sun
        sn = self.render.attachNewNode(sun)
        sn.setHpr(45, -35, 0)
        self.render.setLight(sn)
        fill = DirectionalLight('fill')
        fill.setColor(Vec4(0.15, 0.20, 0.35, 1))  # Deep shadow fill
        fn = self.render.attachNewNode(fill)
        fn.setHpr(225, -60, 0)
        self.render.setLight(fn)
        amb = AmbientLight('amb')
        amb.setColor(Vec4(0.08, 0.10, 0.08, 1))  # Low ambient -- deep shadows
        self.render.setLight(self.render.attachNewNode(amb))

    # ── Controls ──────────────────────────────────────────────────────────

    def setup_controls(self):
        for key in ['w','s','a','d']:
            self.accept(key,         self.update_key_map, [key, True])
            self.accept(f'{key}-up', self.update_key_map, [key, False])
        self.accept('shift',      self.update_key_map, ['shift', True])
        self.accept('shift-up',   self.update_key_map, ['shift', False])
        self.accept('space',      self.do_jump)

    def update_key_map(self,key,val): self.key_map[key]=val

    def do_jump(self):
        if self.on_ground:
            self.vel_z = JUMP_VELOCITY
            self.on_ground = False

    def enable_mouse_look(self):
        self.mouse_look_active=True
        self._last_mx=None
        self._last_my=None
        props=WindowProperties()
        props.setCursorHidden(True)
        props.setMouseMode(WindowProperties.M_relative)
        self.win.requestProperties(props)

    def disable_mouse_look(self):
        self.mouse_look_active=False
        props=WindowProperties()
        props.setCursorHidden(False)
        props.setMouseMode(WindowProperties.M_absolute)
        self.win.requestProperties(props)

    # ── Game loop ─────────────────────────────────────────────────────────

    def game_loop(self, task):
        dt    = globalClock.getDt()
        speed = RUN_SPEED if self.key_map['shift'] else WALK_SPEED

        # Mouse look
        if self.mouse_look_active and self.mouseWatcherNode.hasMouse():
            md = self.win.getPointer(0)
            mx, my = md.getX(), md.getY()
            if self._last_mx is not None:
                dx = mx - self._last_mx
                dy = my - self._last_my
                if abs(dx)<SNAP_THRESHOLD and abs(dy)<SNAP_THRESHOLD:
                    self.cam_yaw   -= dx * MOUSE_SENSITIVITY
                    self.cam_pitch -= dy * MOUSE_SENSITIVITY
                    self.cam_pitch  = max(-PITCH_CLAMP, min(PITCH_CLAMP, self.cam_pitch))
                    self.cam.setHpr(self.cam_yaw, self.cam_pitch, 0)
            self._last_mx, self._last_my = mx, my

        # Movement
        if self.key_map['w']: self.cam.setPos(self.cam, 0,  speed*dt, 0)
        if self.key_map['s']: self.cam.setPos(self.cam, 0, -speed*dt, 0)
        if self.key_map['a']: self.cam.setPos(self.cam, -speed*dt, 0, 0)
        if self.key_map['d']: self.cam.setPos(self.cam,  speed*dt, 0, 0)

        # Jump + gravity
        if not self.on_ground:
            self.vel_z -= GRAVITY * dt
            x, y, z = self.cam.getPos()
            z += self.vel_z * dt
            ground = self._terrain.height_at(x, y) + GROUND_Z
            if z <= ground:
                z = ground
                self.vel_z = 0
                self.on_ground = True
            self.cam.setPos(x, y, z)
        else:
            x, y, z = self.cam.getPos()
            ground = self._terrain.height_at(x, y) + GROUND_Z
            self.cam.setPos(x, y, ground)

        # World bounds
        x, y, z = self.cam.getPos()
        hw = self.WORLD_W/2 - 5
        hd = self.WORLD_D/2 - 5
        self.cam.setX(max(-hw, min(hw, x)))
        self.cam.setY(max(-hd, min(hd, y)))
        return task.cont

    def exit_app(self): sys.exit(0)

if __name__ == '__main__':
    RoomLab().run()