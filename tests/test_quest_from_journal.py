"""Journal entry → Quest bridge.

Validates the pure bridge function (`quest_from_entry`) and the new
`journal_followup` predicate. Brain wiring (the `journal_entry` cmd
handler in brain_server.py) is exercised by the live harness in
tools/journal_feed.py — kept out of pytest because it requires a
running brain process + spaCy model.
"""
from __future__ import annotations

import pytest

from core.systems import quests
from core.systems.quests import predicates
from core.systems.quests.from_journal import (
    NAME_MAX,
    DESC_MAX,
    quest_from_entry,
)


# ── Bridge: quest_from_entry ──────────────────────────────────────


def _terms(*pairs):
    """Helper: build a term list from (term, ngram, category) tuples."""
    return [
        {"term": t, "ngram_size": n, "category": c, "lemma": t, "snippet": t}
        for (t, n, c) in pairs
    ]


def test_empty_raw_note_returns_none():
    assert quest_from_entry(1, "", _terms(("keys", 1, "OBJECT")), set()) is None
    assert quest_from_entry(1, "   ", _terms(("keys", 1, "OBJECT")), set()) is None


def test_no_usable_term_returns_none():
    # Only 2-gram terms — bridge requires a 1-gram head.
    terms = _terms(("the keys", 2, None))
    assert quest_from_entry(1, "I lost the keys.", terms, set()) is None


def test_too_short_term_skipped():
    # Single-token "is" is <3 chars: bridge skips it. Falls through to None.
    terms = _terms(("is", 1, None))
    assert quest_from_entry(1, "is", terms, set()) is None


def test_categorized_term_wins_over_uncategorized():
    # Order in the input shouldn't matter — categorized term wins.
    terms = _terms(
        ("foo", 1, None),
        ("bar", 1, "OBJECT"),
    )
    q = quest_from_entry(7, "foo and bar.", terms, set())
    assert q is not None
    assert q.predicate_args["term"] == "bar"


def test_id_is_stable_per_entry():
    terms = _terms(("keys", 1, "OBJECT"))
    q = quest_from_entry(42, "keys.", terms, set())
    assert q.id == "journal_42"


def test_journal_followup_default_when_no_kind_match():
    terms = _terms(("keys", 1, "OBJECT"))
    q = quest_from_entry(1, "Where are the keys.", terms, kind_set=set())
    assert q.predicate == "journal_followup"
    assert q.predicate_args == {"term": "keys", "birth_entry_id": 1}


def test_destroy_kind_when_term_names_a_game_kind():
    # If the head term matches a registered game kind, gameplay closes
    # the loop instead of journaling.
    terms = _terms(("clay_pot", 1, "OBJECT"))
    q = quest_from_entry(1, "clay_pot.", terms, kind_set={"clay_pot"})
    assert q.predicate == "destroy_kind"
    assert q.predicate_args == {"kind": "clay_pot", "count": 1}


def test_name_is_first_sentence_verbatim():
    raw = "Lost my keys again. Same as last week."
    q = quest_from_entry(1, raw, _terms(("keys", 1, "OBJECT")), set())
    assert q.name == "Lost my keys again"  # period stripped, no paraphrase


def test_name_truncates_long_first_sentence():
    long = "x" * (NAME_MAX + 50) + "."
    q = quest_from_entry(1, long, _terms(("xxx", 1, "OBJECT")), set())
    assert len(q.name) <= NAME_MAX
    assert q.name.endswith("…")


def test_description_truncates_to_desc_max():
    raw = "y" * (DESC_MAX + 50)
    q = quest_from_entry(1, raw, _terms(("yyy", 1, "OBJECT")), set())
    assert len(q.description) <= DESC_MAX


def test_kind_set_none_disables_fallback():
    # kind_set=None must NOT trigger destroy_kind even if the term
    # would happen to match a kind name.
    terms = _terms(("clay_pot", 1, "OBJECT"))
    q = quest_from_entry(1, "clay_pot.", terms, kind_set=None)
    assert q.predicate == "journal_followup"


# ── Predicate: journal_followup ───────────────────────────────────


def _world():
    """Minimal world stub for predicate tests."""
    class _W:
        player = None
        entities = []
    return _W()


def test_journal_followup_unknown_term_returns_false():
    fn = predicates.get("journal_followup")
    assert fn is not None
    assert fn(_world(), {"term": ""}, {}, []) is False


def test_journal_followup_matches_substring_in_new_entry():
    fn = predicates.get("journal_followup")
    events = [
        {"type": "journal_entry", "entry_id": 5, "raw_note": "Found the keys today."}
    ]
    assert fn(_world(), {"term": "keys", "birth_entry_id": 1}, {}, events) is True


def test_journal_followup_skips_birth_entry():
    """The entry that birthed the quest must not satisfy its own predicate."""
    fn = predicates.get("journal_followup")
    events = [
        {"type": "journal_entry", "entry_id": 1, "raw_note": "Lost the keys again."}
    ]
    assert fn(_world(), {"term": "keys", "birth_entry_id": 1}, {}, events) is False


def test_journal_followup_ignores_non_journal_events():
    fn = predicates.get("journal_followup")
    events = [
        {"type": "kind_destroyed", "kind": "keys"},
    ]
    assert fn(_world(), {"term": "keys", "birth_entry_id": 1}, {}, events) is False


def test_journal_followup_case_insensitive():
    fn = predicates.get("journal_followup")
    events = [
        {"type": "journal_entry", "entry_id": 9, "raw_note": "KEYS are back!"}
    ]
    assert fn(_world(), {"term": "keys", "birth_entry_id": 1}, {}, events) is True


# ── register_dynamic ──────────────────────────────────────────────


def test_register_dynamic_is_idempotent():
    # register() raises on duplicate id; register_dynamic must not.
    q1 = quests.Quest(id="journal_test_idem", name="A", description="a",
                      predicate="journal_followup",
                      predicate_args={"term": "x"})
    q2 = quests.Quest(id="journal_test_idem", name="B", description="b",
                      predicate="journal_followup",
                      predicate_args={"term": "y"})
    quests.register_dynamic(q1)
    quests.register_dynamic(q2)  # must not raise
    got = quests.get("journal_test_idem")
    assert got is not None
    assert got.name == "B"  # second registration wins
