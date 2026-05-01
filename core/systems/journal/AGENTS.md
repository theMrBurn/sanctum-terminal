# core/systems/journal — AGENTS.md

Owns vault, lexicon, journal queue (Permanent Objects). J1+J2+J3+J6.0 shipped 2026-04-30.

## Owns
- `core/systems/journal/lexicon.py`, `lexicon_seeds.py`
- `core/vault.py` — schema, queries
- `core/systems/quests/from_journal.py` — entry → quest bridge
- `core/systems/quests/predicates.py` — async predicate tick

## Reads (does not own)
- `config/journal/*.json`, `core/systems/quests/state.py`

## Hot-reload
- lexicon.py / seeds JSON / from_journal.py → restart brain
- vault.py schema → MIGRATION (see `LIVE_STATE.md`)

## Subsystem rules
- raw_note is canonical. parser_version regen-safe.
- Triple-trigger pattern (inline / daily / ad-hoc) — don't break it.
- gensim / spaCy only. No LLM ingestion.
- Vault writes go through `vault.py` public API. No raw SQL inline.

## Acceptance criteria
- TEST always (vault is testable end-to-end)
- MIGRATION if schema touches
- SCENARIO if user-facing path

## Touch test
make test-quest
