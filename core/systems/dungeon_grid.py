"""
core/systems/dungeon_grid.py

DungeonGrid -- discrete grid movement for Wizardry-style dungeon crawl.

Camera snaps to positions, faces N/S/E/W. No free movement.
Each step is a deliberate choice. The grid is the labyrinth.
"""

from __future__ import annotations

# Direction vectors
_DIRECTIONS = {
    "N": (0, 1),
    "E": (1, 0),
    "S": (0, -1),
    "W": (-1, 0),
}

_TURN_RIGHT = {"N": "E", "E": "S", "S": "W", "W": "N"}
_TURN_LEFT  = {"N": "W", "W": "S", "S": "E", "E": "N"}


class DungeonGrid:
    """
    Discrete grid position and facing direction.

    Movement: step_forward, step_back, turn_left, turn_right.
    Position: (x, y) integer grid coordinates.
    Facing: N/S/E/W.
    """

    def __init__(self, pos: tuple = (0, 0), facing: str = "N"):
        self.pos = pos
        self.facing = facing

    def step_forward(self):
        dx, dy = _DIRECTIONS[self.facing]
        self.pos = (self.pos[0] + dx, self.pos[1] + dy)

    def step_back(self):
        dx, dy = _DIRECTIONS[self.facing]
        self.pos = (self.pos[0] - dx, self.pos[1] - dy)

    def turn_right(self):
        self.facing = _TURN_RIGHT[self.facing]

    def turn_left(self):
        self.facing = _TURN_LEFT[self.facing]

    def world_pos(self, grid_scale: float = 4.0) -> tuple:
        """Convert grid position to world coordinates."""
        return (self.pos[0] * grid_scale, self.pos[1] * grid_scale, 0)

    def world_heading(self) -> float:
        """Convert facing to degrees for camera heading."""
        return {"N": 0, "E": 270, "S": 180, "W": 90}[self.facing]
