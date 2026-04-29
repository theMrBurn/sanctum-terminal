"""
tools/lexicon_smoke.py

Empirical inspection of the journal lexicon extractor against a
range of natural journal-style phrases. Not a test -- this is the
"live tuning" surface. Run it, scan the output, decide what to
fix vs accept.

    .venv/bin/python tools/lexicon_smoke.py
    .venv/bin/python tools/lexicon_smoke.py --short   # compact mode

Cultural neutrality: shipped defaults categorize ONLY the universal
grammatical primitive TEMPORAL_LEAD (after/before/when/...). Content
words show as "uncategorized" until the user populates vault.user_seeds
via the planner UI's first-appearance bootstrap.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Repo root on path so `core.systems.journal.lexicon` resolves
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.systems.journal.lexicon import extract_terms


PHRASES = [
    ("simple imperative",
     "take the dog to the vet"),

    ("compound temporal precondition",
     "after the kids go to school, i have to take the cats to the vet"),

    ("named person + appointment",
     "Sean has a dentist appointment on Tuesday at 9am"),

    ("multi-companion list",
     "feed the cats and walk the dog before bed"),

    ("grocery list",
     "pick up groceries: milk, bread, cat food, and my prescription"),

    ("recurring + temporal",
     "every Tuesday morning take Mom to physical therapy"),

    ("emotional register",
     "make sure the kids feel okay about Grandma's surgery on Friday"),

    ("casual contractions",
     "gotta call mom about the dentist appt and pick up the cats from boarding"),

    ("possessive relationships",
     "her birthday is Saturday, get flowers and pick up the kids' artwork from school"),

    ("conditional / negation",
     "if it rains tomorrow don't forget to bring the cats inside"),

    ("long rambling natural voice",
     "remember to drop off the cat carrier at the vet before noon, "
     "then swing by the pharmacy for my prescription, "
     "and if there's time stop at the grocery store for milk and bread "
     "because the kids will want cereal in the morning"),

    ("idiosyncratic nicknames",
     "the babies need their flea meds tonight after dinner"),

    ("simple time-only",
     "lunch with Mom at noon"),

    ("place-only",
     "library books are due back Wednesday"),

    ("she-voice fragment",
     "i keep forgetting the cats' food bowls need washing daily"),
]


def render(name: str, text: str, short: bool = False) -> None:
    print(f"\n=== {name} ===")
    print(f"  input: {text!r}")

    terms = extract_terms(text)
    if not terms:
        print("  (no terms extracted)")
        return

    by_kind = {
        "ents":     [t for t in terms if t["category"] not in (None, "NOUN_PHRASE") and not _is_seed(t["category"])],
        "seeded":   [t for t in terms if _is_seed(t["category"])],
        "phrases":  [t for t in terms if t["category"] == "NOUN_PHRASE"],
        "bigrams":  [t for t in terms if t["category"] is None and t["ngram_size"] == 2],
        "trigrams": [t for t in terms if t["category"] is None and t["ngram_size"] == 3],
        "other_unigrams": [t for t in terms if t["category"] is None and t["ngram_size"] == 1],
    }

    if by_kind["ents"]:
        print("  NER entities:")
        for t in by_kind["ents"]:
            print(f"    [{t['category']:>10}] {t['term']:<25} <- {t['snippet']!r}")

    if by_kind["seeded"]:
        print("  seed-categorized (1-grams):")
        for t in by_kind["seeded"]:
            print(f"    [{t['category']:>10}] {t['term']:<25} <- {t['snippet']!r}")

    if by_kind["other_unigrams"]:
        terms_only = ", ".join(t["term"] for t in by_kind["other_unigrams"])
        print(f"  uncategorized 1-grams: {terms_only}")

    if by_kind["phrases"]:
        print("  noun chunks (voice-phrase candidates):")
        for t in by_kind["phrases"]:
            print(f"    {t['term']:<30} <- {t['snippet']!r}")

    if not short:
        if by_kind["bigrams"]:
            grams = ", ".join(t["term"] for t in by_kind["bigrams"])
            print(f"  bigrams: {grams}")
        if by_kind["trigrams"]:
            grams = ", ".join(t["term"] for t in by_kind["trigrams"])
            print(f"  trigrams: {grams}")

    print(f"  total candidates: {len(terms)}")


def _is_seed(category: str | None) -> bool:
    # Default-seeds set: only universal grammatical primitives.
    # User-defined categories (vault.user_seeds) are arbitrary strings
    # set by the planner UI; they pass through this function as
    # non-seed and are bucketed as "uncategorized" by display, but
    # are still stored correctly in lexicon.category.
    return category in {"TEMPORAL_LEAD"}


def main() -> None:
    short = "--short" in sys.argv
    for name, text in PHRASES:
        render(name, text, short=short)
    print()


if __name__ == "__main__":
    main()
