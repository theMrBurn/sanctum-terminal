"""render.py — curses ASCII renderer for the NetHack make-brain.

Layout (80×24 terminal):
  Row 0:      status bar — Dlvl / HP / AC / Turn
  Rows 1-23:  map area (MAP_H - 1 rows available, map is 24 rows but
               first row is status; full map drawn offset by 1).
  Last rows:  message log (last MSG_LOG_LINES lines, drawn at bottom).

Glyph table, color pairs, and headless capture buffer all live here.

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 3.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.systems.make_brains.nethack.dungeon import MAP_H, MAP_W, Tile

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Rendering constants
# ---------------------------------------------------------------------------

MSG_LOG_LINES: int = 5     # message log lines at bottom of screen
STATUS_ROW:    int = 0     # status bar occupies row 0
MAP_ROW_OFFSET: int = 1    # map renders starting at row 1

# ---------------------------------------------------------------------------
# Tile glyphs and their curses colors
# ---------------------------------------------------------------------------

# (glyph, color_pair_id, dim_when_out_of_fov)
TILE_RENDER: dict[Tile, tuple[str, int, bool]] = {
    Tile.VOID:        (" ", 0, False),
    Tile.WALL:        ("#", 2, True),
    Tile.FLOOR:       (".", 3, True),
    Tile.CORRIDOR:    ("#", 2, True),
    Tile.DOOR:        ("+", 4, True),
    Tile.STAIRS_DOWN: (">", 5, False),
}

PLAYER_GLYPH:  str = "@"
MONSTER_GLYPH: str = "m"   # overridden per kind in entities.py
ITEM_GLYPH:    str = "i"   # overridden per kind in items.py

# ---------------------------------------------------------------------------
# Color pair registry (set up in init_colors)
# ---------------------------------------------------------------------------

# Pair IDs — 0 is reserved by curses.
PAIR_DEFAULT:  int = 1
PAIR_WALL:     int = 2
PAIR_FLOOR:    int = 3
PAIR_DOOR:     int = 4
PAIR_STAIRS:   int = 5
PAIR_PLAYER:   int = 6
PAIR_MONSTER:  int = 7
PAIR_ITEM:     int = 8
PAIR_DIM:      int = 9    # visited-but-out-of-FOV tiles


# ---------------------------------------------------------------------------
# Headless screen buffer (used for tests and CI)
# ---------------------------------------------------------------------------

class HeadlessBuffer:
    """Minimal curses-compatible screen buffer for testing.

    Captures addstr calls into a 2D char grid so tests can inspect
    what would have been drawn to the terminal.
    """

    def __init__(self, rows: int = MAP_H + 1, cols: int = MAP_W):
        self._rows = rows
        self._cols = cols
        self._buf: list[list[str]] = [[" "] * cols for _ in range(rows)]
        self._attr_buf: list[list[int]] = [[0] * cols for _ in range(rows)]

    def addch(self, y: int, x: int, ch: str | int, attr: int = 0) -> None:
        if 0 <= y < self._rows and 0 <= x < self._cols:
            if isinstance(ch, int):
                ch = chr(ch)
            self._buf[y][x] = ch
            self._attr_buf[y][x] = attr

    def addstr(self, y: int, x: int, text: str, attr: int = 0) -> None:
        for i, ch in enumerate(text):
            self.addch(y, x + i, ch, attr)

    def clear(self) -> None:
        self._buf = [[" "] * self._cols for _ in range(self._rows)]
        self._attr_buf = [[0] * self._cols for _ in range(self._rows)]

    def refresh(self) -> None:
        pass  # no-op in headless mode

    def getmaxyx(self) -> tuple[int, int]:
        return (self._rows, self._cols)

    def nodelay(self, flag: bool) -> None:
        pass

    def keypad(self, flag: bool) -> None:
        pass

    def row(self, y: int) -> str:
        """Return row y as a string (useful in assertions)."""
        return "".join(self._buf[y])

    def at(self, y: int, x: int) -> str:
        return self._buf[y][x]


# ---------------------------------------------------------------------------
# Color initialization
# ---------------------------------------------------------------------------

def init_colors() -> None:
    """Initialize curses color pairs. Call once after curses.start_color()."""
    import curses as _curses
    _curses.start_color()
    _curses.use_default_colors()

    _curses.init_pair(PAIR_DEFAULT, _curses.COLOR_WHITE,   -1)
    _curses.init_pair(PAIR_WALL,    _curses.COLOR_WHITE,   -1)
    _curses.init_pair(PAIR_FLOOR,   _curses.COLOR_WHITE,   -1)
    _curses.init_pair(PAIR_DOOR,    _curses.COLOR_YELLOW,  -1)
    _curses.init_pair(PAIR_STAIRS,  _curses.COLOR_CYAN,    -1)
    _curses.init_pair(PAIR_PLAYER,  _curses.COLOR_GREEN,   -1)
    _curses.init_pair(PAIR_MONSTER, _curses.COLOR_RED,     -1)
    _curses.init_pair(PAIR_ITEM,    _curses.COLOR_YELLOW,  -1)
    _curses.init_pair(PAIR_DIM,     _curses.COLOR_BLACK,   -1)


# ---------------------------------------------------------------------------
# Draw routines (work with both curses window and HeadlessBuffer)
# ---------------------------------------------------------------------------

def draw_status(
    win: Any,
    player: Any,         # entities.Player — duck-typed to avoid circular import
    dlvl: int,
    turn: int,
    use_curses: bool = True,
) -> None:
    """Draw the top status bar: Dlvl/HP/MaxHP/AC/XP/Level/Turn."""
    if use_curses:
        import curses as _curses
        attr = _curses.color_pair(PAIR_DEFAULT)
    else:
        attr = 0

    status = (
        f"Dlvl:{dlvl}  "
        f"HP:{player.hp}/{player.max_hp}  "
        f"AC:{player.ac}  "
        f"XP:{player.xp}  "
        f"Lv:{player.level}  "
        f"T:{turn}"
    )
    status = status[:MAP_W]  # truncate to screen width
    try:
        win.addstr(STATUS_ROW, 0, status.ljust(MAP_W), attr)
    except Exception:
        pass  # curses raises when writing to last cell of last row


def draw_map(
    win: Any,
    level: Any,          # dungeon.Level
    visible: set[tuple[int, int]],
    visited: set[tuple[int, int]],
    monsters: list[Any] | None = None,
    items: list[Any] | None = None,
    player_pos: tuple[int, int] | None = None,
    use_curses: bool = True,
) -> None:
    """Draw the dungeon map area (rows 1 through MAP_H)."""
    if use_curses:
        import curses as _curses
        A_DIM = _curses.A_DIM
        def cp(n: int) -> int:
            return _curses.color_pair(n)
    else:
        A_DIM = 0
        def cp(n: int) -> int:
            return 0

    # Build lookup sets for fast monster/item queries
    monster_positions: dict[tuple[int, int], Any] = {}
    if monsters:
        for m in monsters:
            monster_positions[(m.x, m.y)] = m

    item_positions: dict[tuple[int, int], list[Any]] = {}
    if items:
        for it in items:
            pos = (it.x, it.y)
            item_positions.setdefault(pos, []).append(it)

    for map_y in range(MAP_H):
        row = STATUS_ROW + MAP_ROW_OFFSET + map_y
        for map_x in range(MAP_W):
            pos = (map_x, map_y)
            tile = level.at(map_x, map_y)

            # Skip void and un-visited tiles
            if tile == Tile.VOID or pos not in visited:
                try:
                    win.addch(row, map_x, ord(" "), 0)
                except Exception:
                    pass
                continue

            in_fov = pos in visible

            # Determine what to draw at this cell
            if in_fov and player_pos and pos == player_pos:
                glyph = PLAYER_GLYPH
                attr = cp(PAIR_PLAYER)
            elif in_fov and pos in monster_positions:
                m = monster_positions[pos]
                glyph = getattr(m, "glyph", MONSTER_GLYPH)
                attr = cp(PAIR_MONSTER)
            elif in_fov and pos in item_positions:
                it = item_positions[pos][0]
                glyph = getattr(it, "glyph", ITEM_GLYPH)
                attr = cp(PAIR_ITEM)
            else:
                spec = TILE_RENDER.get(tile, (" ", 0, False))
                glyph, pair_id, can_dim = spec
                if not in_fov and can_dim:
                    attr = cp(PAIR_DIM) | A_DIM
                else:
                    attr = cp(pair_id)

            try:
                win.addch(row, map_x, ord(glyph), attr)
            except Exception:
                pass


def draw_messages(
    win: Any,
    messages: list[str],
    use_curses: bool = True,
    screen_rows: int = MAP_H + MSG_LOG_LINES,
) -> None:
    """Draw the last MSG_LOG_LINES messages at the bottom of the screen."""
    if use_curses:
        import curses as _curses
        attr = _curses.color_pair(PAIR_DEFAULT)
    else:
        attr = 0

    recent = messages[-MSG_LOG_LINES:]
    msg_start_row = screen_rows - MSG_LOG_LINES
    for i, line in enumerate(recent):
        row = msg_start_row + i
        try:
            win.addstr(row, 0, line[:MAP_W].ljust(MAP_W), attr)
        except Exception:
            pass


def render_frame(
    win: Any,
    level: Any,
    visible: set[tuple[int, int]],
    visited: set[tuple[int, int]],
    player: Any,
    dlvl: int,
    turn: int,
    messages: list[str],
    monsters: list[Any] | None = None,
    items: list[Any] | None = None,
    use_curses: bool = True,
) -> None:
    """Full frame render: clear, status, map, messages."""
    win.clear()
    draw_status(win, player, dlvl, turn, use_curses=use_curses)
    draw_map(
        win, level, visible, visited,
        monsters=monsters,
        items=items,
        player_pos=(player.x, player.y),
        use_curses=use_curses,
    )
    draw_messages(win, messages, use_curses=use_curses)
    win.refresh()
