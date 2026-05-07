# core/systems/make_brains/nethack — AGENTS.md

Side-project comparator: classic NetHack as a make-brain instance.
Spec: `.claude/feature/feat_make-brain-nethack.md`.

## Owns
- `core/systems/make_brains/nethack/__init__.py` — identity + activate()
- `core/systems/make_brains/nethack/handler.py` — NetHackHandler (substrate)
- `core/systems/make_brains/nethack/{engine,dungeon,entities,combat,items,ai,fov,render,input_map}.py` — V1 build-out
- `nethack_terminal.py` — entry point at repo root

## Reads (does not own)
- `core/systems/make_brain_registry.py` — registration API
- `core/vault.py` — `profile_save / profile_load / run_start / run_end / runs_by_instance`

## Subsystem rules
- **Classic NetHack fidelity, not sanctum substrate.**  This brain
  implements YASD permadeath, classic stats, and NetHack-style combat
  math.  It does **NOT** consume cairn rules, reflective-loop, or
  death-only-regen — those are sanctum proper.
- **No LLM calls anywhere.**  Air-gap rule applies.  All death
  messages, monster names, item names from hardcoded tables.
- **No vector_terminal integration.**  Standalone curses app.
- **Vault is the only persistence boundary.**  No pickle, no JSON
  files, no save-state outside `vault.profiles` + `vault.runs`.
- **Per-PR scope discipline** — PR N may not introduce code that PR N+1
  is supposed to land.  Stub the boundary, land the test, move on.

## Hot-reload
- Edits to anything under `nethack/` → restart `make brain-nethack`.
  No live reload needed; sessions are short.

## Acceptance criteria
- TEST always (every PR ships at least one test)
- SCENARIO for PRs 1, 3, 5, 6, 8 (user-facing scenarios)
- MIGRATION not applicable (no schema changes — vault.profiles +
  vault.runs are inherited from ping_pong)

## Touch test
```
PYTHONPATH=. ./.venv/bin/python -m pytest tests/test_nethack_*.py -v
make brain-nethack
```
