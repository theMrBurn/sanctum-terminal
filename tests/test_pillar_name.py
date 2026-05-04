"""Pillar 1 — NameHandler. The boilerplate prototype for all pillars."""
from __future__ import annotations

from core.systems import pillars
from core.systems.character_draft import CharacterDraft
from core.systems.dial_prompt import RITUAL, SELECT
from core.systems.pillars.name import NameHandler


def test_name_handler_registered():
    handler = pillars.get("name")
    assert handler is not None
    assert handler.pillar_id == "name"


def test_initial_prompt_uses_select_mode():
    handler = NameHandler()
    draft = CharacterDraft()
    prompt = handler.initial_prompt(draft)
    assert prompt.mode == SELECT
    assert prompt.register == RITUAL
    assert prompt.source == "pillar:name"


def test_initial_prompt_offers_three_options():
    handler = NameHandler()
    prompt = handler.initial_prompt(CharacterDraft())
    assert len(prompt.options) == 3
    # First option is the plain username default
    assert prompt.default_index == 0


def test_default_uses_user_env(monkeypatch):
    monkeypatch.setenv("USER", "TestUser")
    handler = NameHandler()
    prompt = handler.initial_prompt(CharacterDraft())
    assert prompt.options[0].value == "TestUser"
    assert prompt.options[0].label == "TestUser"


def test_stylized_options_derive_from_username(monkeypatch):
    monkeypatch.setenv("USER", "Sean")
    handler = NameHandler()
    prompt = handler.initial_prompt(CharacterDraft())
    labels = [o.label for o in prompt.options]
    assert "Sean" in labels
    assert "Sean the Patient" in labels
    assert "Brother Sean" in labels


def test_options_have_descriptive_bias_text(monkeypatch):
    monkeypatch.setenv("USER", "Sean")
    handler = NameHandler()
    prompt = handler.initial_prompt(CharacterDraft())
    biases = [o.bias for o in prompt.options]
    assert "your given name" in biases
    assert "stylized" in biases
    assert "monastic" in biases


def test_fallback_when_no_user_env(monkeypatch):
    monkeypatch.delenv("USER", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)
    handler = NameHandler()
    prompt = handler.initial_prompt(CharacterDraft())
    # Falls back to "Wanderer"
    assert prompt.options[0].value == "Wanderer"


def test_blank_user_falls_back(monkeypatch):
    monkeypatch.setenv("USER", "   ")
    handler = NameHandler()
    prompt = handler.initial_prompt(CharacterDraft())
    # Blank/whitespace falls back to default
    assert prompt.options[0].value == "Wanderer"


def test_apply_returns_name_delta():
    handler = NameHandler()
    delta = handler.apply("Sean")
    assert delta == {"name": "Sean"}


def test_apply_coerces_to_str():
    """Defensive: ensure non-string values become strings."""
    handler = NameHandler()
    delta = handler.apply(42)  # someone sent an int by mistake
    assert delta == {"name": "42"}


def test_next_prompt_returns_none():
    """Select-mode pillar converges in one ask."""
    handler = NameHandler()
    draft = CharacterDraft()
    initial = handler.initial_prompt(draft)
    follow_up = handler.next_prompt(draft, initial, 0)
    assert follow_up is None


def test_full_pillar_flow_via_draft(monkeypatch):
    """End-to-end: handler + draft + state fold."""
    monkeypatch.setenv("USER", "Sean")
    handler = NameHandler()
    draft = CharacterDraft()

    prompt = handler.initial_prompt(draft)
    chosen = prompt.options[prompt.default_index].value  # "Sean"

    draft.append("name", chosen)
    handlers = {"name": handler}
    state = draft.state(handlers)
    assert state == {"name": "Sean"}
