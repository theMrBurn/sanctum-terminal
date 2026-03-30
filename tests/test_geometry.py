"""
tests/test_geometry.py

Real geometry for all 7 primitive types.

BLOCK/SLAB/PILLAR/PLANE = box (existing)
WEDGE = triangular prism (new)
SPIKE = pyramid with square base (new)
ARCH = segmented half-ring (new)

Each function returns a GeomNode with flat-shaded vertex colors.
"""
import pytest
from panda3d.core import GeomNode


# -- Geometry functions exist --------------------------------------------------

class TestGeometryFunctions:

    def test_box_exists(self):
        from core.systems.geometry import make_box as _make_box_geom
        node = _make_box_geom(1, 1, 1, (0.5, 0.5, 0.5))
        assert isinstance(node, GeomNode)

    def test_wedge_exists(self):
        from core.systems.geometry import make_wedge as _make_wedge_geom
        node = _make_wedge_geom(1, 1, 1, (0.5, 0.5, 0.5))
        assert isinstance(node, GeomNode)

    def test_spike_exists(self):
        from core.systems.geometry import make_spike as _make_spike_geom
        node = _make_spike_geom(1, 1, 1, (0.5, 0.5, 0.5))
        assert isinstance(node, GeomNode)

    def test_arch_exists(self):
        from core.systems.geometry import make_arch as _make_arch_geom
        node = _make_arch_geom(1, 1, 1, (0.5, 0.5, 0.5))
        assert isinstance(node, GeomNode)


# -- Geometry has vertices -----------------------------------------------------

class TestGeometryContent:

    def test_wedge_has_geometry(self):
        from core.systems.geometry import make_wedge as _make_wedge_geom
        node = _make_wedge_geom(2, 3, 1, (0.3, 0.3, 0.3))
        geom = node.getGeom(0)
        assert geom.getVertexData().getNumRows() > 0

    def test_spike_has_geometry(self):
        from core.systems.geometry import make_spike as _make_spike_geom
        node = _make_spike_geom(1, 3, 1, (0.5, 0.4, 0.3))
        geom = node.getGeom(0)
        assert geom.getVertexData().getNumRows() > 0

    def test_arch_has_geometry(self):
        from core.systems.geometry import make_arch as _make_arch_geom
        node = _make_arch_geom(4, 0.5, 3, (0.4, 0.4, 0.4))
        geom = node.getGeom(0)
        assert geom.getVertexData().getNumRows() > 0

    def test_wedge_fewer_verts_than_box(self):
        """Wedge is a triangular prism -- should have fewer vertices than a box."""
        from core.systems.geometry import make_box as _make_box_geom, _make_wedge_geom
        box = _make_box_geom(1, 1, 1, (0.5, 0.5, 0.5))
        wedge = _make_wedge_geom(1, 1, 1, (0.5, 0.5, 0.5))
        box_verts = box.getGeom(0).getVertexData().getNumRows()
        wedge_verts = wedge.getGeom(0).getVertexData().getNumRows()
        assert wedge_verts < box_verts


# -- Factory routes to correct geometry ----------------------------------------

class TestFactoryRouting:

    def test_spike_not_a_box(self):
        """SPIKE primitive should produce pyramid geometry, not a box."""
        from core.systems.primitive_factory import PrimitiveFactory
        f = PrimitiveFactory()
        p = f.build("SPIKE", scale=(1.0, 3.0, 1.0), color=(0.5, 0.4, 0.3))
        geom = p.geom_node.getGeom(0)
        spike_verts = geom.getVertexData().getNumRows()
        # A box has 24 verts (4 per face x 6 faces), spike should differ
        assert spike_verts != 24

    def test_wedge_not_a_box(self):
        from core.systems.primitive_factory import PrimitiveFactory
        f = PrimitiveFactory()
        p = f.build("WEDGE", scale=(2.0, 2.0, 1.0), color=(0.3, 0.3, 0.3))
        geom = p.geom_node.getGeom(0)
        wedge_verts = geom.getVertexData().getNumRows()
        assert wedge_verts != 24

    def test_arch_not_a_box(self):
        from core.systems.primitive_factory import PrimitiveFactory
        f = PrimitiveFactory()
        p = f.build("ARCH", scale=(4.0, 0.5, 3.0), color=(0.4, 0.4, 0.4))
        geom = p.geom_node.getGeom(0)
        arch_verts = geom.getVertexData().getNumRows()
        assert arch_verts != 24

    def test_block_still_works(self):
        from core.systems.primitive_factory import PrimitiveFactory
        f = PrimitiveFactory()
        p = f.build("BLOCK", scale=(2.0, 2.0, 2.0), color=(0.5, 0.5, 0.5))
        assert p.geom_node is not None
