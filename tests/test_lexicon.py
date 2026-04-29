"""
tests/test_lexicon.py

J2 -- extract_terms() + update_lexicon().
Verifies the Tier-1+2 extractor (spaCy + n-grams + user_seeds) and the
upsert pipeline against vault.db's lexicon tables.

Cultural neutrality: the default JSON seeds carry NO content terms
(no PERSONS, COMPANIONS, LOCATIONS, OBJECTS, VERBS). Categorization
of content words flows through vault.user_seeds, populated by the
planner's first-appearance bootstrap UI.
"""

import json
import sqlite3
from datetime import datetime, timezone

import pytest


# -- Fixtures ------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path):
    from core.vault import vault as VaultClass
    return VaultClass(db_path=tmp_path / "vault.db")


@pytest.fixture
def vault_with_entry(vault):
    """Vault with one journal entry seeded; lexicon empty."""
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(vault.db_path) as conn:
        cur = conn.execute("""
            INSERT INTO entries (when_ts, severity, frequency, raw_note,
                                 created_at, updated_at)
            VALUES (?, 1, 'once', ?, ?, ?)
        """, ("2026-04-29T09:00:00Z", "placeholder", now, now))
        entry_id = cur.lastrowid
        conn.commit()
    return vault, entry_id


# -- extract_terms -------------------------------------------------------------

class TestExtractTerms:

    def test_empty_string(self):
        from core.systems.journal.lexicon import extract_terms
        assert extract_terms("") == []
        assert extract_terms("   ") == []

    def test_simple_lemma(self):
        """'cats' should produce 1-gram with lemma 'cat'."""
        from core.systems.journal.lexicon import extract_terms
        terms = extract_terms("cats")
        unigrams = [t for t in terms if t["ngram_size"] == 1]
        assert any(t["term"] == "cat" for t in unigrams)

    def test_default_seeds_carry_no_content_terms(self):
        """
        Cultural neutrality contract: shipped defaults must NOT categorize
        content words like 'cat' / 'dog' / 'mom' / 'vet'. Those gain
        meaning only via vault.user_seeds populated by the planner UI.
        """
        from core.systems.journal.lexicon import extract_terms
        terms = extract_terms("take the dog to the vet at noon, mom")
        cats = {t["term"]: t["category"] for t in terms if t["ngram_size"] == 1}
        # No baked-in cultural categorization
        assert cats.get("dog")  != "COMPANION"
        assert cats.get("vet")  not in ("LOCATION", "GPE")  # NER may still tag but not seed
        assert cats.get("mom")  != "PERSON"
        assert cats.get("take") != "VERB"

    def test_temporal_lead_seed_remains(self):
        """The single universal grammatical primitive ships in defaults."""
        from core.systems.journal.lexicon_seeds import categorize
        assert categorize("after") == "TEMPORAL_LEAD"
        assert categorize("before") == "TEMPORAL_LEAD"
        assert categorize("when") == "TEMPORAL_LEAD"

    def test_user_seed_takes_precedence(self, tmp_path):
        """
        User-defined categorization in vault.user_seeds wins over
        defaults. She types whatever string she wants for a category.
        """
        from core.vault import vault as VaultClass
        from core.systems.journal.lexicon import extract_terms
        v = VaultClass(db_path=tmp_path / "vault.db")
        v.add_user_seed("cat", "my babies")
        v.add_user_seed("vet", "doctor for cats")

        terms = extract_terms("take the cat to the vet", vault=v)
        cats = {t["term"]: t["category"] for t in terms if t["ngram_size"] == 1}
        assert cats["cat"] == "my babies"
        assert cats["vet"] == "doctor for cats"

    def test_lang_param_defaults_to_en(self):
        """Smoke: lang='en' is the default and matches no-arg behavior."""
        from core.systems.journal.lexicon import extract_terms
        a = extract_terms("the cats")
        b = extract_terms("the cats", lang="en")
        assert {t["term"] for t in a} == {t["term"] for t in b}

    def test_stopword_only_2gram_excluded(self):
        """'I have' / 'to the' / 'have to' should NOT appear as 2-grams."""
        from core.systems.journal.lexicon import extract_terms
        terms = extract_terms("i have to take the cats to the vet")
        bigrams = {t["term"] for t in terms if t["ngram_size"] == 2}
        # Forbidden -- both tokens stopwords
        assert "i have" not in bigrams
        assert "have to" not in bigrams
        assert "to the" not in bigrams

    def test_stopword_plus_content_2gram_kept(self):
        """'the cats' / 'the vet' / 'the kids' should survive (referent)."""
        from core.systems.journal.lexicon import extract_terms
        terms = extract_terms("after the kids go to school, i have to take the cats to the vet")
        bigrams = {t["term"] for t in terms if t["ngram_size"] == 2}
        assert "the cat" in bigrams or "the cats" in bigrams  # lemma collapse
        assert "the kid" in bigrams or "the kids" in bigrams
        assert "the vet" in bigrams

    def test_3gram_requires_content_word(self):
        """Triples of all stopwords should not appear."""
        from core.systems.journal.lexicon import extract_terms
        terms = extract_terms("after the kids go to school, i have to take the cats to the vet")
        trigrams = {t["term"] for t in terms if t["ngram_size"] == 3}
        # Pure-stopword trigrams
        assert "i have to" not in trigrams
        # Content-bearing trigrams should exist
        assert any("kid" in t for t in trigrams)

    def test_noun_phrase_emitted_only_for_multitoken_chunks(self):
        """
        Multi-token noun chunks come through with NOUN_PHRASE category.
        Single-token chunks are SKIPPED so the 1-gram pass (with access
        to user_seeds + defaults) owns those rows uncontested.
        """
        from core.systems.journal.lexicon import extract_terms
        terms = extract_terms("the cats need to go to the vet")
        np_terms = [t for t in terms if t["category"] == "NOUN_PHRASE"]
        assert len(np_terms) >= 1
        # Multi-token: 'the cat' / 'the vet' should land
        assert any(t["ngram_size"] >= 2 for t in np_terms)
        # No 1-token NOUN_PHRASE rows -- they'd shadow user_seeds
        assert all(t["ngram_size"] >= 2 for t in np_terms)

    def test_snippet_preserves_voice(self):
        """Snippet field stores surface form, not the lemma."""
        from core.systems.journal.lexicon import extract_terms
        terms = extract_terms("Cats")
        # Find the 1-gram for 'cat' -- snippet should be the original 'Cats'
        cat_term = next((t for t in terms if t["term"] == "cat" and t["ngram_size"] == 1), None)
        assert cat_term is not None
        assert cat_term["snippet"] == "Cats"

    def test_within_entry_dedup(self):
        """Same term mentioned twice in one entry returns once."""
        from core.systems.journal.lexicon import extract_terms
        terms = extract_terms("the cat sat on the mat. the cat purred.")
        unigrams = [t for t in terms if t["ngram_size"] == 1 and t["term"] == "cat"]
        assert len(unigrams) == 1


# -- update_lexicon ------------------------------------------------------------

class TestUpdateLexicon:

    def test_inserts_new_terms(self, vault_with_entry):
        from core.systems.journal.lexicon import update_lexicon
        v, entry_id = vault_with_entry
        with sqlite3.connect(v.db_path) as conn:
            result = update_lexicon(conn, entry_id, "take the cat to the vet")
            conn.commit()
        assert result["new_terms"] > 0
        assert result["seen_terms"] == 0
        assert result["candidates_total"] == result["new_terms"]

    def test_increments_existing_terms(self, vault_with_entry):
        """Same text twice: second call has all-seen, none-new."""
        from core.systems.journal.lexicon import update_lexicon
        v, entry_id = vault_with_entry
        with sqlite3.connect(v.db_path) as conn:
            update_lexicon(conn, entry_id, "take the cat to the vet")
            conn.commit()
            result = update_lexicon(conn, entry_id, "take the cat to the vet")
            conn.commit()
        assert result["new_terms"] == 0
        assert result["seen_terms"] > 0

        # Verify occurrences incremented in DB
        with sqlite3.connect(v.db_path) as conn:
            row = conn.execute(
                "SELECT occurrences FROM lexicon WHERE term='cat' AND ngram_size=1"
            ).fetchone()
        assert row[0] == 2

    def test_writes_context_per_call(self, vault_with_entry):
        """Each call writes a lexicon_contexts row per candidate."""
        from core.systems.journal.lexicon import update_lexicon
        v, entry_id = vault_with_entry
        with sqlite3.connect(v.db_path) as conn:
            r1 = update_lexicon(conn, entry_id, "take the cat to the vet")
            conn.commit()
            r2 = update_lexicon(conn, entry_id, "take the cat to the vet")
            conn.commit()
            ctx_count = conn.execute(
                "SELECT COUNT(*) FROM lexicon_contexts"
            ).fetchone()[0]
        assert ctx_count == r1["candidates_total"] + r2["candidates_total"]

    def test_context_snippet_preserves_voice(self, vault_with_entry):
        from core.systems.journal.lexicon import update_lexicon
        v, entry_id = vault_with_entry
        with sqlite3.connect(v.db_path) as conn:
            update_lexicon(conn, entry_id, "Take the Cats to the Vet")
            conn.commit()
            # Find the context for 'cat' lemma -- snippet should preserve 'Cats'
            row = conn.execute("""
                SELECT lc.snippet
                FROM   lexicon_contexts lc
                JOIN   lexicon          l ON l.id = lc.lexicon_id
                WHERE  l.term = 'cat' AND l.ngram_size = 1
                LIMIT  1
            """).fetchone()
        assert row is not None
        # Snippet is the original surface form, not the lemma
        assert "Cat" in row[0]

    def test_co_occurring_json_array(self, vault_with_entry):
        """co_occurring is a JSON array of sibling lexicon_ids."""
        from core.systems.journal.lexicon import update_lexicon
        v, entry_id = vault_with_entry
        with sqlite3.connect(v.db_path) as conn:
            update_lexicon(conn, entry_id, "take the cat to the vet")
            conn.commit()
            row = conn.execute(
                "SELECT co_occurring FROM lexicon_contexts LIMIT 1"
            ).fetchone()
        ids = json.loads(row[0])
        assert isinstance(ids, list)
        assert len(ids) > 0
        assert all(isinstance(i, int) for i in ids)

    def test_state_timestamp_updated(self, vault_with_entry):
        from core.systems.journal.lexicon import update_lexicon
        v, entry_id = vault_with_entry
        before = v.lexicon_state()
        assert before["last_inline_update"] is None
        with sqlite3.connect(v.db_path) as conn:
            update_lexicon(conn, entry_id, "take the cat to the vet")
            conn.commit()
        after = v.lexicon_state()
        assert after["last_inline_update"] is not None
        assert after["last_entry_at"] is not None

    def test_user_seed_category_persisted(self, vault_with_entry):
        """
        User-defined category from vault.user_seeds flows through
        update_lexicon() into lexicon.category. No bias from defaults.
        """
        from core.systems.journal.lexicon import update_lexicon
        v, entry_id = vault_with_entry
        v.add_user_seed("dog", "creature")
        v.add_user_seed("vet", "place we go")
        with sqlite3.connect(v.db_path) as conn:
            update_lexicon(conn, entry_id, "take the dog to the vet", vault=v)
            conn.commit()
            rows = dict(conn.execute(
                "SELECT term, category FROM lexicon WHERE ngram_size=1"
            ).fetchall())
        assert rows.get("dog") == "creature"
        assert rows.get("vet") == "place we go"

    def test_lemma_collapse_across_surface_forms(self, vault_with_entry):
        """'cats' and 'cat' across two entries collapse to one lexicon row."""
        from core.systems.journal.lexicon import update_lexicon
        v, entry_id = vault_with_entry
        with sqlite3.connect(v.db_path) as conn:
            update_lexicon(conn, entry_id, "the cat")
            update_lexicon(conn, entry_id, "the cats")
            conn.commit()
            count = conn.execute(
                "SELECT COUNT(*) FROM lexicon WHERE term='cat' AND ngram_size=1"
            ).fetchone()[0]
            occ = conn.execute(
                "SELECT occurrences FROM lexicon WHERE term='cat' AND ngram_size=1"
            ).fetchone()[0]
        assert count == 1
        assert occ == 2
