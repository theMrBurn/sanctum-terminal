"""Per-primitive surface-height collision — workroom traversal substrate.

Validates that seed_floor_height returns sensible Y at known XZ
positions for each primitive. compute_floor_height tests cover the
multi-seed selection + step_max gate.
"""
from __future__ import annotations

import pytest

from clients.vector_terminal.seed_collision import (
    GROUND_Y,
    STEP_HEIGHT_MAX_M,
    compute_floor_height,
    seed_floor_height,
)


def _seed(sid, base_mesh, *, x=0.0, y=0.0, z=0.0, scale=1.0, mesh_edits=None):
    """Build a seed dict in brain-coord convention (pos_x, pos_y=raylib z,
    pos_z=raylib y). For tests, x/y/z are RAYLIB coords; we swap into
    brain conventions when packing the dict."""
    return {
        "id": sid, "biome": "workroom", "kind": "wireframe_mesh",
        "base_mesh": base_mesh,
        "pos_x": x, "pos_y": z, "pos_z": y,    # raylib z → brain y, raylib y → brain z
        "scale": scale,
        "yaw_deg": 0.0,
        "color_r": 0.7, "color_g": 0.7, "color_b": 0.7,
        "mesh_edits": mesh_edits or [],
    }


# ── Per-primitive surface heights ──────────────────────────────────


def test_cube_top_at_origin_returns_one():
    """Cube spans XZ in [-0.5, 0.5], top Y=1.0 in mesh-local coords."""
    s = _seed(1, "cube")
    assert seed_floor_height(s, 0.0, 0.0) == 1.0


def test_cube_outside_footprint_returns_none():
    s = _seed(1, "cube")
    assert seed_floor_height(s, 5.0, 0.0) is None
    assert seed_floor_height(s, 0.0, 5.0) is None


def test_cube_with_offset_translates_world_y():
    """Cube placed at raylib y=2 — its top is at world Y=3."""
    s = _seed(1, "cube", y=2.0)
    assert seed_floor_height(s, 0.0, 0.0) == 3.0


def test_cube_with_scale_doubles_top_and_footprint():
    s = _seed(1, "cube", scale=2.0)
    # Footprint now [-1, 1] × [-1, 1], top at Y=2.
    assert seed_floor_height(s, 0.0, 0.0) == 2.0
    assert seed_floor_height(s, 0.9, 0.9) == 2.0
    assert seed_floor_height(s, 1.1, 0.0) is None


def test_slab_top_at_zero_one():
    """Slab is thin — top at Y=0.1."""
    s = _seed(1, "slab")
    assert seed_floor_height(s, 0.0, 0.0) == pytest.approx(0.1)


def test_wedge_slope_increases_with_z():
    """Wedge: Y=0 at z=-0.5 (front), Y=1 at z=+0.5 (back)."""
    s = _seed(1, "wedge")
    assert seed_floor_height(s, 0.0, -0.5) == pytest.approx(0.0)
    assert seed_floor_height(s, 0.0,  0.0) == pytest.approx(0.5)
    assert seed_floor_height(s, 0.0,  0.5) == pytest.approx(1.0)


def test_wedge_outside_x_returns_none():
    s = _seed(1, "wedge")
    assert seed_floor_height(s, 1.0, 0.0) is None


def test_stair_step_levels():
    """Stair: 4 steps, each 0.25m rise across [-0.5, 0.5] in Z."""
    s = _seed(1, "stair")
    # Step 1: z in [-0.5, -0.25), top y=0.25
    assert seed_floor_height(s, 0.0, -0.4) == pytest.approx(0.25)
    # Step 2: z in [-0.25, 0.0), top y=0.5
    assert seed_floor_height(s, 0.0, -0.1) == pytest.approx(0.5)
    # Step 3: z in [0.0, 0.25), top y=0.75
    assert seed_floor_height(s, 0.0,  0.1) == pytest.approx(0.75)
    # Step 4: z in [0.25, 0.5], top y=1.0
    assert seed_floor_height(s, 0.0,  0.4) == pytest.approx(1.0)


def test_pyramid_top_at_two():
    s = _seed(1, "pyramid")
    assert seed_floor_height(s, 0.0, 0.0) == pytest.approx(2.0)


def test_unknown_primitive_returns_none():
    """Mesh-edited / unknown bases return None on the simple path —
    callers must use seed_floor_height_with_mesh + cache for AABB."""
    s = _seed(1, "not_a_real_mesh")
    assert seed_floor_height(s, 0.0, 0.0) is None


# ── compute_floor_height multi-seed logic ─────────────────────────


def test_no_seeds_returns_ground():
    floor = compute_floor_height(
        seeds=[], world_x=0.0, world_z=0.0,
        current_y=GROUND_Y, ground_y=GROUND_Y,
    )
    assert floor == GROUND_Y


def test_floor_picks_highest_walkable_surface():
    """Two slabs at different heights — player should snap to the higher."""
    s1 = _seed(1, "slab", y=0.0)   # top at world y=0.1
    s2 = _seed(2, "slab", y=0.5)   # top at world y=0.6
    floor = compute_floor_height(
        seeds=[s1, s2], world_x=0.0, world_z=0.0,
        current_y=0.5, ground_y=0.0,
        step_max=1.0,
    )
    assert floor == pytest.approx(0.6)


def test_floor_excludes_seeds_too_high_to_step():
    """Seed top out of step range stays unselected; player keeps default
    floor. Prevents teleport-onto-tall-stack from below."""
    cube_floor = _seed(1, "cube", y=0.0)     # top at world y=1.0
    cube_high  = _seed(2, "cube", y=5.0)     # top at world y=6.0
    floor = compute_floor_height(
        seeds=[cube_floor, cube_high],
        world_x=0.0, world_z=0.0,
        current_y=0.5, ground_y=0.0,
        step_max=STEP_HEIGHT_MAX_M,
    )
    # Only cube_floor's top is within 0.5+0.6=1.1 of current_y; cube_high's
    # top at 6.0 is too far.
    assert floor == pytest.approx(1.0)


def test_floor_falls_back_to_ground_when_outside_all_footprints():
    s = _seed(1, "cube", x=10.0, y=0.0, z=10.0)  # far away
    floor = compute_floor_height(
        seeds=[s], world_x=0.0, world_z=0.0,
        current_y=2.0, ground_y=2.0,
    )
    assert floor == 2.0


def test_floor_handles_wedge_slope():
    """Player walking up a wedge should see floor rise smoothly."""
    s = _seed(1, "wedge", scale=2.0)  # footprint scales to [-1, 1] in XZ
    # As player walks from z=-1 to z=+1, floor should rise from 0 to 2.
    z_samples = [-1.0, -0.5, 0.0, 0.5, 1.0]
    expected = [0.0, 0.5, 1.0, 1.5, 2.0]
    for z, want in zip(z_samples, expected):
        floor = compute_floor_height(
            seeds=[s], world_x=0.0, world_z=z,
            current_y=want, ground_y=0.0,
            step_max=1.0,
        )
        assert floor == pytest.approx(want), f"at z={z} expected {want} got {floor}"
