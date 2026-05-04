"""Wireframe recipe atom + dispatch sanity."""
from __future__ import annotations

from clients.vector_terminal.recipes import (
    WireframeRecipe,
    cube_wires,
    cylinder_wires,
    heptagon_ring,
    low_poly_sphere,
    octahedron,
    recipe_for_kind,
    stick_figure,
)


def _assert_valid(r: WireframeRecipe) -> None:
    n = len(r.vertices)
    assert n > 0
    assert len(r.edges) > 0
    for a, b in r.edges:
        assert 0 <= a < n
        assert 0 <= b < n
        assert a != b
    for a, b, c in r.faces:
        assert 0 <= a < n
        assert 0 <= b < n
        assert 0 <= c < n
        assert len({a, b, c}) == 3  # degenerate triangles are bugs


def test_recipe_is_frozen():
    r = cube_wires()
    try:
        r.vertices = ()  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised


def test_cube_has_8_vertices_12_edges():
    r = cube_wires()
    assert len(r.vertices) == 8
    assert len(r.edges) == 12
    assert len(r.faces) == 12  # 6 sides × 2 triangles
    _assert_valid(r)


def test_octahedron_has_8_face_triangles():
    r = octahedron()
    assert len(r.faces) == 8
    _assert_valid(r)


def test_heptagon_and_stick_have_no_faces():
    """Flat ring + skeletal humanoid intentionally see-through."""
    assert heptagon_ring().faces == ()
    assert stick_figure().faces == ()


def test_heptagon_has_7_of_each():
    r = heptagon_ring()
    assert len(r.vertices) == 7
    assert len(r.edges) == 7
    _assert_valid(r)


def test_octahedron_has_6_vertices_12_edges():
    r = octahedron()
    assert len(r.vertices) == 6
    assert len(r.edges) == 12
    _assert_valid(r)


def test_cylinder_default_segments():
    r = cylinder_wires(segments=8)
    assert len(r.vertices) == 16  # 8 bottom + 8 top
    assert len(r.edges) == 24    # 8 bottom + 8 top + 8 verticals
    _assert_valid(r)


def test_low_poly_sphere_validity():
    r = low_poly_sphere(rings=3, segments=6)
    # 1 top + (rings-1)*segments + 1 bottom = 1 + 12 + 1 = 14
    assert len(r.vertices) == 14
    _assert_valid(r)


def test_stick_figure_has_humanoid_topology():
    r = stick_figure()
    assert len(r.vertices) == 9
    assert len(r.edges) == 7
    _assert_valid(r)


def test_dispatch_motes_to_heptagon():
    assert recipe_for_kind("ash_mote") is recipe_for_kind("ember_mote")
    assert recipe_for_kind("ash_mote") is heptagon_ring.__wrapped__() if hasattr(heptagon_ring, "__wrapped__") else True
    # Compare by structure since heptagon_ring is cached
    r = recipe_for_kind("dust_mote")
    assert len(r.vertices) == 7


def test_dispatch_rocks_to_sphere():
    r = recipe_for_kind("boulder")
    assert len(r.vertices) == 14  # rings=3, segments=6 default
    r2 = recipe_for_kind("loose_stone")
    assert r is r2  # cached


def test_dispatch_creatures_to_stick_figure():
    r = recipe_for_kind("rat")
    assert len(r.vertices) == 9
    assert recipe_for_kind("rat") is recipe_for_kind("scout")
    assert recipe_for_kind("rat") is recipe_for_kind("skeleton")


def test_dispatch_unknown_kind_falls_back_to_cube():
    r = recipe_for_kind("definitely-not-a-known-kind")
    assert len(r.vertices) == 8


def test_dispatch_crystals_to_octahedron():
    r = recipe_for_kind("ice_crystal")
    assert len(r.vertices) == 6


def test_dispatch_pots_to_cylinder():
    r = recipe_for_kind("clay_pot")
    assert len(r.vertices) == 16
