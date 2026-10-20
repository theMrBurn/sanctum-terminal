"""Wireframe INGEST edit primitives — pure OBJ-in/OBJ-out transforms.

Per `docs/spec_open_source_primitive_pipeline.md` D4. These are the
art-direction verbs `tools/import_obj.py` applies while turning a raw
vendor OBJ (Kenney / Quaternius / …) into a registered, engine-ready
`WireframeMesh`: recenter, rescale, axis-swap, merge-vertices,
decimate-edges, bounds-clip.

NOT to be confused with `core/systems/wireframe_edits.py` — that module
owns the LIVE render-path op-log (`replay(...)`, the BUILD/EDIT sub-mode
verbs move_vertex/add_edge/…). This module is the INGEST-time cleanup
pipeline and is deliberately a separate file so the two never collide.

Each function is pure: `(WireframeMesh, **kwargs) -> WireframeMesh`, no
mutation, no shared state, deterministic. The composition ORDER is the
`provenance.json` `edits` log — re-running the same log against the same
source reproduces byte-identical geometry (`INGEST_EDIT_ORDER` below).

Coordinate convention (cross-referenced against the built-in primitives
in `wireframe_mesh.py`, which are authored ground-anchored y-up — wedge /
slab / stair all have min-y = 0, and raylib is y-up positive): the engine
convention is **y-up**. `recenter(mode="bottom_center")` therefore leaves
min-y at 0, matching how `_spire()` et al. are authored. `test_wireframe_
registry.py` pins this. See AGENTS.md "Coord math pairs" hard rule.
"""
from __future__ import annotations

import math

from core.systems.wireframe_mesh import WireframeMesh


Vertex = tuple[float, float, float]
Edge = tuple[int, int]

# ── Named tunables (AGENTS: no hardcoded literals controlling behavior) ──
DEFAULT_MERGE_EPSILON: float = 1e-6      # vertex-collapse radius
UP_AXIS: str = "y_up"                    # engine convention (raylib y-up)
RECENTER_MODES: tuple[str, ...] = ("centroid", "bottom_center", "origin")

# Canonical order edits are applied by the ingest CLI. The provenance
# `edits` log records ops in THIS order so a re-run is deterministic.
INGEST_EDIT_ORDER: tuple[str, ...] = (
    "recenter",
    "rescale",
    "axis_swap",
    "merge_vertices",
    "decimate_edges",
    "bounds_clip",
)


# ── Shared edge canonicalization (mirrors wireframe_mesh.parse_obj) ──────


def _canon(a: int, b: int) -> Edge:
    return (a, b) if a < b else (b, a)


def _normalize_edges(edges) -> tuple[Edge, ...]:
    """Canonicalize (low, high) + sort + dedup, dropping self-edges."""
    return tuple(sorted({_canon(a, b) for (a, b) in edges if a != b}))


def _bounds(verts) -> tuple[Vertex, Vertex]:
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    return (
        (min(xs), min(ys), min(zs)),
        (max(xs), max(ys), max(zs)),
    )


# ── D4 edit primitives ──────────────────────────────────────────────────


def recenter(mesh: WireframeMesh, mode: str = "centroid") -> WireframeMesh:
    """Translate verts so the chosen anchor point sits at (0, 0, 0).

    - centroid:      the vertex mean → origin.
    - bottom_center: bbox center in X/Z, min-Y → origin (ground-anchored,
                     y-up; leaves min-Y at 0).
    - origin:        no-op (origin is already at origin).
    """
    if mode not in RECENTER_MODES:
        raise ValueError(f"recenter: unknown mode {mode!r}, want {RECENTER_MODES}")
    if not mesh.vertices:
        raise ValueError("recenter: empty mesh")

    if mode == "origin":
        dx = dy = dz = 0.0
    elif mode == "centroid":
        n = len(mesh.vertices)
        dx = sum(v[0] for v in mesh.vertices) / n
        dy = sum(v[1] for v in mesh.vertices) / n
        dz = sum(v[2] for v in mesh.vertices) / n
    else:  # bottom_center
        (minx, miny, minz), (maxx, _maxy, maxz) = _bounds(mesh.vertices)
        dx = (minx + maxx) / 2.0
        dy = miny
        dz = (minz + maxz) / 2.0

    verts = tuple((x - dx, y - dy, z - dz) for (x, y, z) in mesh.vertices)
    return WireframeMesh(vertices=verts, edges=_normalize_edges(mesh.edges))


def rescale(
    mesh: WireframeMesh,
    target_height: float | None = None,
    target_diag: float | None = None,
    factor: float | None = None,
) -> WireframeMesh:
    """Uniform scale about the origin. Exactly ONE metric must be given:
    - target_height: scale so the Y extent equals `target_height`.
    - target_diag:   scale so the bbox diagonal equals `target_diag`.
    - factor:        direct multiplier.
    """
    given = [x for x in (target_height, target_diag, factor) if x is not None]
    if len(given) != 1:
        raise ValueError(
            "rescale: pass exactly one of target_height / target_diag / factor"
        )
    if not mesh.vertices:
        raise ValueError("rescale: empty mesh")

    if factor is not None:
        s = float(factor)
    else:
        (minx, miny, minz), (maxx, maxy, maxz) = _bounds(mesh.vertices)
        if target_height is not None:
            extent = maxy - miny
            metric, target = extent, float(target_height)
        else:
            metric = math.sqrt(
                (maxx - minx) ** 2 + (maxy - miny) ** 2 + (maxz - minz) ** 2
            )
            target = float(target_diag)
        if metric <= 0.0:
            raise ValueError("rescale: source metric is zero (degenerate mesh)")
        s = target / metric

    verts = tuple((x * s, y * s, z * s) for (x, y, z) in mesh.vertices)
    return WireframeMesh(vertices=verts, edges=_normalize_edges(mesh.edges))


def axis_swap(
    mesh: WireframeMesh, from_up: str = "z_up", to_up: str = UP_AXIS
) -> WireframeMesh:
    """Rotate verts so the up-axis changes from `from_up` to `to_up`.

    Supports the common vendor case `z_up → y_up` (and its inverse).
    `from_up == to_up` is an explicit no-op (recorded in provenance so the
    edit log is complete). Raises on unsupported pairs.
    """
    if from_up == to_up:
        remap = lambda x, y, z: (x, y, z)  # noqa: E731
    elif (from_up, to_up) == ("z_up", "y_up"):
        # +Z → +Y : rotate -90° about X. (x, y, z) → (x, z, -y)
        remap = lambda x, y, z: (x, z, -y)  # noqa: E731
    elif (from_up, to_up) == ("y_up", "z_up"):
        # inverse: (x, y, z) → (x, -z, y)
        remap = lambda x, y, z: (x, -z, y)  # noqa: E731
    else:
        raise ValueError(
            f"axis_swap: unsupported {from_up!r} → {to_up!r} "
            "(supported: z_up↔y_up, or from==to)"
        )
    verts = tuple(remap(x, y, z) for (x, y, z) in mesh.vertices)
    return WireframeMesh(vertices=verts, edges=_normalize_edges(mesh.edges))


def merge_vertices(
    mesh: WireframeMesh, epsilon: float = DEFAULT_MERGE_EPSILON
) -> WireframeMesh:
    """Collapse vertices within `epsilon`; rewire edges; drop the now-dup
    edges and self-edges. Verts are keyed on an epsilon grid, so the
    result is deterministic regardless of input ordering."""
    if epsilon <= 0.0:
        raise ValueError("merge_vertices: epsilon must be > 0")

    def _key(v: Vertex) -> tuple[int, int, int]:
        return (
            round(v[0] / epsilon),
            round(v[1] / epsilon),
            round(v[2] / epsilon),
        )

    rep_for_key: dict[tuple[int, int, int], int] = {}
    new_verts: list[Vertex] = []
    old_to_new: list[int] = []
    for v in mesh.vertices:
        k = _key(v)
        if k not in rep_for_key:
            rep_for_key[k] = len(new_verts)
            new_verts.append(v)
        old_to_new.append(rep_for_key[k])

    edges = ((old_to_new[a], old_to_new[b]) for (a, b) in mesh.edges)
    return WireframeMesh(
        vertices=tuple(new_verts),
        edges=_normalize_edges(edges),
    )


def decimate_edges(mesh: WireframeMesh, target_count: int) -> WireframeMesh:
    """Remove the SHORTEST edges first until edge count ≤ target_count.
    Vertices are preserved (removing them would shift indices and break
    the provenance log); only edges are dropped. No-op if already under."""
    if target_count < 0:
        raise ValueError("decimate_edges: target_count must be ≥ 0")
    edges = _normalize_edges(mesh.edges)
    if len(edges) <= target_count:
        return WireframeMesh(vertices=mesh.vertices, edges=edges)

    def _length(e: Edge) -> float:
        va, vb = mesh.vertices[e[0]], mesh.vertices[e[1]]
        return math.sqrt(
            (va[0] - vb[0]) ** 2 + (va[1] - vb[1]) ** 2 + (va[2] - vb[2]) ** 2
        )

    # Sort longest-first, keep the top `target_count`. Tie-break on the
    # canonical index pair so the result is deterministic.
    ranked = sorted(edges, key=lambda e: (-_length(e), e))
    kept = ranked[:target_count]
    return WireframeMesh(
        vertices=mesh.vertices,
        edges=_normalize_edges(kept),
    )


def bounds_clip(
    mesh: WireframeMesh, min: Vertex, max: Vertex
) -> WireframeMesh:
    """Drop verts outside the [min, max] box (post-merge fixup); drop any
    edge touching a removed vert; reindex the survivors compactly."""
    lo, hi = min, max
    keep: list[int] = []
    old_to_new: dict[int, int] = {}
    new_verts: list[Vertex] = []
    for i, (x, y, z) in enumerate(mesh.vertices):
        if lo[0] <= x <= hi[0] and lo[1] <= y <= hi[1] and lo[2] <= z <= hi[2]:
            old_to_new[i] = len(new_verts)
            new_verts.append((x, y, z))
            keep.append(i)
    kept = frozenset(keep)
    edges = (
        (old_to_new[a], old_to_new[b])
        for (a, b) in mesh.edges
        if a in kept and b in kept
    )
    return WireframeMesh(
        vertices=tuple(new_verts),
        edges=_normalize_edges(edges),
    )
