"""Pillar 2 — Pillar of Days. Two-turn sundial: month → day SELECT cascade.

Player turns the sundial twice — once for the month face, once for the
day face. Both default to today, so the fast path is ENTER-ENTER.
Override either step to set any calendar date.

The sealed value is the player's in-game birthday — the calendar anchor
that ticks the level-up clock each year (per `design_character_sheet`
real-time aging).

Verb: TURN. Register: ritual.
"""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from typing import Any

from core.systems import pillars
from core.systems.character_draft import CharacterDraft
from core.systems.dial_prompt import (
    DialOption,
    DialPrompt,
    RITUAL,
    SELECT,
)


_MONTH_NAMES = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)

# Cascade-stage sentinels stashed in DialPrompt.pivot_value so next_prompt
# can route without parsing labels. Brain serializes pivot_value through
# to_manifest verbatim, so client doesn't need to interpret these.
_STAGE_MONTH = "month"
_STAGE_DAY = "day"


def _days_in_month(month: int) -> int:
    """Calendar days for the given month. Feb returns 29 — leap-day is
    always offered; the aging tick handles non-leap years upstream."""
    if month == 2:
        return 29
    # 2024 is arbitrary leap year; only Feb is special-cased above.
    return monthrange(2024, month)[1]


def _month_dial(default_month: int) -> DialPrompt:
    return DialPrompt(
        source="pillar:days",
        label="TURN THE SUNDIAL — MONTH",
        mode=SELECT,
        options=[
            DialOption(
                label=_MONTH_NAMES[m - 1],
                value=m,
                bias="today" if m == default_month else None,
            )
            for m in range(1, 13)
        ],
        default_index=default_month - 1,
        register=RITUAL,
        pivot_value=_STAGE_MONTH,
    )


def _day_dial(month: int, default_day: int) -> DialPrompt:
    n = _days_in_month(month)
    safe_default = max(1, min(default_day, n))
    return DialPrompt(
        source="pillar:days",
        label=f"TURN THE SUNDIAL — DAY OF {_MONTH_NAMES[month - 1]}",
        mode=SELECT,
        options=[
            DialOption(
                label=f"{d:02d}",
                value=(month, d),
                bias="today" if d == default_day else None,
            )
            for d in range(1, n + 1)
        ],
        default_index=safe_default - 1,
        register=RITUAL,
        pivot_value=_STAGE_DAY,
    )


@dataclass
class DaysHandler:
    pillar_id: str = "days"

    def initial_prompt(
        self,
        draft: CharacterDraft,
        hint: dict | None = None,
    ) -> DialPrompt:
        today = date.today()
        prev = (hint or {}).get("previous_birthday")
        if isinstance(prev, (list, tuple)) and len(prev) == 2:
            try:
                default_month = int(prev[0])
                if not 1 <= default_month <= 12:
                    default_month = today.month
            except (TypeError, ValueError):
                default_month = today.month
        else:
            default_month = today.month
        return _month_dial(default_month)

    def next_prompt(
        self,
        draft: CharacterDraft,
        current: DialPrompt,
        answer_idx: int,
    ) -> DialPrompt | None:
        if current.pivot_value == _STAGE_MONTH:
            month = int(current.options[answer_idx].value)
            today = date.today()
            # If picking a month other than today's, day defaults to 1
            # (no meaningful "today" within a different month).
            default_day = today.day if month == today.month else 1
            return _day_dial(month, default_day)
        # _STAGE_DAY → None signals brain to commit via apply().
        return None

    def apply(self, answer: Any) -> dict:
        if isinstance(answer, (list, tuple)) and len(answer) == 2:
            try:
                m, d = int(answer[0]), int(answer[1])
                if 1 <= m <= 12 and 1 <= d <= _days_in_month(m):
                    return {"birthday": (m, d)}
            except (TypeError, ValueError):
                pass
        return {}


pillars.register(DaysHandler())
