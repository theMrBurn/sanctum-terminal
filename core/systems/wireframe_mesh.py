"""Wireframe mesh primitive — vertices + edges, parseable from OBJ.

The content pipeline that unlocks every open-source 3D asset library
for our vector terminal aesthetic. Wireframe rendering = drawing the
edges of polygons. Any format that gives you vertices + face indices
(OBJ, STL, etc.) becomes usable as a kind.

V1 ships:
- WireframeMesh dataclass (vertices + edges)
- A few built-in primitives (cube, tetrahedron, octahedron, spire,
  pyramid) for fast testing without files
- parse_obj() — Wavefront OBJ format parser. Faces decompose to edges
  with deduplication (shared edges between adjacent faces collapse).
- load_obj() — file-based loader

Once integrated, drop any .obj file from OpenGameArt / Kenney /
Quaternius / NASA 3D / Thingiverse into the repo, register the
mesh path in config, ship a new kind. The renderer treats them all
identically — pure edge iteration.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WireframeMesh:
    """Vertices + edges. Edges are vertex-index pairs."""
    vertices: tuple[tuple[float, float, float], ...]
    edges: tuple[tuple[int, int], ...]

    def edge_count(self) -> int:
        return len(self.edges)

    def vertex_count(self) -> int:
        return len(self.vertices)


# ── Built-in primitives ──────────────────────────────────────────


def _cube() -> WireframeMesh:
    """Unit cube centered on origin, side length 2."""
    v = (
        (-1.0, -1.0, -1.0), (1.0, -1.0, -1.0),
        (1.0, 1.0, -1.0), (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0), (1.0, -1.0, 1.0),
        (1.0, 1.0, 1.0), (-1.0, 1.0, 1.0),
    )
    e = (
        (0, 1), (1, 2), (2, 3), (3, 0),  # back face
        (4, 5), (5, 6), (6, 7), (7, 4),  # front face
        (0, 4), (1, 5), (2, 6), (3, 7),  # connecting edges
    )
    return WireframeMesh(vertices=v, edges=e)


def _tetrahedron() -> WireframeMesh:
    """Regular tetrahedron, 4 vertices, 6 edges."""
    v = (
        (1.0, 1.0, 1.0),
        (1.0, -1.0, -1.0),
        (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0),
    )
    e = (
        (0, 1), (0, 2), (0, 3),
        (1, 2), (1, 3), (2, 3),
    )
    return WireframeMesh(vertices=v, edges=e)


def _octahedron() -> WireframeMesh:
    """Regular octahedron, 6 vertices, 12 edges. Reads as a faceted gem."""
    v = (
        (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0), (0.0, -1.0, 0.0),
        (0.0, 0.0, 1.0), (0.0, 0.0, -1.0),
    )
    e = (
        (0, 2), (0, 3), (0, 4), (0, 5),
        (1, 2), (1, 3), (1, 4), (1, 5),
        (2, 4), (2, 5), (3, 4), (3, 5),
    )
    return WireframeMesh(vertices=v, edges=e)


def _pyramid() -> WireframeMesh:
    """Square pyramid — 4 base + 1 apex, 8 edges."""
    v = (
        (-1.0, 0.0, -1.0), (1.0, 0.0, -1.0),
        (1.0, 0.0, 1.0), (-1.0, 0.0, 1.0),
        (0.0, 2.0, 0.0),
    )
    e = (
        (0, 1), (1, 2), (2, 3), (3, 0),  # base
        (0, 4), (1, 4), (2, 4), (3, 4),  # apex connections
    )
    return WireframeMesh(vertices=v, edges=e)


def _wedge() -> WireframeMesh:
    """Right-angled triangular ramp. Slope rises from front (z=-0.5)
    at y=0 to back (z=0.5) at y=1. Authored ground-anchored: y spans
    [0, 1] so a seed placed at floor level rests on the floor.

    6 vertices, 9 edges. Per `docs/spec_workroom_primitives.md` Tier 1.
    """
    v = (
        (-0.5, 0.0, -0.5),  # 0 front-bottom-left
        ( 0.5, 0.0, -0.5),  # 1 front-bottom-right
        (-0.5, 0.0,  0.5),  # 2 back-bottom-left
        ( 0.5, 0.0,  0.5),  # 3 back-bottom-right
        (-0.5, 1.0,  0.5),  # 4 back-top-left
        ( 0.5, 1.0,  0.5),  # 5 back-top-right
    )
    e = (
        (0, 1), (1, 3), (2, 3), (0, 2),  # bottom rect
        (2, 4), (3, 5), (4, 5),           # back rect
        (0, 4), (1, 5),                   # slope edges
    )
    return WireframeMesh(vertices=v, edges=e)


def _slab() -> WireframeMesh:
    """Thin square platform. Same topology as cube; Y span is 0.1 instead
    of 2.0 so it reads as a tile/foundation. Ground-anchored (Y spans
    [0.0, 0.1]).

    8 vertices, 12 edges.
    """
    v = (
        (-0.5, 0.0, -0.5),
        ( 0.5, 0.0, -0.5),
        ( 0.5, 0.0,  0.5),
        (-0.5, 0.0,  0.5),
        (-0.5, 0.1, -0.5),
        ( 0.5, 0.1, -0.5),
        ( 0.5, 0.1,  0.5),
        (-0.5, 0.1,  0.5),
    )
    e = (
        (0, 1), (1, 2), (2, 3), (3, 0),  # bottom face
        (4, 5), (5, 6), (6, 7), (7, 4),  # top face
        (0, 4), (1, 5), (2, 6), (3, 7),  # vertical edges
    )
    return WireframeMesh(vertices=v, edges=e)


def _stair_4() -> WireframeMesh:
    """Four-step staircase, ground-anchored. Each step rises 0.25 in Y
    and advances 0.25 in Z. Standing tread connects step n's top to
    step (n+1)'s base.

    Topology: 5 horizontal cross-sections (z = -0.5, -0.25, 0, 0.25, 0.5)
    each at TWO Y-levels (the tread top and the riser top). 20 vertices.

    Built explicitly so vertex indices stay readable for future edits.
    """
    # Layout (raylib coords):
    # Step 0: tread y=0.00 z in [-0.50, -0.25]   riser to y=0.25
    # Step 1: tread y=0.25 z in [-0.25,  0.00]   riser to y=0.50
    # Step 2: tread y=0.50 z in [ 0.00,  0.25]   riser to y=0.75
    # Step 3: tread y=0.75 z in [ 0.25,  0.50]   riser ends at top y=1.00
    #
    # Each step contributes 4 vertices on the X=-0.5 side and 4 on X=+0.5.
    # The whole staircase has 20 vertices total (5 z-stations × 4 corners).
    # Index layout: for each z-station k in 0..4, vertices [4k, 4k+1, 4k+2, 4k+3]
    # are (x=-0.5, y=tread_low), (x=+0.5, y=tread_low),
    #     (x=-0.5, y=tread_high), (x=+0.5, y=tread_high).
    v: list[tuple[float, float, float]] = []
    for k in range(5):
        z = -0.5 + 0.25 * k
        y_low = max(0.0, 0.25 * (k - 1))   # tread height entering this z
        y_high = 0.25 * k                   # tread height leaving this z
        v.append((-0.5, y_low,  z))
        v.append(( 0.5, y_low,  z))
        v.append((-0.5, y_high, z))
        v.append(( 0.5, y_high, z))

    e: list[tuple[int, int]] = []
    # Bottom rail along z (the ground line) — z-stations k=0 to k=4 at y_low
    # k=0 has y_low=0; subsequent k have non-zero y_low so the "bottom" ramp
    # follows the under-tread profile. Connect (4k, 4(k+1)) and (4k+1, 4(k+1)+1).
    for k in range(4):
        e.append((4 * k,     4 * (k + 1)))      # left bottom rail
        e.append((4 * k + 1, 4 * (k + 1) + 1))  # right bottom rail
    # Top rail along z (the walking surface)
    for k in range(4):
        e.append((4 * k + 2,     4 * (k + 1) + 2))      # left top rail
        e.append((4 * k + 3,     4 * (k + 1) + 3))      # right top rail
    # Risers — vertical edges at each z station (between low and high y)
    for k in range(5):
        e.append((4 * k,     4 * k + 2))  # left riser
        e.append((4 * k + 1, 4 * k + 3))  # right riser
    # Tread cross edges — horizontal X-spanning edges at each z station,
    # at both the low and high Y of that station.
    for k in range(5):
        e.append((4 * k,     4 * k + 1))  # cross at y_low
        e.append((4 * k + 2, 4 * k + 3))  # cross at y_high

    return WireframeMesh(vertices=tuple(v), edges=tuple(e))


def _spire() -> WireframeMesh:
    """Tall narrow obelisk — 4 base, 4 mid (broader), 1 apex.
    Reads as a tower or distant landmark on the horizon."""
    v = (
        # base, narrow square at y=0
        (-0.6, 0.0, -0.6), (0.6, 0.0, -0.6),
        (0.6, 0.0, 0.6), (-0.6, 0.0, 0.6),
        # mid, broader at y=1
        (-1.0, 1.0, -1.0), (1.0, 1.0, -1.0),
        (1.0, 1.0, 1.0), (-1.0, 1.0, 1.0),
        # apex at y=4
        (0.0, 4.0, 0.0),
    )
    e = (
        (0, 1), (1, 2), (2, 3), (3, 0),  # base
        (4, 5), (5, 6), (6, 7), (7, 4),  # mid square
        (0, 4), (1, 5), (2, 6), (3, 7),  # base→mid pillars
        (4, 8), (5, 8), (6, 8), (7, 8),  # mid→apex
    )
    return WireframeMesh(vertices=v, edges=e)


_BUILTIN_MESHES: dict[str, WireframeMesh] = {
    "cube": _cube(),
    "tetrahedron": _tetrahedron(),
    "octahedron": _octahedron(),
    "pyramid": _pyramid(),
    "spire": _spire(),
    # Tier 1 platforming kit per `docs/spec_workroom_primitives.md`.
    "wedge": _wedge(),
    "slab":  _slab(),
    "stair": _stair_4(),
}


def get_builtin(name: str) -> WireframeMesh | None:
    """Return a built-in primitive by name, or None if unknown."""
    return _BUILTIN_MESHES.get(name)


def builtin_names() -> tuple[str, ...]:
    return tuple(sorted(_BUILTIN_MESHES.keys()))


# ── OBJ parser ────────────────────────────────────────────────────


def parse_obj(text: str) -> WireframeMesh:
    """Parse Wavefront OBJ text into a WireframeMesh.

    Handles only `v` (vertex) and `f` (face) lines. Vertex normals,
    UVs, materials, groups are ignored. Face polygons of any arity are
    decomposed into edges by connecting consecutive vertices with a
    closing edge to the first; shared edges between adjacent faces
    are deduplicated (each edge stored as sorted index pair in a set).

    OBJ uses 1-indexed vertex references; converted to 0-indexed here.
    Lines like `f 1/2/3` (vertex/uv/normal) are also handled by
    splitting on `/` and taking the vertex index.

    Raises ValueError on malformed input.
    """
    vertices: list[tuple[float, float, float]] = []
    edges_set: set[tuple[int, int]] = set()

    for line_no, raw in enumerate(text.split("\n"), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        keyword = parts[0]

        if keyword == "v":
            if len(parts) < 4:
                raise ValueError(
                    f"line {line_no}: vertex needs at least 3 coords, got {parts!r}"
                )
            try:
                x = float(parts[1])
                y = float(parts[2])
                z = float(parts[3])
            except ValueError as exc:
                raise ValueError(f"line {line_no}: bad vertex {parts!r}") from exc
            vertices.append((x, y, z))

        elif keyword == "f":
            face_indices: list[int] = []
            for tok in parts[1:]:
                # OBJ face refs: "v", "v/vt", "v/vt/vn", "v//vn"
                # We only need the leading vertex index.
                v_str = tok.split("/")[0]
                if not v_str:
                    continue
                try:
                    idx = int(v_str)
                except ValueError as exc:
                    raise ValueError(
                        f"line {line_no}: bad face index {tok!r}"
                    ) from exc
                # OBJ supports negative indices (relative to current
                # vertex count). Normalize.
                if idx < 0:
                    idx = len(vertices) + idx + 1
                # 1-indexed → 0-indexed
                face_indices.append(idx - 1)

            n = len(face_indices)
            if n < 3:
                continue  # degenerate face — skip
            for i in range(n):
                a = face_indices[i]
                b = face_indices[(i + 1) % n]
                if a == b:
                    continue
                edge = (a, b) if a < b else (b, a)
                edges_set.add(edge)

    return WireframeMesh(
        vertices=tuple(vertices),
        edges=tuple(sorted(edges_set)),
    )


def load_obj(path: str | Path) -> WireframeMesh:
    """Read an OBJ file and parse it. Raises FileNotFoundError if
    path doesn't exist; ValueError on malformed content."""
    return parse_obj(Path(path).read_text())
