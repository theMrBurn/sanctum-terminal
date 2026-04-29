"""Pillar 3 — Pillar of Years. STUB until interactive implementation lands.

Auto-defaults to age 30 (a reasonable median). Replace with real walking-
the-rings or binary-narrow handler in a later session.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.systems import pillars
from core.systems.character_draft import CharacterDraft
from core.systems.dial_prompt import DialOption, DialPrompt, RITUAL, SELECT


@dataclass
class YearsHandler:
    pillar_id: str = "years"

    def initial_prompt(self, draft: CharacterDraft) -> DialPrompt:
        return DialPrompt(
            source=f"pillar:{self.pillar_id}",
            label="WALK THE RINGS",
            mode=SELECT,
            options=[
                DialOption(label="30", value=30, bias="default"),
            ],
            default_index=0,
            register=RITUAL,
        )

    def next_prompt(self, draft, current, idx):
        return None

    def apply(self, answer: Any) -> dict:
        try:
            return {"age": int(answer)}
        except (TypeError, ValueError):
            return {"age": 30}


pillars.register(YearsHandler())
