"""Event-sourced character creation state.

Per `design_character_draft`: each completed pillar emits a PillarEvent;
the draft state at any moment is a fold over the event log. After all
required pillars land, `finalize()` produces the immutable CharacterSheet.

The same pattern generalizes to any multi-step elicitation — onboarding
wizards, multi-turn dialog, journal moments. PillarEvent is the
load-bearing primitive; everything else is conventions on top.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.systems.character_sheet import CharacterSheet, generate_character_sheet


# Pillars that must complete before a draft can finalize.
# Per `design_seven_pillars`.
REQUIRED_PILLARS: frozenset[str] = frozenset({
    "name", "days", "years", "first_path", "vow", "standing", "mark",
})


@dataclass
class PillarEvent:
    timestamp: float
    pillar: str
    answer: Any
    asks_used: int = 1   # number of binary questions that converged (narrow-mode)


@dataclass
class CharacterDraft:
    pillar_events: list[PillarEvent] = field(default_factory=list)

    def append(self, pillar: str, answer: Any, asks_used: int = 1) -> None:
        """Record a completed pillar. Re-doing a pillar appends a new event;
        the fold takes the LATEST event per pillar."""
        self.pillar_events.append(
            PillarEvent(timestamp=time.time(), pillar=pillar,
                        answer=answer, asks_used=asks_used)
        )

    def state(self, handlers: dict) -> dict:
        """Fold the event log into current draft state.

        `handlers` maps pillar_id → object with .apply(answer) -> dict.
        Caller passes the registry; we don't import to avoid cycle.
        For each pillar, the LATEST event wins (re-doing replaces).
        """
        latest_per_pillar: dict[str, PillarEvent] = {}
        for evt in self.pillar_events:
            latest_per_pillar[evt.pillar] = evt
        result: dict[str, Any] = {}
        for pillar_id, evt in latest_per_pillar.items():
            handler = handlers.get(pillar_id)
            if handler is None:
                continue
            result.update(handler.apply(evt.answer))
        return result

    def completed_pillars(self) -> set[str]:
        return {e.pillar for e in self.pillar_events}

    def is_complete(self) -> bool:
        return self.completed_pillars() >= REQUIRED_PILLARS

    def progress(self) -> dict[str, bool]:
        """For manifest emission — pillar_id → True if completed."""
        completed = self.completed_pillars()
        return {pillar: pillar in completed for pillar in REQUIRED_PILLARS}

    def finalize(self, handlers: dict) -> CharacterSheet:
        """Produce the CharacterSheet from a complete draft.

        Raises ValueError if not complete. Caller passes the pillar handler
        registry so .apply() can run."""
        if not self.is_complete():
            missing = REQUIRED_PILLARS - self.completed_pillars()
            raise ValueError(f"draft incomplete; missing pillars: {sorted(missing)}")
        return generate_character_sheet(**self.state(handlers))
