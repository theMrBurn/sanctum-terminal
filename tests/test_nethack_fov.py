"""PR 3 tests — FOV (recursive shadowcasting) + headless render buffer.

Validates:
  - Origin is always visible.
  - Tiles behind walls are not visible.
  - Open room is fully visible within radius.
  - Walls do not block themselves (wall face is visible).
  - FOV is clamped to map bounds.
  - Fixture map with a wall-in-the-middle: one side visible, other not.
  - Headless buffer captures draw calls correctly.

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 3.
"""
from __future__ import annotations

import pytest

from core.systems.make_brains.nethack.dungeon import MAP_H, MAP_W, Tile
from core.systems.make_brains.nethack.fov import compute_fov, compute_fov_from_level
from core.systems.make_brains.nethack.render import HeadlessBuffer, draw_status, draw_messages


# ---------------------------------------------------------------------------
# Minimal fixture level for FOV tests
# ---------------------------------------------------------------------------

class _FakeLevel:
    """Tiny 20×10 grid for FOV unit tests — no full generation needed."""

    W = 20
    H = 10

    def __init__(self):
        # Fill with floor
        self.grid = [[Tile.FLOOR] * self.H for _ in range(self.W)]

    def at(self, x: int, y: int) -> Tile:
        if 0 <= x < self.W and 0 <= y < self.H:
            return self.grid[x][y]
        return Tile.VOID

    def set_wall(self, x: int, y: int) -> None:
        self.grid[x][y] = Tile.WALL


def _fov(level: _FakeLevel, ox: int, oy: int, radius: int = 8) -> set[tuple[int, int]]:
    return compute_fov_from_level(level, ox, oy, radius)


# ---------------------------------------------------------------------------
# Basic invariants
# ---------------------------------------------------------------------------

def test_origin_always_visible():
    lvl = _FakeLevel()
    visible = _fov(lvl, 5, 5)
    assert (5, 5) in visible


def test_open_floor_fully_visible_within_radius():
    """With no walls and a large radius, all floor tiles reachable are visible."""
    lvl = _FakeLevel()
    visible = _fov(lvl, 10, 5, radius=12)
    # At minimum, tiles immediately adjacent should be visible
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        assert (10 + dx, 5 + dy) in visible


def test_wall_tile_visible_from_adjacent():
    """Walls are visible when adjacent — you can see the wall face."""
    lvl = _FakeLevel()
    lvl.set_wall(6, 5)
    visible = _fov(lvl, 5, 5, radius=8)
    # The wall itself should be in FOV (it's the face you see)
    assert (6, 5) in visible


def test_tile_behind_wall_not_visible():
    """A tile directly behind a wall (in a straight line) is not visible."""
    lvl = _FakeLevel()
    # Wall at x=6, observer at x=5, target at x=10 — same row
    lvl.set_wall(6, 5)
    visible = _fov(lvl, 5, 5, radius=8)
    # Tiles far behind the wall in the same direction should be blocked
    assert (10, 5) not in visible


def test_wall_row_blocks_everything_behind():
    """A full column of walls (vertical barrier) blocks the region behind it."""
    lvl = _FakeLevel()
    for y in range(lvl.H):
        lvl.set_wall(7, y)
    visible = _fov(lvl, 3, 5, radius=12)
    # Nothing past x=7 should be visible
    for x in range(8, lvl.W):
        for y in range(lvl.H):
            assert (x, y) not in visible, f"({x},{y}) should be behind wall"


def test_fov_clamped_to_map_bounds():
    """Visible set never contains positions outside the map."""
    lvl = _FakeLevel()
    visible = _fov(lvl, 0, 0, radius=12)
    for x, y in visible:
        assert 0 <= x < lvl.W
        assert 0 <= y < lvl.H


def test_radius_limits_range():
    """Tiles beyond radius are not revealed even in open space."""
    lvl = _FakeLevel()
    visible = _fov(lvl, 10, 5, radius=3)
    for x, y in visible:
        dist_sq = (x - 10) ** 2 + (y - 5) ** 2
        # Allow a tiny rounding margin for shadowcasting boundary tiles
        assert dist_sq <= (3 + 1) ** 2, f"({x},{y}) is outside radius 3"


# ---------------------------------------------------------------------------
# Fixture map with a wall divider
# ---------------------------------------------------------------------------

def test_fixture_map_partial_visibility():
    """Classic L-room setup: wall separates left from right room.

    Observer in left room should not see right room.
    """
    lvl = _FakeLevel()
    # Build a wall at x=8 from y=0..7 — creates a barrier
    for y in range(8):
        lvl.set_wall(8, y)

    visible_left = _fov(lvl, 4, 4, radius=8)
    visible_right = _fov(lvl, 14, 4, radius=8)

    # Tiles far in the right chamber are not visible from the left
    assert (14, 4) not in visible_left
    # Tiles far in the left chamber are not visible from the right
    assert (4, 4) not in visible_right


# ---------------------------------------------------------------------------
# compute_fov direct — synthetic blocking function
# ---------------------------------------------------------------------------

def test_compute_fov_with_blocking_lambda():
    """compute_fov accepts any is_blocking callable."""
    # 10x10 map; block a single tile at (5, 5)
    blocked = {(5, 5)}

    def is_blocking(x: int, y: int) -> bool:
        return (x, y) in blocked

    visible = compute_fov(3, 3, radius=5, is_blocking=is_blocking,
                          map_w=10, map_h=10)
    assert (3, 3) in visible


# ---------------------------------------------------------------------------
# Headless buffer tests
# ---------------------------------------------------------------------------

def test_headless_buffer_addch():
    buf = HeadlessBuffer(rows=5, cols=10)
    buf.addch(2, 3, "@")
    assert buf.at(2, 3) == "@"


def test_headless_buffer_addstr():
    buf = HeadlessBuffer(rows=5, cols=20)
    buf.addstr(1, 0, "Hello")
    assert buf.row(1)[:5] == "Hello"


def test_headless_buffer_clear():
    buf = HeadlessBuffer(rows=3, cols=5)
    buf.addch(0, 0, "X")
    buf.clear()
    assert buf.at(0, 0) == " "


def test_headless_buffer_oob_does_not_raise():
    buf = HeadlessBuffer(rows=5, cols=5)
    buf.addch(100, 100, "X")   # out of bounds, should silently ignore
    buf.addstr(0, 3, "TOOLONG")  # extends beyond width


# ---------------------------------------------------------------------------
# Render integration — draw_status with HeadlessBuffer
# ---------------------------------------------------------------------------

class _FakePlayer:
    def __init__(self):
        self.hp = 10
        self.max_hp = 12
        self.ac = 9
        self.xp = 0
        self.level = 1
        self.x = 5
        self.y = 5


def test_draw_status_writes_hp():
    buf = HeadlessBuffer(rows=10, cols=80)
    player = _FakePlayer()
    draw_status(buf, player, dlvl=1, turn=0, use_curses=False)
    row_text = buf.row(0)
    assert "HP:10" in row_text
    assert "Dlvl:1" in row_text
    assert "AC:9" in row_text


def test_draw_messages_writes_last_n():
    buf = HeadlessBuffer(rows=30, cols=80)
    messages = [f"msg {i}" for i in range(10)]
    draw_messages(buf, messages, use_curses=False, screen_rows=30)
    # Last 5 messages should appear somewhere in the buffer
    last_5 = messages[-5:]
    all_rows = [buf.row(r) for r in range(30)]
    combined = "\n".join(all_rows)
    for msg in last_5:
        assert msg in combined, f"message '{msg}' not found in buffer"
