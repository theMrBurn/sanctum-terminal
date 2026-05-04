"""Quest journal overlay — async-quest UAT surface.

Per `project_async_quest_refactor` PR 1.3. Press J anywhere (in HUB or
mid-mission) to open the journal; toggle any number of available
quests to active; close to resume play. World state doesn't pause —
this is an in-place overlay, not a modal state transition (per
`feedback_no_modal_state_changes`).

Reuses the dial overlay's panel chrome + viewport shape via the
existing `dial_input` primitives (`MAX_VISIBLE_OPTIONS`, `_dimmed`,
`HUD_FONT_SIZE` from cfg). No new render primitives — this is a
specialized list overlay built from the same pieces.

Cursor semantics: navigates only across toggleable rows
(active + available). Completed rows render dim and are skipped by
UP/DOWN. ENTER on the cursor row sends `journal_toggle_quest` to the
brain; the manifest reflects the new state on the next frame.

Manifest contract (per brain_server.py):
  manifest["quests"]["registry"]   id → {name, description}
  manifest["quests"]["available"]  list[id]
  manifest["quests"]["active"]     list[id]
  manifest["quests"]["completed"]  list[id]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pyray as rl

from clients.vector_terminal import config as cfg
from clients.vector_terminal import dial_input
from clients.vector_terminal import hud


PANEL_W = 600
PANEL_H = 500
PANEL_PAD = 24

LABEL_FONT_SIZE = 22
HEADER_FONT_SIZE = 16
ROW_FONT_SIZE = 18
HINT_FONT_SIZE = 14

ROW_H = 28
SECTION_GAP = 16


@dataclass
class JournalState:
    """Local cursor position. Index points into the flat toggleable
    rows list (active + available, NOT completed). Recomputed each
    frame from the manifest in case the underlying lists changed
    (e.g., a quest just completed on the brain side)."""
    cursor: int = 0


def _build_rows(manifest: dict) -> tuple[list[dict], list[dict]]:
    """Compose the journal's row lists from the manifest's quest payload.

    Returns (toggleable_rows, all_rows). Toggleable rows are the union
    of active + available, in display order; the cursor navigates this
    list. All_rows includes completed rows as well, used for rendering
    only. Each row is `{kind, id, name, description}`.
    """
    quests_payload = manifest.get("quests", {}) or {}
    registry = quests_payload.get("registry", {}) or {}
    active = list(quests_payload.get("active", []) or [])
    available = list(quests_payload.get("available", []) or [])
    completed = list(quests_payload.get("completed", []) or [])

    def _row(qid: str, kind: str) -> dict:
        meta = registry.get(qid, {}) or {}
        return {
            "kind": kind,
            "id": qid,
            "name": meta.get("name", qid),
            "description": meta.get("description", ""),
        }

    toggleable = [_row(q, "active") for q in active] \
        + [_row(q, "available") for q in available]
    all_rows = list(toggleable) + [_row(q, "completed") for q in completed]
    return toggleable, all_rows


def handle_input(
    manifest: dict,
    state: JournalState,
) -> tuple[str | None, str | None]:
    """Process one frame. Returns (action, quest_id) where action is
    "toggle" / "close" / None and quest_id is set only on "toggle"."""
    toggleable, _ = _build_rows(manifest)
    n = len(toggleable)

    # ESC closes from inside; J is owned by the outer toggle in main.py
    # so the same key cleanly opens AND closes (single keystroke loop).
    if rl.is_key_pressed(rl.KeyboardKey.KEY_ESCAPE):
        return "close", None

    if n == 0:
        # No toggleable rows — only ESC/J close has any effect.
        return None, None

    state.cursor = max(0, min(state.cursor, n - 1))

    if rl.is_key_pressed(rl.KeyboardKey.KEY_DOWN):
        state.cursor = (state.cursor + 1) % n
    if rl.is_key_pressed(rl.KeyboardKey.KEY_UP):
        state.cursor = (state.cursor - 1) % n

    if rl.is_key_pressed(rl.KeyboardKey.KEY_ENTER):
        row = toggleable[state.cursor]
        return "toggle", row["id"]

    return None, None


def draw_journal_overlay(
    manifest: dict,
    state: JournalState,
    screen_w: int,
    screen_h: int,
    color,
) -> None:
    """Render the journal overlay. Three sections (ACTIVE / AVAILABLE /
    COMPLETED), cursor-row highlighted in toggleable area, completed
    rows dim. Mirrors dial overlay chrome — same panel border, same
    dim background, same font."""
    toggleable, all_rows = _build_rows(manifest)
    px = (screen_w - PANEL_W) // 2
    py = (screen_h - PANEL_H) // 2

    rl.draw_rectangle(0, 0, screen_w, screen_h, (0, 0, 0, 200))
    rl.draw_rectangle(px, py, PANEL_W, PANEL_H, (0, 0, 0, 240))
    rl.draw_rectangle_lines(px, py, PANEL_W, PANEL_H, color)

    font = hud.font()
    inner_x = px + PANEL_PAD
    cursor_y = py + 22

    rl.draw_text_ex(font, "JOURNAL",
                    rl.Vector2(inner_x, cursor_y),
                    LABEL_FONT_SIZE, 1.0, color)
    cursor_y += 36

    # Build section data once; render in order ACTIVE / AVAILABLE / COMPLETED.
    sections = [
        ("ACTIVE", "active"),
        ("AVAILABLE", "available"),
        ("COMPLETED", "completed"),
    ]
    # Map row -> its index in the toggleable list (or -1 if completed)
    toggleable_idx = {id(r): i for i, r in enumerate(toggleable)}

    for header, kind in sections:
        rl.draw_text_ex(font, header,
                        rl.Vector2(inner_x, cursor_y),
                        HEADER_FONT_SIZE, 1.0,
                        dial_input._dimmed(color, 0.7))
        cursor_y += 22
        rows = [r for r in all_rows if r["kind"] == kind]
        if not rows:
            rl.draw_text_ex(font, "  (none)",
                            rl.Vector2(inner_x, cursor_y),
                            ROW_FONT_SIZE, 1.0,
                            dial_input._dimmed(color, 0.4))
            cursor_y += ROW_H
        for row in rows:
            t_idx = toggleable_idx.get(id(row), -1)
            is_cursor = (t_idx == state.cursor and kind != "completed")
            prefix = "> " if is_cursor else "  "
            glyph = {
                "active": "[*]",
                "available": "[ ]",
                "completed": "[x]",
            }.get(kind, "[ ]")
            text = f"{prefix}{glyph} {row['name']}"
            row_color = color if kind != "completed" else dial_input._dimmed(color, 0.45)
            rl.draw_text_ex(font, text,
                            rl.Vector2(inner_x, cursor_y),
                            ROW_FONT_SIZE, 1.0, row_color)
            cursor_y += ROW_H
        cursor_y += SECTION_GAP

    # Hint footer (anchored to panel bottom)
    hint_y = py + PANEL_H - 30
    hint_ascii = "[UP/DOWN] cursor   [ENTER] toggle   [J] close"
    rl.draw_text_ex(font, hint_ascii,
                    rl.Vector2(inner_x, hint_y),
                    HINT_FONT_SIZE, 1.0,
                    dial_input._dimmed(color, 0.45))
