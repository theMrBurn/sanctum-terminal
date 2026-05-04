# LIVE_STATE.md

Files whose edits mutate persistent state. Touch these without a migration → eat past saves.

## Persistent stores
- `data/vault.db` — SQLite. Tables: archive, scenarios, objects, entries, lexicon, lexicon_contexts, lexicon_state, user_seeds.
- `save/player.json` — V3 schema (active_quests + completed_quests on PlayerState).

## Schema-defining files (edits = migration required)
- `core/vault.py` — vault class, table DDL, query API.
- `core/systems/save_state.py` / `player_state.py` — save schema.
- `core/systems/scenario_ledger.py` — scenario provenance hash schema.
- `core/systems/journal/lexicon.py` — `parser_version` field gates lexicon regen.
- `config/kind_config.json` — schema enforced by `core/systems/kind_config_schema.py`. Migrations live in `core/systems/migrations/kind_config/`.

## Migration discipline
- kind_config: migration scripts exist. Use them. Bump schema version atomically.
- vault: NO formal migration framework yet. `parser_version` lets lexicon regenerate; other table changes require ad-hoc migration. Flag in PR.
- save: bump version field, write loader that handles old shapes.

## Before any edit to files above
1. Does this break old saves/vault? If yes → write migration first.
2. If schema changes are unavoidable, confirm with user before merging.
3. Tag PR as MIGRATION in acceptance criteria.
