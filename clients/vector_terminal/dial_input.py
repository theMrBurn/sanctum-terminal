"""Universal dial overlay renderer.

Reads `manifest.dial_prompt` and renders a 2D overlay on top of the 3D
scene. Same renderer for any source (pillar, chest, latch, dialog) per
`design_dial_input` — atmospheric register changes the timing curve, but
the visual structure is identical.

Input handling:
- Arrow up / down: cycle selection
- ENTER: commit current selection
- 1-9 number keys: jump-select by index
- Esc: cancel (closes dial without committing — caller decides whether
  to re-engage)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pyray as rl

from clients.vector_terminal import config as cfg
from clients.vector_terminal import hud


# Pulse-rate per register. Vector terminal uses these to vary the dial's
# breathing animation by context. Per `design_dial_input` atmospheric table.
PULSE_HZ_BY_REGISTER: dict[str, float] = {
    "ritual": 0.3,         # slow breath — sacred moments
    "tense": 1.5,          # tight kinetic — encounters
    "ambient": 0.8,        # light glance — chests, latches
    "reflective": 0.4,     # peripheral — journal moments
    "transactional": 1.0,  # moderate — vendors
}


# Layout — derived from screen dims at draw time. Defaults sized for 1280×720.
PANEL_W = 540
PANEL_H_PER_OPTION = 32
PANEL_PAD = 24
LABEL_FONT_SIZE = 22
OPTION_FONT_SIZE = 18
BIAS_FONT_SIZE = 14
HINT_FONT_SIZE = 14

# Cap the number of option rows drawn at once. Beyond this, the overlay
# scrolls — selected_idx stays centered and "..." indicators show when
# more options exist above/below. Sized so 720p has comfortable margins.
MAX_VISIBLE_OPTIONS = 12


def visible_window(option_count: int, selected_idx: int) -> tuple[int, int]:
    """Return [start, end) slice of options to render.

    For lists at or below MAX_VISIBLE_OPTIONS, returns the full range.
    Otherwise centers a window of MAX_VISIBLE_OPTIONS around selected_idx,
    clamped to the list bounds.
    """
    if option_count <= MAX_VISIBLE_OPTIONS:
        return 0, option_count
    half = MAX_VISIBLE_OPTIONS // 2
    start = max(0, selected_idx - half)
    end = start + MAX_VISIBLE_OPTIONS
    if end > option_count:
        end = option_count
        start = end - MAX_VISIBLE_OPTIONS
    return start, end


def panel_height(option_count: int) -> int:
    rows = min(option_count, MAX_VISIBLE_OPTIONS)
    # Reserve 2 extra row-heights for "..." indicators when scrolling.
    indicator_rows = 2 if option_count > MAX_VISIBLE_OPTIONS else 0
    return 100 + (rows + indicator_rows) * PANEL_H_PER_OPTION + 40


def draw_dial_overlay(
    prompt: dict,
    selected_idx: int,
    screen_w: int,
    screen_h: int,
    color,
) -> None:
    """Render the active dial. `prompt` is the manifest's dial_prompt dict.
    `selected_idx` is the client's local cursor; brain is told only on commit.
    """
    options = prompt.get("options", [])
    if not options:
        return

    panel_w = PANEL_W
    panel_h = panel_height(len(options))
    px = (screen_w - panel_w) // 2
    py = (screen_h - panel_h) // 2

    # Dim the world behind
    rl.draw_rectangle(0, 0, screen_w, screen_h, (0, 0, 0, 200))
    # Panel
    rl.draw_rectangle(px, py, panel_w, panel_h, (0, 0, 0, 240))
    rl.draw_rectangle_lines(px, py, panel_w, panel_h, color)

    font = hud.font()
    inner_x = px + PANEL_PAD
    cursor_y = py + 24

    # Label (the pillar's prompt, e.g., "INSCRIBE YOUR NAME")
    label = str(prompt.get("label", ""))
    rl.draw_text_ex(font, label, rl.Vector2(inner_x, cursor_y),
                    LABEL_FONT_SIZE, 1.0, color)
    cursor_y += 40

    # Options — selected one highlighted with a leading marker, others dim.
    # When the list exceeds MAX_VISIBLE_OPTIONS, render only a window
    # centered on selected_idx and show "..." indicators above/below.
    window_start, window_end = visible_window(len(options), selected_idx)
    if window_start > 0:
        rl.draw_text_ex(font, "  ...",
                        rl.Vector2(inner_x, cursor_y),
                        OPTION_FONT_SIZE, 1.0, _dimmed(color, 0.45))
        cursor_y += PANEL_H_PER_OPTION
    for i in range(window_start, window_end):
        opt = options[i]
        is_selected = (i == selected_idx)
        prefix = "> " if is_selected else "  "
        # Index label uses 1-based numbering matching the [1-9] jump-select
        # contract for the first 9 options; later entries omit the bracket
        # since they aren't keyboard-jumpable.
        idx_label = f"[{i + 1}] " if i < 9 else "    "
        text = f"{prefix}{idx_label}{opt.get('label', '')}"
        opt_color = color if is_selected else _dimmed(color, 0.55)
        rl.draw_text_ex(font, text,
                        rl.Vector2(inner_x, cursor_y),
                        OPTION_FONT_SIZE, 1.0, opt_color)
        bias = opt.get("bias")
        if bias:
            bias_x = inner_x + 280
            rl.draw_text_ex(font, f"({bias})",
                            rl.Vector2(bias_x, cursor_y + 3),
                            BIAS_FONT_SIZE, 1.0, _dimmed(color, 0.5))
        cursor_y += PANEL_H_PER_OPTION
    if window_end < len(options):
        rl.draw_text_ex(font, "  ...",
                        rl.Vector2(inner_x, cursor_y),
                        OPTION_FONT_SIZE, 1.0, _dimmed(color, 0.45))

    cursor_y += 20
    hint = "[↑/↓] cycle    [ENTER] commit    [ESC] cancel"
    # ↑/↓ arrows are unicode but hud font (VT323) limited charset — fall back
    # to text approximations.
    hint_ascii = "[UP/DOWN] cycle    [1-9] jump    [ENTER] commit    [ESC] cancel"
    rl.draw_text_ex(font, hint_ascii,
                    rl.Vector2(inner_x, cursor_y),
                    HINT_FONT_SIZE, 1.0, _dimmed(color, 0.45))


def _dimmed(color, factor: float) -> tuple[int, int, int, int]:
    r, g, b, a = color
    return int(r * factor), int(g * factor), int(b * factor), a


def handle_input(
    prompt: dict,
    selected_idx: int,
) -> tuple[int, str | None]:
    """Process one frame of dial input. Returns (new_selected_idx, action)
    where action is "commit" / "cancel" / None."""
    options = prompt.get("options", [])
    if not options:
        return selected_idx, None
    n = len(options)

    if rl.is_key_pressed(rl.KeyboardKey.KEY_DOWN):
        selected_idx = (selected_idx + 1) % n
    if rl.is_key_pressed(rl.KeyboardKey.KEY_UP):
        selected_idx = (selected_idx - 1) % n

    # 1-9 jump-select
    for i in range(min(9, n)):
        key = getattr(rl.KeyboardKey, f"KEY_{['ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE'][i]}")
        if rl.is_key_pressed(key):
            selected_idx = i

    if rl.is_key_pressed(rl.KeyboardKey.KEY_ENTER):
        return selected_idx, "commit"
    if rl.is_key_pressed(rl.KeyboardKey.KEY_ESCAPE):
        return selected_idx, "cancel"

    return selected_idx, None


def pillar_id_from_kind(kind: str) -> str | None:
    """Extract pillar id from an entity kind name.
    'pillar_name' → 'name'; 'rat' → None."""
    if kind.startswith("pillar_"):
        return kind[len("pillar_"):]
    return None
