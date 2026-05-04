"""
Personal lexicon -- extracts and accumulates novel terms from
journal entries' raw_note. Pure write-side helpers; vault.db is
the source of truth.

raw_note is canon (her voice). The lexicon is derived. PARSER_VERSION
in lexicon_state advances when this module's extraction logic changes,
allowing full regen from raw_note via consolidation.

Tier 1 + Tier 2 per design_lexicon_architecture: spaCy lemma/POS/NER
+ n-gram crawler + user_seeds (vault). No LLM. Fully offline at runtime.

Cultural neutrality: NO content seeds shipped. Category meaning is
learned from her corpus + populated by the planner UI's first-appearance
bootstrap (vault.user_seeds). The system never invents a category for
a term without her input.

Localization: `lang` parameter threaded through the pipeline. Default
"en". Adding a language = drop a `config/journal/seeds_<lang>.json` and
download the matching spaCy model; no code changes.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import spacy

from core.systems.journal.lexicon_seeds import categorize


PARSER_VERSION       = 2     # bumped: 1-token chunk skip + lang/vault threading
MAX_RAW_NOTE_CHARS   = 4000  # defensive cap; design limit is ~1000
_SPACY_MODELS        = {     # lang -> spaCy pipeline name
    "en": "en_core_web_sm",
}
_NLP_CACHE: dict[str, "spacy.language.Language"] = {}


def _nlp(lang: str = "en"):
    """
    Lazy-load and cache the spaCy pipeline for `lang`. Falls back to
    English if the language has no registered model yet.
    """
    if lang not in _NLP_CACHE:
        model_name = _SPACY_MODELS.get(lang, _SPACY_MODELS["en"])
        _NLP_CACHE[lang] = spacy.load(model_name)
    return _NLP_CACHE[lang]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_lemma(token) -> str:
    """
    Robust lemma extractor. spaCy preserves case + spelling for tokens
    it tags as PROPN, so 'Cats' stays 'Cats' instead of collapsing to
    'cat'. Apply a naive trailing-'s' strip when spaCy's lemma matches
    the surface form on a noun-like token.
    """
    lemma = token.lemma_.lower().strip()
    surface = token.text.lower().strip()
    if (lemma == surface
            and token.pos_ in ("NOUN", "PROPN")
            and len(lemma) > 3
            and lemma.endswith("s")):
        return lemma[:-1]
    return lemma


def extract_terms(text: str, lang: str = "en", vault=None) -> list[dict]:
    """
    Extract candidate lexicon rows for `text`.

    Yields dicts: { term, lemma, ngram_size, category, snippet }.

    Pass order matters -- earlier passes win the (term, ngram_size)
    dedup, so richer-source categories take precedence:

      1. Named entities    -- spaCy NER labels (PERSON/GPE/ORG/DATE/...)
      2. Noun chunks       -- category=NOUN_PHRASE (voice_phrase candidates),
                              SKIPPED for 1-token chunks (1-gram pass owns those
                              and has access to user_seeds + seed defaults)
      3. 1-grams           -- vault.user_seeds first, then seed defaults; stopwords
                              with no category are filtered out
      4. 2-grams           -- consecutive pairs with >=1 non-stopword
      5. 3-grams           -- consecutive triples with >=1 non-stopword

    `vault`: optional Vault instance. When supplied, user-defined categories
    in `vault.user_seeds` take precedence over JSON defaults. The planner
    UI's first-appearance bootstrap populates this table.

    `lang`: language code for spaCy model + seed file selection. Defaults
    to "en". Drop `config/journal/seeds_<lang>.json` + download the matching
    spaCy model to add a language; no code changes.

    Term form: space-joined lowercase lemmas. Snippet preserves the
    surface form she actually wrote (her-voice contract).
    """
    if not text or not text.strip():
        return []
    if len(text) > MAX_RAW_NOTE_CHARS:
        text = text[:MAX_RAW_NOTE_CHARS]

    doc = _nlp(lang)(text)
    out: list[dict] = []
    seen: set[tuple[str, int]] = set()

    def emit(term: str, ngram: int, snippet: str, category: str | None):
        key = (term, ngram)
        if key in seen:
            return
        seen.add(key)
        out.append({
            "term":       term,
            "lemma":      term if ngram == 1 else None,
            "ngram_size": ngram,
            "category":   category,
            "snippet":    snippet,
        })

    # Pass 1: named entities -- richest categorization, claims first
    for ent in doc.ents:
        ent_tokens = [t for t in ent if not t.is_punct and not t.is_space]
        if not ent_tokens:
            continue
        term = " ".join(_normalize_lemma(t) for t in ent_tokens).strip()
        if term:
            emit(term, len(ent_tokens), ent.text, ent.label_)

    # Pass 2: noun chunks -- voice_phrases candidates.
    # Skip single-token chunks: the 1-gram pass already covers them and has
    # access to user_seeds + JSON defaults, which are richer than NOUN_PHRASE.
    for chunk in doc.noun_chunks:
        chunk_tokens = [t for t in chunk if not t.is_punct and not t.is_space]
        if len(chunk_tokens) <= 1:
            continue
        term = " ".join(_normalize_lemma(t) for t in chunk_tokens).strip()
        if term:
            emit(term, len(chunk_tokens), chunk.text, "NOUN_PHRASE")

    tokens = [t for t in doc if not t.is_punct and not t.is_space]

    # Pass 3: 1-grams -- vault.user_seeds + JSON defaults; stopwords without
    # category are filtered out.
    for t in tokens:
        lemma = _normalize_lemma(t)
        if not lemma or not lemma.isalpha():
            continue
        cat = categorize(lemma, lang=lang, vault=vault)
        if cat is None and t.is_stop:
            continue
        emit(lemma, 1, t.text, cat)

    # Pass 4: 2-grams -- referent phrases, require >=1 non-stopword
    for i in range(len(tokens) - 1):
        a, b = tokens[i], tokens[i + 1]
        if a.is_stop and b.is_stop:
            continue
        term = f"{_normalize_lemma(a)} {_normalize_lemma(b)}".strip()
        if len(term) >= 3:
            emit(term, 2, f"{a.text} {b.text}", None)

    # Pass 5: 3-grams -- temporal/preconditional phrases, >=1 content word
    for i in range(len(tokens) - 2):
        a, b, c = tokens[i], tokens[i + 1], tokens[i + 2]
        if a.is_stop and b.is_stop and c.is_stop:
            continue
        term = f"{_normalize_lemma(a)} {_normalize_lemma(b)} {_normalize_lemma(c)}".strip()
        if len(term) >= 5:
            emit(term, 3, f"{a.text} {b.text} {c.text}", None)

    return out


def update_lexicon(
    conn: sqlite3.Connection,
    entry_id: int,
    raw_note: str,
    *,
    register: str | None = None,
    slot: str = "raw_note",
    lang: str = "en",
    vault=None,
) -> dict:
    """
    Process one entry. Upserts each candidate term into `lexicon`
    (UNIQUE(term, ngram_size) handles cross-entry dedup), appends a
    `lexicon_contexts` row per appearance, and stamps lexicon_state
    timestamps.

    `lang` and `vault` are threaded into extract_terms() for
    language-aware parsing and user-defined categorization.

    Returns a small summary dict for the endpoint response.
    """
    candidates = extract_terms(raw_note or "", lang=lang, vault=vault)
    now = _now_iso()
    new_terms = 0
    seen_terms = 0
    inserted_ids: list[int] = []

    for c in candidates:
        # Insert-or-bump. RETURNING gives us the id and a flag for new vs seen.
        # On UPDATE, occurrences was N then becomes N+1; new rows have occurrences=1.
        cur = conn.execute("""
            INSERT INTO lexicon (term, lemma, ngram_size, category,
                                 first_seen_entry_id, first_seen_at,
                                 last_seen_at, occurrences)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(term, ngram_size) DO UPDATE SET
              occurrences  = occurrences + 1,
              last_seen_at = excluded.last_seen_at,
              category     = COALESCE(lexicon.category, excluded.category)
            RETURNING id, occurrences
        """, (
            c["term"], c["lemma"], c["ngram_size"], c["category"],
            entry_id, now, now,
        ))
        row = cur.fetchone()
        lex_id, occ = row[0], row[1]
        inserted_ids.append(lex_id)
        if occ == 1:
            new_terms += 1
        else:
            seen_terms += 1

    # Contexts: one row per appearance, with co-occurring siblings as graph hint
    co_occurring_json = json.dumps(inserted_ids)
    for lex_id, c in zip(inserted_ids, candidates):
        conn.execute("""
            INSERT INTO lexicon_contexts
              (lexicon_id, entry_id, snippet, slot, register, co_occurring)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (lex_id, entry_id, c["snippet"], slot, register, co_occurring_json))

    # State timestamps
    conn.execute("""
        UPDATE lexicon_state
        SET last_inline_update = ?,
            last_entry_at      = ?
        WHERE id = 1
    """, (now, now))

    return {
        "new_terms":        new_terms,
        "seen_terms":       seen_terms,
        "lexicon_ids":      inserted_ids,
        "candidates_total": len(candidates),
    }
