"""Pillar 6 — Pillar of Standing. STUB until interactive implementation lands.

Auto-defaults to no stat override — the generator uses the most recent
class's stat preset. Replace with real stone-lifting handler later.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.systems import pillars
from core.systems.character_draft import CharacterDraft
from core.systems.dial_prompt import DialOption, DialPrompt, RITUAL, SELECT


@dataclass
class StandingHandler:
    pillar_id: str = "standing"

    def initial_prompt(self, draft: CharacterDraft) -> DialPrompt:
        return DialPrompt(
            source=f"pillar:{self.pillar_id}",
            label="LIFT THE STONES",
            mode=SELECT,
            options=[DialOption(label="DEX/WIS/CHA", value=["DEX", "WIS", "CHA"])],
            default_index=0,
            register=RITUAL,
            multi_select_max=3,
        )

    def next_prompt(self, draft, current, idx):
        return None

    def apply(self, answer: Any) -> dict:
        # Stub returns empty so generator uses class-derived stat preset.
        return {}


pillars.register(StandingHandler())
