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


# ── Cached recipes (atoms are deterministic, build once at import) ───────────

_CUBE = cube_wires()
_CYLINDER = cylinder_wires()
_SPHERE = low_poly_sphere()
_OCTAHEDRON = octahedron()
_HEPTAGON = heptagon_ring()
_STICK = stick_figure()


# ── Heuristic dispatch ───────────────────────────────────────────────────────


def recipe_for_kind(kind: str) -> WireframeRecipe:
    """Map a brain kind name to its wireframe recipe. Heuristic — V4-final
    will move this mapping into config/kind_config.json."""
    name = kind.lower()
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
