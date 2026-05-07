"""Volley console — text input overlay.

Bottom-of-screen overlay for live profile tuning. Backtick toggles open;
ESC closes. Each ENTER fires `console_exec` to the brain; ack output
lines append to the scrollback.

Per `.claude/feature/feat_make-brain-ping-pong.md` PR 7.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pyray as rl

from clients.vector_terminal import config as cfg


# Maximum scrollback lines retained. Older lines drop off.
_HISTORY_CAP = 24

# Maximum input line length (sanity guard against runaway typing).
_INPUT_CAP = 240

# Visible character range for raylib char input.
_PRINTABLE_MIN = 32
_PRINTABLE_MAX = 126


@dataclass
class ConsoleState:
    open:    bool       = False
    input:   str        = ""
    history: list[str]  = field(default_factory=list)
    cmd_history: list[str] = field(default_factory=list)
    cmd_history_idx: int = -1     # -1 = not browsing; >=0 = index into cmd_history


def toggle(state: ConsoleState) -> None:
    state.open = not state.open
    if not state.open:
        state.input = ""
        state.cmd_history_idx = -1


def close(state: ConsoleState) -> None:
    state.open = False
    state.input = ""
    state.cmd_history_idx = -1


def append_output(state: ConsoleState, lines: list[str]) -> None:
    """Append output lines to scrollback, trimming to cap."""
    for line in lines:
        state.history.append(str(line))
    if len(state.history) > _HISTORY_CAP:
        state.history = state.history[-_HISTORY_CAP:]


def consume_chars(state: ConsoleState) -> None:
    """Drain raylib's char-pressed queue into the current input line."""
    while True:
        ch = rl.get_char_pressed()
        if ch == 0:
            break
        if _PRINTABLE_MIN <= ch <= _PRINTABLE_MAX:
            if len(state.input) < _INPUT_CAP:
                state.input += chr(ch)


def handle_editing(state: ConsoleState) -> str | None:
    """Handle BACKSPACE / ENTER / UP / DOWN. Returns the submitted line
    on ENTER (caller dispatches to brain), else None."""
    if rl.is_key_pressed(rl.KeyboardKey.KEY_BACKSPACE):
        state.input = state.input[:-1]
        state.cmd_history_idx = -1
    if rl.is_key_pressed(rl.KeyboardKey.KEY_ENTER):
        line = state.input
        state.input = ""
        state.cmd_history_idx = -1
        if line.strip():
            state.cmd_history.append(line)
            if len(state.cmd_history) > _HISTORY_CAP:
                state.cmd_history = state.cmd_history[-_HISTORY_CAP:]
            append_output(state, [f"> {line}"])
        return line
    if rl.is_key_pressed(rl.KeyboardKey.KEY_UP):
        if state.cmd_history:
            if state.cmd_history_idx == -1:
                state.cmd_history_idx = len(state.cmd_history) - 1
            elif state.cmd_history_idx > 0:
                state.cmd_history_idx -= 1
            state.input = state.cmd_history[state.cmd_history_idx]
    if rl.is_key_pressed(rl.KeyboardKey.KEY_DOWN):
        if state.cmd_history and state.cmd_history_idx >= 0:
            if state.cmd_history_idx < len(state.cmd_history) - 1:
                state.cmd_history_idx += 1
                state.input = state.cmd_history[state.cmd_history_idx]
            else:
                state.cmd_history_idx = -1
                state.input = ""
    return None


# ----------------------------------------------------------------------
# Render
# ----------------------------------------------------------------------


def render(state: ConsoleState, screen_w: int, screen_h: int, color, bg_color) -> None:
    """Draw the overlay. Caller must be OUT of begin_mode_3d (2D mode)."""
    if not state.open:
        return
    line_h = max(14, cfg.HUD_LINE_HEIGHT)
    visible_lines = 12                            # number of history rows shown
    pane_h = (visible_lines + 1) * line_h + 16    # +1 for input row, +pad
    pane_y = screen_h - pane_h - 8
    pane_x = 8
    pane_w = screen_w - 16

    # Backdrop — translucent dark.
    rl.draw_rectangle(
        pane_x, pane_y, pane_w, pane_h,
        rl.Color(0, 0, 0, 180),
    )
    rl.draw_rectangle_lines(
        pane_x, pane_y, pane_w, pane_h, color,
    )

    # History (newest at bottom, just above the input row).
    history_top_y = pane_y + 8
    visible = state.history[-visible_lines:]
    for i, line in enumerate(visible):
        rl.draw_text(line, pane_x + 8, history_top_y + i * line_h, line_h - 4, color)

    # Input line — `> input_| `
    cursor = "_"
    prompt = f"> {state.input}{cursor}"
    rl.draw_text(
        prompt,
        pane_x + 8,
        pane_y + pane_h - line_h - 4,
        line_h - 4,
        color,
    )
