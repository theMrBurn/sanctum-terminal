"""
Seed loader for the personal lexicon.

Cultural neutrality is the design constraint: we ship NO content seeds
(no PERSONS, COMPANIONS, LOCATIONS, OBJECTS, VERBS lists). Categories
emerge from two sources:

  1. The user's own writing -- corpus-driven via Word2Vec (Phase J4).
  2. The planner UI's first-appearance bootstrap -- when a novel
     content term appears, the planner asks the user once what it
     means to her. Her answer is stored in vault.user_seeds and
     becomes the category. Whatever string she types is valid.

The only defaults we ship are universal grammatical primitives
(temporal leads), kept in `config/journal/seeds_<lang>.json`.

Localization hook: pass `lang` through `categorize()`. The default
is "en"; future languages drop a `seeds_<lang>.json` file and need
no Python changes.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


SEEDS_DIR = Path(__file__).parent.parent.parent.parent / "config" / "journal"


@lru_cache(maxsize=8)
def _load_seeds(lang: str) -> dict[str, frozenset[str]]:
    """
    Load `config/journal/seeds_<lang>.json` and return a mapping of
    category -> frozenset[lemma]. Cached per-language. Falls back to
    English silently if the requested language has no seed file yet.
    """
    path = SEEDS_DIR / f"seeds_{lang}.json"
    if not path.exists():
        path = SEEDS_DIR / "seeds_en.json"

    raw = json.loads(path.read_text())
    return {
        category: frozenset(terms)
        for category, terms in raw.items()
        if not category.startswith("_")  # skip _comment, _schema_version
    }


def categorize(lemma: str, lang: str = "en", vault=None) -> str | None:
    """
    Return the category for `lemma`, or None if uncategorized.

    Lookup order:
      1. vault.user_seeds  (her categories win unconditionally)
      2. seeds_<lang>.json (universal grammatical primitives only)

    Note: spaCy NER labels (PERSON/GPE/ORG/...) are applied separately
    in extract_terms() based on `Doc.ents`, not via this function. This
    function only handles seed-based categorization for plain 1-grams.
    """
    if vault is not None:
        cat = vault.user_seed_category(lemma)
        if cat is not None:
            return cat

    seeds = _load_seeds(lang)
    for category, terms in seeds.items():
        if lemma in terms:
            return category
    return None
