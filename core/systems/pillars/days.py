"""Pillar 2 — Pillar of Days. STUB until interactive implementation lands.

Auto-defaults to today's date so the draft can finalize via Pillar 1 alone
during the UAT-only-Name-pillar window. Replace with real interactive
sundial-rotation handler in a later session.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from core.systems import pillars
from core.systems.character_draft import CharacterDraft
from core.systems.dial_prompt import DialOption, DialPrompt, RITUAL, SELECT


@dataclass
class DaysHandler:
    pillar_id: str = "days"

    def initial_prompt(self, draft: CharacterDraft) -> DialPrompt:
        today = date.today()
        return DialPrompt(
            source=f"pillar:{self.pillar_id}",
            label="ALIGN THE SUNDIAL",
            mode=SELECT,
            options=[
                DialOption(
                    label=f"{today.month:02d} / {today.day:02d}",
                    value=(today.month, today.day),
                    bias="today",
                ),
            ],
            default_index=0,
            register=RITUAL,
        )

    def next_prompt(self, draft, current, idx):
        return None

    def apply(self, answer: Any) -> dict:
        if isinstance(answer, (list, tuple)) and len(answer) == 2:
            return {"birthday": (int(answer[0]), int(answer[1]))}
        today = date.today()
        return {"birthday": (today.month, today.day)}


pillars.register(DaysHandler())
