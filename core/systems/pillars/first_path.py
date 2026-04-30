"""Pillar 4 — Pillar of First Path. STUB until interactive implementation lands.

Auto-defaults to no class_history override — the generator falls back to
default_class_history(age) which gives the rogue→monk template at age >= 32.
Replace with real relic-pickup handler in a later session.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.systems import pillars
from core.systems.character_draft import CharacterDraft
from core.systems.dial_prompt import DialOption, DialPrompt, RITUAL, SELECT


@dataclass
class FirstPathHandler:
    pillar_id: str = "first_path"

    def initial_prompt(self, draft: CharacterDraft, hint: dict | None = None) -> DialPrompt:
        return DialPrompt(
            source=f"pillar:{self.pillar_id}",
            label="CHOOSE A RELIC",
            mode=SELECT,
            options=[DialOption(label="lockpick", value="rogue", bias="rogue path")],
            default_index=0,
            register=RITUAL,
        )

    def next_prompt(self, draft, current, idx):
        return None

    def apply(self, answer: Any) -> dict:
        # Stub returns empty so generator falls back to default_class_history.
        # Real implementation will populate class_history.
        return {}


pillars.register(FirstPathHandler())
