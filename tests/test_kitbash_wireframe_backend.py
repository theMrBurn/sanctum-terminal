"""
tests/test_kitbash_wireframe_backend.py

Persona B -- wireframe backend. Pure geometry: no Panda3D, no headless client,
no bus. Verifies `compose()` merges greebles onto a base at the right socket
positions with the right vertex/edge counts, deterministically, and that the
live-path `mesh_edits` -> `replay` seam reproduces the same geometry.

Tags: TEST.
"""

from __future__ import annotations

import core.systems.kitbash_wireframe_backend as kb
from core.systems.kitbash_engine import (
    Base,
    KitbashEngine,
    Part,
    Socket,
)
from core.systems.wireframe_edits import replay
from core.systems.wireframe_mesh import WireframeMesh


# -- Fixtures (small, explicit -- not the full library) -----------------------

def _fixture_base_mesh() -> WireframeMesh:
    """A trivial 2-vertex, 1-edge base so counts are obvious."""
    return WireframeMesh(vertices=((0.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
                         edges=((0, 1),))


def _fixture_socket_positions() -> dict[str, tuple[float, float, float]]:
    return {
        "left":  (-5.0, 0.0, 0.0),
        "right": (5.0, 0.0, 0.0),
    }


def _fixture_greeble() -> WireframeMesh:
    """A tetrahedron-like greeble: 3 verts, 3 edges, with one vertex NOT at the
    origin so the transform (scale+translate) is observable."""
    return WireframeMesh(
        vertices=((1.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 4.0)),
        edges=((0, 1), (1, 2), (2, 0)),
    )


def _fixture_parts() -> list[Part]:
    """Two greeble parts, distinct socket types, distinct scale classes."""
    return [
        Part(part_id="fin",  socket_types=frozenset({"wing"}),
             scale_class="small",  category="aero"),      # factor 0.5
        Part(part_id="mast", socket_types=frozenset({"pole"}),
             scale_class="medium", category="rig"),        # factor 1.0
    ]


def _fixture_base() -> Base:
    return Base(base_id="fixture", sockets=(
        Socket(name="left",  socket_type="wing", scale_class="small"),
        Socket(name="right", socket_type="pole", scale_class="medium"),
    ))


def _fixture_assembly():
    """Deterministic AssemblyResult from the real engine over the fixtures."""
    engine = KitbashEngine()
    return engine.assemble(_fixture_base(), _fixture_parts(),
                           signal_state=None, seed=0)


# -- Tests --------------------------------------------------------------------

def test_engine_binds_both_sockets():
    """Sanity: each fixture socket has exactly one compatible part."""
    result = _fixture_assembly()
    assert result.bindings == [("left", "fin"), ("right", "mast")]


def test_compose_vertex_and_edge_counts():
    """compose = base + Σ greebles, nothing dropped or deduplicated."""
    base_mesh = _fixture_base_mesh()
    greeble = _fixture_greeble()
    part_meshes = {"fin": greeble, "mast": greeble}
    scales = {"fin": "small", "mast": "medium"}
    result = _fixture_assembly()

    mesh = kb.compose(base_mesh, _fixture_socket_positions(),
                      result, part_meshes, scales=scales)

    # base 2 verts + 2 greebles × 3 verts = 8; base 1 edge + 2 × 3 = 7
    assert mesh.vertex_count() == 2 + 2 * greeble.vertex_count()
    assert mesh.edge_count() == 1 + 2 * greeble.edge_count()


def test_compose_places_greeble_vertex_at_transformed_socket_coord():
    """A greeble vertex lands at socket_pos + scale_factor * local_vertex --
    NOT at the socket coord itself (no fixture vertex is at the local origin).
    Pins AGENTS.md line-27 coordinate discipline."""
    base_mesh = _fixture_base_mesh()
    greeble = _fixture_greeble()
    part_meshes = {"fin": greeble, "mast": greeble}
    scales = {"fin": "small", "mast": "medium"}
    result = _fixture_assembly()

    mesh = kb.compose(base_mesh, _fixture_socket_positions(),
                      result, part_meshes, scales=scales)

    # "right" -> mast, medium (factor 1.0), socket (5,0,0).
    # greeble vertex (0,0,4) -> (5 + 1.0*0, 0, 0 + 1.0*4) = (5,0,4).
    assert (5.0, 0.0, 4.0) in mesh.vertices
    # "left" -> fin, small (factor 0.5), socket (-5,0,0).
    # greeble vertex (0,2,0) -> (-5, 0 + 0.5*2, 0) = (-5,1,0).
    assert (-5.0, 1.0, 0.0) in mesh.vertices
    # And the socket coord itself is NOT a vertex (proves scale+translate, not
    # a bare snap-to-socket).
    assert (5.0, 0.0, 0.0) not in mesh.vertices
    assert (-5.0, 0.0, 0.0) not in mesh.vertices


def test_compose_is_deterministic():
    """Same inputs -> byte-identical geometry."""
    base_mesh = _fixture_base_mesh()
    part_meshes = {"fin": _fixture_greeble(), "mast": _fixture_greeble()}
    scales = {"fin": "small", "mast": "medium"}
    a = kb.compose(base_mesh, _fixture_socket_positions(),
                   _fixture_assembly(), part_meshes, scales=scales)
    b = kb.compose(base_mesh, _fixture_socket_positions(),
                   _fixture_assembly(), part_meshes, scales=scales)
    assert a.vertices == b.vertices
    assert a.edges == b.edges


def test_mesh_edits_replay_reproduces_compose():
    """The LIVE seam: replay(base, to_mesh_edits(...)) == compose(...).
    Vertices compare in order (both preserve order); edges compare as sets
    (replay canonicalizes/sorts, compose only offsets)."""
    base_mesh = _fixture_base_mesh()
    part_meshes = {"fin": _fixture_greeble(), "mast": _fixture_greeble()}
    scales = {"fin": "small", "mast": "medium"}
    result = _fixture_assembly()
    positions = _fixture_socket_positions()

    composed = kb.compose(base_mesh, positions, result, part_meshes,
                          scales=scales)
    log = kb.to_mesh_edits(base_mesh, positions, result, part_meshes,
                           scales=scales)
    replayed = replay(base_mesh, log)

    assert replayed.vertices == composed.vertices
    canon = lambda es: {(min(a, b), max(a, b)) for (a, b) in es}
    assert canon(replayed.edges) == canon(composed.edges)


# -- Provider / real base (no fixtures) ---------------------------------------

def test_provider_parts_cover_every_hull_socket():
    """Every socket on the real hull base has at least one compatible built-in
    greeble -> a full (non-partial) assembly."""
    base = kb.base_hull()
    result = KitbashEngine().assemble(base, kb.iter_parts(),
                                      signal_state=None, seed=0)
    bound = {name for name, _ in result.bindings}
    assert bound == {s.name for s in base.sockets}


def test_compose_real_hull_counts_and_default_scales():
    """End-to-end over the real base with the 4-arg compose (provider default
    scales): counts equal base + Σ bound greebles."""
    base = kb.base_hull()
    result = KitbashEngine().assemble(base, kb.iter_parts(),
                                      signal_state=None, seed=0)
    meshes = kb.part_meshes()

    mesh = kb.compose(kb.hull_base_mesh(), kb.hull_socket_positions(),
                      result, meshes)

    expected_v = kb.hull_base_mesh().vertex_count() + sum(
        meshes[pid].vertex_count() for _, pid in result.bindings)
    expected_e = kb.hull_base_mesh().edge_count() + sum(
        meshes[pid].edge_count() for _, pid in result.bindings)
    assert mesh.vertex_count() == expected_v
    assert mesh.edge_count() == expected_e


def test_compose_unknown_part_raises():
    """A binding to a part with no mesh is a bug, not a silent skip."""
    base_mesh = _fixture_base_mesh()
    from core.systems.kitbash_engine import AssemblyResult
    bad = AssemblyResult(base_id="fixture",
                         bindings=[("left", "ghost")],
                         signal_snapshot={})
    import pytest
    with pytest.raises(KeyError):
        kb.compose(base_mesh, _fixture_socket_positions(), bad, {})
