import math
import random
from panda3d.core import (
    Geom, GeomNode, GeomTriangles,
    GeomVertexData, GeomVertexFormat, GeomVertexWriter
)


class TerrainGenerator:
    """
    Procedural heightmap terrain using layered sine/cosine noise.
    No external dependencies -- pure math, Pi-safe.
    Each sector has different amplitude/frequency for biome feel.
    """

    # Sector bounds (matches room_lab 3200x3200 world)
    # NW=verdant, NE=mountain, SW=desert, SE=transition
    SECTOR_CONFIGS = {
        'VERDANT':    {'x': (-1600,    0), 'y': (   0, 1600), 'amp': 6.0,  'freq': 0.008},
        'MOUNTAIN':   {'x': (    0, 1600), 'y': (   0, 1600), 'amp': 22.0, 'freq': 0.012},
        'DESERT':     {'x': (-1600,    0), 'y': (-1600,   0), 'amp': 4.0,  'freq': 0.005},
        'TRANSITION': {'x': (    0, 1600), 'y': (-1600,   0), 'amp': 12.0, 'freq': 0.009},
    }

    def __init__(self, seed=42):
        self.seed   = seed
        self._rng   = random.Random(seed)
        # Randomize phase offsets per seed so each world is unique
        self._px = self._rng.uniform(0, 1000)
        self._py = self._rng.uniform(0, 1000)
        self._px2= self._rng.uniform(0, 500)
        self._py2= self._rng.uniform(0, 500)

    def _sector_params(self, x, y):
        """Return amplitude and frequency for the sector containing (x,y)."""
        for name, cfg in self.SECTOR_CONFIGS.items():
            if cfg['x'][0] <= x < cfg['x'][1] and cfg['y'][0] <= y < cfg['y'][1]:
                return cfg['amp'], cfg['freq']
        # Default -- verdant
        return 6.0, 0.008

    def height_at(self, x, y):
        """
        Returns elevation at world position (x, y).
        Layered noise: large slow waves + small fast detail.
        Deterministic -- same inputs always return same height.
        """
        amp, freq = self._sector_params(x, y)

        # Layer 1 -- large rolling hills
        h  = amp * math.sin((x + self._px) * freq) * math.cos((y + self._py) * freq)
        # Layer 2 -- medium variation
        h += amp * 0.4 * math.sin((x + self._px2) * freq * 2.1) * math.sin((y + self._py2) * freq * 1.7)
        # Layer 3 -- small surface detail
        h += amp * 0.15 * math.cos((x + self._px) * freq * 4.3 + 0.5) * math.sin((y + self._py) * freq * 3.9)

        return float(h)

    def build_mesh(self, cx, cy, width, depth, subdivisions=16,
                   color=(0.1, 0.25, 0.1), sector='verdant'):
        """
        Build a terrain mesh GeomNode centered at (cx, cy).
        subdivisions = grid resolution (higher = smoother but more verts).
        """
        cols = subdivisions + 1
        rows = subdivisions + 1
        r, g, b = color

        fmt   = GeomVertexFormat.getV3c4()
        vdata = GeomVertexData('terrain', fmt, Geom.UHStatic)
        vdata.setNumRows(cols * rows)
        vw = GeomVertexWriter(vdata, 'vertex')
        cw = GeomVertexWriter(vdata, 'color')

        hw = width / 2
        hd = depth / 2

        for row in range(rows):
            for col in range(cols):
                fx = cx - hw + (col / subdivisions) * width
                fy = cy - hd + (row / subdivisions) * depth
                fz = self.height_at(fx, fy)
                vw.addData3(fx, fy, fz)
                if sector == 'mountain':
                    t = min(1.0, max(0.0, fz / 25.0))
                    cr = r*(1-t) + 0.55*t
                    cg = g*(1-t) + 0.50*t
                    cb = b*(1-t) + 0.48*t
                    shade = 0.8 + min(0.4, max(0.0, fz / 20.0))
                    cw.addData4(cr*shade, cg*shade, cb*shade, 1.0)
                elif sector == 'desert':
                    shade = 0.75 + min(0.35, max(0.0, fz / 15.0))
                    cw.addData4(r*shade*1.1, g*shade*0.95, b*shade*0.7, 1.0)
                elif sector == 'transition':
                    shade = 0.8 + min(0.3, max(0.0, fz / 20.0))
                    cw.addData4(r*shade, g*shade*0.9, b*shade*0.8, 1.0)
                else:
                    shade = 0.75 + min(0.35, max(0.0, (fz + 5.0) / 25.0))
                    cw.addData4(r*shade, g*shade*1.05, b*shade*0.9, 1.0)

        tris = GeomTriangles(Geom.UHStatic)
        for row in range(subdivisions):
            for col in range(subdivisions):
                i  = row * cols + col
                tris.addVertices(i,        i+1,      i+cols)
                tris.addVertices(i+1,      i+cols+1, i+cols)

        geom = Geom(vdata)
        geom.addPrimitive(tris)
        node = GeomNode('terrain')
        node.addGeom(geom)
        return node

    def is_slope(self, x, y, threshold=0.3, step=5.0):
        """Returns True if the terrain slope at (x,y) exceeds threshold."""
        h0 = self.height_at(x, y)
        h1 = self.height_at(x + step, y)
        h2 = self.height_at(x, y + step)
        slope = math.sqrt(((h1-h0)/step)**2 + ((h2-h0)/step)**2)
        return slope > threshold

    def slope_direction(self, x, y, step=5.0):
        """Returns (dx, dy) unit vector pointing downhill."""
        h0 = self.height_at(x, y)
        hx = self.height_at(x + step, y)
        hy = self.height_at(x, y + step)
        dx = -(hx - h0)
        dy = -(hy - h0)
        length = math.sqrt(dx*dx + dy*dy) or 1.0
        return float(dx/length), float(dy/length)

    def lowest_neighbor(self, x, y, step=10.0):
        """Returns the (x,y) neighbor position with lowest elevation."""
        candidates = [
            (x+step, y), (x-step, y),
            (x, y+step), (x, y-step),
        ]
        return min(candidates, key=lambda p: self.height_at(p[0], p[1]))