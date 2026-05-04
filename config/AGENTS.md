# config — AGENTS.md

Single-source config consumed by both brain and clients.

## Files
- `kind_config.json` — entity render/scale/color/collision/recipes. Schema: `core/systems/kind_config_schema.py`. Symlinked into `godot/`.
- `kind_config.snapshot.json` — last validated snapshot.
- `encounters.json` / `attacks.json` / `verbs.json` — encounter postures, attack lib, 7 verbs.
- `ghost_profiles.json` / `signal_map.json` — ghost seed registry, signal routing.
- `manifest.json` — runtime manifest (generated; do not hand-edit).
- `journal/*.json`, `blueprints/*.json` — lexicon seeds, character/world blueprints.

## Subsystem rules
- New per-kind behavior → row in `kind_config.json` + schema entry. No per-kind branches in code.
- New per-biome behavior → entry in `BIOME_REGISTRY` (`core/systems/biome_data.py`).
- Schema changes require migration in `core/systems/migrations/kind_config/` + validator pass.
- Authoring is CRUD: new gameplay = new row, not new code (modulo one-time engine extensions).

## Hot-reload
- `kind_config.json` → brain restart, Godot reconnect.
- `encounters.json` / `attacks.json` / `verbs.json` → brain restart.
- Schema (`kind_config_schema.py`) → brain restart + validate snapshot.

## Acceptance criteria
- TEST (schema validation)
- SCENARIO if behavior-bearing

## Touch test
make test-unit
