"""Reflective-mode overlay — fridge UI for the vector terminal.

Renders the fridge UI when `manifest.reflective.active` is True. Per
`design_reflective_loop`: composing magnets into a poem under a
varying rule (Wario Ware DNA — V1 ships compose_three).

Layout (panel-centered, mirrors journal overlay chrome):
    ┌─────────────────────────────────────────────────┐
    │ FRIDGE — <rule.name>                            │
    │ <rule.instructions>                             │
    │                                                 │
    │ [the] [river] [moss] [breath] [...]             │  <- TRAY (cursor highlight)
    │                                                 │
    │ ┌─ COMPOSED ─────────────────────────────────┐  │
    │ │ the river moss                             │  │
    │ └────────────────────────────────────────────┘  │
    │                                                 │
    │ UP/DOWN tray  ENTER place  BKSP remove          │
    │ C commit  ESC abort (voluntary only)            │
    └─────────────────────────────────────────────────┘

Key bindings (active only when reflective overlay is rendered):
  UP / DOWN         move tray cursor
  ENTER             place tray-cursor magnet onto composed
  BACKSPACE / DELETE  remove last composed magnet
  C                 commit
  ESC               abort (brain rejects unless trigger=voluntary)

Brain owns truth (per `design_brain_ground_truth`); this module just
sends cmds and renders manifest contents.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pyray as rl

from clients.vector_terminal import config as cfg
from clients.vector_terminal import hud


PANEL_W = 720
PANEL_H = 460
PANEL_PAD = 24

LABEL_FONT_SIZE = 22
HEADER_FONT_SIZE = 16
ROW_FONT_SIZE = 18
HINT_FONT_SIZE = 14

TRAY_COLS = 6
TRAY_ROW_H = 30
TRAY_CHIP_PAD_X = 12
CANVAS_H = 80


@dataclass
class ReflectiveState:
    """Local UI cursor position into the magnet tray. Recomputed each
    frame against the manifest's pool length so brain-side pool
    changes don't strand the cursor out-of-bounds."""
    tray_cursor: int = 0


def _is_active(manifest: dict) -> bool:
    block = manifest.get("reflective")
    return bool(block and block.get("active"))


def handle_input(
    manifest: dict,
    state: ReflectiveState,
) -> tuple[str | None, dict | None]:
    """Process one frame.

    Returns (cmd_name, payload) where cmd_name is one of:
      "place"  payload {"magnet": str}
      "remove" payload {"index": int}
      "commit" payload {}
      "abort"  payload {}
      None     no action this frame
    """
    block = manifest.get("reflective") or {}
    pool: list = list(block.get("magnet_pool", []))
    composed: list = list(block.get("composed", []))
    n_pool = len(pool)

    # Clamp cursor.
    if n_pool == 0:
        state.tray_cursor = 0
    else:
        state.tray_cursor = max(0, min(state.tray_cursor, n_pool - 1))

    if rl.is_key_pressed(rl.KeyboardKey.KEY_DOWN):
        if n_pool > 0:
            state.tray_cursor = (state.tray_cursor + TRAY_COLS) % n_pool
    elif rl.is_key_pressed(rl.KeyboardKey.KEY_UP):
        if n_pool > 0:
            state.tray_cursor = (state.tray_cursor - TRAY_COLS) % n_pool
    elif rl.is_key_pressed(rl.KeyboardKey.KEY_RIGHT):
        if n_pool > 0:
            state.tray_cursor = (state.tray_cursor + 1) % n_pool
    elif rl.is_key_pressed(rl.KeyboardKey.KEY_LEFT):
        if n_pool > 0:
            state.tray_cursor = (state.tray_cursor - 1) % n_pool

    if rl.is_key_pressed(rl.KeyboardKey.KEY_ENTER):
        if n_pool > 0:
            return "place", {"magnet": pool[state.tray_cursor]}

    if (rl.is_key_pressed(rl.KeyboardKey.KEY_BACKSPACE)
            or rl.is_key_pressed(rl.KeyboardKey.KEY_DELETE)):
        if composed:
            return "remove", {"index": len(composed) - 1}

    if rl.is_key_pressed(rl.KeyboardKey.KEY_C):
        return "commit", {}

    if rl.is_key_pressed(rl.KeyboardKey.KEY_ESCAPE):
        return "abort", {}

    return None, None


def draw_overlay(
    manifest: dict,
    state: ReflectiveState,
    screen_w: int,
    screen_h: int,
    color,
) -> None:
    block = manifest.get("reflective") or {}
    rule = block.get("rule") or {}
    pool: list[str] = list(block.get("magnet_pool", []))
    composed: list[str] = list(block.get("composed", []))
    attempts = int(block.get("attempt_count", 0))
    trigger = str(block.get("trigger", ""))

    px = (screen_w - PANEL_W) // 2
    py = (screen_h - PANEL_H) // 2

    rl.draw_rectangle(0, 0, screen_w, screen_h, (0, 0, 0, 200))
    rl.draw_rectangle(px, py, PANEL_W, PANEL_H, (0, 0, 0, 240))
    rl.draw_rectangle_lines(px, py, PANEL_W, PANEL_H, color)

    font = hud.font()
    inner_x = px + PANEL_PAD
    cursor_y = py + 22

    # Header.
    title = "FRIDGE"
    if rule.get("name"):
        title = f"FRIDGE — {rule['name'].upper()}"
    rl.draw_text_ex(font, title,
                    rl.Vector2(inner_x, cursor_y),
                    LABEL_FONT_SIZE, 1.0, color)
    cursor_y += 30

    # Instructions.
    instr = str(rule.get("instructions", ""))
    if instr:
        rl.draw_text_ex(font, instr,
                        rl.Vector2(inner_x, cursor_y),
                        HEADER_FONT_SIZE, 1.0, color)
    cursor_y += 28

    # Tray label.
    rl.draw_text_ex(font, "MAGNETS",
                    rl.Vector2(inner_x, cursor_y),
                    HEADER_FONT_SIZE, 1.0, color)
    cursor_y += 22

    # Magnet tray — grid of chips.
    chip_y = cursor_y
    chip_w = (PANEL_W - PANEL_PAD * 2) // TRAY_COLS
    for i, magnet in enumerate(pool):
        col = i % TRAY_COLS
        row = i // TRAY_COLS
        cx = inner_x + col * chip_w
        cy = chip_y + row * TRAY_ROW_H
        is_cursor = (i == state.tray_cursor)
        if is_cursor:
            rl.draw_rectangle(cx - 4, cy - 2, chip_w - 8, TRAY_ROW_H - 4, color)
            rl.draw_text_ex(font, magnet,
                            rl.Vector2(cx + TRAY_CHIP_PAD_X, cy + 4),
                            ROW_FONT_SIZE, 1.0, (0, 0, 0, 255))
        else:
            rl.draw_text_ex(font, magnet,
                            rl.Vector2(cx + TRAY_CHIP_PAD_X, cy + 4),
                            ROW_FONT_SIZE, 1.0, color)
    tray_rows = (len(pool) + TRAY_COLS - 1) // TRAY_COLS
    cursor_y = chip_y + tray_rows * TRAY_ROW_H + 12

    # Canvas — the composed poem.
    rl.draw_text_ex(font, "COMPOSED",
                    rl.Vector2(inner_x, cursor_y),
                    HEADER_FONT_SIZE, 1.0, color)
    cursor_y += 22
    canvas_y = cursor_y
    rl.draw_rectangle_lines(inner_x, canvas_y,
                            PANEL_W - PANEL_PAD * 2, CANVAS_H, color)
    composed_text = " ".join(composed) if composed else "(empty)"
    rl.draw_text_ex(font, composed_text,
                    rl.Vector2(inner_x + 12, canvas_y + 12),
                    ROW_FONT_SIZE, 1.0, color)
    cursor_y = canvas_y + CANVAS_H + 14

    # Footer hints.
    hint1 = "ARROWS move  ENTER place  BKSP remove  C commit"
    hint2 = "ESC abort (voluntary only)" if trigger == "voluntary" \
        else "(commit required to continue)"
    rl.draw_text_ex(font, hint1,
                    rl.Vector2(inner_x, py + PANEL_H - 38),
                    HINT_FONT_SIZE, 1.0, color)
    rl.draw_text_ex(font, hint2,
                    rl.Vector2(inner_x, py + PANEL_H - 22),
                    HINT_FONT_SIZE, 1.0, color)

    # Attempt counter on the right edge.
    if attempts > 0:
        attempt_text = f"attempts: {attempts}"
        rl.draw_text_ex(font, attempt_text,
                        rl.Vector2(px + PANEL_W - 140, py + PANEL_H - 22),
                        HINT_FONT_SIZE, 1.0, color)
