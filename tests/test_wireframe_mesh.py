"""Wireframe mesh primitive — built-ins + OBJ parser tests.

Per `core/systems/wireframe_mesh.py`: vertices + edges with built-in
shapes and an OBJ parser. The parser is the unlock for arbitrary
open-source 3D assets — every test here is on the parser's contract
+ defensive behavior, since asset libraries vary in their OBJ
formatting.
"""
from __future__ import annotations

import pytest

from core.systems.wireframe_mesh import (
    WireframeMesh,
    builtin_names,
    get_builtin,
    parse_obj,
)


# ── Built-in primitives ──────────────────────────────────────────


def test_cube_has_8_vertices_12_edges():
    cube = get_builtin("cube")
    assert cube is not None
    assert cube.vertex_count() == 8
    assert cube.edge_count() == 12


def test_tetrahedron_has_4_vertices_6_edges():
    tet = get_builtin("tetrahedron")
    assert tet.vertex_count() == 4
    assert tet.edge_count() == 6


def test_octahedron_has_6_vertices_12_edges():
    octa = get_builtin("octahedron")
    assert octa.vertex_count() == 6
    assert octa.edge_count() == 12


def test_pyramid_has_5_vertices_8_edges():
    pyr = get_builtin("pyramid")
    assert pyr.vertex_count() == 5
    assert pyr.edge_count() == 8


def test_spire_has_9_vertices_16_edges():
    """Spire: 4 base + 4 mid + 1 apex = 9 vertices; base square (4) +
    mid square (4) + base→mid pillars (4) + mid→apex (4) = 16 edges."""
    spire = get_builtin("spire")
    assert spire.vertex_count() == 9
    assert spire.edge_count() == 16


def test_wedge_has_6_vertices_9_edges():
    """Wedge: triangular ramp. Per `docs/spec_workroom_primitives.md` Tier 1.
    Bottom rect (4 edges) + back rect (3 edges) + slope (2 edges) = 9 edges."""
    wedge = get_builtin("wedge")
    assert wedge.vertex_count() == 6
    assert wedge.edge_count() == 9


def test_wedge_is_ground_anchored():
    """Wedge should rest on the floor: minimum Y is 0, maximum Y is 1.0.
    Seeds placed at floor level should sit on the ground."""
    wedge = get_builtin("wedge")
    ys = [v[1] for v in wedge.vertices]
    assert min(ys) == 0.0
    assert max(ys) == 1.0


def test_slab_has_8_vertices_12_edges():
    """Slab: thin platform — same topology as cube, compressed in Y."""
    slab = get_builtin("slab")
    assert slab.vertex_count() == 8
    assert slab.edge_count() == 12


def test_slab_is_thin_and_ground_anchored():
    """Slab Y range = [0, 0.1] — thin tile, sits on the floor."""
    slab = get_builtin("slab")
    ys = [v[1] for v in slab.vertices]
    assert min(ys) == 0.0
    assert max(ys) == pytest.approx(0.1)


def test_stair_4_vertex_count():
    """4-step stair: 5 z-stations × 4 corners (low+high × left+right) = 20 verts."""
    stair = get_builtin("stair")
    assert stair.vertex_count() == 20


def test_stair_4_edge_count_under_budget():
    """Edge count well under the 200-edge soft budget for clean rendering."""
    stair = get_builtin("stair")
    assert stair.edge_count() == 36
    assert stair.edge_count() < 200


def test_stair_4_is_ground_anchored_and_top_at_unit():
    """Bottom at Y=0, top at Y=1.0. Each step rises 0.25."""
    stair = get_builtin("stair")
    ys = [v[1] for v in stair.vertices]
    assert min(ys) == 0.0
    assert max(ys) == pytest.approx(1.0)


def test_stair_4_edges_reference_valid_vertices():
    """No edge points to a non-existent vertex; no self-loops."""
    stair = get_builtin("stair")
    n = stair.vertex_count()
    for (a, b) in stair.edges:
        assert 0 <= a < n
        assert 0 <= b < n
        assert a != b


def test_get_builtin_unknown_returns_none():
    assert get_builtin("does_not_exist") is None


def test_builtin_names_listed():
    names = builtin_names()
    for expected in (
        "cube", "tetrahedron", "octahedron", "pyramid", "spire",
        "wedge", "slab", "stair",
    ):
        assert expected in names


# ── WireframeMesh dataclass ──────────────────────────────────────


def test_wireframe_mesh_is_immutable():
    """frozen dataclass — accidental mutation is a doctrine violation."""
    cube = get_builtin("cube")
    with pytest.raises(Exception):  # FrozenInstanceError
        cube.vertices = ()  # type: ignore[misc]


# ── OBJ parser ───────────────────────────────────────────────────


def test_parse_obj_basic_cube():
    obj_text = """
v -1.0 -1.0 -1.0
v 1.0 -1.0 -1.0
v 1.0 1.0 -1.0
v -1.0 1.0 -1.0
v -1.0 -1.0 1.0
v 1.0 -1.0 1.0
v 1.0 1.0 1.0
v -1.0 1.0 1.0
f 1 2 3 4
f 5 6 7 8
f 1 2 6 5
f 4 3 7 8
f 1 4 8 5
f 2 3 7 6
"""
    mesh = parse_obj(obj_text)
    assert mesh.vertex_count() == 8
    # Cube has 12 unique edges; deduplication should collapse shared edges.
    assert mesh.edge_count() == 12


def test_parse_obj_handles_comments():
    obj_text = """
# This is a comment
v 0.0 0.0 0.0
# Another comment
v 1.0 0.0 0.0
v 0.0 1.0 0.0
f 1 2 3
"""
    mesh = parse_obj(obj_text)
    assert mesh.vertex_count() == 3
    assert mesh.edge_count() == 3


def test_parse_obj_handles_face_with_uv_and_normal_refs():
    """OBJ faces can be `v/vt/vn` or `v//vn`. Parser should ignore
    everything after the first slash."""
    obj_text = """
v 0.0 0.0 0.0
v 1.0 0.0 0.0
v 0.0 1.0 0.0
f 1/1/1 2/2/2 3/3/3
"""
    mesh = parse_obj(obj_text)
    assert mesh.edge_count() == 3


def test_parse_obj_handles_double_slash_normal_refs():
    obj_text = """
v 0.0 0.0 0.0
v 1.0 0.0 0.0
v 0.0 1.0 0.0
f 1//1 2//2 3//3
"""
    mesh = parse_obj(obj_text)
    assert mesh.edge_count() == 3


def test_parse_obj_skips_degenerate_faces():
    """A face with fewer than 3 vertices is skipped."""
    obj_text = """
v 0.0 0.0 0.0
v 1.0 0.0 0.0
v 0.0 1.0 0.0
f 1 2
f 1 2 3
"""
    mesh = parse_obj(obj_text)
    assert mesh.edge_count() == 3


def test_parse_obj_handles_negative_indices():
    """OBJ allows negative face indices (relative to current vertex
    count). Common in some exporters."""
    obj_text = """
v 0.0 0.0 0.0
v 1.0 0.0 0.0
v 0.0 1.0 0.0
f -3 -2 -1
"""
    mesh = parse_obj(obj_text)
    assert mesh.edge_count() == 3


def test_parse_obj_dedupes_shared_edges():
    """Two adjacent triangles sharing an edge should produce 5 edges,
    not 6 (the shared edge collapses)."""
    obj_text = """
v 0.0 0.0 0.0
v 1.0 0.0 0.0
v 0.0 1.0 0.0
v 1.0 1.0 0.0
f 1 2 3
f 2 4 3
"""
    mesh = parse_obj(obj_text)
    # Shared edge (2,3) appears in both faces; deduplicated.
    assert mesh.edge_count() == 5


def test_parse_obj_ignores_unknown_keywords():
    """Material refs, normals, UVs, groups — ignored cleanly."""
    obj_text = """
mtllib something.mtl
g group_name
v 0.0 0.0 0.0
v 1.0 0.0 0.0
v 0.0 1.0 0.0
vn 0.0 0.0 1.0
vt 0.5 0.5
usemtl mat1
s 1
f 1 2 3
"""
    mesh = parse_obj(obj_text)
    assert mesh.vertex_count() == 3


def test_parse_obj_raises_on_malformed_vertex():
    obj_text = "v 0.0 0.0\n"
    with pytest.raises(ValueError):
        parse_obj(obj_text)


def test_parse_obj_raises_on_non_numeric_vertex():
    obj_text = "v abc 0.0 0.0\n"
    with pytest.raises(ValueError):
        parse_obj(obj_text)


def test_parse_obj_empty_input():
    mesh = parse_obj("")
    assert mesh.vertex_count() == 0
    assert mesh.edge_count() == 0
