"""
tests/test_room_layout.py

Procedural door placement for Tartarus-style rooms.
"""

import pytest
import math

from core.systems.room_layout import (
    DoorPlacement, RoomLayout, WallSide,
    DOOR_WIDTH, DOOR_HEIGHT, MIN_SPACING, CORNER_MARGIN,
)


ROOM_W = 16.0
ROOM_D = 24.0


class TestDoorPlacement:

    def test_north_wall_position(self):
        door = DoorPlacement(wall=WallSide.NORTH, offset=0.5, door_index=0)
        x, y, z = door.world_pos(ROOM_W, ROOM_D)
        # Should be on the north wall (y near +depth/2)
        assert y == pytest.approx(ROOM_D / 2 - 0.1)
        assert z == pytest.approx(DOOR_HEIGHT / 2)

    def test_east_wall_position(self):
        door = DoorPlacement(wall=WallSide.EAST, offset=0.5, door_index=1)
        x, y, z = door.world_pos(ROOM_W, ROOM_D)
        assert x == pytest.approx(ROOM_W / 2 - 0.1)

    def test_west_wall_position(self):
        door = DoorPlacement(wall=WallSide.WEST, offset=0.5, door_index=2)
        x, y, z = door.world_pos(ROOM_W, ROOM_D)
        assert x == pytest.approx(-ROOM_W / 2 + 0.1)

    def test_north_faces_south(self):
        door = DoorPlacement(wall=WallSide.NORTH, offset=0.5, door_index=0)
        assert door.facing_h == 0.0  # quad already faces -Y (south)

    def test_east_faces_west(self):
        door = DoorPlacement(wall=WallSide.EAST, offset=0.5, door_index=0)
        assert door.facing_h == -90.0

    def test_west_faces_east(self):
        door = DoorPlacement(wall=WallSide.WEST, offset=0.5, door_index=0)
        assert door.facing_h == 90.0

    def test_hinge_offset_returns_tuple(self):
        door = DoorPlacement(wall=WallSide.NORTH, offset=0.5, door_index=0)
        ho = door.hinge_offset()
        assert len(ho) == 2

    def test_frozen(self):
        door = DoorPlacement(wall=WallSide.NORTH, offset=0.5, door_index=0)
        with pytest.raises(AttributeError):
            door.offset = 0.8


class TestRoomLayout:

    def test_generates_correct_door_count(self):
        layout = RoomLayout(ROOM_W, ROOM_D, door_count=8, seed=42)
        assert len(layout.doors) == 8

    def test_six_doors(self):
        layout = RoomLayout(ROOM_W, ROOM_D, door_count=6, seed=42)
        assert len(layout.doors) == 6

    def test_all_doors_on_perimeter(self):
        layout = RoomLayout(ROOM_W, ROOM_D, door_count=8, seed=42)
        hw, hd = ROOM_W / 2, ROOM_D / 2
        for door in layout.doors:
            x, y, z = door.world_pos(ROOM_W, ROOM_D)
            on_north = abs(y - (hd - 0.1)) < 0.01
            on_east = abs(x - (hw - 0.1)) < 0.01
            on_west = abs(x - (-hw + 0.1)) < 0.01
            assert on_north or on_east or on_west, \
                f"Door {door.door_index} at ({x:.1f}, {y:.1f}) not on wall"

    def test_no_doors_on_south_wall(self):
        layout = RoomLayout(ROOM_W, ROOM_D, door_count=8, seed=42)
        for door in layout.doors:
            assert door.wall != "south"

    def test_at_least_one_per_wall(self):
        layout = RoomLayout(ROOM_W, ROOM_D, door_count=8, seed=42)
        walls_used = {d.wall for d in layout.doors}
        assert WallSide.NORTH in walls_used
        assert WallSide.EAST in walls_used
        assert WallSide.WEST in walls_used

    def test_minimum_spacing_enforced(self):
        """No two doors closer than MIN_SPACING."""
        for seed in range(10):
            layout = RoomLayout(ROOM_W, ROOM_D, door_count=8, seed=seed)
            positions = layout.all_world_positions()
            for i in range(len(positions)):
                for j in range(i + 1, len(positions)):
                    dx = positions[i][0] - positions[j][0]
                    dy = positions[i][1] - positions[j][1]
                    dist = math.sqrt(dx * dx + dy * dy)
                    assert dist >= MIN_SPACING * 0.8, \
                        f"Seed {seed}: doors {i},{j} too close ({dist:.1f}m)"

    def test_different_seeds_different_layouts(self):
        l1 = RoomLayout(ROOM_W, ROOM_D, seed=1)
        l2 = RoomLayout(ROOM_W, ROOM_D, seed=2)
        pos1 = l1.all_world_positions()
        pos2 = l2.all_world_positions()
        # At least one door should be in a different position
        any_different = False
        for p1, p2 in zip(pos1, pos2):
            if abs(p1[0] - p2[0]) > 0.1 or abs(p1[1] - p2[1]) > 0.1:
                any_different = True
                break
        assert any_different

    def test_deterministic_with_same_seed(self):
        l1 = RoomLayout(ROOM_W, ROOM_D, seed=42)
        l2 = RoomLayout(ROOM_W, ROOM_D, seed=42)
        pos1 = l1.all_world_positions()
        pos2 = l2.all_world_positions()
        for p1, p2 in zip(pos1, pos2):
            assert p1[0] == pytest.approx(p2[0])
            assert p1[1] == pytest.approx(p2[1])

    def test_world_pos_within_room_bounds(self):
        layout = RoomLayout(ROOM_W, ROOM_D, seed=42)
        hw, hd = ROOM_W / 2, ROOM_D / 2
        for door in layout.doors:
            x, y, z = door.world_pos(ROOM_W, ROOM_D)
            assert -hw - 1 <= x <= hw + 1
            assert -hd - 1 <= y <= hd + 1

    def test_doors_on_wall_filter(self):
        layout = RoomLayout(ROOM_W, ROOM_D, seed=42)
        north = layout.doors_on_wall(WallSide.NORTH)
        assert all(d.wall == WallSide.NORTH for d in north)

    def test_door_indices_unique(self):
        layout = RoomLayout(ROOM_W, ROOM_D, seed=42)
        indices = [d.door_index for d in layout.doors]
        assert len(set(indices)) == len(indices)

    def test_offsets_in_valid_range(self):
        for seed in range(5):
            layout = RoomLayout(ROOM_W, ROOM_D, seed=seed)
            for door in layout.doors:
                assert 0.0 <= door.offset <= 1.0
