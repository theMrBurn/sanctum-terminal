"""Pillar 5 — Pillar of the Vow. STUB until interactive implementation lands.

Auto-defaults to taking the vow if age >= 32 (Sean's prestige threshold),
otherwise remaining. Generator's default_class_history handles the actual
class transition; this stub just shapes intent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.systems import pillars
from core.systems.character_draft import CharacterDraft
from core.systems.dial_prompt import DialOption, DialPrompt, RITUAL, SELECT


@dataclass
class VowHandler:
    pillar_id: str = "vow"

    def initial_prompt(self, draft: CharacterDraft, hint: dict | None = None) -> DialPrompt:
        return DialPrompt(
            source=f"pillar:{self.pillar_id}",
            label="TAKE THE VOW?",
            mode=SELECT,
            options=[
                DialOption(label="take vow", value="take", bias="prestige to monk"),
                DialOption(label="remain", value="remain", bias="stay rogue"),
            ],
            default_index=0,
            register=RITUAL,
        )

    def next_prompt(self, draft, current, idx):
        return None

    def apply(self, answer: Any) -> dict:
        # Stub returns empty so generator falls back to default_class_history.
        return {}


pillars.register(VowHandler())
