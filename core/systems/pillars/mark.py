"""Pillar 7 — Pillar of Mark. STUB until interactive implementation lands.

Auto-defaults to no ability override — the generator picks one active per
class (default_selected_abilities). Replace with real mote-touch handler later.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.systems import pillars
from core.systems.character_draft import CharacterDraft
from core.systems.dial_prompt import DialOption, DialPrompt, RITUAL, SELECT


@dataclass
class MarkHandler:
    pillar_id: str = "mark"

    def initial_prompt(self, draft: CharacterDraft, hint: dict | None = None) -> DialPrompt:
        return DialPrompt(
            source=f"pillar:{self.pillar_id}",
            label="TOUCH THREE MOTES",
            mode=SELECT,
            options=[
                DialOption(
                    label="default abilities",
                    value=["Quiet Tread", "Patient Eye", "Margin Note"],
                ),
            ],
            default_index=0,
            register=RITUAL,
            multi_select_max=3,
        )

    def next_prompt(self, draft, current, idx):
        return None

    def apply(self, answer: Any) -> dict:
        # Stub returns empty so generator uses default_selected_abilities.
        return {}


pillars.register(MarkHandler())
