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


def test_get_builtin_unknown_returns_none():
    assert get_builtin("does_not_exist") is None


def test_builtin_names_listed():
    names = builtin_names()
    assert "cube" in names
    assert "tetrahedron" in names
    assert "octahedron" in names
    assert "pyramid" in names
    assert "spire" in names


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
