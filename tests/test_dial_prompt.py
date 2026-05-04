"""DialPrompt + DialOption — primitive shape and serialization."""
from __future__ import annotations

from core.systems.dial_prompt import (
    AMBIENT,
    DialOption,
    DialPrompt,
    NARROW,
    RITUAL,
    SELECT,
    TENSE,
    to_manifest,
)


def test_dial_option_minimal_construction():
    opt = DialOption(label="Sean", value="Sean")
    assert opt.label == "Sean"
    assert opt.value == "Sean"
    assert opt.bias is None


def test_dial_option_with_bias():
    opt = DialOption(label="Brother Sean", value="Brother Sean", bias="monastic")
    assert opt.bias == "monastic"


def test_select_mode_dial():
    prompt = DialPrompt(
        source="pillar:name",
        label="INSCRIBE YOUR NAME",
        mode=SELECT,
        options=[
            DialOption("Sean", "Sean"),
            DialOption("Sean the Patient", "Sean the Patient"),
        ],
        default_index=0,
    )
    assert prompt.mode == SELECT
    assert prompt.default_index == 0
    assert len(prompt.options) == 2
    assert prompt.register == RITUAL  # default register


def test_narrow_mode_dial_with_pivot():
    prompt = DialPrompt(
        source="pillar:years",
        label="OLDER OR YOUNGER",
        mode=NARROW,
        options=[DialOption("Younger", "<"), DialOption("Older", ">=")],
        default_index=1,
        pivot_value=20,
        range_remaining=(1, 100),
    )
    assert prompt.mode == NARROW
    assert prompt.pivot_value == 20
    assert prompt.range_remaining == (1, 100)


def test_register_constants_are_distinct():
    assert len({RITUAL, TENSE, AMBIENT}) == 3


def test_to_manifest_serialization():
    prompt = DialPrompt(
        source="pillar:name",
        label="INSCRIBE YOUR NAME",
        mode=SELECT,
        options=[
            DialOption("Sean", "Sean", bias="given name"),
            DialOption("Brother Sean", "Brother Sean", bias="monastic"),
        ],
        default_index=0,
        register=RITUAL,
    )
    payload = to_manifest(prompt)
    assert payload["source"] == "pillar:name"
    assert payload["label"] == "INSCRIBE YOUR NAME"
    assert payload["mode"] == SELECT
    assert payload["default_index"] == 0
    assert payload["register"] == RITUAL
    assert len(payload["options"]) == 2
    assert payload["options"][0] == {
        "label": "Sean",
        "value": "Sean",
        "bias": "given name",
    }
    assert payload["range_remaining"] == []  # empty tuple → empty list


def test_to_manifest_roundtrip_preserves_values():
    """Any JSON-serializable value should survive to_manifest."""
    import json
    prompt = DialPrompt(
        source="pillar:days",
        label="ALIGN THE SUNDIAL",
        mode=SELECT,
        options=[
            DialOption(label=f"Month {i}", value=i) for i in range(1, 4)
        ],
        default_index=2,
    )
    payload = to_manifest(prompt)
    text = json.dumps(payload)
    parsed = json.loads(text)
    assert parsed["options"][1]["value"] == 2
