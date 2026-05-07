# Archived orphans — 2026-05-07

Files moved here as part of audit ask **A7-subset** (see
`.claude/audit_2026-05-06.md`). Each was verified to have:

1. Zero live (brain_server / vector_terminal) consumers.
2. A clear superseding system already shipped on main.

Importers were exclusively legacy Panda3D-era files (`cavern.py`,
`creation_lab.py`, `room_lab.py`, `simulation_theater.py`, `main.py`,
`SimulationRunner.py`) — themselves slated for archival in audit ask
A14 once decisions on the remaining medium-confidence orphans land.

## Manifest

| File | Superseded by | Notes |
|---|---|---|
| `input_handler.py` | (no replacement — pygame-based, never wired into vector_terminal) | Originally at `core/input_handler.py`. No consumers. |
| `interview.py` | `core/systems/pillars/` + `character_draft.py` + `dial_prompt.py` | InterviewEngine pre-dates the seven-pillars character creation flow. |
| `interview_ui.py` | `clients/vector_terminal/dial_input.py` + `pillars/` | Panda3D-imported (`from panda3d.core import TextNode`). |
| `inventory.py` | `PlayerState.inventory: tuple[Item,...]` (NamedTuple field on player_state.py) | Class survived as legacy; live inventory is the tuple field. |
| `quest_engine.py` | `core/systems/quests/` registry + `quests/tick.py` + `quests/predicates/` | Pre-async-quest-refactor. Async refactor PRs 1-6 shipped 2026-05-02. |
| `encounter_generator.py` | `core/systems/encounter_session.py:on_camera()` | Generator's proximity logic is now inside session. |

## Tests

Bound tests moved to `tests/` subdirectory:

- `test_input.py` (was at `tests/unit/test_input.py`)
- `test_interview.py`
- `test_interview_ui.py`
- `test_input_baseline.py` — was actually testing interview_ui import availability
- `test_inventory.py`
- `test_quest_engine.py`

These will not be collected by `pytest` from this archive location.

## What was NOT archived in this batch

Per audit A7, the following orphans were tagged "medium confidence" and
require explicit user direction (retire vs. wire) before archival:

- `core/systems/placement_engine.py`
- `core/systems/entropy_engine.py`
- `core/systems/ghost_profile_engine.py`
- `core/systems/tree_builder.py`
- `core/systems/object_ecology.py` (DESIGNED, not built — different category)
- `core/systems/pickup_system.py`

Plus `core/systems/scenario_runner.py`, `consolidation.py`,
`crafting_engine.py`, `crafting_integration.py`, `material_system.py` —
deferred to A9 / A10 since they may rewire under the
`design_creature_engagement_v1` spec.

See audit doc A7 + A14 for the full disposition map.
