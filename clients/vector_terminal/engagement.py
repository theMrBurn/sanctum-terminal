"""Creature engagement overlay — vector terminal V1.

Renders the active engagement based on `manifest.engagement_state.
engagement_type`. V1 implements `compose_three` directly here; per
the spec, PR 6 splits each type into its own overlay file as the
catalog grows.

Mirrors reflective_overlay's structure (input handler returns
(cmd, payload) tuples; main.py wires them to brain cmds). Compose_three
overlay matches the fridge UI shape since the cognitive model is the
same: tray + composed area + commit button.

Brain owns truth (`design_brain_ground_truth`); this module reads
manifest.engagement_state every frame and emits cmds.
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
class EngagementState:
    """Local UI cursor into the magnet tray. Recomputed each frame
    against the live pool length so brain-side changes don't strand
    the cursor."""
    tray_cursor: int = 0


def is_active(manifest: dict) -> bool:
    """True when the brain reports an engagement is in flight."""
    block = manifest.get("engagement_state")
    return bool(block)


def engagement_type(manifest: dict) -> str:
    block = manifest.get("engagement_state") or {}
    return str(block.get("engagement_type", ""))


# ── Input dispatcher ─────────────────────────────────────────────────


def handle_input(
    manifest: dict,
    state: EngagementState,
) -> tuple[str | None, dict | None]:
    """Process one frame. Dispatches by engagement_type.

    Returns (cmd_name, payload):
      "engagement_place"  {"magnet": str}
      "engagement_remove" {"index": int}
      "engagement_commit" {}
      "engagement_abort"  {}
      None                no action this frame

    V1: compose_three is the only registered engagement type. Other
    types fall through to None (the overlay still draws a "(unsupported
    engagement type)" placeholder via draw_overlay)."""
    et = engagement_type(manifest)
    if et == "compose_three":
        return _handle_compose_three_input(manifest, state)
    return None, None


def _handle_compose_three_input(
    manifest: dict,
    state: EngagementState,
) -> tuple[str | None, dict | None]:
    block = manifest.get("engagement_state") or {}
    pool: list = list(block.get("pool", []))
    composed: list = list(block.get("composed", []))
    n_pool = len(pool)

    # Clamp cursor against live pool.
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
            return "engagement_place", {"magnet": pool[state.tray_cursor]}

    if (rl.is_key_pressed(rl.KeyboardKey.KEY_BACKSPACE)
            or rl.is_key_pressed(rl.KeyboardKey.KEY_DELETE)):
        if composed:
            return "engagement_remove", {"index": len(composed) - 1}

    if rl.is_key_pressed(rl.KeyboardKey.KEY_C):
        return "engagement_commit", {}

    if rl.is_key_pressed(rl.KeyboardKey.KEY_ESCAPE):
        return "engagement_abort", {}

    return None, None


# ── Drawing ──────────────────────────────────────────────────────────


def draw_overlay(
    manifest: dict,
    state: EngagementState,
    screen_w: int,
    screen_h: int,
    color,
) -> None:
    """Dispatch to the per-type renderer. Unknown types render a
    placeholder so the player isn't stuck staring at nothing if the
    brain ships a new type before the client knows it."""
    et = engagement_type(manifest)
    if et == "compose_three":
        _draw_compose_three(manifest, state, screen_w, screen_h, color)
    else:
        _draw_unsupported(et, screen_w, screen_h, color)


def _draw_compose_three(
    manifest: dict,
    state: EngagementState,
    screen_w: int,
    screen_h: int,
    color,
) -> None:
    block = manifest.get("engagement_state") or {}
    kind = str(block.get("kind", ""))
    pool: list[str] = list(block.get("pool", []))
    composed: list[str] = list(block.get("composed", []))
    target = int(block.get("target_count") or 0)
    attempts = int(block.get("attempt_count", 0))
    max_attempts = int(block.get("max_attempts") or 0)

    px = (screen_w - PANEL_W) // 2
    py = (screen_h - PANEL_H) // 2

    rl.draw_rectangle(0, 0, screen_w, screen_h, (0, 0, 0, 200))
    rl.draw_rectangle(px, py, PANEL_W, PANEL_H, (0, 0, 0, 240))
    rl.draw_rectangle_lines(px, py, PANEL_W, PANEL_H, color)

    font = hud.font()
    inner_x = px + PANEL_PAD
    cursor_y = py + 22

    # Header — engagement framing
    title = f"ENGAGE — {kind.upper()}" if kind else "ENGAGE"
    rl.draw_text_ex(font, title,
                    rl.Vector2(inner_x, cursor_y),
                    LABEL_FONT_SIZE, 1.0, color)
    cursor_y += 30

    # Instructions
    instr = f"Compose {target} magnets, then commit."
    rl.draw_text_ex(font, instr,
                    rl.Vector2(inner_x, cursor_y),
                    HEADER_FONT_SIZE, 1.0, color)
    cursor_y += 28

    # Tray label
    rl.draw_text_ex(font, "MAGNETS",
                    rl.Vector2(inner_x, cursor_y),
                    HEADER_FONT_SIZE, 1.0, color)
    cursor_y += 22

    # Magnet tray — grid of chips
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

    # Canvas — the composed sequence
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

    # Footer hints
    hint1 = "ARROWS move  ENTER place  BKSP remove  C commit"
    hint2 = "ESC abort"
    rl.draw_text_ex(font, hint1,
                    rl.Vector2(inner_x, py + PANEL_H - 38),
                    HINT_FONT_SIZE, 1.0, color)
    rl.draw_text_ex(font, hint2,
                    rl.Vector2(inner_x, py + PANEL_H - 22),
                    HINT_FONT_SIZE, 1.0, color)

    # Attempt counter on the right edge
    if max_attempts > 0:
        attempt_text = f"attempts: {attempts}/{max_attempts}"
    elif attempts > 0:
        attempt_text = f"attempts: {attempts}"
    else:
        attempt_text = ""
    if attempt_text:
        rl.draw_text_ex(font, attempt_text,
                        rl.Vector2(px + PANEL_W - 160, py + PANEL_H - 22),
                        HINT_FONT_SIZE, 1.0, color)


def _draw_unsupported(et: str, screen_w: int, screen_h: int, color) -> None:
    """Placeholder for engagement_types the client doesn't render yet."""
    rl.draw_rectangle(0, 0, screen_w, screen_h, (0, 0, 0, 200))
    msg = f"(engagement type {et!r} — overlay not implemented)"
    font = hud.font()
    rl.draw_text_ex(font, msg,
                    rl.Vector2(screen_w // 2 - 240, screen_h // 2),
                    LABEL_FONT_SIZE, 1.0, color)
