"""Per-kind wireframe recipes — atoms + heuristic dispatch.

Each recipe is a frozen `WireframeRecipe(vertices, edges, faces)` in
unit-cube local space (-0.5..0.5). The renderer scales by entity bounds
and rotates by entity heading per draw.

`faces` are optional triangle indices used to draw a filled black "mass"
behind the amber edges so wireframes read as opaque (back edges hidden
by depth buffer). Atoms without faces (heptagon ring, stick figure) stay
fully see-through, which matches their flat/skeletal silhouette intent.

Atoms compose the visible vocabulary: cube for default/structural,
cylinder for stems/columns/containers, low_poly_sphere for rocks,
octahedron for crystals/shards, heptagon_ring for motes (per
design_meta_pixel_mote), stick_figure for creatures.

Dispatch is a name-substring heuristic. V4-final will move per-kind
mappings into config/kind_config.json; this hardcoded heuristic is the
walking-skeleton form per feedback_most_with_least.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WireframeRecipe:
    vertices: tuple[tuple[float, float, float], ...]
    edges: tuple[tuple[int, int], ...]
    faces: tuple[tuple[int, int, int], ...] = field(default_factory=tuple)


# ── Atom generators ──────────────────────────────────────────────────────────


def cube_wires() -> WireframeRecipe:
    v = (
        (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, -0.5, 0.5), (-0.5, -0.5, 0.5),
        (-0.5, 0.5, -0.5), (0.5, 0.5, -0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
    )
    e = (
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    )
    # 12 triangles, 6 quads each split as 2 tris. Winding is per-face — the
    # renderer disables backface culling during the fill pass so we don't
    # have to be exact about orientation.
    f = (
        (0, 1, 2), (0, 2, 3),       # bottom
        (4, 6, 5), (4, 7, 6),       # top
        (3, 2, 6), (3, 6, 7),       # front (+z)
        (1, 0, 4), (1, 4, 5),       # back (-z)
        (2, 1, 5), (2, 5, 6),       # right (+x)
        (0, 3, 7), (0, 7, 4),       # left (-x)
    )
    return WireframeRecipe(vertices=v, edges=e, faces=f)


def cylinder_wires(segments: int = 8) -> WireframeRecipe:
    """Vertical cylinder along local Y axis. Top + bottom rings + verticals,
    plus cap fans + side quads as faces."""
    verts: list[tuple[float, float, float]] = []
    for i in range(segments):
        a = 2 * math.pi * i / segments
        verts.append((0.5 * math.cos(a), -0.5, 0.5 * math.sin(a)))
    for i in range(segments):
        a = 2 * math.pi * i / segments
        verts.append((0.5 * math.cos(a), 0.5, 0.5 * math.sin(a)))

    edges: list[tuple[int, int]] = []
    faces: list[tuple[int, int, int]] = []
    for i in range(segments):
        edges.append((i, (i + 1) % segments))
        edges.append((segments + i, segments + (i + 1) % segments))
        edges.append((i, segments + i))
        # side quad i, i+1, top-i+1, top-i
        a = i
        b = (i + 1) % segments
        c = segments + b
        d = segments + a
        faces.append((a, b, c))
        faces.append((a, c, d))
    # cap fans
    for i in range(1, segments - 1):
        faces.append((0, i + 1, i))                       # bottom
        faces.append((segments, segments + i, segments + i + 1))  # top
    return WireframeRecipe(vertices=tuple(verts), edges=tuple(edges), faces=tuple(faces))


def heptagon_ring() -> WireframeRecipe:
    """7-sided horizontal ring at y=0 — meta-pixel atom per design_meta_pixel_mote.
    No faces — motes are intentionally see-through."""
    n = 7
    verts = tuple(
        (0.5 * math.cos(2 * math.pi * i / n), 0.0, 0.5 * math.sin(2 * math.pi * i / n))
        for i in range(n)
    )
    edges = tuple((i, (i + 1) % n) for i in range(n))
    return WireframeRecipe(vertices=verts, edges=edges)


def low_poly_sphere(rings: int = 3, segments: int = 6) -> WireframeRecipe:
    """Lat/long wireframe sphere with cap fans + ring quad strips as faces."""
    verts: list[tuple[float, float, float]] = [(0.0, 0.5, 0.0)]
    for r in range(1, rings):
        phi = math.pi * r / rings
        y = 0.5 * math.cos(phi)
        radius = 0.5 * math.sin(phi)
        for s in range(segments):
            theta = 2 * math.pi * s / segments
            verts.append((radius * math.cos(theta), y, radius * math.sin(theta)))
    verts.append((0.0, -0.5, 0.0))
    top = 0
    bot = len(verts) - 1
    last_ring_start = 1 + (rings - 2) * segments

    edges: list[tuple[int, int]] = []
    faces: list[tuple[int, int, int]] = []

    for s in range(segments):
        ns = (s + 1) % segments
        edges.append((top, 1 + s))
        edges.append((last_ring_start + s, bot))
        # top fan + bottom fan triangles
        faces.append((top, 1 + s, 1 + ns))
        faces.append((bot, last_ring_start + ns, last_ring_start + s))
    for r in range(rings - 1):
        ring_start = 1 + r * segments
        for s in range(segments):
            edges.append((ring_start + s, ring_start + (s + 1) % segments))
    for r in range(rings - 2):
        a = 1 + r * segments
        b = 1 + (r + 1) * segments
        for s in range(segments):
            ns = (s + 1) % segments
            edges.append((a + s, b + s))
            # quad strip
            faces.append((a + s, a + ns, b + ns))
            faces.append((a + s, b + ns, b + s))
    return WireframeRecipe(vertices=tuple(verts), edges=tuple(edges), faces=tuple(faces))


def octahedron() -> WireframeRecipe:
    """6-vertex bipyramid — sharper crystal feel than cube. 8 triangle faces."""
    v = (
        (0.0, 0.5, 0.0),
        (0.5, 0.0, 0.0), (0.0, 0.0, 0.5), (-0.5, 0.0, 0.0), (0.0, 0.0, -0.5),
        (0.0, -0.5, 0.0),
    )
    e = (
        (0, 1), (0, 2), (0, 3), (0, 4),
        (1, 2), (2, 3), (3, 4), (4, 1),
        (5, 1), (5, 2), (5, 3), (5, 4),
    )
    f = (
        (0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1),
        (5, 2, 1), (5, 3, 2), (5, 4, 3), (5, 1, 4),
    )
    return WireframeRecipe(vertices=v, edges=e, faces=f)


def stick_figure() -> WireframeRecipe:
    """Humanoid: head, spine, shoulders + arms, legs. No faces — skeletal by design."""
    v = (
        (0.0, 0.5, 0.0),
        (0.0, 0.35, 0.0),
        (0.0, 0.0, 0.0),
        (-0.25, 0.3, 0.0),
        (0.25, 0.3, 0.0),
        (-0.4, 0.0, 0.0),
        (0.4, 0.0, 0.0),
        (-0.15, -0.5, 0.0),
        (0.15, -0.5, 0.0),
    )
    e = (
        (0, 1),
        (1, 2),
        (3, 4),
        (3, 5),
        (4, 6),
        (2, 7),
        (2, 8),
    )
    return WireframeRecipe(vertices=v, edges=e)


def banner_billboard() -> WireframeRecipe:
    """Wide flat panel facing +Z. Reads as a sign / poster / billboard
    rather than a generic cube. Scale-wide-in-x, thin-in-z."""
    v = (
        (-0.5, -0.3, 0.0), (0.5, -0.3, 0.0),
        (0.5, 0.3, 0.0),  (-0.5, 0.3, 0.0),
        # Inner cross — gives texture so it doesn't read as an empty rectangle.
        (-0.5, 0.0, 0.0), (0.5, 0.0, 0.0),
        (0.0, -0.3, 0.0), (0.0, 0.3, 0.0),
    )
    e = (
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (6, 7),                       # cross
    )
    f = (
        (0, 1, 2), (0, 2, 3),
    )
    return WireframeRecipe(vertices=v, edges=e, faces=f)


def lattice_7() -> WireframeRecipe:
    """Triangular lattice of 7 points — heptagon ring + center, all wired.
    Same prime-7 invariant as heptagon_ring but feels like a node graph
    rather than a single shape."""
    n = 6
    verts = [(0.0, 0.0, 0.0)]                  # center
    for i in range(n):
        a = 2 * math.pi * i / n
        verts.append((0.5 * math.cos(a), 0.0, 0.5 * math.sin(a)))
    e = []
    for i in range(1, n + 1):
        e.append((0, i))                       # spokes
        e.append((i, 1 + (i % n)))             # ring
    return WireframeRecipe(vertices=tuple(verts), edges=tuple(e))


def scatter_7() -> WireframeRecipe:
    """7 points scattered in 3D, fully connected at near edges. Reads as
    a node cloud — the visual hint of an irregular grouping."""
    v = (
        (-0.4, 0.3, -0.2),
        (0.4, 0.4, 0.1),
        (0.0, -0.4, -0.3),
        (-0.3, 0.0, 0.4),
        (0.3, -0.2, 0.3),
        (0.0, 0.5, 0.0),
        (-0.4, -0.3, 0.0),
    )
    # Spanning edges — k-nearest-like cross-links
    e = (
        (0, 5), (0, 3), (0, 6),
        (1, 5), (1, 4),
        (2, 4), (2, 6), (2, 5),
        (3, 6), (3, 5),
        (4, 5),
    )
    return WireframeRecipe(vertices=v, edges=e)


def chain_vertical() -> WireframeRecipe:
    """Stacked links — 3 small cube outlines along Y. Reads as a chain
    / tether / spinal column."""
    link_h = 0.3
    links: list[tuple[float, float, float]] = []
    edges: list[tuple[int, int]] = []
    for i, cy in enumerate((-0.4, 0.0, 0.4)):
        base = i * 8
        s = 0.15                                # link half-size
        links.extend([
            (-s, cy - link_h * 0.4, -s), (s, cy - link_h * 0.4, -s),
            (s, cy - link_h * 0.4,  s), (-s, cy - link_h * 0.4,  s),
            (-s, cy + link_h * 0.4, -s), (s, cy + link_h * 0.4, -s),
            (s, cy + link_h * 0.4,  s), (-s, cy + link_h * 0.4,  s),
        ])
        # bottom + top rings of each link
        edges.extend([
            (base + 0, base + 1), (base + 1, base + 2),
            (base + 2, base + 3), (base + 3, base + 0),
            (base + 4, base + 5), (base + 5, base + 6),
            (base + 6, base + 7), (base + 7, base + 4),
            (base + 0, base + 4), (base + 1, base + 5),
            (base + 2, base + 6), (base + 3, base + 7),
        ])
        if i > 0:
            # link the bottom of this cube to the top of the previous
            prev = (i - 1) * 8
            edges.append((prev + 5, base + 0))
            edges.append((prev + 7, base + 2))
    return WireframeRecipe(vertices=tuple(links), edges=tuple(edges))


def ground_hug_disc() -> WireframeRecipe:
    """Flat disc at y≈0 — wide ring + cross-spokes. Reads as a tile /
    decal / shadow rather than a 3D object."""
    n = 8
    verts: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0)]
    for i in range(n):
        a = 2 * math.pi * i / n
        verts.append((0.5 * math.cos(a), 0.0, 0.5 * math.sin(a)))
    e = []
    for i in range(1, n + 1):
        nxt = 1 + (i % n)
        e.append((i, nxt))
        if i % 2 == 1:
            e.append((0, i))                    # half the spokes for sparse feel
    return WireframeRecipe(vertices=tuple(verts), edges=tuple(e))


def vector_sprite_tpose() -> WireframeRecipe:
    """T-pose figure — richer than stick_figure. Head circle + body box +
    outstretched arms + base. Reads as a character glyph more than a
    skeleton."""
    v = (
        # Head (4-point diamond up top)
        (-0.10, 0.5, 0.0), (0.10, 0.5, 0.0),
        (0.0, 0.55, 0.0),  (0.0, 0.40, 0.0),
        # Body box
        (-0.15, 0.40, 0.0), (0.15, 0.40, 0.0),
        (0.15, -0.10, 0.0), (-0.15, -0.10, 0.0),
        # Arms (outstretched)
        (-0.45, 0.30, 0.0), (0.45, 0.30, 0.0),
        # Legs
        (-0.10, -0.10, 0.0), (-0.10, -0.50, 0.0),
        (0.10, -0.10, 0.0), (0.10, -0.50, 0.0),
    )
    e = (
        # head diamond
        (0, 2), (2, 1), (1, 3), (3, 0),
        # body
        (4, 5), (5, 6), (6, 7), (7, 4),
        # arms
        (4, 8), (5, 9),
        # legs
        (10, 11), (12, 13),
    )
    return WireframeRecipe(vertices=v, edges=e)


# ── Cached recipes (atoms are deterministic, build once at import) ───────────

_CUBE = cube_wires()
_CYLINDER = cylinder_wires()
_SPHERE = low_poly_sphere()
_OCTAHEDRON = octahedron()
_HEPTAGON = heptagon_ring()
_STICK = stick_figure()
_BANNER = banner_billboard()
_LATTICE7 = lattice_7()
_SCATTER7 = scatter_7()
_CHAIN = chain_vertical()
_GROUND_HUG = ground_hug_disc()
_VECTOR_SPRITE = vector_sprite_tpose()


# ── Heuristic dispatch ───────────────────────────────────────────────────────


def recipe_for_kind(kind: str) -> WireframeRecipe:
    """Map a brain kind name to its wireframe recipe. Heuristic — V4-final
    will move this mapping into config/kind_config.json."""
    name = kind.lower()
    # tools/scan_to_kinds.py emits `scan_<shape>_<idx>` — image-derived
    # entities. Match by embedded shape token so the experiment
    # bridges raw classification → vector primitive without authoring
    # one kind_config entry per image.
    if name.startswith("scan_"):
        if "orb" in name:                return _SPHERE
        if "tapered_vertical" in name:   return _CYLINDER
        if "banner" in name:             return _BANNER
        if "heptagonal_mote" in name:    return _HEPTAGON
        if "silhouette_void" in name:    return _STICK
        if "lattice_7" in name:          return _LATTICE7
        if "scatter_7" in name:          return _SCATTER7
        if "chain" in name:              return _CHAIN
        if "ground_hug" in name:         return _GROUND_HUG
        if "vector_sprite" in name:      return _VECTOR_SPRITE
        return _CUBE
    if "mote" in name or "spark" in name or "wisp" in name:
        return _HEPTAGON
    if any(s in name for s in ("rock", "stone", "boulder", "rubble", "pebble", "scree")):
        return _SPHERE
    if any(s in name for s in ("crystal", "shard", "gem", "geode")):
        return _OCTAHEDRON
    if any(s in name for s in ("mushroom", "spore", "fungus", "stalk", "shroom")):
        return _CYLINDER
    if any(s in name for s in ("rat", "scout", "creature", "monster", "skeleton",
                                "ghoul", "goblin", "slime", "watcher", "beast")):
        return _STICK
    if any(s in name for s in ("pot", "vase", "urn", "barrel", "jar", "container",
                                "column", "pillar", "torch")):
        return _CYLINDER
    return _CUBE
