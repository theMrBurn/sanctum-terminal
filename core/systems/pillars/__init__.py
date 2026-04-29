"""Pillar handler registry — one handler per character-creation pillar.

Each pillar (`name`, `days`, `years`, `first_path`, `vow`, `standing`, `mark`)
implements the PillarHandler protocol: produces a DialPrompt on engage,
optionally produces follow-up prompts in narrow mode, and applies the
committed answer to the CharacterDraft state via .apply().

Per `design_character_draft`, this same shape powers any multi-step
elicitation — pillar handlers are the prototype.
"""
from __future__ import annotations

from typing import Any, Protocol

from core.systems.character_draft import CharacterDraft
from core.systems.dial_prompt import DialPrompt


class PillarHandler(Protocol):
    pillar_id: str

    def initial_prompt(self, draft: CharacterDraft) -> DialPrompt:
        """First prompt when player engages the pillar.
        Default index computed from current draft state (CSP-light)."""
        ...

    def next_prompt(self, draft: CharacterDraft,
                    current: DialPrompt, answer_idx: int) -> DialPrompt | None:
        """For narrow-mode pillars: emit next binary question, or None
        when the answer has converged. Select-mode pillars return None
        on first call."""
        ...

    def apply(self, answer: Any) -> dict:
        """Translate the committed answer into a state-delta dict that
        the draft fold will merge into character state."""
        ...


# Registry — populated by importing each pillar's module.
# Use `register` to add handlers; lookup via `get`.
_REGISTRY: dict[str, PillarHandler] = {}


def register(handler: PillarHandler) -> None:
    _REGISTRY[handler.pillar_id] = handler


def get(pillar_id: str) -> PillarHandler | None:
    return _REGISTRY.get(pillar_id)


def all_handlers() -> dict[str, PillarHandler]:
    """Snapshot of the full registry. Used by CharacterDraft.state() and
    .finalize() to fold events through the right .apply() functions."""
    return dict(_REGISTRY)


# Import pillar modules to trigger their registration. Each module calls
# `register(...)` at import time.
from core.systems.pillars import name as _name  # noqa: E402, F401
from core.systems.pillars import days as _days  # noqa: E402, F401
from core.systems.pillars import years as _years  # noqa: E402, F401
from core.systems.pillars import first_path as _first_path  # noqa: E402, F401
from core.systems.pillars import vow as _vow  # noqa: E402, F401
from core.systems.pillars import standing as _standing  # noqa: E402, F401
from core.systems.pillars import mark as _mark  # noqa: E402, F401
