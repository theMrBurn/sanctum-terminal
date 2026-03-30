"""
Tests for UV-mapped textured 3D primitives.

Every manufacturing primitive must have:
- Correct vertex count
- Normals on every vertex
- UV coords on every vertex
- Valid triangle indices
"""

import pytest
from panda3d.core import GeomNode, GeomVertexReader

from core.systems.geometry import (
    make_textured_box,
    make_textured_wedge,
    make_textured_spike,
    make_textured_arch,
    TEXTURED_BUILDERS,
)


def _read_geom_data(geom_node):
    """Extract vertex/normal/uv data from a GeomNode."""
    geom = geom_node.getGeom(0)
    vdata = geom.getVertexData()
    num_verts = vdata.getNumRows()

    verts, normals, uvs = [], [], []
    vr = GeomVertexReader(vdata, "vertex")
    nr = GeomVertexReader(vdata, "normal")
    tr = GeomVertexReader(vdata, "texcoord")

    for _ in range(num_verts):
        v = vr.getData3()
        verts.append((v.getX(), v.getY(), v.getZ()))
        n = nr.getData3()
        normals.append((n.getX(), n.getY(), n.getZ()))
        t = tr.getData2()
        uvs.append((t.getX(), t.getY()))

    # Count triangles
    prim = geom.getPrimitive(0)
    num_tris = prim.getNumPrimitives()

    return {
        "num_verts": num_verts,
        "verts": verts,
        "normals": normals,
        "uvs": uvs,
        "num_tris": num_tris,
    }


class TestTexturedBox:

    def test_creates_geom_node(self):
        node = make_textured_box(1.0, 1.0, 1.0)
        assert isinstance(node, GeomNode)

    def test_vertex_count(self):
        node = make_textured_box(1.0, 1.0, 1.0)
        data = _read_geom_data(node)
        assert data["num_verts"] == 24  # 6 faces * 4 verts

    def test_triangle_count(self):
        node = make_textured_box(1.0, 1.0, 1.0)
        data = _read_geom_data(node)
        assert data["num_tris"] == 12  # 6 faces * 2 tris

    def test_all_normals_nonzero(self):
        node = make_textured_box(2.0, 3.0, 1.5)
        data = _read_geom_data(node)
        for n in data["normals"]:
            mag = sum(c**2 for c in n) ** 0.5
            assert mag > 0.9, f"Zero/degenerate normal: {n}"

    def test_all_uvs_in_range(self):
        node = make_textured_box(1.0, 1.0, 1.0)
        data = _read_geom_data(node)
        for u, v in data["uvs"]:
            assert 0.0 <= u <= 1.0, f"U out of range: {u}"
            assert 0.0 <= v <= 1.0, f"V out of range: {v}"

    def test_custom_dimensions(self):
        node = make_textured_box(2.0, 4.0, 0.5)
        data = _read_geom_data(node)
        xs = [v[0] for v in data["verts"]]
        assert max(xs) == pytest.approx(1.0, abs=0.01)
        assert min(xs) == pytest.approx(-1.0, abs=0.01)

    def test_custom_name(self):
        node = make_textured_box(1, 1, 1, name="my_box")
        assert node.getName() == "my_box"


class TestTexturedWedge:

    def test_creates_geom_node(self):
        node = make_textured_wedge(1.0, 1.0, 1.0)
        assert isinstance(node, GeomNode)

    def test_vertex_count(self):
        node = make_textured_wedge(1.0, 1.0, 1.0)
        data = _read_geom_data(node)
        # 3 quad faces (4 verts each) + 2 tri faces (3 verts each) = 18
        assert data["num_verts"] == 18

    def test_triangle_count(self):
        node = make_textured_wedge(1.0, 1.0, 1.0)
        data = _read_geom_data(node)
        # 3 quads * 2 tris + 2 tris = 8
        assert data["num_tris"] == 8

    def test_all_normals_nonzero(self):
        node = make_textured_wedge(1.0, 2.0, 1.0)
        data = _read_geom_data(node)
        for n in data["normals"]:
            mag = sum(c**2 for c in n) ** 0.5
            assert mag > 0.5, f"Degenerate normal: {n}"

    def test_all_uvs_in_range(self):
        node = make_textured_wedge(1.0, 1.0, 1.0)
        data = _read_geom_data(node)
        for u, v in data["uvs"]:
            assert 0.0 <= u <= 1.0
            assert 0.0 <= v <= 1.0


class TestTexturedSpike:

    def test_creates_geom_node(self):
        node = make_textured_spike(1.0, 1.0, 1.0)
        assert isinstance(node, GeomNode)

    def test_vertex_count(self):
        node = make_textured_spike(1.0, 1.0, 1.0)
        data = _read_geom_data(node)
        # Base: 4 verts + 4 sides * 3 verts = 16
        assert data["num_verts"] == 16

    def test_triangle_count(self):
        node = make_textured_spike(1.0, 1.0, 1.0)
        data = _read_geom_data(node)
        # Base: 2 tris + 4 sides: 4 tris = 6
        assert data["num_tris"] == 6

    def test_all_normals_nonzero(self):
        node = make_textured_spike(1.0, 2.0, 1.0)
        data = _read_geom_data(node)
        for n in data["normals"]:
            mag = sum(c**2 for c in n) ** 0.5
            assert mag > 0.5

    def test_apex_at_top(self):
        node = make_textured_spike(1.0, 2.0, 1.0)
        data = _read_geom_data(node)
        max_z = max(v[2] for v in data["verts"])
        assert max_z == pytest.approx(1.0, abs=0.01)  # h/2


class TestTexturedArch:

    def test_creates_geom_node(self):
        node = make_textured_arch(2.0, 0.5, 2.0)
        assert isinstance(node, GeomNode)

    def test_has_normals_and_uvs(self):
        node = make_textured_arch(2.0, 0.5, 2.0)
        data = _read_geom_data(node)
        assert data["num_verts"] > 0
        assert len(data["normals"]) == data["num_verts"]
        assert len(data["uvs"]) == data["num_verts"]

    def test_segment_count_affects_verts(self):
        node4 = make_textured_arch(2.0, 0.5, 2.0, segments=4)
        node8 = make_textured_arch(2.0, 0.5, 2.0, segments=8)
        d4 = _read_geom_data(node4)
        d8 = _read_geom_data(node8)
        assert d8["num_verts"] > d4["num_verts"]

    def test_all_uvs_in_range(self):
        node = make_textured_arch(2.0, 0.5, 2.0)
        data = _read_geom_data(node)
        for u, v in data["uvs"]:
            assert 0.0 <= u <= 1.0
            assert 0.0 <= v <= 1.0


class TestTexturedBuilderDispatch:

    def test_all_types_in_dispatch(self):
        expected = {"BLOCK", "SLAB", "PILLAR", "WEDGE", "SPIKE", "ARCH"}
        assert expected == set(TEXTURED_BUILDERS.keys())

    def test_all_builders_callable(self):
        for name, builder in TEXTURED_BUILDERS.items():
            node = builder(1.0, 1.0, 1.0)
            assert isinstance(node, GeomNode), f"{name} builder failed"

    def test_slab_is_box(self):
        assert TEXTURED_BUILDERS["SLAB"] is make_textured_box

    def test_pillar_is_box(self):
        assert TEXTURED_BUILDERS["PILLAR"] is make_textured_box
