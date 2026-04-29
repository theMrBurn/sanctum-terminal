"""Blender V0 — composition tests + end-to-end pipeline proof.

Phase 5 of the lexicon → CharacterSheet → in-game asset chain. Verifies
the substrate composes correctly with stub lexicon data, AND the full
extract → blender pipeline works with real spaCy when available.
"""
from __future__ import annotations

import pytest

from core.systems.blender import (
    LexiconStub,
    LexiconTerm,
    WorldBlender,
    default_blender,
)


# ── LexiconStub ──


def test_stub_empty_returns_nothing():
    stub = LexiconStub()
    assert stub.query() == []
    assert stub.query(category="PERSON") == []
    assert stub.voice_phrases() == []
    assert stub.similar("anything") == []


def test_stub_filters_by_category():
    stub = LexiconStub(terms=[
        LexiconTerm(term="sean", category="PERSON"),
        LexiconTerm(term="kitchen", category="LOCATION"),
        LexiconTerm(term="run", category="VERB"),
    ])
    persons = stub.query(category="PERSON")
    assert len(persons) == 1 and persons[0].term == "sean"
    locations = stub.query(category="LOCATION")
    assert len(locations) == 1 and locations[0].term == "kitchen"
    assert stub.query(category="NONEXISTENT") == []


def test_stub_voice_phrases_passthrough():
    stub = LexiconStub(voice=["the WHOLE thing", "she said it'd be fine"])
    phrases = stub.voice_phrases(min_occurrences=2)
    # Verbatim — no transformation
    assert phrases == ["the WHOLE thing", "she said it'd be fine"]


def test_stub_similar_returns_seeded_list():
    stub = LexiconStub(similar_map={"vet": ["dog", "cat", "appointment"]})
    assert stub.similar("vet", k=2) == ["dog", "cat"]
    assert stub.similar("missing") == []


# ── Blender NPC composition ──


def test_npc_uses_lexicon_person_when_available():
    stub = LexiconStub(terms=[
        LexiconTerm(term="sean", category="PERSON", snippet="Sean"),
    ])
    blender = WorldBlender(lexicon=stub)
    sheet = blender.npc_for_role("companion", seed=42)
    # Snippet wins (preserves capitalization per voice contract)
    assert sheet.name == "Sean"


def test_npc_falls_back_to_role_label_when_lexicon_empty():
    blender = default_blender()
    sheet = blender.npc_for_role("watcher")
    # Role is title-cased; never invents synthetic name
    assert sheet.name == "Watcher"


def test_npc_role_maps_to_class():
    blender = default_blender()
    sheet = blender.npc_for_role("watcher", seed=1)
    assert sheet.class_history[0].name == "watcher"
    sheet2 = blender.npc_for_role("companion", seed=1)
    assert sheet2.class_history[0].name == "monk"


def test_npc_unknown_role_defaults_to_rogue():
    blender = default_blender()
    sheet = blender.npc_for_role("invented-role", seed=1)
    assert sheet.class_history[0].name == "rogue"


def test_npc_seed_makes_age_deterministic():
    blender = default_blender()
    a = blender.npc_for_role("watcher", seed=12345)
    b = blender.npc_for_role("watcher", seed=12345)
    assert a.age == b.age


def test_npc_random_person_choice_is_deterministic_given_seed():
    stub = LexiconStub(terms=[
        LexiconTerm(term="sean", category="PERSON", snippet="Sean"),
        LexiconTerm(term="ali", category="PERSON", snippet="Ali"),
        LexiconTerm(term="rita", category="PERSON", snippet="Rita"),
    ])
    blender = WorldBlender(lexicon=stub)
    a = blender.npc_for_role("companion", seed=42)
    b = blender.npc_for_role("companion", seed=42)
    assert a.name == b.name


# ── Voice contract — verbatim only ──


def test_voice_lines_verbatim_passthrough():
    """Per design_wont_tolerate #1: never paraphrase, never smooth."""
    stub = LexiconStub(voice=[
        "the WHOLE thing fell apart",       # caps preserved
        "she said it'd be fine",             # contraction preserved
        "she's got that look on her face",   # possessive + colloquialism
    ])
    blender = WorldBlender(lexicon=stub)
    lines = blender.voice_lines_for_npc("watcher", n=10)
    assert lines == [
        "the WHOLE thing fell apart",
        "she said it'd be fine",
        "she's got that look on her face",
    ]


def test_voice_lines_caps_at_n():
    stub = LexiconStub(voice=["a", "b", "c", "d", "e"])
    blender = WorldBlender(lexicon=stub)
    assert blender.voice_lines_for_npc("watcher", n=2) == ["a", "b"]


def test_voice_lines_empty_when_no_phrases():
    blender = default_blender()
    # Per design_wont_tolerate: fall back to empty (renderer uses
    # neutral fallback) rather than synthesizing voice
    assert blender.voice_lines_for_npc("watcher") == []


# ── Encounter template ──


def test_encounter_template_carries_npc_and_voice():
    stub = LexiconStub(
        terms=[LexiconTerm(term="elder", category="PERSON", snippet="Elder")],
        voice=["the time has come"],
    )
    blender = WorldBlender(lexicon=stub)
    enc = blender.encounter_template(biome="cavern", role="watcher", seed=42)
    assert enc["name"] == "Elder"
    assert enc["biome"] == "cavern"
    assert enc["tension"] == "open"
    assert enc["voice_phrases"] == ["the time has come"]
    assert "parley" in enc["action_options"]
    assert enc["npc_sheet"]["name"] == "Elder"


def test_encounter_template_with_empty_lexicon_uses_role_label():
    blender = default_blender()
    enc = blender.encounter_template(biome="cavern", role="scout", seed=1)
    assert enc["name"] == "Scout"
    assert enc["voice_phrases"] == []


# ── End-to-end pipeline: text → extract → blender ──


def test_full_pipeline_text_to_npc():
    """End-to-end: a plausible journal-shaped text produces a personalized NPC.

    Uses spaCy if available; skipped otherwise (CI compatibility).
    Demonstrates the full lexicon arc → blender contract works against
    real extract_terms output, not just hand-crafted fixtures.
    """
    spacy = pytest.importorskip("spacy")
    try:
        spacy.load("en_core_web_sm")
    except (OSError, IOError):
        pytest.skip("en_core_web_sm not installed (run `python -m spacy download en_core_web_sm`)")

    from core.systems.journal.lexicon import extract_terms

    text = "Sarah called about the meeting on Thursday."
    terms = extract_terms(text, lang="en", vault=None)

    # spaCy NER reliably tags 'Sarah' as PERSON in this context
    persons_extracted = [t for t in terms if t.get("category") == "PERSON"]
    assert any(t["term"] == "sarah" for t in persons_extracted), \
        f"expected 'sarah' as PERSON; got {persons_extracted}"

    # Convert extracted dicts into LexiconTerm shape
    lex_terms = [
        LexiconTerm(
            term=t["term"],
            category=t["category"],
            snippet=t["snippet"],
        )
        for t in persons_extracted
    ]
    blender = WorldBlender(lexicon=LexiconStub(terms=lex_terms))

    sheet = blender.npc_for_role("companion", seed=42)
    # The chosen NPC name comes from the lexicon — preserves journal capitalization
    assert sheet.name == "Sarah"
