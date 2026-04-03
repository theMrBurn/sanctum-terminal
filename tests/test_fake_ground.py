"""
tests/test_fake_ground.py

Regression tests for the WorldRunner fake ground plane.
Headless Panda3D — no display.
"""

import math
import pytest

from panda3d.core import NodePath, TextureStage


@pytest.fixture
def ground():
    """Create a FakeGround parented to a dummy scene root."""
    from core.systems.fake_ground import FakeGround
    root = NodePath("test_root")
    palette = {"stage_floor": (0.08, 0.06, 0.05)}
    fg = FakeGround(root, palette, chunk_seed=42)
    return fg


# -- UV world-locking (the "backwards motion" regression) ----------------------

class TestUVWorldLocking:
    """The ground texture must stay fixed in world space as the camera moves.
    If UVs drift, the texture slides relative to world-space decals and
    the player perceives backwards motion."""

    def _get_uv_at_world(self, ground, world_x, world_y):
        """Calculate what UV the texture produces at a given world position.

        Returns the effective UV (u, v) at world coords (world_x, world_y)
        after applying tex_scale and tex_offset.
        """
        node = ground._node
        ts = TextureStage.getDefault()
        # Get current transform values
        scale_u = node.getTexScale(ts).getX()
        scale_v = node.getTexScale(ts).getY()
        offset_u = node.getTexOffset(ts).getX()
        offset_v = node.getTexOffset(ts).getY()
        nx = node.getX()
        ny = node.getY()
        # The card goes from -half to +half in local space
        half = ground._plane_size / 2.0
        # Local position on the card
        local_x = world_x - nx
        local_y = world_y - ny
        # Raw UV [0,1] across the card
        raw_u = (local_x + half) / ground._plane_size
        raw_v = (local_y + half) / ground._plane_size
        # Final UV after scale + offset
        final_u = raw_u * scale_u + offset_u
        final_v = raw_v * scale_v + offset_v
        return final_u, final_v

    def test_texture_stationary_when_walking_x(self, ground):
        """Moving camera along X should not shift texture at a world point."""
        # Place a world landmark at (10, 10)
        ground.update(0.0, 0.0)
        u1, v1 = self._get_uv_at_world(ground, 10.0, 10.0)

        ground.update(20.0, 0.0)
        u2, v2 = self._get_uv_at_world(ground, 10.0, 10.0)

        assert abs(u1 - u2) < 0.001, f"UV drifted along U: {u1} -> {u2}"
        assert abs(v1 - v2) < 0.001, f"UV drifted along V: {v1} -> {v2}"

    def test_texture_stationary_when_walking_y(self, ground):
        """Moving camera along Y should not shift texture at a world point."""
        ground.update(0.0, 0.0)
        u1, v1 = self._get_uv_at_world(ground, 5.0, 5.0)

        ground.update(0.0, 30.0)
        u2, v2 = self._get_uv_at_world(ground, 5.0, 5.0)

        assert abs(u1 - u2) < 0.001, f"UV drifted along U: {u1} -> {u2}"
        assert abs(v1 - v2) < 0.001, f"UV drifted along V: {v1} -> {v2}"

    def test_texture_stationary_diagonal(self, ground):
        """Diagonal movement must also keep UVs world-locked."""
        ground.update(0.0, 0.0)
        u1, v1 = self._get_uv_at_world(ground, 0.0, 0.0)

        ground.update(15.0, 25.0)
        u2, v2 = self._get_uv_at_world(ground, 0.0, 0.0)

        assert abs(u1 - u2) < 0.001, f"UV drifted along U: {u1} -> {u2}"
        assert abs(v1 - v2) < 0.001, f"UV drifted along V: {v1} -> {v2}"

    def test_uv_proportional_to_world_position(self, ground):
        """UV at two world points should differ by their spatial separation / tile_size."""
        ground.update(0.0, 0.0)
        u1, _ = self._get_uv_at_world(ground, 0.0, 0.0)
        u2, _ = self._get_uv_at_world(ground, 16.0, 0.0)
        # 16m apart with tile_size=16 → exactly 1 tile of UV difference
        assert abs((u2 - u1) - 1.0) < 0.01, f"Expected 1 tile diff, got {u2 - u1}"


# -- Plane positioning ---------------------------------------------------------

class TestPlanePositioning:

    def test_plane_follows_camera(self, ground):
        ground.update(50.0, 30.0)
        assert ground._node.getX() == pytest.approx(50.0)
        assert ground._node.getY() == pytest.approx(30.0)

    def test_plane_at_ground_level(self, ground):
        ground.update(0.0, 0.0)
        assert ground._node.getZ() == pytest.approx(0.0)


# -- Camera bob ----------------------------------------------------------------

class TestCameraBob:

    def test_bob_returns_zero_when_still(self, ground):
        bob = ground.update(0.0, 0.0, dt=0.016, moving=False)
        # Bob should decay toward zero when not moving
        assert abs(bob) < 0.1

    def test_bob_nonzero_when_moving(self, ground):
        # Pump several frames to build phase
        for _ in range(30):
            bob = ground.update(0.0, 0.0, dt=0.016, moving=True)
        assert abs(bob) > 0.001, "Bob should be nonzero after sustained movement"

    def test_bob_bounded(self, ground):
        for _ in range(200):
            bob = ground.update(0.0, 0.0, dt=0.016, moving=True)
        assert abs(bob) <= 0.07, f"Bob {bob} exceeds ±6cm bound"


# -- Show/hide -----------------------------------------------------------------

class TestShowHide:

    def test_starts_visible_after_show(self, ground):
        ground.show()
        assert not ground._node.isHidden()

    def test_hidden_after_hide(self, ground):
        ground.show()
        ground.hide()
        assert ground._node.isHidden()

    def test_node_property(self, ground):
        assert ground.node is ground._node
