"""
core/systems/kitbash_wireframe_backend.py

Persona B -- the WIREFRAME backend (the LIVE path) for the kitbash / greeble
subsystem (spec_kitbash_greeble.md §4, Persona B in §5).

This is the renderer-facing half of the hybrid: it consumes the renderer-
agnostic `AssemblyResult` produced by `KitbashEngine` (Persona A) and turns it
into concrete `WireframeMesh` geometry for the vector terminal -- the canonical
live client (AGENTS.md "Vector terminal first").

Prior-art reality check (verified 2026-07-28, adapted to what's on disk):
  * `core/systems/wireframe_mesh.py` EXISTS -- `WireframeMesh`, the built-in
    primitives, and `parse_obj`. This is the mesh type used here.
  * `config/wireframe_meshes.json` + `get_registered()` from the DRAFT
    `spec_open_source_primitive_pipeline.md` are NOT built. So the ingestion
    pipeline is intentionally NOT used; the greeble library is the BUILT-IN
    primitive set (cube / tetrahedron / octahedron / pyramid / spire / wedge /
    slab / stair). When the registry lands, `part_meshes()` is the one seam to
    swap.
  * `core/systems/wireframe_edits.py` EXISTS with `add_vertex` / `add_edge` /
    `replay`. The vector terminal renders a seed as `replay(base_mesh,
    mesh_edits)` (see `clients/vector_terminal/seed_mesh_cache.py`). So the LIVE
    consumption seam is a `mesh_edits` op-log: `to_mesh_edits()` emits exactly
    the log that, replayed against the base mesh, reproduces `compose()`. A seed
    row `{base_mesh_name, mesh_edits}` therefore references the composed
    assembly through the existing live path -- no running terminal required to
    verify it (headless `replay` reproduces the geometry).

Public surface
--------------
    iter_parts()               -> list[Part]           kitbash parts for the greeble library
    part_meshes()              -> dict[str, WireframeMesh]   part_id -> greeble mesh
    part_scale_classes()       -> dict[str, str]       part_id -> scale_class
    base_hull()                -> Base                  one real base (its sockets)
    hull_base_mesh()           -> WireframeMesh         the base's own geometry
    hull_socket_positions()    -> dict[str, XYZ]        socket_name -> 3D attach point
    compose(base_mesh, socket_positions, assembly_result, part_meshes, scales=None)
                               -> WireframeMesh         THE core deliverable
    to_mesh_edits(base_mesh, socket_positions, assembly_result, part_meshes, scales=None)
                               -> list[dict]            live-path op-log (replay -> compose)
    export_obj(mesh, path)     -> None                  inspectable wireframe .obj (v + l)

No renderer import, no bpy, no LLM -- pure geometry, deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional

from core.systems.kitbash_engine import AssemblyResult, Base, Part, Socket
from core.systems.wireframe_mesh import WireframeMesh, get_builtin, resolve_mesh


XYZ = tuple[float, float, float]


# -- Constants (no hardcoded tunables -- AGENTS.md line 18) --------------------

# Per-scale-class linear multiplier applied to a greeble's local geometry before
# it is translated to its socket. Keys mirror kitbash_engine.SCALE_CLASSES.
# NOTE: spec §7 / AGENTS.md line 19 gesture at config/kind_config.json as the
# eventual single source for scale recipes; kept as a named const here per the
# Persona-B task, ready to migrate to config when the backend needs it.
SCALE_FACTOR: dict[str, float] = {
    "tiny":   0.25,
    "small":  0.50,
    "medium": 1.00,
    "large":  1.50,
    "huge":   2.00,
}
# Fallback scale_class for a part with no registered scale (e.g. an ad-hoc
# greeble handed straight to compose without going through iter_parts()).
DEFAULT_SCALE_CLASS = "medium"

# The greeble library: built-in primitive name -> (socket_type, scale_class,
# category). part_id == the built-in name. This is the small named data table
# the task asks for; it is the ONLY place a greeble's kitbash metadata lives.
#   socket_type -- which base sockets this part may attach to
#   scale_class -- its own size band (drives SCALE_FACTOR + CSP tolerance)
#   category    -- its kit (drives same-kit vs scavenged selection in Persona A)
PART_SPECS: dict[str, tuple[str, str, str]] = {
    #  part_id        socket_type  scale_class  category
    "cube":        ("panel",     "medium",   "structural"),
    "slab":        ("panel",     "medium",   "structural"),
    "stair":       ("panel",     "large",    "structural"),
    "octahedron":  ("gem",       "small",    "ornament"),
    "tetrahedron": ("spike",     "small",    "ornament"),
    "pyramid":     ("spike",     "medium",   "ornament"),
    "spire":       ("antenna",   "large",    "comms"),
    "wedge":       ("fin",       "small",    "aero"),
}

# One real base: a "hull" whose own geometry is the built-in cube, with five
# named attach points (bow / stern / port / starboard / top). Socket tuples
# feed Persona A's CSP; the 3D positions live here (a Socket carries no
# coordinate -- the backend owns the base_id -> {socket: xyz} map).
HULL_BASE_MESH_NAME = "cube"

HULL_SOCKETS: tuple[tuple[str, str, str], ...] = (
    #  name         socket_type  scale_class
    ("top",       "antenna",   "large"),
    ("bow",       "spike",     "medium"),
    ("stern",     "fin",       "small"),
    ("port",      "panel",     "medium"),
    ("starboard", "gem",       "small"),
)

# base_id -> {socket_name: (x, y, z)}. Attach points sit on the faces of the
# hull cube (which spans [-1, 1]); greebles are placed at +/-2 so they read as
# mounted outboard of the hull surface.
HULL_SOCKET_POSITIONS: dict[str, XYZ] = {
    "top":       (0.0,  2.0,  0.0),
    "bow":       (0.0,  0.0,  2.0),
    "stern":     (0.0,  0.0, -2.0),
    "port":      (-2.0, 0.0,  0.0),
    "starboard": (2.0,  0.0,  0.0),
}

HULL_BASE_ID = "hull"

# -- Registry-backed greebles (spec_open_source_primitive_pipeline) ------------
# A registered real mesh becomes a usable greeble with zero extra authoring. Its
# kitbash metadata comes from an optional "kitbash" block in its provenance.json
# sidecar; absent, these defaults apply. DEFAULT_REG_SOCKET matches the hull's
# "port" socket so any registered mesh can bind somewhere out of the box.
REGISTRY_PATH        = Path("config/wireframe_meshes.json")
DERIVED_DIR          = Path("assets/derived")
KITBASH_META_KEY     = "kitbash"
DEFAULT_REG_SOCKET   = "panel"
DEFAULT_REG_SCALE    = "medium"
DEFAULT_REG_CATEGORY = "salvage"    # a distinct kit → high-entropy selection can scavenge it


# -- Parts provider (built-in primitives as greebles) -------------------------

def iter_parts() -> list[Part]:
    """The kitbash greeble library: one `Part` per built-in primitive that has
    an entry in PART_SPECS. Sorted by part_id for determinism. This is the
    `parts` argument to `KitbashEngine().assemble`."""
    parts: list[Part] = []
    for part_id in sorted(PART_SPECS):
        socket_type, scale_class, category = PART_SPECS[part_id]
        parts.append(
            Part(
                part_id=part_id,
                socket_types=frozenset({socket_type}),
                scale_class=scale_class,
                category=category,
            )
        )
    return parts


def part_meshes() -> dict[str, WireframeMesh]:
    """part_id -> its (unit-local) greeble `WireframeMesh`. Values come straight
    from the built-in primitive set. This is the single seam to swap for the
    registry when `spec_open_source_primitive_pipeline.md` is built."""
    meshes: dict[str, WireframeMesh] = {}
    for part_id in PART_SPECS:
        mesh = get_builtin(part_id)
        if mesh is None:                       # pragma: no cover - guards a typo
            raise KeyError(f"no built-in primitive named {part_id!r}")
        meshes[part_id] = mesh
    return meshes


def part_scale_classes() -> dict[str, str]:
    """part_id -> scale_class, the default scale table `compose` consults when
    the caller does not pass an explicit `scales` map."""
    return {pid: spec[1] for pid, spec in PART_SPECS.items()}


# -- Registry-backed greebles: built-in primitives + real ingested meshes -----

def _registered_names() -> list[str]:
    """Names in the wireframe registry (empty when it doesn't exist / is empty)."""
    if not REGISTRY_PATH.is_file():
        return []
    try:
        return sorted(json.loads(REGISTRY_PATH.read_text()).keys())
    except (json.JSONDecodeError, OSError):
        return []


def _kitbash_meta(name: str) -> tuple[str, str, str]:
    """(socket_type, scale_class, category) for a registered mesh: an optional
    `kitbash` block in its provenance.json sidecar, else the defaults."""
    sidecar = DERIVED_DIR / name / "provenance.json"
    if sidecar.is_file():
        try:
            block = json.loads(sidecar.read_text()).get(KITBASH_META_KEY) or {}
            return (block.get("socket_type", DEFAULT_REG_SOCKET),
                    block.get("scale_class", DEFAULT_REG_SCALE),
                    block.get("category", DEFAULT_REG_CATEGORY))
        except (json.JSONDecodeError, OSError):
            pass
    return (DEFAULT_REG_SOCKET, DEFAULT_REG_SCALE, DEFAULT_REG_CATEGORY)


def registered_parts() -> list[Part]:
    """Greebles drawn from the wireframe registry (real ingested meshes), each
    carrying kitbash metadata from its sidecar (or defaults). Empty when the
    registry is empty — so built-in-only behaviour is unchanged until real
    meshes are ingested."""
    parts: list[Part] = []
    for name in _registered_names():
        if name in PART_SPECS:                    # a built-in already owns this id
            continue
        stype, sclass, cat = _kitbash_meta(name)
        parts.append(Part(part_id=name, socket_types=frozenset({stype}),
                          scale_class=sclass, category=cat))
    return parts


def all_parts() -> list[Part]:
    """The full greeble library: built-in primitives + registered real meshes.
    This is the `parts` argument to `KitbashEngine().assemble` for real use."""
    return iter_parts() + registered_parts()


def meshes_for(parts) -> dict[str, WireframeMesh]:
    """part_id -> mesh for ANY parts (built-in OR registered), via resolve_mesh
    (built-in first, then the registry). The general seam `compose` consumes."""
    return {p.part_id: resolve_mesh(p.part_id) for p in parts}


def scale_map(parts) -> dict[str, str]:
    """part_id -> scale_class for ANY parts (built-in or registered) — the
    `scales` argument for `compose`/`to_mesh_edits` when parts include registered
    meshes not present in PART_SPECS."""
    return {p.part_id: p.scale_class for p in parts}


# -- Base + socket positions --------------------------------------------------

def base_hull() -> Base:
    """The one real base: its ordered named attach points as kitbash `Socket`s
    (no 3D coords -- those live in HULL_SOCKET_POSITIONS)."""
    sockets = tuple(
        Socket(name=name, socket_type=stype, scale_class=sclass)
        for (name, stype, sclass) in HULL_SOCKETS
    )
    return Base(base_id=HULL_BASE_ID, sockets=sockets)


def hull_base_mesh() -> WireframeMesh:
    """The hull's own geometry (the built-in cube)."""
    mesh = get_builtin(HULL_BASE_MESH_NAME)
    if mesh is None:                           # pragma: no cover
        raise KeyError(f"no built-in primitive named {HULL_BASE_MESH_NAME!r}")
    return mesh


def hull_socket_positions() -> dict[str, XYZ]:
    """socket_name -> 3D attach point for the hull base."""
    return dict(HULL_SOCKET_POSITIONS)


# -- Transform helper ---------------------------------------------------------

def _scale_factor(part_id: str, scales: Optional[Mapping[str, str]]) -> float:
    """Resolve a part's linear scale multiplier. `scales` (part_id ->
    scale_class) overrides the provider default; unknown parts fall back to
    DEFAULT_SCALE_CLASS. SCALE_FACTOR is the single numeric source."""
    table = scales if scales is not None else part_scale_classes()
    scale_class = table.get(part_id, DEFAULT_SCALE_CLASS)
    return SCALE_FACTOR.get(scale_class, SCALE_FACTOR[DEFAULT_SCALE_CLASS])


def _placed_vertices(
    mesh: WireframeMesh, position: XYZ, factor: float
) -> list[XYZ]:
    """Scale a greeble's local vertices about the origin, THEN translate to the
    socket position. Order matters (scale first) so the scale never multiplies
    the socket offset -- see AGENTS.md line 27 coordinate discipline."""
    px, py, pz = position
    return [
        (px + factor * vx, py + factor * vy, pz + factor * vz)
        for (vx, vy, vz) in mesh.vertices
    ]


# -- compose (THE core deliverable) -------------------------------------------

def compose(
    base_mesh: WireframeMesh,
    socket_positions: Mapping[str, XYZ],
    assembly_result: AssemblyResult,
    part_meshes: Mapping[str, WireframeMesh],
    scales: Optional[Mapping[str, str]] = None,
) -> WireframeMesh:
    """Merge each greeble named in `assembly_result.bindings` onto a copy of the
    base mesh, returning one combined `WireframeMesh`.

    For each `(socket_name, part_id)` binding (bindings are already sorted by
    socket name in the AssemblyResult):
        1. look up the greeble mesh `part_meshes[part_id]`,
        2. scale it about the origin by SCALE_FACTOR[scale_class],
        3. translate it to `socket_positions[socket_name]`,
        4. append its vertices to the running vertex list and its edges with
           every index offset by the current vertex count.

    Vertex order is preserved (base first, then greebles in binding order), so
    counts are exactly base + Σ greebles: no vertex is ever deduplicated or
    dropped. Edges keep their local orientation (offset only).

    `scales` (part_id -> scale_class) lets a caller with custom greebles supply
    scale metadata; when omitted, the provider's `part_scale_classes()` is used.
    The 4-arg form is the common call; the 5th arg keeps compose usable with
    fixture greebles that aren't in PART_SPECS.

    A binding whose part_id or socket_name is unknown raises KeyError -- a
    malformed assembly is a bug, not something to silently skip.
    """
    vertices: list[XYZ] = list(base_mesh.vertices)
    edges: list[tuple[int, int]] = list(base_mesh.edges)

    for socket_name, part_id in assembly_result.bindings:
        if socket_name not in socket_positions:
            raise KeyError(f"no socket position for {socket_name!r}")
        if part_id not in part_meshes:
            raise KeyError(f"no greeble mesh for part {part_id!r}")

        position = socket_positions[socket_name]
        greeble = part_meshes[part_id]
        factor = _scale_factor(part_id, scales)

        offset = len(vertices)
        vertices.extend(_placed_vertices(greeble, position, factor))
        edges.extend((a + offset, b + offset) for (a, b) in greeble.edges)

    return WireframeMesh(vertices=tuple(vertices), edges=tuple(edges))


# -- Live-path seam: express the composition as a mesh_edits op-log ------------

def to_mesh_edits(
    base_mesh: WireframeMesh,
    socket_positions: Mapping[str, XYZ],
    assembly_result: AssemblyResult,
    part_meshes: Mapping[str, WireframeMesh],
    scales: Optional[Mapping[str, str]] = None,
) -> list[dict]:
    """Emit the `mesh_edits` op-log that, replayed against `base_mesh` via
    `core.systems.wireframe_edits.replay`, reproduces `compose(...)`.

    This is the LIVE consumption seam: the vector terminal renders a seed as
    `replay(base_mesh, mesh_edits)` (`clients/vector_terminal/seed_mesh_cache.py`).
    Persisting `{base_mesh_name: <name>, mesh_edits: <this log>}` as a seed row
    therefore makes the composed assembly renderable through the existing path
    with no new render code -- and verifiable headlessly (replay reproduces the
    geometry without a running terminal).

    Ops are ordered greeble-by-greeble: all `add_vertex` for a greeble (they
    append at the running vertex count), then all `add_edge` referencing those
    just-added indices. Index bookkeeping mirrors `compose` exactly, so
    `replay(base_mesh, log)` yields the same vertices in the same order and the
    same edge set (replay canonicalizes/sorts edges; compare edges as a set).
    """
    log: list[dict] = []
    running = base_mesh.vertex_count()

    for socket_name, part_id in assembly_result.bindings:
        if socket_name not in socket_positions:
            raise KeyError(f"no socket position for {socket_name!r}")
        if part_id not in part_meshes:
            raise KeyError(f"no greeble mesh for part {part_id!r}")

        position = socket_positions[socket_name]
        greeble = part_meshes[part_id]
        factor = _scale_factor(part_id, scales)
        offset = running

        for (vx, vy, vz) in _placed_vertices(greeble, position, factor):
            log.append({"op": "add_vertex", "at": [vx, vy, vz]})
            running += 1
        for (a, b) in greeble.edges:
            log.append({"op": "add_edge", "a": a + offset, "b": b + offset})

    return log


# -- Inspectable artifact -----------------------------------------------------

def export_obj(mesh: WireframeMesh, path: str | Path) -> None:
    """Write a wireframe `.obj` -- `v` vertex lines + `l` line-elements (the
    standard OBJ encoding for edges, viewable in Blender / any 3D tool). Purely
    for eyeballing a composed assembly; the live render path is the mesh_edits
    seam above, not this file.

    (Note: the repo's `parse_obj` reads only `v`/`f`, so this `l`-encoded file
    is for inspection, not a `parse_obj` round-trip. The headless round-trip
    that IS supported is `to_mesh_edits` -> `replay`.)
    """
    lines = [f"# kitbash wireframe assembly -- {mesh.vertex_count()} verts, "
             f"{mesh.edge_count()} edges"]
    for (x, y, z) in mesh.vertices:
        lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
    for (a, b) in mesh.edges:                  # OBJ is 1-indexed
        lines.append(f"l {a + 1} {b + 1}")
    Path(path).write_text("\n".join(lines) + "\n")


# -- Demo (verifiable artifact) -----------------------------------------------

def _demo(out_dir: str | Path = ".") -> AssemblyResult:
    """Compose a real hull + greebles and drop an inspectable .obj. Also prints
    the counts. Run: `python -m core.systems.kitbash_wireframe_backend`."""
    from core.systems.kitbash_engine import KitbashEngine

    base = base_hull()
    result = KitbashEngine().assemble(base, iter_parts(), signal_state=None, seed=0)
    mesh = compose(
        hull_base_mesh(), hull_socket_positions(), result, part_meshes()
    )
    out = Path(out_dir) / "kitbash_hull_assembly.obj"
    export_obj(mesh, out)
    print(f"bindings: {result.bindings}")
    print(f"composed: {mesh.vertex_count()} verts, {mesh.edge_count()} edges")
    print(f"wrote {out}")
    return result


if __name__ == "__main__":                     # pragma: no cover
    _demo()
