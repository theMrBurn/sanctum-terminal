"""StateEvent toast renderer.

Consumes `manifest.state_events` (per `core/systems/state_events.py`),
shows context-appropriate toasts top-center. First-frame baseline
suppresses historical events (no spam on connect). Register field drives
per-event timing — ritual is slow breath, system is quick blip, etc.

Pure rendering + watermark tracking. No game logic.
"""
from __future__ import annotations

from dataclasses import dataclass

import pyray as rl

from clients.vector_terminal import hud as hud_module


# Register → toast duration (seconds). Tunable per-deployment without
# touching renderer logic.
DURATIONS: dict[str, float] = {
    "ritual": 3.5,    # slow breath; sacred moments
    "loop": 2.0,      # normal pacing; mission/state transitions
    "system": 1.5,    # quick blip; saves, reconnects
    "tense": 2.5,     # tight kinetic
    "discovery": 4.0, # lingering; lexicon recognition, voice echo
}
DEFAULT_DURATION = 2.0


# Layout constants — tuned for 1280×720; scale with screen size at draw.
TOAST_FONT_SIZE_LABEL = 22
TOAST_FONT_SIZE_DETAIL = 16
TOAST_PAD_X = 24
TOAST_PAD_Y = 12
TOAST_LINE_GAP = 4
TOAST_STACK_GAP = 8
TOAST_TOP_MARGIN = 56
FADE_IN = 0.18
FADE_OUT = 0.4


@dataclass
class _ActiveToast:
    event: dict     # the raw event dict from manifest
    started_at: float


def update(
    events_in_manifest: list[dict],
    seen_id: int,
    active: list[_ActiveToast],
    now: float,
) -> tuple[int, list[_ActiveToast]]:
    """Advance toast state given the latest manifest events.

    Watermark semantics:
      - seen_id == 0 (first call): sync to max id in manifest, no active
        toasts. Suppresses historical events on first connect.
      - seen_id > 0: any event with id > seen_id becomes a fresh active
        toast. Existing actives expire by duration.

    Returns (new_seen_id, new_active_list).
    """
    if not events_in_manifest:
        # No events streamed yet — preserve current state, drop expired
        return seen_id, _prune_expired(active, now)

    if seen_id == 0:
        # First-frame sync — set watermark to max, suppress history
        new_seen = max(int(e.get("id", 0)) for e in events_in_manifest)
        return new_seen, []

    new_seen = seen_id
    new_active = list(active)
    for e in events_in_manifest:
        eid = int(e.get("id", 0))
        if eid > seen_id:
            new_active.append(_ActiveToast(event=dict(e), started_at=now))
            new_seen = max(new_seen, eid)

    return new_seen, _prune_expired(new_active, now)


def _prune_expired(active: list[_ActiveToast], now: float) -> list[_ActiveToast]:
    return [
        t for t in active
        if (now - t.started_at) < DURATIONS.get(t.event.get("register", ""), DEFAULT_DURATION)
    ]


def draw(
    active: list[_ActiveToast],
    screen_w: int,
    now: float,
    color,
) -> None:
    """Render active toasts top-center, stacked vertically."""
    if not active:
        return
    font = hud_module.font()
    if font is None:
        hud_module.load_font()
        font = hud_module.font()

    # Newest at top of the stack — render in reverse so latest is most prominent
    cursor_y = TOAST_TOP_MARGIN
    for t in reversed(active):
        register = t.event.get("register", "")
        duration = DURATIONS.get(register, DEFAULT_DURATION)
        age = now - t.started_at
        if age >= duration:
            continue

        # Fade envelope: rise quickly, hold, fall over FADE_OUT
        if age < FADE_IN:
            intensity = age / FADE_IN
        elif age > duration - FADE_OUT:
            intensity = max(0.0, (duration - age) / FADE_OUT)
        else:
            intensity = 1.0
        intensity = max(0.0, min(1.0, intensity))

        toast_color = _scaled(color, intensity)

        label = str(t.event.get("label", ""))
        detail = t.event.get("detail")
        detail_str = str(detail) if detail else ""

        label_w = rl.measure_text_ex(font, label, TOAST_FONT_SIZE_LABEL, 1.0).x
        detail_w = (
            rl.measure_text_ex(font, detail_str, TOAST_FONT_SIZE_DETAIL, 1.0).x
            if detail_str else 0
        )
        panel_w = int(max(label_w, detail_w)) + TOAST_PAD_X * 2
        panel_h = TOAST_PAD_Y * 2 + TOAST_FONT_SIZE_LABEL
        if detail_str:
            panel_h += TOAST_LINE_GAP + TOAST_FONT_SIZE_DETAIL

        px = (screen_w - panel_w) // 2
        py = cursor_y

        # Background panel — dim black with subtle outline at toast color
        rl.draw_rectangle(px, py, panel_w, panel_h, (0, 0, 0, int(220 * intensity)))
        rl.draw_rectangle_lines(px, py, panel_w, panel_h, toast_color)

        # Label
        rl.draw_text_ex(
            font, label,
            rl.Vector2(px + TOAST_PAD_X, py + TOAST_PAD_Y),
            TOAST_FONT_SIZE_LABEL, 1.0, toast_color,
        )

        # Detail (optional second line)
        if detail_str:
            rl.draw_text_ex(
                font, detail_str,
                rl.Vector2(
                    px + TOAST_PAD_X,
                    py + TOAST_PAD_Y + TOAST_FONT_SIZE_LABEL + TOAST_LINE_GAP,
                ),
                TOAST_FONT_SIZE_DETAIL, 1.0, _scaled(color, intensity * 0.7),
            )

        cursor_y += panel_h + TOAST_STACK_GAP


def _scaled(color, factor: float) -> tuple[int, int, int, int]:
    r, g, b, a = color
    return int(r * factor), int(g * factor), int(b * factor), a
