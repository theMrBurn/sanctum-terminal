"""
core/systems/geometry.py

Flat-shaded procedural geometry for all primitive types.

7 primitive types, 4 real shapes + 3 scale aliases:
    BLOCK / SLAB / PILLAR / PLANE = box variants
    WEDGE = triangular prism
    SPIKE = square-base pyramid
    ARCH  = segmented half-ring

All geometry is vertex-colored with per-vertex noise for surface variation.
No textures. No normal maps. Color, shape, and depth do the work.
"""

import math
import random

from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
)


# -- Vertex color noise --------------------------------------------------------

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


# -- Box -----------------------------------------------------------------------

def make_box(w, h, d, color):
    """Builds a flat-shaded colored box GeomNode."""
    fmt = GeomVertexFormat.getV3c4()
    vdata = GeomVertexData("box", fmt, Geom.UHStatic)
    vdata.setNumRows(24)

    vwriter = GeomVertexWriter(vdata, "vertex")
    cwriter = GeomVertexWriter(vdata, "color")

    hw, hh, hd = w / 2, h / 2, d / 2
    r, g, b = color

    faces = [
        [(-hw, -hd, -hh), (hw, -hd, -hh), (hw, -hd, hh), (-hw, -hd, hh)],
        [(hw, hd, -hh), (-hw, hd, -hh), (-hw, hd, hh), (hw, hd, hh)],
        [(-hw, hd, -hh), (-hw, -hd, -hh), (-hw, -hd, hh), (-hw, hd, hh)],
        [(hw, -hd, -hh), (hw, hd, -hh), (hw, hd, hh), (hw, -hd, hh)],
        [(-hw, hd, -hh), (hw, hd, -hh), (hw, -hd, -hh), (-hw, -hd, -hh)],
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


# -- Pebble cluster (composite brick from many small stones) -------------------

def make_pebble_cluster(w, h, d, color, count=20, seed=0,
                        scatter=0.0):
    """
    Builds a brick-shaped cluster of tiny pebble boxes.

    When scatter=0.0, pebbles pack tightly into a brick shape (intact).
    When scatter=1.0, pebbles spread outward from center (crumbled).
    Intermediate values give partial disintegration.

    Uses golden angle phyllotaxis for natural non-overlapping fill.
    Each pebble gets gaussian-weighted size: bigger near center, smaller at edges.

    Returns a GeomNode containing all pebbles as one merged mesh (fast render).
    """
    PHI_ANGLE = 137.5077640500378
    angle_rad = math.radians(PHI_ANGLE)
    phase = math.radians(PHI_ANGLE * seed)
    rng = random.Random(seed)

    fmt = GeomVertexFormat.getV3c4()
    vdata = GeomVertexData("pebble_cluster", fmt, Geom.UHStatic)
    vdata.setNumRows(count * 24)

    vwriter = GeomVertexWriter(vdata, "vertex")
    cwriter = GeomVertexWriter(vdata, "color")
    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    r, g, b = color
    hw, hh, hd_half = w / 2, h / 2, d / 2

    for i in range(count):
        # Golden spiral position within brick footprint
        t = (i + 0.5) / count
        radius = math.sqrt(t)  # even density fill
        theta = i * angle_rad + phase
        # Map to brick-shaped footprint (elliptical)
        lx = radius * math.cos(theta) * hw
        lz = radius * math.sin(theta) * hh
        ly = rng.uniform(-hd_half, hd_half) * 0.6

        # Gaussian: bigger pebbles near center, smaller at edges
        dist_from_center = math.sqrt((lx / hw) ** 2 + (lz / hh) ** 2)
        size_weight = math.exp(-2.0 * dist_from_center * dist_from_center)
        base_size = 0.3 + size_weight * 0.7  # 0.3-1.0

        # Scatter: push pebbles outward from center
        if scatter > 0.0:
            push = scatter * rng.uniform(0.5, 2.0)
            lx += lx * push
            lz += lz * push
            ly += rng.uniform(-0.1, 0.1) * scatter
            # Scattered pebbles are smaller (broken)
            base_size *= max(0.3, 1.0 - scatter * 0.5)

        # Pebble dimensions — irregular, never uniform
        pw = w / count * 2.5 * base_size * rng.uniform(0.6, 1.4)
        ph = h / count * 2.5 * base_size * rng.uniform(0.6, 1.4)
        pd = d * 0.4 * base_size * rng.uniform(0.5, 1.3)
        phw, phh, phd = pw / 2, ph / 2, pd / 2

        # Per-pebble color variation — wider range for natural stone
        shade_var = rng.uniform(-0.06, 0.06)
        warm_var = rng.uniform(-0.02, 0.03)  # warm/cool drift
        pr = max(0.0, r + shade_var + warm_var)
        pg = max(0.0, g + shade_var)
        pb = max(0.0, b + shade_var - warm_var * 0.5)

        # Clean box faces — no skew, soft shading (worn stone, not sharp crystal)
        faces = [
            [(lx - phw, ly - phd, lz - phh), (lx + phw, ly - phd, lz - phh),
             (lx + phw, ly - phd, lz + phh), (lx - phw, ly - phd, lz + phh)],
            [(lx + phw, ly + phd, lz - phh), (lx - phw, ly + phd, lz - phh),
             (lx - phw, ly + phd, lz + phh), (lx + phw, ly + phd, lz + phh)],
            [(lx - phw, ly + phd, lz - phh), (lx - phw, ly - phd, lz - phh),
             (lx - phw, ly - phd, lz + phh), (lx - phw, ly + phd, lz + phh)],
            [(lx + phw, ly - phd, lz - phh), (lx + phw, ly + phd, lz - phh),
             (lx + phw, ly + phd, lz + phh), (lx + phw, ly - phd, lz + phh)],
            [(lx - phw, ly + phd, lz - phh), (lx + phw, ly + phd, lz - phh),
             (lx + phw, ly - phd, lz - phh), (lx - phw, ly - phd, lz - phh)],
            [(lx - phw, ly - phd, lz + phh), (lx + phw, ly - phd, lz + phh),
             (lx + phw, ly + phd, lz + phh), (lx - phw, ly + phd, lz + phh)],
        ]
        # Soft shading — narrower range so no face reads as pitch black
        face_shading = [0.75, 0.75, 0.65, 0.65, 0.55, 1.0]

        for face, shade in zip(faces, face_shading):
            for v in face:
                vwriter.addData3(*v)
                cr, cg, cb = _noisy_color(pr, pg, pb, shade)
                cwriter.addData4(cr, cg, cb, 1.0)
            tris.addVertices(idx, idx + 1, idx + 2)
            tris.addVertices(idx, idx + 2, idx + 3)
            idx += 4

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("pebble_cluster")
    node.addGeom(geom)
    return node


# -- Plane ---------------------------------------------------------------------

def make_plane(w, d, color, subdivisions=12):
    """
    Builds a subdivided ground plane with per-vertex color/height noise.
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
            z = rng.uniform(-0.08, 0.08)
            vw.addData3(x, y, z)
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


# -- Wedge ---------------------------------------------------------------------

def make_wedge(w, h, d, color):
    """
    Builds a flat-shaded triangular prism (wedge) GeomNode.
    Full width at base, tapers to ridge at top.
    """
    fmt = GeomVertexFormat.getV3c4()
    vdata = GeomVertexData("wedge", fmt, Geom.UHStatic)
    vdata.setNumRows(18)

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    hw, hh, hd = w / 2, h / 2, d / 2
    r, g, b = color

    faces_quads = [
        ([(-hw, -hd, -hh), (hw, -hd, -hh), (hw, hd, -hh), (-hw, hd, -hh)], 0.3),
        ([(-hw, -hd, -hh), (-hw, hd, -hh), (0, hd, hh), (0, -hd, hh)], 0.6),
        ([(hw, hd, -hh), (hw, -hd, -hh), (0, -hd, hh), (0, hd, hh)], 0.8),
    ]

    faces_tris = [
        ([(-hw, -hd, -hh), (hw, -hd, -hh), (0, -hd, hh)], 0.5),
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


# -- Spike ---------------------------------------------------------------------

def make_spike(w, h, d, color):
    """
    Builds a flat-shaded pyramid GeomNode.
    Square base at z=-h/2, apex at z=+h/2.
    """
    fmt = GeomVertexFormat.getV3c4()
    vdata = GeomVertexData("spike", fmt, Geom.UHStatic)
    vdata.setNumRows(16)

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    hw, hh, hd = w / 2, h / 2, d / 2
    r, g, b = color
    apex = (0, 0, hh)

    base = [(-hw, -hd, -hh), (hw, -hd, -hh), (hw, hd, -hh), (-hw, hd, -hh)]

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    shade = 0.3
    cr, cg, cb = r * shade, g * shade, b * shade
    for v in base:
        vw.addData3(*v)
        cw.addData4(cr, cg, cb, 1.0)
    tris.addVertices(idx, idx + 1, idx + 2)
    tris.addVertices(idx, idx + 2, idx + 3)
    idx += 4

    side_faces = [
        ([base[0], base[1], apex], 0.7),
        ([base[1], base[2], apex], 0.5),
        ([base[2], base[3], apex], 0.7),
        ([base[3], base[0], apex], 1.0),
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


# -- Arch ----------------------------------------------------------------------

def make_arch(w, h, d, color, segments=8):
    """
    Builds a flat-shaded arch (half-ring) GeomNode.
    w = span width, h = thickness, d = arch height (rise).
    """
    fmt = GeomVertexFormat.getV3c4()
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

        ox0 = -math.cos(a0) * outer_radius
        oz0 = math.sin(a0) * d
        ox1 = -math.cos(a1) * outer_radius
        oz1 = math.sin(a1) * d

        ix0 = -math.cos(a0) * inner_radius
        iz0 = math.sin(a0) * d * 0.85
        ix1 = -math.cos(a1) * inner_radius
        iz1 = math.sin(a1) * d * 0.85

        shade = 0.8
        for v in [(ox0, -hh, oz0), (ox1, -hh, oz1), (ox1, hh, oz1), (ox0, hh, oz0)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx+1, idx+2)
        tris.addVertices(idx, idx+2, idx+3)
        idx += 4

        shade = 0.4
        for v in [(ix1, -hh, iz1), (ix0, -hh, iz0), (ix0, hh, iz0), (ix1, hh, iz1)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx+1, idx+2)
        tris.addVertices(idx, idx+2, idx+3)
        idx += 4

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


# -- Legacy aliases (backward compatibility) -----------------------------------
# These maintain the old _make_*_geom names so existing imports don't break.

def make_textured_quad(w, h, name="tquad"):
    """
    Builds a single textured quad (two triangles) with UV coords.
    Centered at origin, facing -Y (toward camera in corridor view).
    """
    fmt = GeomVertexFormat.getV3t2()
    vdata = GeomVertexData(name, fmt, Geom.UHStatic)
    vdata.setNumRows(4)

    vw = GeomVertexWriter(vdata, "vertex")
    tw = GeomVertexWriter(vdata, "texcoord")

    hw, hh = w / 2, h / 2
    # Quad corners: bottom-left, bottom-right, top-right, top-left
    vw.addData3(-hw, 0, -hh)
    tw.addData2(0, 0)
    vw.addData3(hw, 0, -hh)
    tw.addData2(1, 0)
    vw.addData3(hw, 0, hh)
    tw.addData2(1, 1)
    vw.addData3(-hw, 0, hh)
    tw.addData2(0, 1)

    tris = GeomTriangles(Geom.UHStatic)
    tris.addVertices(0, 1, 2)
    tris.addVertices(0, 2, 3)

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode(name)
    node.addGeom(geom)
    return node


def make_textured_wall(w, h, tile_x=1.0, tile_y=1.0, name="twall"):
    """
    Builds a textured quad with tiling UV coords.
    Facing -Y. tile_x/tile_y control how many times texture repeats.
    """
    fmt = GeomVertexFormat.getV3t2()
    vdata = GeomVertexData(name, fmt, Geom.UHStatic)
    vdata.setNumRows(4)

    vw = GeomVertexWriter(vdata, "vertex")
    tw = GeomVertexWriter(vdata, "texcoord")

    hw, hh = w / 2, h / 2
    vw.addData3(-hw, 0, -hh)
    tw.addData2(0, 0)
    vw.addData3(hw, 0, -hh)
    tw.addData2(tile_x, 0)
    vw.addData3(hw, 0, hh)
    tw.addData2(tile_x, tile_y)
    vw.addData3(-hw, 0, hh)
    tw.addData2(0, tile_y)

    tris = GeomTriangles(Geom.UHStatic)
    tris.addVertices(0, 1, 2)
    tris.addVertices(0, 2, 3)

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode(name)
    node.addGeom(geom)
    return node


def make_textured_floor(w, d, tile_x=1.0, tile_y=1.0, name="tfloor"):
    """
    Builds a horizontal textured quad (floor or ceiling).
    Lies flat in the XY plane at z=0, facing +Z (upward).
    """
    fmt = GeomVertexFormat.getV3t2()
    vdata = GeomVertexData(name, fmt, Geom.UHStatic)
    vdata.setNumRows(4)

    vw = GeomVertexWriter(vdata, "vertex")
    tw = GeomVertexWriter(vdata, "texcoord")

    hw, hd = w / 2, d / 2
    vw.addData3(-hw, -hd, 0)
    tw.addData2(0, 0)
    vw.addData3(hw, -hd, 0)
    tw.addData2(tile_x, 0)
    vw.addData3(hw, hd, 0)
    tw.addData2(tile_x, tile_y)
    vw.addData3(-hw, hd, 0)
    tw.addData2(0, tile_y)

    tris = GeomTriangles(Geom.UHStatic)
    tris.addVertices(0, 1, 2)
    tris.addVertices(0, 2, 3)

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode(name)
    node.addGeom(geom)
    return node


# ==============================================================================
# TEXTURED 3D PRIMITIVES — V3n3t2 format (vertex + normal + texcoord)
# These are the manufacturing primitives. Any PNG maps onto any part.
# ==============================================================================

def _add_vert_nt(vw, nw, tw, pos, normal, uv):
    """Helper: add one vertex with position, normal, and texcoord."""
    vw.addData3(*pos)
    nw.addData3(*normal)
    tw.addData2(*uv)


def make_textured_box(w, h, d, name="tbox"):
    """
    UV-mapped box with normals on all 6 faces.
    Each face gets the full [0,1] UV range — texture maps per-face.
    """
    fmt = GeomVertexFormat.getV3n3t2()
    vdata = GeomVertexData(name, fmt, Geom.UHStatic)
    vdata.setNumRows(24)

    vw = GeomVertexWriter(vdata, "vertex")
    nw = GeomVertexWriter(vdata, "normal")
    tw = GeomVertexWriter(vdata, "texcoord")

    hw, hh, hd = w / 2, h / 2, d / 2

    # 6 faces: (4 verts each, normal, UV corners)
    # Front (-Y face, toward camera)
    faces = [
        {
            "normal": (0, -1, 0),
            "verts": [(-hw, -hd, -hh), (hw, -hd, -hh), (hw, -hd, hh), (-hw, -hd, hh)],
        },
        {
            "normal": (0, 1, 0),
            "verts": [(hw, hd, -hh), (-hw, hd, -hh), (-hw, hd, hh), (hw, hd, hh)],
        },
        {
            "normal": (-1, 0, 0),
            "verts": [(-hw, hd, -hh), (-hw, -hd, -hh), (-hw, -hd, hh), (-hw, hd, hh)],
        },
        {
            "normal": (1, 0, 0),
            "verts": [(hw, -hd, -hh), (hw, hd, -hh), (hw, hd, hh), (hw, -hd, hh)],
        },
        {
            "normal": (0, 0, -1),
            "verts": [(-hw, hd, -hh), (hw, hd, -hh), (hw, -hd, -hh), (-hw, -hd, -hh)],
        },
        {
            "normal": (0, 0, 1),
            "verts": [(-hw, -hd, hh), (hw, -hd, hh), (hw, hd, hh), (-hw, hd, hh)],
        },
    ]

    uvs = [(0, 0), (1, 0), (1, 1), (0, 1)]

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0
    for face in faces:
        n = face["normal"]
        for v, uv in zip(face["verts"], uvs):
            _add_vert_nt(vw, nw, tw, v, n, uv)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode(name)
    node.addGeom(geom)
    return node


def make_textured_wedge(w, h, d, name="twedge"):
    """
    UV-mapped triangular prism (wedge) with normals.
    Full width at base, tapers to ridge at top.
    """
    fmt = GeomVertexFormat.getV3n3t2()
    vdata = GeomVertexData(name, fmt, Geom.UHStatic)
    vdata.setNumRows(18)

    vw = GeomVertexWriter(vdata, "vertex")
    nw = GeomVertexWriter(vdata, "normal")
    tw = GeomVertexWriter(vdata, "texcoord")

    hw, hh, hd = w / 2, h / 2, d / 2

    # Quad faces (bottom, left slope, right slope)
    quad_faces = [
        {   # Bottom
            "normal": (0, 0, -1),
            "verts": [(-hw, -hd, -hh), (hw, -hd, -hh), (hw, hd, -hh), (-hw, hd, -hh)],
        },
        {   # Left slope
            "normal": (-0.707, 0, 0.707),
            "verts": [(-hw, -hd, -hh), (-hw, hd, -hh), (0, hd, hh), (0, -hd, hh)],
        },
        {   # Right slope
            "normal": (0.707, 0, 0.707),
            "verts": [(hw, hd, -hh), (hw, -hd, -hh), (0, -hd, hh), (0, hd, hh)],
        },
    ]

    # Triangle faces (front, back)
    tri_faces = [
        {   # Front
            "normal": (0, -1, 0),
            "verts": [(-hw, -hd, -hh), (hw, -hd, -hh), (0, -hd, hh)],
        },
        {   # Back
            "normal": (0, 1, 0),
            "verts": [(hw, hd, -hh), (-hw, hd, -hh), (0, hd, hh)],
        },
    ]

    uvs_quad = [(0, 0), (1, 0), (1, 1), (0, 1)]
    uvs_tri = [(0, 0), (1, 0), (0.5, 1)]

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    for face in quad_faces:
        n = face["normal"]
        for v, uv in zip(face["verts"], uvs_quad):
            _add_vert_nt(vw, nw, tw, v, n, uv)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

    for face in tri_faces:
        n = face["normal"]
        for v, uv in zip(face["verts"], uvs_tri):
            _add_vert_nt(vw, nw, tw, v, n, uv)
        tris.addVertices(idx, idx + 1, idx + 2)
        idx += 3

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode(name)
    node.addGeom(geom)
    return node


def make_textured_spike(w, h, d, name="tspike"):
    """
    UV-mapped square-base pyramid with normals.
    Base at z=-h/2, apex at z=+h/2.
    """
    fmt = GeomVertexFormat.getV3n3t2()
    vdata = GeomVertexData(name, fmt, Geom.UHStatic)
    vdata.setNumRows(16)

    vw = GeomVertexWriter(vdata, "vertex")
    nw = GeomVertexWriter(vdata, "normal")
    tw = GeomVertexWriter(vdata, "texcoord")

    hw, hh, hd = w / 2, h / 2, d / 2
    apex = (0, 0, hh)
    base = [(-hw, -hd, -hh), (hw, -hd, -hh), (hw, hd, -hh), (-hw, hd, -hh)]

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    # Base face
    n = (0, 0, -1)
    for v, uv in zip(base, [(0, 0), (1, 0), (1, 1), (0, 1)]):
        _add_vert_nt(vw, nw, tw, v, n, uv)
    tris.addVertices(idx, idx + 1, idx + 2)
    tris.addVertices(idx, idx + 2, idx + 3)
    idx += 4

    # 4 triangular side faces
    # Approximate normals pointing outward from each face
    side_normals = [
        (0, -1, 0.5),   # front
        (1, 0, 0.5),    # right
        (0, 1, 0.5),    # back
        (-1, 0, 0.5),   # left
    ]
    for i in range(4):
        v0 = base[i]
        v1 = base[(i + 1) % 4]
        sn = side_normals[i]
        # Normalize
        mag = (sn[0]**2 + sn[1]**2 + sn[2]**2) ** 0.5
        sn = (sn[0]/mag, sn[1]/mag, sn[2]/mag)

        _add_vert_nt(vw, nw, tw, v0, sn, (0, 0))
        _add_vert_nt(vw, nw, tw, v1, sn, (1, 0))
        _add_vert_nt(vw, nw, tw, apex, sn, (0.5, 1))
        tris.addVertices(idx, idx + 1, idx + 2)
        idx += 3

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode(name)
    node.addGeom(geom)
    return node


def make_textured_arch(w, h, d, segments=8, name="tarch"):
    """
    UV-mapped arch (half-ring) with normals.
    w = span width, h = thickness, d = arch height (rise).
    """
    fmt = GeomVertexFormat.getV3n3t2()
    num_verts = segments * 8 + 8
    vdata = GeomVertexData(name, fmt, Geom.UHStatic)
    vdata.setNumRows(num_verts)

    vw = GeomVertexWriter(vdata, "vertex")
    nw = GeomVertexWriter(vdata, "normal")
    tw = GeomVertexWriter(vdata, "texcoord")

    hw, hh, hd = w / 2, h / 2, d / 2
    inner_radius = hw * 0.7
    outer_radius = hw

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    for i in range(segments):
        a0 = math.pi * i / segments
        a1 = math.pi * (i + 1) / segments

        ox0 = -math.cos(a0) * outer_radius
        oz0 = math.sin(a0) * d
        ox1 = -math.cos(a1) * outer_radius
        oz1 = math.sin(a1) * d

        ix0 = -math.cos(a0) * inner_radius
        iz0 = math.sin(a0) * d * 0.85
        ix1 = -math.cos(a1) * inner_radius
        iz1 = math.sin(a1) * d * 0.85

        u0 = i / segments
        u1 = (i + 1) / segments

        # Normal pointing outward from center
        mid_a = (a0 + a1) / 2
        on = (-math.cos(mid_a), 0, math.sin(mid_a))

        # Outer face
        for v, uv in zip(
            [(ox0, -hh, oz0), (ox1, -hh, oz1), (ox1, hh, oz1), (ox0, hh, oz0)],
            [(u0, 0), (u1, 0), (u1, 1), (u0, 1)],
        ):
            _add_vert_nt(vw, nw, tw, v, on, uv)
        tris.addVertices(idx, idx+1, idx+2)
        tris.addVertices(idx, idx+2, idx+3)
        idx += 4

        # Inner face (normal points inward)
        in_ = (math.cos(mid_a), 0, -math.sin(mid_a))
        for v, uv in zip(
            [(ix1, -hh, iz1), (ix0, -hh, iz0), (ix0, hh, iz0), (ix1, hh, iz1)],
            [(u1, 0), (u0, 0), (u0, 1), (u1, 1)],
        ):
            _add_vert_nt(vw, nw, tw, v, in_, uv)
        tris.addVertices(idx, idx+1, idx+2)
        tris.addVertices(idx, idx+2, idx+3)
        idx += 4

    # End caps
    for side, sign in [(-1, -1), (1, 1)]:
        a = 0.0 if side == -1 else math.pi
        ox = -math.cos(a) * outer_radius
        oz = math.sin(a) * d
        ix = -math.cos(a) * inner_radius
        iz = math.sin(a) * d * 0.85
        n = (sign, 0, 0)
        for v, uv in zip(
            [(ox, -hh, oz), (ix, -hh, iz), (ix, hh, iz), (ox, hh, oz)],
            [(0, 0), (1, 0), (1, 1), (0, 1)],
        ):
            _add_vert_nt(vw, nw, tw, v, n, uv)
        tris.addVertices(idx, idx+1, idx+2)
        tris.addVertices(idx, idx+2, idx+3)
        idx += 4

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode(name)
    node.addGeom(geom)
    return node


# -- Textured primitive dispatch -----------------------------------------------

TEXTURED_BUILDERS = {
    "BLOCK":  make_textured_box,
    "SLAB":   make_textured_box,
    "PILLAR": make_textured_box,
    "WEDGE":  make_textured_wedge,
    "SPIKE":  make_textured_spike,
    "ARCH":   make_textured_arch,
}


_make_box_geom   = make_box
_make_plane_geom = make_plane
_make_wedge_geom = make_wedge
_make_spike_geom = make_spike
_make_arch_geom  = make_arch
