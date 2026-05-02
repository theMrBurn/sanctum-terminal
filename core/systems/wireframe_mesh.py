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
