import math
from rich.console import Console
from core.systems.biome_renderer import _make_box_geom, _make_plane_geom

console = Console()

# Spawn cavern anchor -- flattest point near origin for seed=42
CAVERN_X  = -10.0
CAVERN_Y  =  20.0
CAVERN_Z  =  -4.23  # terrain height at anchor


class CavernBuilder:
    """
    Builds the spawn cavern -- primitive man emerging with ancient torch.
    Fixed interior space regardless of terrain height.
    Opening faces south (negative Y) toward the biome.
    Avatar spawns at back of cavern, walks toward light.
    """

    # Material colors
    STONE_DARK  = (0.18, 0.16, 0.14)
    STONE_MID   = (0.28, 0.25, 0.22)
    STONE_LIGHT = (0.38, 0.34, 0.30)
    EARTH       = (0.22, 0.18, 0.12)
    MOSS        = (0.15, 0.25, 0.12)

    def __init__(self, render_root, terrain):
        self.render  = render_root
        self.terrain = terrain
        self.cx      = CAVERN_X
        self.cy      = CAVERN_Y
        self.gz      = terrain.height_at(CAVERN_X, CAVERN_Y)

    def build(self):
        """Build full cavern. Returns spawn position (x, y, z) for avatar."""
        self._build_floor()
        self._build_ceiling()
        self._build_walls()
        self._build_mouth()
        self._build_detail()
        spawn_z = self.gz + 6.0  # EYE_Z above cavern floor
        console.log(
            f'[bold cyan]CAVERN[/bold cyan] — spawn at '
            f'({self.cx:.0f}, {self.cy:.0f}, {spawn_z:.1f})'
        )
        return (self.cx, self.cy - 6.0, spawn_z)

    def _build_floor(self):
        cx, cy, gz = self.cx, self.cy, self.gz
        # Main floor -- rough earth
        fn = _make_plane_geom(14, 20, self.EARTH)
        fp = self.render.attachNewNode(fn)
        fp.setPos(cx, cy + 4, gz + 0.1)
        # Stone floor patches -- irregular
        for ox, oy, s, c in [
            (-2, 2, 4, self.STONE_MID),
            (3, -1, 3, self.STONE_DARK),
            (-1, 6, 5, self.STONE_MID),
            (2, 10, 4, self.STONE_LIGHT),
        ]:
            pn = _make_plane_geom(s, s, c)
            pp = self.render.attachNewNode(pn)
            pp.setPos(cx + ox, cy + oy, gz + 0.15)

    def _build_ceiling(self):
        cx, cy, gz = self.cx, self.cy, self.gz
        ceiling_z = gz + 10.0
        # Main ceiling slab
        cn = _make_box_geom(14, 3.0, 20, self.STONE_DARK)
        cp = self.render.attachNewNode(cn)
        cp.setPos(cx, cy + 4, ceiling_z + 1.5)
        # Irregular ceiling drops -- stalactite-like slabs
        for ox, oy, w, d, drop in [
            (-3, 8, 3, 4, 1.5),
            (2, 3, 4, 3, 2.0),
            (-1, 12, 5, 4, 1.0),
            (3, 7, 2, 3, 2.5),
            (-4, 4, 3, 2, 1.8),
        ]:
            sn = _make_box_geom(w, drop, d, self.STONE_MID)
            sp = self.render.attachNewNode(sn)
            sp.setPos(cx + ox, cy + oy, ceiling_z - drop/2)

    def _build_walls(self):
        cx, cy, gz = self.cx, self.cy, self.gz
        h  = 10.0
        hz = gz + h/2
        # Back wall -- deepest point
        bn = _make_box_geom(14, h, 1.0, self.STONE_DARK)
        bp = self.render.attachNewNode(bn)
        bp.setPos(cx, cy + 14, hz)
        # Left wall
        ln = _make_box_geom(1.0, h, 20, self.STONE_MID)
        lp = self.render.attachNewNode(ln)
        lp.setPos(cx - 7, cy + 4, hz)
        # Right wall
        rn = _make_box_geom(1.0, h, 20, self.STONE_MID)
        rp = self.render.attachNewNode(rn)
        rp.setPos(cx + 7, cy + 4, hz)
        # Partial front walls -- frame the mouth
        fl = _make_box_geom(3.0, h, 1.0, self.STONE_DARK)
        flp = self.render.attachNewNode(fl)
        flp.setPos(cx - 5.5, cy - 6, hz)
        fr = _make_box_geom(3.0, h, 1.0, self.STONE_DARK)
        frp = self.render.attachNewNode(fr)
        frp.setPos(cx + 5.5, cy - 6, hz)
        # Lintel -- top of mouth opening
        ltn = _make_box_geom(8, 2.5, 1.0, self.STONE_DARK)
        ltp = self.render.attachNewNode(ltn)
        ltp.setPos(cx, cy - 6, gz + 9.0)

    def _build_mouth(self):
        """
        The opening -- faces south toward biome.
        Framed by rough stone, no door.
        Light bleeds in from outside.
        """
        cx, cy, gz = self.cx, self.cy, self.gz
        # Ground ramp out -- gentle slope from cavern floor to terrain
        for i in range(4):
            ramp_z = gz + i * 0.3
            rn = _make_plane_geom(8, 2, self.EARTH)
            rp = self.render.attachNewNode(rn)
            rp.setPos(cx, cy - 7 - i*2, ramp_z)
        # Rock pile at mouth edge -- natural debris
        for ox, oy, s in [(-3,-8,1.2),(2,-9,0.8),(-1,-7,1.5),(3,-8,1.0),(-2,-9,0.9)]:
            rk = _make_box_geom(s, s*0.6, s, self.STONE_MID)
            rp = self.render.attachNewNode(rk)
            rp.setPos(cx+ox, cy+oy, gz + s*0.3)

    def _build_detail(self):
        """Moss patches, small rocks, ground detail inside cavern."""
        cx, cy, gz = self.cx, self.cy, self.gz
        # Moss on walls -- low patches
        for ox, oy, w, h in [
            (-6, 2, 1.5, 0.8),
            (-6, 8, 2.0, 1.2),
            (6, 5,  1.8, 0.6),
            (6, 10, 1.2, 1.0),
            (-5, 12, 1.0, 0.8),
        ]:
            mn = _make_box_geom(0.2, h, w, self.MOSS)
            mp = self.render.attachNewNode(mn)
            mp.setPos(cx+ox, cy+oy, gz + h/2 + 0.5)
        # Small floor rocks
        for ox, oy, s in [
            (2, 4, 0.4), (-3, 7, 0.6), (4, 11, 0.3),
            (-2, 9, 0.5), (1, 13, 0.4), (-4, 3, 0.3)
        ]:
            rk = _make_box_geom(s, s*0.5, s, self.STONE_LIGHT)
            rp = self.render.attachNewNode(rk)
            rp.setPos(cx+ox, cy+oy, gz + s*0.25)
        # Sanctum stone -- back of cavern, marks the seed origin
        sn = _make_box_geom(0.3, 6.0, 0.3, (0.08, 0.06, 0.14))
        sp = self.render.attachNewNode(sn)
        sp.setPos(cx, cy + 13, gz + 3.0)
        # Glow band on stone
        gn = _make_box_geom(0.4, 0.3, 0.4, (0.25, 0.20, 0.45))
        gp = self.render.attachNewNode(gn)
        gp.setPos(cx, cy + 13, gz + 2.5)