"""input_map.py — keystroke to command mapping for the NetHack terminal.

V1 supports: hjkl movement, arrow keys, comma (pickup), Q (quit),
and item-management keys (w, W, q, r) added in later PRs.

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 3.
"""
from __future__ import annotations

import curses


# ---------------------------------------------------------------------------
# Command constants — what the game loop dispatches on
# ---------------------------------------------------------------------------

CMD_MOVE_N: str  = "move_n"
CMD_MOVE_S: str  = "move_s"
CMD_MOVE_E: str  = "move_e"
CMD_MOVE_W: str  = "move_w"
CMD_PICKUP: str  = "pickup"
CMD_QUIT:   str  = "quit"
CMD_STAIRS: str  = "stairs"
CMD_WIELD:  str  = "wield"
CMD_WEAR:   str  = "wear"
CMD_QUAFF:  str  = "quaff"
CMD_READ:   str  = "read"
CMD_HISCORES: str = "hiscores"
CMD_UNKNOWN: str = "unknown"


def build_keymap() -> dict[int, str]:
    """Return a mapping from curses key codes to command strings.

    Called once at game-loop start so curses constants are available.
    """
    return {
        # hjkl — classic roguelike movement
        ord("h"):          CMD_MOVE_W,
        ord("j"):          CMD_MOVE_S,
        ord("k"):          CMD_MOVE_N,
        ord("l"):          CMD_MOVE_E,
        # Arrow keys
        curses.KEY_UP:     CMD_MOVE_N,
        curses.KEY_DOWN:   CMD_MOVE_S,
        curses.KEY_LEFT:   CMD_MOVE_W,
        curses.KEY_RIGHT:  CMD_MOVE_E,
        # Item interaction
        ord(","):          CMD_PICKUP,
        ord(">"):          CMD_STAIRS,
        ord("w"):          CMD_WIELD,
        ord("W"):          CMD_WEAR,
        ord("q"):          CMD_QUAFF,
        ord("r"):          CMD_READ,
        # Meta
        ord("Q"):          CMD_QUIT,
    }


# Delta mapping: command → (dx, dy) in map coords (y increases downward)
MOVE_DELTAS: dict[str, tuple[int, int]] = {
    CMD_MOVE_N: ( 0, -1),
    CMD_MOVE_S: ( 0,  1),
    CMD_MOVE_E: ( 1,  0),
    CMD_MOVE_W: (-1,  0),
}
