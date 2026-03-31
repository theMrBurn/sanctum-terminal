"""
core/systems/geometry.py

Flat-shaded procedural geometry for all primitive types.

21 primitive types across 3 sets:

Set 1 — core solids:
    BLOCK / SLAB / PILLAR / PLANE = box variants
    WEDGE   = triangular prism
    SPIKE   = square-base pyramid
    ARCH    = segmented half-ring

Set 2 — organic/terrain:
    CYLINDER = vertical cylinder (oval-capable)
    CONE     = tapered cone
    SPHERE   = UV sphere (egg-capable)
    TORUS    = donut ring
    CAPSULE  = cylinder with hemisphere caps
    DOME     = half sphere (open bottom)
    TUBE     = hollow cylinder

Set 3 — structural/detail:
    RAMP     = smooth incline
    CROSS    = two intersecting boxes
    LATTICE  = grid of thin bars
    STAIR    = stepped block
    BEVEL_BOX = chamfered-edge box
    FIN      = tapered blade
    RING     = flat annular washer

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


# ==============================================================================
# SET 2 — ORGANIC / TERRAIN PRIMITIVES
# ==============================================================================


# -- Cylinder ------------------------------------------------------------------

def make_cylinder(w, h, d, color, segments=12):
    """
    Builds a flat-shaded vertical cylinder GeomNode.
    w = diameter along X, d = diameter along Y (oval when w != d), h = height.
    """
    fmt = GeomVertexFormat.getV3c4()
    # segments side quads (4 verts each) + 2 caps (segments * 3 verts each)
    num_verts = segments * 4 + segments * 3 * 2
    vdata = GeomVertexData("cylinder", fmt, Geom.UHStatic)
    vdata.setNumRows(num_verts)

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    rx, ry = w / 2, d / 2
    hh = h / 2
    r, g, b = color

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    # Side faces — each segment is a flat-shaded quad
    for i in range(segments):
        a0 = 2.0 * math.pi * i / segments
        a1 = 2.0 * math.pi * (i + 1) / segments

        x0, y0 = math.cos(a0) * rx, math.sin(a0) * ry
        x1, y1 = math.cos(a1) * rx, math.sin(a1) * ry

        # Shade based on facing direction (use midpoint angle)
        mid_a = (a0 + a1) / 2
        # Map angle to shade: front=0.85, right=0.75, back=0.65, left=0.70
        nx = math.cos(mid_a)
        ny = math.sin(mid_a)
        shade = 0.75 + 0.10 * nx - 0.10 * ny  # blend directional shading

        for v in [(x0, y0, -hh), (x1, y1, -hh), (x1, y1, hh), (x0, y0, hh)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

    # Top cap — fan of triangles, shade = 1.0
    for i in range(segments):
        a0 = 2.0 * math.pi * i / segments
        a1 = 2.0 * math.pi * (i + 1) / segments
        for v in [(0, 0, hh),
                   (math.cos(a0) * rx, math.sin(a0) * ry, hh),
                   (math.cos(a1) * rx, math.sin(a1) * ry, hh)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, 1.0)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        idx += 3

    # Bottom cap — fan of triangles, shade = 0.55
    for i in range(segments):
        a0 = 2.0 * math.pi * i / segments
        a1 = 2.0 * math.pi * (i + 1) / segments
        for v in [(0, 0, -hh),
                   (math.cos(a1) * rx, math.sin(a1) * ry, -hh),
                   (math.cos(a0) * rx, math.sin(a0) * ry, -hh)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, 0.55)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        idx += 3

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("cylinder")
    node.addGeom(geom)
    return node


# -- Cone ----------------------------------------------------------------------

def make_cone(w, h, d, color, segments=12):
    """
    Builds a flat-shaded cone GeomNode.
    w/d = base diameters (X/Y), h = height. Apex at top.
    """
    fmt = GeomVertexFormat.getV3c4()
    num_verts = segments * 3 + segments * 3  # side tris + base fan
    vdata = GeomVertexData("cone", fmt, Geom.UHStatic)
    vdata.setNumRows(num_verts)

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    rx, ry = w / 2, d / 2
    hh = h / 2
    r, g, b = color
    apex = (0, 0, hh)

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    # Side faces — triangles from base edge to apex
    for i in range(segments):
        a0 = 2.0 * math.pi * i / segments
        a1 = 2.0 * math.pi * (i + 1) / segments

        x0, y0 = math.cos(a0) * rx, math.sin(a0) * ry
        x1, y1 = math.cos(a1) * rx, math.sin(a1) * ry

        mid_a = (a0 + a1) / 2
        nx = math.cos(mid_a)
        ny = math.sin(mid_a)
        shade = 0.75 + 0.10 * nx - 0.10 * ny

        for v in [(x0, y0, -hh), (x1, y1, -hh), apex]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        idx += 3

    # Bottom cap
    for i in range(segments):
        a0 = 2.0 * math.pi * i / segments
        a1 = 2.0 * math.pi * (i + 1) / segments
        for v in [(0, 0, -hh),
                   (math.cos(a1) * rx, math.sin(a1) * ry, -hh),
                   (math.cos(a0) * rx, math.sin(a0) * ry, -hh)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, 0.55)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        idx += 3

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("cone")
    node.addGeom(geom)
    return node


# -- Sphere --------------------------------------------------------------------

def make_sphere(w, h, d, color, rings=8, segments=12):
    """
    Builds a flat-shaded UV sphere GeomNode.
    w/h/d = radii per axis (egg shapes when non-uniform).
    Quads split into two triangles for flat shading.
    """
    fmt = GeomVertexFormat.getV3c4()
    # Each quad = 2 tris = 6 verts (no shared verts for flat shading)
    # Top/bottom caps: segments tris each. Middle bands: (rings-2) * segments quads.
    num_tris = segments * 2 + (rings - 2) * segments * 2
    vdata = GeomVertexData("sphere", fmt, Geom.UHStatic)
    vdata.setNumRows(num_tris * 3)

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    rx, rz, ry = w / 2, h / 2, d / 2
    r, g, b = color

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    def _sphere_pt(ring_i, seg_j):
        phi = math.pi * ring_i / rings
        theta = 2.0 * math.pi * seg_j / segments
        sp = math.sin(phi)
        return (
            math.cos(theta) * sp * rx,
            math.sin(theta) * sp * ry,
            math.cos(phi) * rz,
        )

    def _shade_for_z(z_frac):
        """Map vertical position to shade. Top=1.0, bottom=0.55."""
        return 0.55 + 0.45 * (z_frac * 0.5 + 0.5)

    for i in range(rings):
        for j in range(segments):
            p00 = _sphere_pt(i, j)
            p10 = _sphere_pt(i + 1, j)
            p11 = _sphere_pt(i + 1, j + 1)
            p01 = _sphere_pt(i, j + 1)

            # Shade based on face center Z
            cz = (p00[2] + p10[2] + p11[2] + p01[2]) / (4.0 * rz) if rz else 0
            shade = _shade_for_z(cz)

            if i == 0:
                # Top cap triangle
                for v in [p00, p10, p11]:
                    vw.addData3(*v)
                    cr, cg, cb = _noisy_color(r, g, b, shade)
                    cw.addData4(cr, cg, cb, 1.0)
                tris.addVertices(idx, idx + 1, idx + 2)
                idx += 3
            elif i == rings - 1:
                # Bottom cap triangle
                for v in [p00, p10, p01]:
                    vw.addData3(*v)
                    cr, cg, cb = _noisy_color(r, g, b, shade)
                    cw.addData4(cr, cg, cb, 1.0)
                tris.addVertices(idx, idx + 1, idx + 2)
                idx += 3
            else:
                # Middle band — two triangles per quad
                for v in [p00, p10, p11]:
                    vw.addData3(*v)
                    cr, cg, cb = _noisy_color(r, g, b, shade)
                    cw.addData4(cr, cg, cb, 1.0)
                tris.addVertices(idx, idx + 1, idx + 2)
                idx += 3

                for v in [p00, p11, p01]:
                    vw.addData3(*v)
                    cr, cg, cb = _noisy_color(r, g, b, shade)
                    cw.addData4(cr, cg, cb, 1.0)
                tris.addVertices(idx, idx + 1, idx + 2)
                idx += 3

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("sphere")
    node.addGeom(geom)
    return node


# -- Torus ---------------------------------------------------------------------

def make_torus(w, h, d, color, ring_segments=16, tube_segments=8):
    """
    Builds a flat-shaded torus GeomNode.
    w = major radius, h = tube radius, d = depth scale.
    """
    fmt = GeomVertexFormat.getV3c4()
    num_quads = ring_segments * tube_segments
    vdata = GeomVertexData("torus", fmt, Geom.UHStatic)
    vdata.setNumRows(num_quads * 6)  # 2 tris per quad, 3 verts each

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    R = w   # major radius
    tr = h  # tube radius
    r, g, b = color

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    def _torus_pt(ri, ti):
        theta = 2.0 * math.pi * ri / ring_segments
        phi = 2.0 * math.pi * ti / tube_segments
        cx = math.cos(theta) * R
        cy = math.sin(theta) * R * d
        dist = R + tr * math.cos(phi)
        return (
            math.cos(theta) * dist,
            math.sin(theta) * dist * (d / max(w, 0.001)),
            tr * math.sin(phi),
        )

    for i in range(ring_segments):
        for j in range(tube_segments):
            p00 = _torus_pt(i, j)
            p10 = _torus_pt(i + 1, j)
            p11 = _torus_pt(i + 1, j + 1)
            p01 = _torus_pt(i, j + 1)

            # Shade by tube angle — top of tube bright, bottom dark
            mid_phi = 2.0 * math.pi * (j + 0.5) / tube_segments
            shade = 0.55 + 0.45 * (math.sin(mid_phi) * 0.5 + 0.5)

            for v in [p00, p10, p11]:
                vw.addData3(*v)
                cr, cg, cb = _noisy_color(r, g, b, shade)
                cw.addData4(cr, cg, cb, 1.0)
            tris.addVertices(idx, idx + 1, idx + 2)
            idx += 3

            for v in [p00, p11, p01]:
                vw.addData3(*v)
                cr, cg, cb = _noisy_color(r, g, b, shade)
                cw.addData4(cr, cg, cb, 1.0)
            tris.addVertices(idx, idx + 1, idx + 2)
            idx += 3

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("torus")
    node.addGeom(geom)
    return node


# -- Capsule -------------------------------------------------------------------

def make_capsule(w, h, d, color, segments=12, rings=4):
    """
    Builds a flat-shaded capsule GeomNode (cylinder + hemisphere caps).
    w/d = diameters, h = total height including caps.
    """
    fmt = GeomVertexFormat.getV3c4()
    # Cylinder body: segments quads. Each cap: rings * segments tris/quads.
    body_verts = segments * 4
    cap_verts = rings * segments * 6  # per cap (flat shaded tris)
    vdata = GeomVertexData("capsule", fmt, Geom.UHStatic)
    vdata.setNumRows(body_verts + cap_verts * 2)

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    rx, ry = w / 2, d / 2
    cap_h = min(rx, ry)  # hemisphere radius
    cyl_h = max(0, h - 2.0 * cap_h) / 2  # half-height of cylinder portion
    r, g, b = color

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    # Cylinder body
    for i in range(segments):
        a0 = 2.0 * math.pi * i / segments
        a1 = 2.0 * math.pi * (i + 1) / segments
        x0, y0 = math.cos(a0) * rx, math.sin(a0) * ry
        x1, y1 = math.cos(a1) * rx, math.sin(a1) * ry

        mid_a = (a0 + a1) / 2
        shade = 0.75 + 0.10 * math.cos(mid_a) - 0.10 * math.sin(mid_a)

        for v in [(x0, y0, -cyl_h), (x1, y1, -cyl_h),
                   (x1, y1, cyl_h), (x0, y0, cyl_h)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

    # Hemisphere caps
    def _cap_pt(ring_i, seg_j, top):
        phi = (math.pi / 2) * ring_i / rings
        theta = 2.0 * math.pi * seg_j / segments
        sp = math.cos(phi)
        z_off = cyl_h if top else -cyl_h
        z_sign = 1 if top else -1
        return (
            math.cos(theta) * sp * rx,
            math.sin(theta) * sp * ry,
            z_off + z_sign * math.sin(phi) * cap_h,
        )

    for top in [True, False]:
        for i in range(rings):
            for j in range(segments):
                p00 = _cap_pt(i, j, top)
                p10 = _cap_pt(i + 1, j, top)
                p11 = _cap_pt(i + 1, j + 1, top)
                p01 = _cap_pt(i, j + 1, top)

                shade = 1.0 if top else 0.55
                # Blend shade for middle rings
                frac = (i + 0.5) / rings
                if top:
                    shade = 0.85 + 0.15 * frac
                else:
                    shade = 0.70 - 0.15 * frac

                if i == rings - 1:
                    # Tip triangle
                    verts = [p00, p10, p01] if top else [p00, p01, p10]
                    for v in verts:
                        vw.addData3(*v)
                        cr, cg, cb = _noisy_color(r, g, b, shade)
                        cw.addData4(cr, cg, cb, 1.0)
                    tris.addVertices(idx, idx + 1, idx + 2)
                    idx += 3
                else:
                    # Quad as two tris
                    if top:
                        tri_a = [p00, p10, p11]
                        tri_b = [p00, p11, p01]
                    else:
                        tri_a = [p00, p11, p10]
                        tri_b = [p00, p01, p11]
                    for v in tri_a:
                        vw.addData3(*v)
                        cr, cg, cb = _noisy_color(r, g, b, shade)
                        cw.addData4(cr, cg, cb, 1.0)
                    tris.addVertices(idx, idx + 1, idx + 2)
                    idx += 3
                    for v in tri_b:
                        vw.addData3(*v)
                        cr, cg, cb = _noisy_color(r, g, b, shade)
                        cw.addData4(cr, cg, cb, 1.0)
                    tris.addVertices(idx, idx + 1, idx + 2)
                    idx += 3

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("capsule")
    node.addGeom(geom)
    return node


# -- Dome ----------------------------------------------------------------------

def make_dome(w, h, d, color, rings=6, segments=12):
    """
    Builds a flat-shaded dome (upper hemisphere, open bottom) GeomNode.
    w/h/d = radii per axis.
    """
    fmt = GeomVertexFormat.getV3c4()
    num_tris = segments + (rings - 1) * segments * 2
    vdata = GeomVertexData("dome", fmt, Geom.UHStatic)
    vdata.setNumRows(num_tris * 3)

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    rx, rz, ry = w / 2, h / 2, d / 2
    r, g, b = color

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    def _dome_pt(ring_i, seg_j):
        phi = (math.pi / 2) * ring_i / rings
        theta = 2.0 * math.pi * seg_j / segments
        sp = math.cos(phi)
        return (
            math.cos(theta) * sp * rx,
            math.sin(theta) * sp * ry,
            math.sin(phi) * rz,
        )

    for i in range(rings):
        for j in range(segments):
            p00 = _dome_pt(i, j)
            p10 = _dome_pt(i + 1, j)
            p11 = _dome_pt(i + 1, j + 1)
            p01 = _dome_pt(i, j + 1)

            # Shade by height
            avg_z = (p00[2] + p10[2]) / (2.0 * rz) if rz else 0
            shade = 0.65 + 0.35 * avg_z

            if i == rings - 1:
                # Top cap — single triangle
                for v in [p00, p10, p01]:
                    vw.addData3(*v)
                    cr, cg, cb = _noisy_color(r, g, b, shade)
                    cw.addData4(cr, cg, cb, 1.0)
                tris.addVertices(idx, idx + 1, idx + 2)
                idx += 3
            else:
                for v in [p00, p10, p11]:
                    vw.addData3(*v)
                    cr, cg, cb = _noisy_color(r, g, b, shade)
                    cw.addData4(cr, cg, cb, 1.0)
                tris.addVertices(idx, idx + 1, idx + 2)
                idx += 3

                for v in [p00, p11, p01]:
                    vw.addData3(*v)
                    cr, cg, cb = _noisy_color(r, g, b, shade)
                    cw.addData4(cr, cg, cb, 1.0)
                tris.addVertices(idx, idx + 1, idx + 2)
                idx += 3

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("dome")
    node.addGeom(geom)
    return node


# -- Tube ----------------------------------------------------------------------

def make_tube(w, h, d, color, thickness=0.15, segments=12):
    """
    Builds a flat-shaded hollow cylinder (tube) GeomNode.
    w/d = outer diameters, h = height, thickness = wall fraction of radius.
    """
    fmt = GeomVertexFormat.getV3c4()
    # Outer wall + inner wall + top ring + bottom ring
    num_verts = segments * 4 * 4
    vdata = GeomVertexData("tube", fmt, Geom.UHStatic)
    vdata.setNumRows(num_verts)

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    orx, ory = w / 2, d / 2
    irx, iry = orx * (1.0 - thickness), ory * (1.0 - thickness)
    hh = h / 2
    r, g, b = color

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    for i in range(segments):
        a0 = 2.0 * math.pi * i / segments
        a1 = 2.0 * math.pi * (i + 1) / segments
        c0, s0 = math.cos(a0), math.sin(a0)
        c1, s1 = math.cos(a1), math.sin(a1)

        ox0, oy0 = c0 * orx, s0 * ory
        ox1, oy1 = c1 * orx, s1 * ory
        ix0, iy0 = c0 * irx, s0 * iry
        ix1, iy1 = c1 * irx, s1 * iry

        mid_a = (a0 + a1) / 2
        shade_outer = 0.75 + 0.10 * math.cos(mid_a) - 0.10 * math.sin(mid_a)
        shade_inner = shade_outer * 0.7  # inner wall is darker

        # Outer wall
        for v in [(ox0, oy0, -hh), (ox1, oy1, -hh),
                   (ox1, oy1, hh), (ox0, oy0, hh)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade_outer)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

        # Inner wall (reversed winding)
        for v in [(ix1, iy1, -hh), (ix0, iy0, -hh),
                   (ix0, iy0, hh), (ix1, iy1, hh)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade_inner)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

        # Top ring face
        for v in [(ox0, oy0, hh), (ox1, oy1, hh),
                   (ix1, iy1, hh), (ix0, iy0, hh)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, 1.0)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

        # Bottom ring face
        for v in [(ox1, oy1, -hh), (ox0, oy0, -hh),
                   (ix0, iy0, -hh), (ix1, iy1, -hh)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, 0.55)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("tube")
    node.addGeom(geom)
    return node


# ==============================================================================
# SET 3 — STRUCTURAL / DETAIL PRIMITIVES
# ==============================================================================


# -- Ramp ----------------------------------------------------------------------

def make_ramp(w, h, d, color):
    """
    Builds a flat-shaded ramp (smooth incline) GeomNode.
    Bottom is flat, back wall is vertical, top slopes from 0 at front to h at back.
    w = width, h = max height at back, d = depth/length.
    """
    fmt = GeomVertexFormat.getV3c4()
    vdata = GeomVertexData("ramp", fmt, Geom.UHStatic)
    vdata.setNumRows(18)  # 3 quads + 2 tris

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    hw, hh, hd = w / 2, h / 2, d / 2
    r, g, b = color

    # Vertices: front edge at z=0 (ground), back edge at z=h
    # Bottom: flat quad at z=-hh (ground level, conceptually z=0)
    # Using coordinate system: X=width, Y=depth, Z=height
    # Front at Y=-hd, back at Y=+hd

    faces_quads = [
        # Bottom face (flat)
        ([(-hw, -hd, -hh), (hw, -hd, -hh), (hw, hd, -hh), (-hw, hd, -hh)], 0.55),
        # Slope face (top) — front at ground level, back at full height
        ([(-hw, -hd, -hh), (-hw, hd, hh), (hw, hd, hh), (hw, -hd, -hh)], 1.0),
        # Back wall (vertical)
        ([(hw, hd, -hh), (-hw, hd, -hh), (-hw, hd, hh), (hw, hd, hh)], 0.65),
    ]

    faces_tris = [
        # Left side triangle
        ([(-hw, -hd, -hh), (-hw, hd, -hh), (-hw, hd, hh)], 0.70),
        # Right side triangle
        ([(hw, hd, -hh), (hw, -hd, -hh), (hw, hd, hh)], 0.75),
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
    node = GeomNode("ramp")
    node.addGeom(geom)
    return node


# -- Cross ---------------------------------------------------------------------

def make_cross(w, h, d, color):
    """
    Builds a flat-shaded cross (two intersecting boxes) GeomNode.
    One box is w x h x thickness, the other is thickness x h x d.
    thickness = min(w, d) * 0.25.
    """
    fmt = GeomVertexFormat.getV3c4()
    vdata = GeomVertexData("cross", fmt, Geom.UHStatic)
    vdata.setNumRows(48)  # 2 boxes * 6 faces * 4 verts

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    r, g, b = color
    thickness = min(w, d) * 0.25
    hh = h / 2

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    face_shading = [0.85, 0.65, 0.70, 0.75, 0.55, 1.0]

    # Two boxes: (width, height, depth) for each
    boxes = [
        (w / 2, hh, thickness / 2),   # wide bar
        (thickness / 2, hh, d / 2),   # deep bar
    ]

    for bhw, bhh, bhd in boxes:
        faces = [
            [(-bhw, -bhd, -bhh), (bhw, -bhd, -bhh),
             (bhw, -bhd, bhh), (-bhw, -bhd, bhh)],
            [(bhw, bhd, -bhh), (-bhw, bhd, -bhh),
             (-bhw, bhd, bhh), (bhw, bhd, bhh)],
            [(-bhw, bhd, -bhh), (-bhw, -bhd, -bhh),
             (-bhw, -bhd, bhh), (-bhw, bhd, bhh)],
            [(bhw, -bhd, -bhh), (bhw, bhd, -bhh),
             (bhw, bhd, bhh), (bhw, -bhd, bhh)],
            [(-bhw, bhd, -bhh), (bhw, bhd, -bhh),
             (bhw, -bhd, -bhh), (-bhw, -bhd, -bhh)],
            [(-bhw, -bhd, bhh), (bhw, -bhd, bhh),
             (bhw, bhd, bhh), (-bhw, bhd, bhh)],
        ]

        for face, shade in zip(faces, face_shading):
            for v in face:
                vw.addData3(*v)
                cr, cg, cb = _noisy_color(r, g, b, shade)
                cw.addData4(cr, cg, cb, 1.0)
            tris.addVertices(idx, idx + 1, idx + 2)
            tris.addVertices(idx, idx + 2, idx + 3)
            idx += 4

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("cross")
    node.addGeom(geom)
    return node


# -- Lattice -------------------------------------------------------------------

def make_lattice(w, h, d, color, bars_x=4, bars_y=4):
    """
    Builds a flat-shaded lattice (grid of thin bars) GeomNode.
    w x h face with d depth. bars_x horizontal bars, bars_y vertical bars.
    """
    fmt = GeomVertexFormat.getV3c4()
    total_bars = bars_x + bars_y
    vdata = GeomVertexData("lattice", fmt, Geom.UHStatic)
    vdata.setNumRows(total_bars * 24)  # each bar is a box (6 faces * 4 verts)

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    r, g, b = color
    hw, hh, hd = w / 2, h / 2, d / 2
    bar_w = w / (bars_x * 3)  # bar thickness for vertical bars
    bar_h = h / (bars_y * 3)  # bar thickness for horizontal bars

    face_shading = [0.85, 0.65, 0.70, 0.75, 0.55, 1.0]

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    def _add_bar(bx, by, bz, bw, bh, bd):
        nonlocal idx
        faces = [
            [(bx - bw, by - bd, bz - bh), (bx + bw, by - bd, bz - bh),
             (bx + bw, by - bd, bz + bh), (bx - bw, by - bd, bz + bh)],
            [(bx + bw, by + bd, bz - bh), (bx - bw, by + bd, bz - bh),
             (bx - bw, by + bd, bz + bh), (bx + bw, by + bd, bz + bh)],
            [(bx - bw, by + bd, bz - bh), (bx - bw, by - bd, bz - bh),
             (bx - bw, by - bd, bz + bh), (bx - bw, by + bd, bz + bh)],
            [(bx + bw, by - bd, bz - bh), (bx + bw, by + bd, bz - bh),
             (bx + bw, by + bd, bz + bh), (bx + bw, by - bd, bz + bh)],
            [(bx - bw, by + bd, bz - bh), (bx + bw, by + bd, bz - bh),
             (bx + bw, by - bd, bz - bh), (bx - bw, by - bd, bz - bh)],
            [(bx - bw, by - bd, bz + bh), (bx + bw, by - bd, bz + bh),
             (bx + bw, by + bd, bz + bh), (bx - bw, by + bd, bz + bh)],
        ]
        for face, shade in zip(faces, face_shading):
            for v in face:
                vw.addData3(*v)
                cr, cg, cb = _noisy_color(r, g, b, shade)
                cw.addData4(cr, cg, cb, 1.0)
            tris.addVertices(idx, idx + 1, idx + 2)
            tris.addVertices(idx, idx + 2, idx + 3)
            idx += 4

    # Vertical bars (along Z axis)
    for i in range(bars_x):
        x = -hw + w * (i + 0.5) / bars_x
        _add_bar(x, 0, 0, bar_w / 2, hd, hh)

    # Horizontal bars (along X axis)
    for j in range(bars_y):
        z = -hh + h * (j + 0.5) / bars_y
        _add_bar(0, 0, z, hw, hd, bar_h / 2)

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("lattice")
    node.addGeom(geom)
    return node


# -- Stair ---------------------------------------------------------------------

def make_stair(w, h, d, color, steps=4):
    """
    Builds a flat-shaded staircase block GeomNode.
    w = width, h = total height, d = total depth. Each step is h/steps tall
    and d/steps deep.
    """
    fmt = GeomVertexFormat.getV3c4()
    # Each step: top face + front face + 2 side tris = 3 quads worth
    # Plus bottom face and back face
    num_verts = steps * (4 + 4 + 3 + 3) + 4 + 4  # steps + bottom + back
    vdata = GeomVertexData("stair", fmt, Geom.UHStatic)
    vdata.setNumRows(num_verts + 100)  # pad for safety

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    hw, hh, hd = w / 2, h / 2, d / 2
    r, g, b = color
    step_h = h / steps
    step_d = d / steps

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    for s in range(steps):
        # Step geometry: front-left is low, back is high
        z_bot = -hh + s * step_h
        z_top = -hh + (s + 1) * step_h
        y_front = -hd + s * step_d
        y_back = -hd + (s + 1) * step_d

        # Top face of this step
        face = [(-hw, y_front, z_top), (hw, y_front, z_top),
                (hw, y_back, z_top), (-hw, y_back, z_top)]
        for v in face:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, 1.0)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

        # Front (riser) face of this step
        face = [(-hw, y_front, z_bot), (hw, y_front, z_bot),
                (hw, y_front, z_top), (-hw, y_front, z_top)]
        for v in face:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, 0.85)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

        # Left side of step (triangle for the step profile)
        face = [(-hw, y_front, z_bot), (-hw, y_front, z_top),
                (-hw, y_back, z_top)]
        for v in face:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, 0.70)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        idx += 3

        # Right side of step
        face = [(hw, y_front, z_bot), (hw, y_back, z_top),
                (hw, y_front, z_top)]
        for v in face:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, 0.75)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        idx += 3

    # Bottom face (full footprint)
    face = [(-hw, hd, -hh), (hw, hd, -hh), (hw, -hd, -hh), (-hw, -hd, -hh)]
    for v in face:
        vw.addData3(*v)
        cr, cg, cb = _noisy_color(r, g, b, 0.55)
        cw.addData4(cr, cg, cb, 1.0)
    tris.addVertices(idx, idx + 1, idx + 2)
    tris.addVertices(idx, idx + 2, idx + 3)
    idx += 4

    # Back face (full height at back)
    face = [(hw, hd, -hh), (-hw, hd, -hh), (-hw, hd, hh), (hw, hd, hh)]
    for v in face:
        vw.addData3(*v)
        cr, cg, cb = _noisy_color(r, g, b, 0.65)
        cw.addData4(cr, cg, cb, 1.0)
    tris.addVertices(idx, idx + 1, idx + 2)
    tris.addVertices(idx, idx + 2, idx + 3)
    idx += 4

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("stair")
    node.addGeom(geom)
    return node


# -- Bevel Box -----------------------------------------------------------------

def make_bevel_box(w, h, d, color, bevel=0.1):
    """
    Builds a flat-shaded box with chamfered edges GeomNode.
    bevel = fraction of smallest dimension to cut.
    Creates 26-face solid: 6 main faces + 12 edge bevels + 8 corner tris.
    """
    fmt = GeomVertexFormat.getV3c4()
    # 6 main quads + 12 edge quads + 8 corner tris
    num_verts = 6 * 4 + 12 * 4 + 8 * 3
    vdata = GeomVertexData("bevel_box", fmt, Geom.UHStatic)
    vdata.setNumRows(num_verts)

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    r, g, b = color
    smallest = min(w, h, d)
    bv = smallest * bevel
    hw, hh, hd = w / 2, h / 2, d / 2
    # Inset amounts
    bw, bh, bd = hw - bv, hh - bv, hd - bv

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    def _quad(verts, shade):
        nonlocal idx
        for v in verts:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

    def _tri(verts, shade):
        nonlocal idx
        for v in verts:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        idx += 3

    # 6 main faces (inset by bevel)
    # Front (-Y)
    _quad([(-bw, -hd, -bh), (bw, -hd, -bh), (bw, -hd, bh), (-bw, -hd, bh)], 0.85)
    # Back (+Y)
    _quad([(bw, hd, -bh), (-bw, hd, -bh), (-bw, hd, bh), (bw, hd, bh)], 0.65)
    # Left (-X)
    _quad([(-hw, -bd, -bh), (-hw, bd, -bh), (-hw, bd, bh), (-hw, -bd, bh)], 0.70)
    # Right (+X) -- note: reversed winding so it faces outward
    _quad([(hw, bd, -bh), (hw, -bd, -bh), (hw, -bd, bh), (hw, bd, bh)], 0.75)
    # Bottom (-Z)
    _quad([(-bw, bd, -hh), (bw, bd, -hh), (bw, -bd, -hh), (-bw, -bd, -hh)], 0.55)
    # Top (+Z)
    _quad([(-bw, -bd, hh), (bw, -bd, hh), (bw, bd, hh), (-bw, bd, hh)], 1.0)

    # 12 edge bevels (connecting main faces)
    # Bottom-front edge
    _quad([(-bw, -hd, -bh), (-bw, -bd, -hh), (bw, -bd, -hh), (bw, -hd, -bh)], 0.68)
    # Bottom-back edge
    _quad([(bw, hd, -bh), (bw, bd, -hh), (-bw, bd, -hh), (-bw, hd, -bh)], 0.58)
    # Bottom-left edge
    _quad([(-hw, -bd, -bh), (-bw, -bd, -hh), (-bw, bd, -hh), (-hw, bd, -bh)], 0.60)
    # Bottom-right edge
    _quad([(hw, bd, -bh), (bw, bd, -hh), (bw, -bd, -hh), (hw, -bd, -bh)], 0.63)
    # Top-front edge
    _quad([(-bw, -bd, hh), (-bw, -hd, bh), (bw, -hd, bh), (bw, -bd, hh)], 0.92)
    # Top-back edge
    _quad([(bw, bd, hh), (bw, hd, bh), (-bw, hd, bh), (-bw, bd, hh)], 0.82)
    # Top-left edge
    _quad([(-bw, -bd, hh), (-hw, -bd, bh), (-hw, bd, bh), (-bw, bd, hh)], 0.85)
    # Top-right edge
    _quad([(bw, bd, hh), (hw, bd, bh), (hw, -bd, bh), (bw, -bd, hh)], 0.87)
    # Front-left edge
    _quad([(-hw, -bd, -bh), (-bw, -hd, -bh), (-bw, -hd, bh), (-hw, -bd, bh)], 0.76)
    # Front-right edge
    _quad([(bw, -hd, -bh), (hw, -bd, -bh), (hw, -bd, bh), (bw, -hd, bh)], 0.79)
    # Back-left edge
    _quad([(-bw, hd, -bh), (-hw, bd, -bh), (-hw, bd, bh), (-bw, hd, bh)], 0.66)
    # Back-right edge
    _quad([(hw, bd, -bh), (bw, hd, -bh), (bw, hd, bh), (hw, bd, bh)], 0.69)

    # 8 corner tris
    corners = [
        # Bottom corners
        ((-bw, -hd, -bh), (-hw, -bd, -bh), (-bw, -bd, -hh), 0.60),
        ((bw, -hd, -bh), (bw, -bd, -hh), (hw, -bd, -bh), 0.62),
        ((bw, hd, -bh), (hw, bd, -bh), (bw, bd, -hh), 0.58),
        ((-bw, hd, -bh), (-bw, bd, -hh), (-hw, bd, -bh), 0.56),
        # Top corners
        ((-bw, -hd, bh), (-bw, -bd, hh), (-hw, -bd, bh), 0.90),
        ((bw, -hd, bh), (hw, -bd, bh), (bw, -bd, hh), 0.92),
        ((bw, hd, bh), (bw, bd, hh), (hw, bd, bh), 0.88),
        ((-bw, hd, bh), (-hw, bd, bh), (-bw, bd, hh), 0.86),
    ]

    for v0, v1, v2, shade in corners:
        _tri([v0, v1, v2], shade)

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("bevel_box")
    node.addGeom(geom)
    return node


# -- Fin -----------------------------------------------------------------------

def make_fin(w, h, d, color):
    """
    Builds a flat-shaded tapered fin/blade GeomNode.
    Wide at base (w), narrows to edge at top (h). d = thickness at base,
    tapers to near-zero at top. Like a shark fin or leaf.
    """
    fmt = GeomVertexFormat.getV3c4()
    vdata = GeomVertexData("fin", fmt, Geom.UHStatic)
    vdata.setNumRows(22)  # 4 side tris + 1 bottom quad + 2 top edge tris

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    hw, hh, hd = w / 2, h / 2, d / 2
    r, g, b = color
    tip_d = d * 0.02  # near-zero thickness at top

    # Key points:
    # Base: 4 corners at z=-hh
    # Tip: single edge at z=+hh, x=0, narrow depth
    bl = (-hw, -hd, -hh)
    br = (hw, -hd, -hh)
    fl = (-hw, hd, -hh)
    fr = (hw, hd, -hh)
    tl = (0, -tip_d / 2, hh)  # tip back
    tf = (0, tip_d / 2, hh)   # tip front

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    # Front (-Y side)
    for v in [bl, br, tl]:
        vw.addData3(*v)
        cr, cg, cb = _noisy_color(r, g, b, 0.85)
        cw.addData4(cr, cg, cb, 1.0)
    tris.addVertices(idx, idx + 1, idx + 2)
    idx += 3

    # Back (+Y side)
    for v in [fr, fl, tf]:
        vw.addData3(*v)
        cr, cg, cb = _noisy_color(r, g, b, 0.65)
        cw.addData4(cr, cg, cb, 1.0)
    tris.addVertices(idx, idx + 1, idx + 2)
    idx += 3

    # Left side (-X)
    for v in [fl, bl, tl]:
        vw.addData3(*v)
        cr, cg, cb = _noisy_color(r, g, b, 0.70)
        cw.addData4(cr, cg, cb, 1.0)
    tris.addVertices(idx, idx + 1, idx + 2)
    idx += 3

    # Right side (+X)
    for v in [br, fr, tf]:
        vw.addData3(*v)
        cr, cg, cb = _noisy_color(r, g, b, 0.75)
        cw.addData4(cr, cg, cb, 1.0)
    tris.addVertices(idx, idx + 1, idx + 2)
    idx += 3

    # Bottom quad
    for v in [fl, fr, br, bl]:
        vw.addData3(*v)
        cr, cg, cb = _noisy_color(r, g, b, 0.55)
        cw.addData4(cr, cg, cb, 1.0)
    tris.addVertices(idx, idx + 1, idx + 2)
    tris.addVertices(idx, idx + 2, idx + 3)
    idx += 4

    # Top edge (connecting front tip to back tip — two thin tris)
    for v in [tl, tf, bl]:
        vw.addData3(*v)
        cr, cg, cb = _noisy_color(r, g, b, 1.0)
        cw.addData4(cr, cg, cb, 1.0)
    tris.addVertices(idx, idx + 1, idx + 2)
    idx += 3

    for v in [tf, tl, fr]:
        vw.addData3(*v)
        cr, cg, cb = _noisy_color(r, g, b, 1.0)
        cw.addData4(cr, cg, cb, 1.0)
    tris.addVertices(idx, idx + 1, idx + 2)
    idx += 3

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("fin")
    node.addGeom(geom)
    return node


# -- Ring ----------------------------------------------------------------------

def make_ring(w, h, d, color, segments=16):
    """
    Builds a flat-shaded annular ring (washer shape) GeomNode.
    w = outer diameter, d = inner diameter fraction (0.5 = half outer radius),
    h = thickness.
    """
    fmt = GeomVertexFormat.getV3c4()
    # 4 faces per segment: top, bottom, outer, inner
    num_verts = segments * 4 * 4
    vdata = GeomVertexData("ring", fmt, Geom.UHStatic)
    vdata.setNumRows(num_verts)

    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")

    outer_r = w / 2
    inner_r = outer_r * d  # d is fraction
    hh = h / 2
    r, g, b = color

    tris = GeomTriangles(Geom.UHStatic)
    idx = 0

    for i in range(segments):
        a0 = 2.0 * math.pi * i / segments
        a1 = 2.0 * math.pi * (i + 1) / segments
        c0, s0 = math.cos(a0), math.sin(a0)
        c1, s1 = math.cos(a1), math.sin(a1)

        ox0, oy0 = c0 * outer_r, s0 * outer_r
        ox1, oy1 = c1 * outer_r, s1 * outer_r
        ix0, iy0 = c0 * inner_r, s0 * inner_r
        ix1, iy1 = c1 * inner_r, s1 * inner_r

        # Top face
        for v in [(ox0, oy0, hh), (ox1, oy1, hh),
                   (ix1, iy1, hh), (ix0, iy0, hh)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, 1.0)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

        # Bottom face
        for v in [(ox1, oy1, -hh), (ox0, oy0, -hh),
                   (ix0, iy0, -hh), (ix1, iy1, -hh)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, 0.55)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

        # Outer edge
        mid_a = (a0 + a1) / 2
        shade = 0.75 + 0.10 * math.cos(mid_a) - 0.10 * math.sin(mid_a)

        for v in [(ox0, oy0, -hh), (ox1, oy1, -hh),
                   (ox1, oy1, hh), (ox0, oy0, hh)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

        # Inner edge (reversed winding, darker)
        for v in [(ix1, iy1, -hh), (ix0, iy0, -hh),
                   (ix0, iy0, hh), (ix1, iy1, hh)]:
            vw.addData3(*v)
            cr, cg, cb = _noisy_color(r, g, b, shade * 0.7)
            cw.addData4(cr, cg, cb, 1.0)
        tris.addVertices(idx, idx + 1, idx + 2)
        tris.addVertices(idx, idx + 2, idx + 3)
        idx += 4

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("ring")
    node.addGeom(geom)
    return node


# -- Rock (noise-displaced sphere with flat base) -----------------------------

def make_rock(w, h, d, color, rings=8, segments=10, seed=0, roughness=0.3):
    """Irregular rock — displaced sphere with flattened base.

    Unlike make_sphere, vertices are displaced by seeded noise so no two
    rocks look the same. Bottom hemisphere is squashed flat for natural sitting.

    w/h/d = approximate radii per axis.
    roughness = 0.0 (smooth sphere) to 1.0 (very jagged).
    """
    rng = random.Random(seed)
    fmt = GeomVertexFormat.getV3c4()
    r, g, b = color

    # Pre-compute displaced vertex positions on a sphere grid
    # Each vertex gets a seeded noise offset
    positions = []  # [ring][segment] = (x, y, z)
    for ri in range(rings + 1):
        phi = math.pi * ri / rings  # 0 (top) to pi (bottom)
        ring_row = []
        for si in range(segments):
            theta = 2.0 * math.pi * si / segments

            # Base sphere position
            sp = math.sin(phi)
            sx = sp * math.cos(theta) * w
            sy = sp * math.sin(theta) * d
            sz = math.cos(phi) * h

            # Noise displacement — seeded per vertex
            noise_val = rng.uniform(-1, 1)
            # Additional angular noise for asymmetry
            noise_val += 0.5 * rng.uniform(-1, 1) * math.sin(theta * 3 + seed)
            noise_val += 0.3 * rng.uniform(-1, 1) * math.cos(phi * 2 + seed * 0.7)
            disp = noise_val * roughness

            # Scale displacement by radius at this point
            radius_here = math.sqrt(sx * sx + sy * sy + sz * sz)
            if radius_here > 0.01:
                scale = radius_here * 0.25 * disp
                sx += (sx / radius_here) * scale
                sy += (sy / radius_here) * scale
                sz += (sz / radius_here) * scale

            # Flatten bottom hemisphere — squash Z below equator
            if sz < 0:
                sz *= 0.2  # squash to 20% — creates flat base

            ring_row.append((sx, sy, sz))
        positions.append(ring_row)

    # Count triangles for buffer allocation
    num_tris = segments * 2 + (rings - 2) * segments * 2
    vdata = GeomVertexData("rock", fmt, Geom.UHStatic)
    vdata.setNumRows(num_tris * 3)
    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")
    tris = GeomTriangles(Geom.UHStatic)
    vi = 0

    shades = [1.0, 0.55, 0.85, 0.65, 0.75, 0.70]

    def add_tri(p0, p1, p2, shade_idx):
        shade = shades[shade_idx % len(shades)]
        for px, py, pz in (p0, p1, p2):
            vw.addData3(px, py, pz)
            cr, cg, cb = _noisy_color(r, g, b, shade)
            cw.addData4(cr, cg, cb, 1.0)

    # Top cap
    top = positions[0][0]  # all ring-0 points converge
    for si in range(segments):
        sn = (si + 1) % segments
        p1 = positions[1][si]
        p2 = positions[1][sn]
        add_tri(top, p1, p2, 0)
        tris.addVertices(vi, vi + 1, vi + 2)
        vi += 3

    # Middle bands
    for ri in range(1, rings - 1):
        for si in range(segments):
            sn = (si + 1) % segments
            a = positions[ri][si]
            b_pos = positions[ri][sn]
            c_pos = positions[ri + 1][sn]
            d_pos = positions[ri + 1][si]
            # Shade based on height — top faces brighter
            avg_z = (a[2] + b_pos[2] + c_pos[2] + d_pos[2]) * 0.25
            shade_idx = 0 if avg_z > 0 else 1
            add_tri(a, b_pos, c_pos, shade_idx)
            tris.addVertices(vi, vi + 1, vi + 2)
            vi += 3
            add_tri(a, c_pos, d_pos, shade_idx)
            tris.addVertices(vi, vi + 1, vi + 2)
            vi += 3

    # Bottom cap
    bot = positions[rings][0]
    for si in range(segments):
        sn = (si + 1) % segments
        p1 = positions[rings - 1][si]
        p2 = positions[rings - 1][sn]
        add_tri(bot, p2, p1, 1)
        tris.addVertices(vi, vi + 1, vi + 2)
        vi += 3

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    gn = GeomNode("rock")
    gn.addGeom(geom)
    return gn


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
