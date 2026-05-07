"""dungeon.py — Level data types and classic Rogue 3×3 supergrid generation.

Implements a deterministic, seed-driven dungeon generator that produces
rooms-and-corridors levels in the classic Rogue / early-NetHack style.

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 2.
"""
from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Iterator


# ---------------------------------------------------------------------------
# Map constants — locked by spec §Locked numbers
# ---------------------------------------------------------------------------

MAP_W: int = 80
MAP_H: int = 24

SUPERGRID_W: int = 3       # 3 columns of room slots
SUPERGRID_H: int = 2       # 2 rows of room slots — gives 11-tall slots so
                           # max room height can hit 8 (NetHack-feel rooms,
                           # not hallway-ratio rooms). 3-row supergrid
                           # capped slot_h at 7, forcing room_h ≤ 5.

MIN_ROOM_W: int = 4
MIN_ROOM_H: int = 4        # was 3; minimum 2-row interior is the floor.
MAX_ROOM_W: int = 12
MAX_ROOM_H: int = 8

# Leave a 1-cell border around the entire map so corridors never touch edges.
BORDER: int = 1


# ---------------------------------------------------------------------------
# Tile enum
# ---------------------------------------------------------------------------

class Tile(IntEnum):
    """Map cell types. Order matches rendering priority (lowest rendered first)."""
    VOID      = 0   # unvisited / outside map (never displayed)
    WALL      = 1
    FLOOR     = 2
    CORRIDOR  = 3
    DOOR      = 4
    STAIRS_DOWN = 5


# Tiles that are passable (player/monster can stand on them)
PASSABLE: frozenset[Tile] = frozenset({
    Tile.FLOOR, Tile.CORRIDOR, Tile.DOOR, Tile.STAIRS_DOWN
})

# Tiles that block field of view
FOV_BLOCKING: frozenset[Tile] = frozenset({Tile.WALL, Tile.VOID})


# ---------------------------------------------------------------------------
# Room dataclass
# ---------------------------------------------------------------------------

@dataclass
class Room:
    """Axis-aligned rectangular room within the level grid."""
    x: int          # leftmost column (inclusive)
    y: int          # top row (inclusive)
    w: int          # width in cells
    h: int          # height in cells

    @property
    def x2(self) -> int:
        return self.x + self.w - 1

    @property
    def y2(self) -> int:
        return self.y + self.h - 1

    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)

    def inner_cells(self) -> Iterator[tuple[int, int]]:
        """Yield all floor positions inside the room (excluding walls)."""
        for ry in range(self.y + 1, self.y + self.h - 1):
            for rx in range(self.x + 1, self.x + self.w - 1):
                yield (rx, ry)

    def random_inner(self, rng: random.Random) -> tuple[int, int]:
        """Return a random floor position inside this room."""
        rx = rng.randint(self.x + 1, self.x + self.w - 2)
        ry = rng.randint(self.y + 1, self.y + self.h - 2)
        return (rx, ry)


# ---------------------------------------------------------------------------
# Level dataclass
# ---------------------------------------------------------------------------

@dataclass
class Level:
    """A single dungeon floor.

    grid: column-major indexing grid[x][y], values are Tile.
    rooms: list of Room objects carved into the grid.
    spawn_pos: (x, y) where the player starts.
    stairs_pos: (x, y) of the STAIRS_DOWN tile.
    seed: integer seed used to generate this level (for reproducibility).
    """
    grid: list[list[Tile]]
    rooms: list[Room]
    spawn_pos: tuple[int, int]
    stairs_pos: tuple[int, int]
    seed: int

    def at(self, x: int, y: int) -> Tile:
        """Return the tile at (x, y), or VOID if out of bounds."""
        if 0 <= x < MAP_W and 0 <= y < MAP_H:
            return self.grid[x][y]
        return Tile.VOID

    def set(self, x: int, y: int, tile: Tile) -> None:
        if 0 <= x < MAP_W and 0 <= y < MAP_H:
            self.grid[x][y] = tile

    def passable(self, x: int, y: int) -> bool:
        return self.at(x, y) in PASSABLE

    def is_floor_or_passable(self, x: int, y: int) -> bool:
        return self.at(x, y) in PASSABLE

    def all_passable_positions(self) -> list[tuple[int, int]]:
        return [
            (x, y)
            for x in range(MAP_W)
            for y in range(MAP_H)
            if self.grid[x][y] in PASSABLE
        ]


# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------

def _empty_grid() -> list[list[Tile]]:
    """Return a MAP_W × MAP_H grid filled with WALL."""
    return [[Tile.WALL] * MAP_H for _ in range(MAP_W)]


def _carve_room(grid: list[list[Tile]], room: Room) -> None:
    """Stamp a room into the grid: border stays WALL, interior becomes FLOOR."""
    for ry in range(room.y, room.y + room.h):
        for rx in range(room.x, room.x + room.w):
            if rx == room.x or rx == room.x + room.w - 1:
                grid[rx][ry] = Tile.WALL
            elif ry == room.y or ry == room.y + room.h - 1:
                grid[rx][ry] = Tile.WALL
            else:
                grid[rx][ry] = Tile.FLOOR


def _carve_h_corridor(grid: list[list[Tile]], x1: int, x2: int, y: int) -> None:
    """Carve a horizontal corridor segment. Doesn't overwrite FLOOR."""
    for x in range(min(x1, x2), max(x1, x2) + 1):
        if grid[x][y] == Tile.WALL:
            grid[x][y] = Tile.CORRIDOR


def _carve_v_corridor(grid: list[list[Tile]], x: int, y1: int, y2: int) -> None:
    """Carve a vertical corridor segment. Doesn't overwrite FLOOR."""
    for y in range(min(y1, y2), max(y1, y2) + 1):
        if grid[x][y] == Tile.WALL:
            grid[x][y] = Tile.CORRIDOR


def _place_door(grid: list[list[Tile]], x: int, y: int) -> None:
    """Place a door where a corridor meets a room wall (if currently CORRIDOR)."""
    if grid[x][y] == Tile.CORRIDOR:
        grid[x][y] = Tile.DOOR


def _connect_rooms_l_shaped(
    grid: list[list[Tile]],
    rng: random.Random,
    r1: Room,
    r2: Room,
) -> None:
    """Connect two rooms with an L-shaped corridor.

    Pick a random interior cell from each room as the corridor endpoints.
    The elbow of the L is randomly either horizontal-then-vertical or
    vertical-then-horizontal.
    """
    cx1, cy1 = r1.center()
    cx2, cy2 = r2.center()

    if rng.random() < 0.5:
        # Horizontal first, then vertical
        elbow_x, elbow_y = cx2, cy1
    else:
        # Vertical first, then horizontal
        elbow_x, elbow_y = cx1, cy2

    _carve_h_corridor(grid, cx1, elbow_x, cy1)
    _carve_v_corridor(grid, elbow_x, cy1, elbow_y)
    _carve_h_corridor(grid, elbow_x, cx2, elbow_y)
    _carve_v_corridor(grid, cx2, elbow_y, cy2)


def _bfs_connected(grid: list[list[Tile]], start: tuple[int, int]) -> set[tuple[int, int]]:
    """Return all passable positions reachable from start via BFS."""
    visited: set[tuple[int, int]] = set()
    queue: deque[tuple[int, int]] = deque([start])
    visited.add(start)

    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if (nx, ny) not in visited and 0 <= nx < MAP_W and 0 <= ny < MAP_H:
                if grid[nx][ny] in PASSABLE:
                    visited.add((nx, ny))
                    queue.append((nx, ny))
    return visited


# ---------------------------------------------------------------------------
# Public generation API
# ---------------------------------------------------------------------------

def generate_level(seed: int) -> Level:
    """Generate a complete dungeon level deterministically from seed.

    Algorithm (classic Rogue 3×3 supergrid):
      1. Divide the usable map into a 3×3 grid of room-slots.
      2. For each slot, randomly decide to place a room (probability ~0.7).
         Force at least 2 rooms so there's always something to connect.
      3. Carve each room into the grid.
      4. Connect adjacent occupied slots with an L-shaped corridor.
         Adjacency is 4-directional (no diagonal corridors).
      5. Build a spanning connection so every room is reachable from every
         other room (simple: connect each room to the next in occupation order
         to guarantee a spanning tree, then add random extra connections).
      6. Place STAIRS_DOWN in a random room that is not the spawn room.
      7. Spawn position = center of room 0.
    """
    rng = random.Random(seed)
    grid = _empty_grid()

    # Slot dimensions — divide the usable interior into 3×3 slots.
    usable_w = MAP_W - 2 * BORDER
    usable_h = MAP_H - 2 * BORDER
    slot_w = usable_w // SUPERGRID_W
    slot_h = usable_h // SUPERGRID_H

    rooms: list[Room] = []
    slot_to_room: dict[tuple[int, int], Room] = {}

    # Step 1+2: attempt to place a room in each slot.
    for sg_row in range(SUPERGRID_H):
        for sg_col in range(SUPERGRID_W):
            if rng.random() < 0.75 or len(rooms) < 2:
                # Slot origin in map coords
                slot_x = BORDER + sg_col * slot_w
                slot_y = BORDER + sg_row * slot_h

                room_w = rng.randint(MIN_ROOM_W, min(MAX_ROOM_W, slot_w - 2))
                room_h = rng.randint(MIN_ROOM_H, min(MAX_ROOM_H, slot_h - 2))

                # Position the room randomly within the slot (with 1-cell margin)
                room_x = rng.randint(slot_x + 1, slot_x + slot_w - room_w - 1)
                room_y = rng.randint(slot_y + 1, slot_y + slot_h - room_h - 1)

                # Clamp to map bounds
                room_x = max(BORDER, min(room_x, MAP_W - room_w - BORDER))
                room_y = max(BORDER, min(room_y, MAP_H - room_h - BORDER))

                room = Room(room_x, room_y, room_w, room_h)
                rooms.append(room)
                slot_to_room[(sg_col, sg_row)] = room
                _carve_room(grid, room)

    # Step 3: connect rooms — spanning tree first (rooms in order)
    # then add a few extra connections for loops.
    for i in range(len(rooms) - 1):
        _connect_rooms_l_shaped(grid, rng, rooms[i], rooms[i + 1])

    # Extra connections (random pairs) to make levels feel less linear
    extra = rng.randint(0, max(0, len(rooms) - 2))
    for _ in range(extra):
        ra = rng.choice(rooms)
        rb = rng.choice(rooms)
        if ra is not rb:
            _connect_rooms_l_shaped(grid, rng, ra, rb)

    # Step 4: spawn + stairs
    spawn_room = rooms[0]
    spawn_pos = spawn_room.center()

    # Stairs go in a room that isn't the spawn room.
    stair_candidates = [r for r in rooms if r is not spawn_room]
    if not stair_candidates:
        # Edge case: only 1 room generated. Put stairs in a random inner cell
        # that isn't the spawn position.
        cells = [c for c in spawn_room.inner_cells() if c != spawn_pos]
        stairs_pos = rng.choice(cells) if cells else spawn_pos
    else:
        stair_room = rng.choice(stair_candidates)
        stairs_pos = stair_room.center()

    grid[stairs_pos[0]][stairs_pos[1]] = Tile.STAIRS_DOWN

    return Level(
        grid=grid,
        rooms=rooms,
        spawn_pos=spawn_pos,
        stairs_pos=stairs_pos,
        seed=seed,
    )
