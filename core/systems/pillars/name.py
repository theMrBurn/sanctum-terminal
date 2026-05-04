"""Pillar 1 — Pillar of Name.

The first pillar establishes the boilerplate: select-mode, three options,
default biased to system $USER. The cavern recognizes you; the pillar
inscribes what is already true. Two override variants offer monk
register without ever requiring free-form text input.

Verb: INSCRIBE (per `design_seven_pillars`).
Register: ritual.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from core.systems import pillars
from core.systems.character_draft import CharacterDraft
from core.systems.dial_prompt import (
    DialOption,
    DialPrompt,
    RITUAL,
    SELECT,
)


_DEFAULT_FALLBACK = "Wanderer"


def _resolve_username() -> str:
    """System username, or a flavorful fallback if no $USER. Brain-side
    only — pillars never run client-side."""
    name = os.environ.get("USER") or os.environ.get("USERNAME") or _DEFAULT_FALLBACK
    return name.strip() or _DEFAULT_FALLBACK


def _options_for(username: str) -> list[DialOption]:
    return [
        DialOption(label=username, value=username, bias="your given name"),
        DialOption(
            label=f"{username} the Patient",
            value=f"{username} the Patient",
            bias="stylized",
        ),
        DialOption(
            label=f"Brother {username}",
            value=f"Brother {username}",
            bias="monastic",
        ),
    ]


@dataclass
class NameHandler:
    pillar_id: str = "name"

    def initial_prompt(self, draft: CharacterDraft, hint: dict | None = None) -> DialPrompt:
        username = _resolve_username()
        return DialPrompt(
            source=f"pillar:{self.pillar_id}",
            label="INSCRIBE YOUR NAME",
            mode=SELECT,
            options=_options_for(username),
            default_index=0,
            register=RITUAL,
        )

    def next_prompt(
        self,
        draft: CharacterDraft,
        current: DialPrompt,
        answer_idx: int,
    ) -> DialPrompt | None:
        # Select-mode pillar — converges in one ask.
        return None

    def apply(self, answer: Any) -> dict:
        return {"name": str(answer)}


pillars.register(NameHandler())
