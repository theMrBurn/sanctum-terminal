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

_make_box_geom   = make_box
_make_plane_geom = make_plane
_make_wedge_geom = make_wedge
_make_spike_geom = make_spike
_make_arch_geom  = make_arch
