"""Journal-entry → Quest bridge.

A journal entry becomes a Quest. v1 contract:

  - id          = "journal_{entry_id}" — stable; bridge can re-run
  - name        = first sentence of raw_note, ≤ NAME_MAX chars
  - description = raw_note, ≤ DESC_MAX chars
  - predicate   = "journal_followup" (default) — completes when she
                  journals about it again. If the head term names a
                  registered game kind, fall back to "destroy_kind"
                  so gameplay closes the loop instead.
  - rewards     = []  — placeholder; her-voice item generation defers
                       to a later session

Voice integrity (per `feedback_her_voice`, `design_wont_tolerate`):
name + description are verbatim slices of raw_note. No summarization,
no rephrasing, no LLM. The bridge truncates with `…` rather than
paraphrase.

Pure function — no I/O, no DB. Brain owns persistence + registration;
this module computes the Quest from inputs and returns it.
"""
from __future__ import annotations

import re

from core.systems.quests import Quest


NAME_MAX = 80
DESC_MAX = 200

# Sentence terminator: period, question mark, exclamation, or newline.
# Keeps it ASCII-conservative — her raw_note may contain anything, the
# regex stays narrow on purpose.
_SENT_END = re.compile(r"[.!?\n]")


def _first_sentence(raw_note: str) -> str:
    """First sentence by simple terminator split. Whole string if none."""
    m = _SENT_END.search(raw_note)
    if m is None:
        return raw_note.strip()
    return raw_note[: m.start()].strip()


def _truncate(s: str, limit: int) -> str:
    s = s.strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"


def _pick_term(terms: list[dict]) -> str | None:
    """Choose the head term for the predicate.

    Priority:
      1. First categorized 1-gram (richer signal — user_seed or NER).
      2. First 1-gram with any category.
      3. First 1-gram at all.
      4. None — caller skips quest synthesis.

    Skips terms <3 chars to avoid degenerate matches like 'is'/'a'.
    """
    short_floor = 3
    candidates = [t for t in terms
                  if int(t.get("ngram_size", 0)) == 1
                  and len(str(t.get("term", ""))) >= short_floor]
    if not candidates:
        return None
    with_cat = [t for t in candidates if t.get("category")]
    pool = with_cat if with_cat else candidates
    return str(pool[0]["term"]).lower()


def quest_from_entry(
    entry_id: int,
    raw_note: str,
    terms: list[dict],
    kind_set: set[str] | None = None,
    *,
    scenario_id: str | None = None,
) -> Quest | None:
    """Build a Quest from one journal entry.

    Returns None when raw_note is empty or no usable head term exists —
    skip silently rather than register a degenerate quest.

    `terms` is the lexicon's extract_terms() output for raw_note.
    `kind_set` is the registered game kinds (for destroy_kind fallback);
    None disables the fallback entirely.
    `scenario_id` is the persisted vault.scenarios row backing this
    quest. When supplied, it's stashed in predicate_args so brain-side
    completion handlers can flip the scenario row's state through
    scenario_ledger.transition. The Quest -> scenario reference is
    one-way; scenarios know nothing about Quests.
    """
    if not raw_note or not raw_note.strip():
        return None
    term = _pick_term(terms)
    if term is None:
        return None

    name = _truncate(_first_sentence(raw_note), NAME_MAX) or term
    description = _truncate(raw_note, DESC_MAX)

    if kind_set is not None and term in kind_set:
        predicate = "destroy_kind"
        predicate_args = {"kind": term, "count": 1}
    else:
        predicate = "journal_followup"
        predicate_args = {"term": term, "birth_entry_id": entry_id}

    if scenario_id is not None:
        predicate_args["scenario_id"] = scenario_id

    return Quest(
        id=f"journal_{entry_id}",
        name=name,
        description=description,
        predicate=predicate,
        predicate_args=predicate_args,
        rewards=[],
        register="loop",
    )
