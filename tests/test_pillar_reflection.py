"""Pillar of Reflection — re-do mechanic.

Not in REQUIRED_PILLARS (it's a meta-pillar). Engaged from HUB after a
character is sealed; commit triggers brain-side re-do flow that transitions
back to CHARACTER_CREATION with a fresh draft.
"""
from __future__ import annotations

from core.systems import pillars
from core.systems.character_draft import CharacterDraft, REQUIRED_PILLARS
from core.systems.dial_prompt import RITUAL, SELECT
from core.systems.pillars.reflection import REMAIN, RESET, ReflectionHandler


def test_reflection_not_in_required_pillars():
    """Reflection is a meta-pillar; sealing all 7 of REQUIRED_PILLARS
    doesn't depend on it. The draft can finalize without it."""
    assert "reflection" not in REQUIRED_PILLARS


def test_reflection_handler_registered():
    handler = pillars.get("reflection")
    assert handler is not None
    assert handler.pillar_id == "reflection"


def test_initial_prompt_offers_remain_and_reset():
    h = ReflectionHandler()
    p = h.initial_prompt(CharacterDraft())
    assert p.mode == SELECT
    assert p.register == RITUAL
    assert p.source == "pillar:reflection"
    values = [o.value for o in p.options]
    assert REMAIN in values
    assert RESET in values


def test_default_index_is_remain():
    """Single ENTER must NOT accidentally wipe a sealed character.
    Default biases toward keeping the existing identity."""
    h = ReflectionHandler()
    p = h.initial_prompt(CharacterDraft())
    assert p.options[p.default_index].value == REMAIN


def test_apply_reset_returns_sentinel():
    h = ReflectionHandler()
    delta = h.apply(RESET)
    assert delta == {"_reflection": RESET}


def test_apply_remain_returns_sentinel():
    h = ReflectionHandler()
    delta = h.apply(REMAIN)
    assert delta == {"_reflection": REMAIN}


def test_reflection_sentinel_does_not_pollute_character_state():
    """Even if the sentinel were appended to the draft (it shouldn't be —
    brain handles reflection specially) the fold ignores `_reflection`
    keys because they don't map to a CharacterSheet field."""
    draft = CharacterDraft()
    draft.append("reflection", RESET)
    state = draft.state(pillars.all_handlers())
    # `_reflection` key is in the dict but shouldn't crash anything
    assert "_reflection" in state
    # The actual CharacterSheet fields are untouched
    assert "name" not in state


def test_next_prompt_returns_none():
    """Reflection is single-shot; no cascade."""
    h = ReflectionHandler()
    draft = CharacterDraft()
    initial = h.initial_prompt(draft)
    assert h.next_prompt(draft, initial, 0) is None
    assert h.next_prompt(draft, initial, 1) is None
