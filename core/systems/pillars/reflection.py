"""Pillar of Reflection — the re-do mechanic.

Not one of the seven required-for-sealing pillars (REQUIRED_PILLARS).
This is a META-pillar that lives in HUB after a character is sealed.
Engaging it initiates a fresh CHARACTER_CREATION cycle so the player
can walk through their identity again.

Apply value carries a sentinel — `{"_reflection": "reset"}` or
`{"_reflection": "remain"}` — that the brain's dial_response handler
recognizes specially. The draft fold ignores `_reflection` keys (they
don't map to any CharacterSheet field) so spurious applies are safe.

Verb: MEDITATE. Register: ritual.
"""
from __future__ import annotations

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


# Sentinel values — brain's dial_response handler watches for these
# and triggers the re-do flow on commit.
RESET = "reset"
REMAIN = "remain"


@dataclass
class ReflectionHandler:
    pillar_id: str = "reflection"

    def initial_prompt(
        self,
        draft: CharacterDraft,
        hint: dict | None = None,
    ) -> DialPrompt:
        return DialPrompt(
            source=f"pillar:{self.pillar_id}",
            label="BEGIN AGAIN?",
            mode=SELECT,
            options=[
                DialOption(label="REMAIN AS YOU ARE", value=REMAIN,
                           bias="keep your sealed identity"),
                DialOption(label="WALK THE RITUAL AGAIN", value=RESET,
                           bias="re-do character creation"),
            ],
            # Default to "remain" — must explicitly opt into reset.
            # Single ENTER won't accidentally wipe a sealed character.
            default_index=0,
            register=RITUAL,
        )

    def next_prompt(
        self,
        draft: CharacterDraft,
        current: DialPrompt,
        answer_idx: int,
    ) -> DialPrompt | None:
        return None

    def apply(self, answer: Any) -> dict:
        # Sentinel reaches brain via the dial_response handler, which
        # treats `_reflection` specially. Draft.state() folds ignore
        # `_reflection` keys (they don't match any CharacterSheet field),
        # so even if accidentally appended to the draft they're inert.
        if answer == RESET:
            return {"_reflection": RESET}
        return {"_reflection": REMAIN}


pillars.register(ReflectionHandler())
