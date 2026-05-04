"""Wireframe mesh-edit operations — pure functions over WireframeMesh.

Per `.claude/feature/feat_vector-workroom.md` PR 3. Five structural
verbs the BUILD/EDIT sub-mode (PR 5) writes into a seed's `mesh_edits`
log; this module replays the log against a base mesh at render time.

Ops are pure functions `(WireframeMesh, op_dict) -> WireframeMesh` —
no in-place mutation, no shared state, deterministic. Each op normalizes
edges to the canonical form (sorted index pair, list of edges sorted)
that `wireframe_mesh.parse_obj` and the built-in primitives also emit,
so equality on a final mesh is well-defined regardless of op order.

The five verbs:
    move_vertex     — bend (relocate joint, adjacent edges flex)
    add_vertex      — drop a free joint (returns its index implicitly = len(verts))
    add_edge        — join two joints with a wire
    remove_edge     — sever a wire (joints stay)
    subdivide_edge  — curve (split a wire at fraction t, midpoint joint inserted)

The op dict shape is the same shape that lands in `vault.world_seeds.mesh_edits`:

    {"op": "move_vertex",    "i": int,   "to": [x, y, z]}
    {"op": "add_vertex",     "at": [x, y, z]}
    {"op": "add_edge",       "a": int,   "b": int}
    {"op": "remove_edge",    "a": int,   "b": int}
    {"op": "subdivide_edge", "a": int,   "b": int, "t": float}

Validation: each op raises ValueError on a malformed payload (bad index,
edge already absent for remove, t out of range, etc.). The BUILD-mode UI
in PR 5 should construct legal ops by construction; raises here catch
serialization corruption, hand-edits, and migration drift.
"""
from __future__ import annotations

from typing import Callable

from core.systems.wireframe_mesh import WireframeMesh


Vertex = tuple[float, float, float]
Edge = tuple[int, int]


def _canonical_edge(a: int, b: int) -> Edge:
    """Edges are stored sorted (low, high) per parse_obj."""
    return (a, b) if a < b else (b, a)


def _normalize_edges(edges: list[Edge] | tuple[Edge, ...]) -> tuple[Edge, ...]:
    """Canonicalize each edge pair (low, high) and sort the list. The
    built-in primitives in `wireframe_mesh.py` store edges in face-
    traversal order (e.g. `(3, 0)` for the cube), so callers can't
    assume input pairs are already sorted — we normalize defensively."""
    return tuple(sorted((min(a, b), max(a, b)) for (a, b) in edges))


def _validate_index(i: int, n: int, label: str) -> None:
    if not isinstance(i, int) or i < 0 or i >= n:
        raise ValueError(
            f"{label} out of range: got {i!r}, mesh has {n} vertices"
        )


def _coerce_vertex(value, label: str) -> Vertex:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{label} must be a 3-element list/tuple, got {value!r}")
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} non-numeric component: {value!r}") from exc


# ── The five verbs ───────────────────────────────────────────────────


def move_vertex(mesh: WireframeMesh, op: dict) -> WireframeMesh:
    """Relocate vertex `i` to `to`. Adjacent edges keep their endpoints
    so the wireframe visually bends with the joint."""
    if "i" not in op:
        raise ValueError("move_vertex: missing 'i'")
    if "to" not in op:
        raise ValueError("move_vertex: missing 'to'")
    i = op["i"]
    _validate_index(i, len(mesh.vertices), "move_vertex.i")
    new_pos = _coerce_vertex(op["to"], "move_vertex.to")
    new_verts = list(mesh.vertices)
    new_verts[i] = new_pos
    return WireframeMesh(
        vertices=tuple(new_verts),
        edges=_normalize_edges(mesh.edges),
    )


def add_vertex(mesh: WireframeMesh, op: dict) -> WireframeMesh:
    """Append a new free vertex at `at`. Its index is implicitly
    len(old_vertices) — subsequent ops in the log can reference it."""
    if "at" not in op:
        raise ValueError("add_vertex: missing 'at'")
    new_pos = _coerce_vertex(op["at"], "add_vertex.at")
    return WireframeMesh(
        vertices=mesh.vertices + (new_pos,),
        edges=_normalize_edges(mesh.edges),
    )


def add_edge(mesh: WireframeMesh, op: dict) -> WireframeMesh:
    """Add an edge between two existing vertices. Idempotent: if the
    edge already exists, returns the mesh unchanged."""
    if "a" not in op or "b" not in op:
        raise ValueError("add_edge: missing 'a' or 'b'")
    a, b = op["a"], op["b"]
    n = len(mesh.vertices)
    _validate_index(a, n, "add_edge.a")
    _validate_index(b, n, "add_edge.b")
    if a == b:
        raise ValueError(f"add_edge: degenerate self-edge a==b=={a}")
    edge = _canonical_edge(a, b)
    canonical_edges = _normalize_edges(mesh.edges)
    if edge in canonical_edges:
        return WireframeMesh(vertices=mesh.vertices, edges=canonical_edges)
    return WireframeMesh(
        vertices=mesh.vertices,
        edges=_normalize_edges(list(canonical_edges) + [edge]),
    )


def remove_edge(mesh: WireframeMesh, op: dict) -> WireframeMesh:
    """Drop an edge between two vertices. The vertices themselves remain.
    Raises ValueError if the edge isn't present."""
    if "a" not in op or "b" not in op:
        raise ValueError("remove_edge: missing 'a' or 'b'")
    a, b = op["a"], op["b"]
    n = len(mesh.vertices)
    _validate_index(a, n, "remove_edge.a")
    _validate_index(b, n, "remove_edge.b")
    edge = _canonical_edge(a, b)
    canonical_edges = _normalize_edges(mesh.edges)
    if edge not in canonical_edges:
        raise ValueError(f"remove_edge: edge {edge} not present")
    new_edges = _normalize_edges(e for e in canonical_edges if e != edge)
    return WireframeMesh(vertices=mesh.vertices, edges=new_edges)


def subdivide_edge(mesh: WireframeMesh, op: dict) -> WireframeMesh:
    """Split edge (a, b) at fraction `t in (0, 1)`. Inserts a new vertex
    at lerp(va, vb, t); replaces (a, b) with (a, new_idx) + (new_idx, b).
    The new vertex's index is len(old.vertices)."""
    if "a" not in op or "b" not in op:
        raise ValueError("subdivide_edge: missing 'a' or 'b'")
    if "t" not in op:
        raise ValueError("subdivide_edge: missing 't'")
    a, b = op["a"], op["b"]
    n = len(mesh.vertices)
    _validate_index(a, n, "subdivide_edge.a")
    _validate_index(b, n, "subdivide_edge.b")
    edge = _canonical_edge(a, b)
    canonical_edges = _normalize_edges(mesh.edges)
    if edge not in canonical_edges:
        raise ValueError(f"subdivide_edge: edge {edge} not present")
    try:
        t = float(op["t"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"subdivide_edge.t non-numeric: {op['t']!r}") from exc
    if not (0.0 < t < 1.0):
        raise ValueError(f"subdivide_edge.t out of range (0, 1): {t}")
    va = mesh.vertices[a]
    vb = mesh.vertices[b]
    midpoint = (
        va[0] + (vb[0] - va[0]) * t,
        va[1] + (vb[1] - va[1]) * t,
        va[2] + (vb[2] - va[2]) * t,
    )
    new_idx = n
    new_verts = mesh.vertices + (midpoint,)
    remaining = [e for e in canonical_edges if e != edge]
    remaining.append(_canonical_edge(a, new_idx))
    remaining.append(_canonical_edge(new_idx, b))
    return WireframeMesh(
        vertices=new_verts,
        edges=_normalize_edges(remaining),
    )


# ── Dispatch + replay ───────────────────────────────────────────────


_OP_DISPATCH: dict[str, Callable[[WireframeMesh, dict], WireframeMesh]] = {
    "move_vertex":    move_vertex,
    "add_vertex":     add_vertex,
    "add_edge":       add_edge,
    "remove_edge":    remove_edge,
    "subdivide_edge": subdivide_edge,
}


def op_names() -> tuple[str, ...]:
    return tuple(sorted(_OP_DISPATCH.keys()))


def apply_op(mesh: WireframeMesh, op: dict) -> WireframeMesh:
    """Dispatch a single op against the mesh. Raises ValueError on
    unknown op or malformed payload (the verb's own validation)."""
    name = op.get("op") if isinstance(op, dict) else None
    if not name:
        raise ValueError(f"apply_op: missing 'op' key in {op!r}")
    handler = _OP_DISPATCH.get(name)
    if handler is None:
        raise ValueError(f"apply_op: unknown op {name!r}")
    return handler(mesh, op)


def replay(base: WireframeMesh, log: list | tuple) -> WireframeMesh:
    """Apply each op in `log` in order against `base`. Determinism:
    same base + same log = same final mesh. Empty log returns base."""
    mesh = base
    for op in log:
        mesh = apply_op(mesh, op)
    return mesh
