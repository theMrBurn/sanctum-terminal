"""water_plane primitive — schema + recipe + animation flag."""
from __future__ import annotations

from core.systems import thing_schema, thing_library


def test_water_plane_in_primitives():
    assert "water_plane" in thing_schema.PRIMITIVES


def test_water_plane_in_primitive_visual():
    assert "water_plane" in thing_schema.PRIMITIVE_VISUAL


def test_water_plane_visual_mentions_animation():
    """The visual hint should warn authors the primitive animates."""
    hint = thing_schema.PRIMITIVE_VISUAL["water_plane"].lower()
    assert any(s in hint for s in ("water", "wave", "flow"))


def test_pond_fixture_loads_with_water_plane():
    pond = thing_library.get("pond")
    assert pond is not None
    primitives = [p.primitive for p in pond.parts]
    assert "water_plane" in primitives


def test_pond_carries_pnw_tag():
    pond = thing_library.get("pond")
    assert pond is not None
    assert "pnw" in pond.tags
    assert "water" in pond.tags


# Recipe + dispatch tests — only run if raylib is installed (client lib)
import pytest


@pytest.fixture
def recipes_module():
    try:
        from clients.vector_terminal import recipes as r
        return r
    except ImportError:
        pytest.skip("raylib-py not available in this env")


def test_water_grid_recipe_animate_flag(recipes_module):
    r = recipes_module.water_grid()
    assert r.animate_water is True
    # Default 6×6 grid
    assert len(r.vertices) == 36


def test_water_grid_vertices_at_y_zero(recipes_module):
    """Static grid before animation — all verts at y=0. Animation
    happens at draw time, not at recipe construction."""
    r = recipes_module.water_grid()
    for vx, vy, vz in r.vertices:
        assert vy == 0.0


def test_water_grid_in_unit_xz_box(recipes_module):
    """Recipe is in (-0.5, 0.5) unit-cube space, scaled at draw."""
    r = recipes_module.water_grid()
    for vx, vy, vz in r.vertices:
        assert -0.5 <= vx <= 0.5
        assert -0.5 <= vz <= 0.5


def test_recipe_for_kind_dispatches_water_plane(recipes_module):
    """scan_water_plane_* → water grid (animate_water=True)."""
    r = recipes_module.recipe_for_kind("scan_water_plane_0")
    assert r.animate_water


def test_recipe_for_kind_river_dispatches_water(recipes_module):
    """Generic water-name heuristic also routes through water_grid."""
    for name in ("river", "stream", "pond", "lake", "ocean"):
        r = recipes_module.recipe_for_kind(name)
        assert r.animate_water, f"{name!r} should dispatch water"


def test_other_kinds_not_animated(recipes_module):
    """Sanity: non-water kinds keep animate_water=False."""
    for kind in ("scan_orb_1", "scan_cube_terrain_wall", "skull",
                 "mushroom", "rock"):
        r = recipes_module.recipe_for_kind(kind)
        assert not r.animate_water
