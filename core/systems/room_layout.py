"""
core/systems/room_layout.py

Procedural door placement for Tartarus-style rooms.

Same room geometry, different door positions every time.
Doors scatter across 3 walls (north, east, west). South is spawn.
Minimum spacing enforced. Deterministic from seed.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum


class WallSide(Enum):
    NORTH = "north"
    EAST  = "east"
    WEST  = "west"


# Door faces inward from its wall
# make_textured_quad faces -Y by default
# H=0: faces -Y (south), H=90: faces +X (east), H=-90: faces -X (west)
_FACING = {
    WallSide.NORTH:   0.0,  # quad already faces -Y (south, toward player)
    WallSide.EAST:  -90.0,  # rotated to face -X (west, into room)
    WallSide.WEST:   90.0,  # rotated to face +X (east, into room)
}

DOOR_WIDTH  = 1.8
DOOR_HEIGHT = 3.2
MIN_SPACING = 2.5   # minimum distance between any two doors
CORNER_MARGIN = 2.0  # keep doors away from room corners


@dataclass(frozen=True)
class DoorPlacement:
    """One door's position in a room."""
    wall: WallSide
    offset: float       # 0.0-1.0 along usable wall length
    door_index: int     # 0-7, maps to CorridorScene.doors

    def world_pos(self, room_w: float, room_d: float) -> tuple[float, float, float]:
        """World position (x, y, z) of this door's center."""
        hw, hd = room_w / 2, room_d / 2
        margin = CORNER_MARGIN
        z = DOOR_HEIGHT / 2

        if self.wall == WallSide.NORTH:
            usable = room_w - 2 * margin
            x = -hw + margin + self.offset * usable
            return (x, hd - 0.1, z)

        elif self.wall == WallSide.EAST:
            usable = room_d - 2 * margin
            y = -hd + margin + self.offset * usable
            return (hw - 0.1, y, z)

        elif self.wall == WallSide.WEST:
            usable = room_d - 2 * margin
            y = -hd + margin + self.offset * usable
            return (-hw + 0.1, y, z)

        return (0, 0, z)

    @property
    def facing_h(self) -> float:
        """Heading in degrees — door faces into room."""
        return _FACING[self.wall]

    def hinge_offset(self) -> tuple[float, float]:
        """
        Local offset from door center to hinge edge.
        Used to create a pivot NodePath for swing animation.
        """
        hw = DOOR_WIDTH / 2
        if self.wall == WallSide.NORTH:
            return (-hw, 0.0)  # hinge on left edge
        elif self.wall == WallSide.EAST:
            return (0.0, -hw)
        elif self.wall == WallSide.WEST:
            return (0.0, hw)
        return (0.0, 0.0)


class RoomLayout:
    """
    Generates random door placements for a room.

    Parameters
    ----------
    width      : room width (X axis)
    depth      : room depth (Y axis)
    door_count : number of doors (default 8)
    seed       : RNG seed for deterministic layout
    """

    def __init__(self, width: float, depth: float,
                 door_count: int = 8, seed: int = 0):
        self.width = width
        self.depth = depth
        self.door_count = door_count
        self.rng = random.Random(seed)
        self.doors: list[DoorPlacement] = []
        self._generate()

    def _generate(self):
        """Distribute doors across walls with minimum spacing."""
        walls = [WallSide.NORTH, WallSide.EAST, WallSide.WEST]

        # Ensure at least 1 door per wall, rest distributed randomly
        assignments: list[WallSide] = []
        for wall in walls:
            assignments.append(wall)
        for _ in range(self.door_count - len(walls)):
            assignments.append(self.rng.choice(walls))
        self.rng.shuffle(assignments)

        # Group by wall
        wall_doors: dict[WallSide, list[int]] = {w: [] for w in walls}
        for i, wall in enumerate(assignments[:self.door_count]):
            wall_doors[wall].append(i)

        # Place doors on each wall with spacing, then validate cross-wall
        for _attempt in range(20):
            placements = []
            for wall, indices in wall_doors.items():
                if not indices:
                    continue
                offsets = self._distribute_on_wall(len(indices), wall)
                for idx, offset in zip(indices, offsets):
                    placements.append(DoorPlacement(
                        wall=wall, offset=offset, door_index=idx
                    ))

            if self._check_cross_wall_spacing(placements):
                break

        # Sort by door_index for consistent access
        self.doors = sorted(placements, key=lambda d: d.door_index)

    def _check_cross_wall_spacing(self, placements: list[DoorPlacement]) -> bool:
        """Verify no two doors are too close across different walls."""
        positions = [p.world_pos(self.width, self.depth) for p in placements]
        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                dx = positions[i][0] - positions[j][0]
                dy = positions[i][1] - positions[j][1]
                dist = (dx * dx + dy * dy) ** 0.5
                if dist < MIN_SPACING * 0.9:
                    return False
        return True

    def _distribute_on_wall(self, count: int, wall: WallSide) -> list[float]:
        """
        Generate evenly-jittered offsets for `count` doors on a wall.
        Returns list of floats in [0, 1].
        """
        if count == 0:
            return []
        if count == 1:
            return [self.rng.uniform(0.3, 0.7)]

        # Compute wall length for spacing check
        if wall == WallSide.NORTH:
            wall_len = self.width - 2 * CORNER_MARGIN
        else:
            wall_len = self.depth - 2 * CORNER_MARGIN

        min_gap = MIN_SPACING / wall_len if wall_len > 0 else 0.3

        # Start with even distribution, add jitter
        base_spacing = 1.0 / (count + 1)
        offsets = []
        for i in range(count):
            base = (i + 1) * base_spacing
            jitter = self.rng.uniform(-base_spacing * 0.3, base_spacing * 0.3)
            offsets.append(max(0.05, min(0.95, base + jitter)))

        # Sort and enforce minimum spacing
        offsets.sort()
        for i in range(1, len(offsets)):
            if offsets[i] - offsets[i - 1] < min_gap:
                offsets[i] = min(0.95, offsets[i - 1] + min_gap)

        return offsets

    def doors_on_wall(self, wall: WallSide) -> list[DoorPlacement]:
        """All doors placed on a specific wall."""
        return [d for d in self.doors if d.wall == wall]

    def all_world_positions(self) -> list[tuple[float, float, float]]:
        """World positions for all doors."""
        return [d.world_pos(self.width, self.depth) for d in self.doors]
