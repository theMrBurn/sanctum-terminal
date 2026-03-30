import random

from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    LVector3,
    LVector4,
    NodePath,
)

# -- Vertex color noise --------------------------------------------------------
# System-wide surface variation. Breaks up flat faces.
# Applied per-vertex in all geometry functions.

_NOISE_RNG = random.Random(0)
VERTEX_NOISE = 0.12  # ±12% brightness variation per vertex


def _noisy_color(r, g, b, shade, noise=VERTEX_NOISE):
    """Apply face shading + per-vertex noise to a base color."""
    n = 1.0 + _NOISE_RNG.uniform(-noise, noise)
    return (
        max(0.0, min(1.0, r * shade * n)),
        max(0.0, min(1.0, g * shade * n)),
        max(0.0, min(1.0, b * shade * n)),
    )

# ── Biome visual signatures ───────────────────────────────────────────────────

BIOME_PALETTE = {
    "VOID": {"floor": (0.05, 0.05, 0.08), "accent": (0.2, 0.1, 0.3), "scale": 1.0},
    "NEON": {"floor": (0.05, 0.0, 0.15), "accent": (0.8, 0.0, 1.0), "scale": 0.8},
    "IRON": {"floor": (0.2, 0.15, 0.1), "accent": (0.5, 0.35, 0.2), "scale": 1.2},
    "SILICA": {"floor": (0.7, 0.65, 0.5), "accent": (0.9, 0.85, 0.7), "scale": 0.6},
    "FROZEN": {"floor": (0.6, 0.75, 0.9), "accent": (0.9, 0.95, 1.0), "scale": 1.1},
    "SULPHUR": {"floor": (0.3, 0.28, 0.0), "accent": (0.7, 0.6, 0.0), "scale": 0.9},
    "BASALT": {"floor": (0.08, 0.04, 0.04), "accent": (0.4, 0.1, 0.05), "scale": 1.3},
    "VERDANT": {"floor": (0.1, 0.25, 0.1), "accent": (0.3, 0.6, 0.2), "scale": 0.7},
    "MYCELIUM": {"floor": (0.15, 0.08, 0.18), "accent": (0.6, 0.3, 0.7), "scale": 0.9},
    "CHROME": {"floor": (0.6, 0.6, 0.65), "accent": (1.0, 1.0, 1.0), "scale": 1.0},
}

DEFAULT_PALETTE = BIOME_PALETTE["VOID"]


def _make_box_geom(w, h, d, color):
    """Builds a flat-shaded colored box GeomNode."""
    fmt = GeomVertexFormat.getV3c4()
    vdata = GeomVertexData("box", fmt, Geom.UHStatic)
    vdata.setNumRows(24)

    vwriter = GeomVertexWriter(vdata, "vertex")
    cwriter = GeomVertexWriter(vdata, "color")

    hw, hh, hd = w / 2, h / 2, d / 2
    r, g, b = color

    faces = [
        # front
        [(-hw, -hd, -hh), (hw, -hd, -hh), (hw, -hd, hh), (-hw, -hd, hh)],
        # back
        [(hw, hd, -hh), (-hw, hd, -hh), (-hw, hd, hh), (hw, hd, hh)],
        # left
        [(-hw, hd, -hh), (-hw, -hd, -hh), (-hw, -hd, hh), (-hw, hd, hh)],
        # right
        [(hw, -hd, -hh), (hw, hd, -hh), (hw, hd, hh), (hw, -hd, hh)],
        # bottom
        [(-hw, hd, -hh), (hw, hd, -hh), (hw, -hd, -hh), (-hw, -hd, -hh)],
        # top
        [(-hw, -hd, hh), (hw, -hd, hh), (hw, hd, hh), (-hw, hd, hh)],
    ]

    face_shading = [0.7, 0.7, 0.5, 0.5, 0.3, 1.0]

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0
    for face, shade in zip(faces, face_shading):
        for v in face:
            vwriter.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cwriter.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("box")
    node.addGeom(geom)
    return node


def _make_plane_geom(w, d, color, subdivisions=12):
    """
    Builds a subdivided ground plane with per-vertex color/height noise.
    Gives the ground subtle variation -- not flat, not tiled.
    """
    fmt = GeomVertexFormat.getV3c4()
    cols = subdivisions
    rows = subdivisions
    num_verts = (cols + 1) * (rows + 1)
    vdata = GeomVertexData("plane", fmt, Geom.UHStatic)
    vdata.setNumRows(num_verts)

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    hw, hd = w / 2, d / 2
    r, g, b = color
    rng = random.Random(int(r * 1000 + g * 100 + b * 10))

    for row in range(rows + 1):
        for col in range(cols + 1):
            x = -hw + (col / cols) * w
            y = -hd + (row / rows) * d
            # Subtle height variation
            z = rng.uniform(-0.08, 0.08)
            vw.addData3(x, y, z)
            # Per-vertex color noise
            cr, cg, cb = _noisy_color(r, g, b, 1.0, noise=0.15)
            cw.addData4(cr, cg, cb, 1.0)

    tris = GeomTriangles(Geom.UHStatic)
    for row in range(rows):
        for col in range(cols):
            i = row * (cols + 1) + col
            tris.addVertices(i, i + 1, i + cols + 2)
            tris.addVertices(i, i + cols + 2, i + cols + 1)

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("plane")
    node.addGeom(geom)
    return node


def _make_wedge_geom(w, h, d, color):
    """
    Builds a flat-shaded triangular prism (wedge) GeomNode.
    Triangular cross-section: full width at base, tapers to ridge at top.
    w = width, h = height (taper direction), d = depth.
    """
    import math
    fmt = GeomVertexFormat.getV3c4()
    vdata = GeomVertexData("wedge", fmt, Geom.UHStatic)
    vdata.setNumRows(18)

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    hw, hh, hd = w / 2, h / 2, d / 2
    r, g, b = color

    # 6 vertices: rectangular base + ridge on top
    #   base: 4 corners at z = -hh
    #   ridge: 2 points at z = +hh, x = 0
    # Faces: bottom (quad), front (tri), back (tri), left (quad), right (quad)

    faces_quads = [
        # bottom
        ([(-hw, -hd, -hh), (hw, -hd, -hh), (hw, hd, -hh), (-hw, hd, -hh)], 0.3),
        # left slope
        ([(-hw, -hd, -hh), (-hw, hd, -hh), (0, hd, hh), (0, -hd, hh)], 0.6),
        # right slope
        ([(hw, hd, -hh), (hw, -hd, -hh), (0, -hd, hh), (0, hd, hh)], 0.8),
    ]

    faces_tris = [
        # front triangle
        ([(-hw, -hd, -hh), (hw, -hd, -hh), (0, -hd, hh)], 0.5),
        # back triangle
        ([(hw, hd, -hh), (-hw, hd, -hh), (0, hd, hh)], 0.5),
    ]

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    for face, shade in faces_quads:
        for v in face:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

    for face, shade in faces_tris:
        for v in face:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        idx += 3

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("wedge")
    node.addGeom(geom)
    return node


def _make_spike_geom(w, h, d, color):
    """
    Builds a flat-shaded pyramid GeomNode.
    Square base at z=-h/2, apex at z=+h/2.
    w = base width, h = height, d = base depth.
    """
    fmt = GeomVertexFormat.getV3c4()
    vdata = GeomVertexData("spike", fmt, Geom.UHStatic)
    vdata.setNumRows(16)

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    hw, hh, hd = w / 2, h / 2, d / 2
    r, g, b = color
    apex = (0, 0, hh)

    # Base quad + 4 triangular faces
    base = [(-hw, -hd, -hh), (hw, -hd, -hh), (hw, hd, -hh), (-hw, hd, -hh)]

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    # Base (quad)
    shade = 0.3
    cr, cg, cb = r * shade, g * shade, b * shade
    for v in base:
        vw.addData3(*v)
        cw.addData4(cr, cg, cb, 1.0)
    tris.addVertices(idx, idx + 1, idx + 2)
    tris.addVertices(idx, idx + 2, idx + 3)
    idx += 4

    # 4 triangular faces
    side_faces = [
        ([base[0], base[1], apex], 0.7),   # front
        ([base[1], base[2], apex], 0.5),   # right
        ([base[2], base[3], apex], 0.7),   # back
        ([base[3], base[0], apex], 1.0),   # left
    ]

    for face, shade in side_faces:
        for v in face:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        idx += 3

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("spike")
    node.addGeom(geom)
    return node


def _make_arch_geom(w, h, d, color, segments=8):
    """
    Builds a flat-shaded arch (half-ring) GeomNode.
    w = span width, h = thickness, d = arch height (rise).
    The arch curves from (-w/2, 0) to (+w/2, 0) rising to d at center.
    """
    import math
    fmt = GeomVertexFormat.getV3c4()
    # Each segment = 4 verts (outer quad) + 4 verts (inner quad) + side caps
    num_verts = segments * 8 + 8
    vdata = GeomVertexData("arch", fmt, Geom.UHStatic)
    vdata.setNumRows(num_verts)

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    hw, hh, hd = w / 2, h / 2, d / 2
    r, g, b = color
    inner_radius = hw * 0.7
    outer_radius = hw

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    for i in range(segments):
        a0 = math.pi * i / segments
        a1 = math.pi * (i + 1) / segments

        # Outer edge points
        ox0 = -math.cos(a0) * outer_radius
        oz0 = math.sin(a0) * d
        ox1 = -math.cos(a1) * outer_radius
        oz1 = math.sin(a1) * d

        # Inner edge points
        ix0 = -math.cos(a0) * inner_radius
        iz0 = math.sin(a0) * d * 0.85
        ix1 = -math.cos(a1) * inner_radius
        iz1 = math.sin(a1) * d * 0.85

        # Outer face (front)
        shade = 0.8
        for v in [(ox0, -hh, oz0), (ox1, -hh, oz1), (ox1, hh, oz1), (ox0, hh, oz0)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx+1, idx+2)
        tris.addVertices(idx, idx+2, idx+3)
        idx += 4

        # Inner face (underside of arch)
        shade = 0.4
        for v in [(ix1, -hh, iz1), (ix0, -hh, iz0), (ix0, hh, iz0), (ix1, hh, iz1)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx+1, idx+2)
        tris.addVertices(idx, idx+2, idx+3)
        idx += 4

    # End caps (left and right pillars of the arch)
    for side, shade in [(-1, 0.6), (1, 0.6)]:
        a = 0.0 if side == -1 else math.pi
        ox = -math.cos(a) * outer_radius
        oz = math.sin(a) * d
        ix = -math.cos(a) * inner_radius
        iz = math.sin(a) * d * 0.85
        for v in [(ox, -hh, oz), (ix, -hh, iz), (ix, hh, iz), (ox, hh, oz)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx+1, idx+2)
        tris.addVertices(idx, idx+2, idx+3)
        idx += 4

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("arch")
    node.addGeom(geom)
    return node


class BiomeRenderer:
    """
    Procedural Panda3D geometry renderer for biome scenes.
    No texture dependencies. Pure colored geometry.
    Lo-fi PS1/PS2 flat-shaded aesthetic.
    """

    def __init__(self, render_root, biome_key="VOID", seed=42):
        self.render_root = render_root
        self.palette = BIOME_PALETTE.get(biome_key, DEFAULT_PALETTE)
        self.rng = random.Random(seed)
        self.nodes = []

    def clear(self):
        """Remove all rendered geometry."""
        for np in self.nodes:
            np.removeNode()
        self.nodes = []

    def render_floor(self, radius=60):
        """Renders the ground plane."""
        node = _make_plane_geom(radius * 2, radius * 2, self.palette["floor"])
        np = self.render_root.attachNewNode(node)
        np.setPos(0, 0, 0)
        self.nodes.append(np)
        return np

    def render_scatter(self, count=20, radius=40):
        """
        Scatters accent-colored boxes around origin.
        Count and scale driven by biome palette.
        """
        scale = self.palette["scale"]
        color = self.palette["accent"]

        for _ in range(count):
            w = self.rng.uniform(0.5, 3.0) * scale
            h = self.rng.uniform(0.5, 5.0) * scale
            d = self.rng.uniform(0.5, 3.0) * scale

            x = self.rng.uniform(-radius, radius)
            y = self.rng.uniform(-radius, radius)

            # Keep objects out of immediate player space
            if abs(x) < 3 and abs(y) < 3:
                x += 5 * (1 if x >= 0 else -1)

            node = _make_box_geom(w, h, d, color)
            np = self.render_root.attachNewNode(node)
            np.setPos(x, y, h / 2)
            np.setHpr(
                self.rng.uniform(0, 360),
                self.rng.uniform(-5, 5),
                self.rng.uniform(-5, 5),
            )
            self.nodes.append(np)

        return self.nodes

    def render_scene(self, encounter_density=0.3, seed=None):
        """
        Full scene render — floor + scatter.
        encounter_density (0-1) scales object count.
        """
        if seed is not None:
            self.rng = random.Random(seed)

        count = int(5 + encounter_density * 40)
        self.render_floor()
        self.render_scatter(count=count)
        return self.nodes
