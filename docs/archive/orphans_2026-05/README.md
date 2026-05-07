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

## A7-medium archived 2026-05-07

The medium-confidence batch landed in a follow-up commit. Verification
pass: each module's importers grep'd; all consumers were legacy
(Panda3D-era files: `cavern.py`, `shadowbox_dungeon.py`, `creation_lab.py`,
`simulation_theater.py`, `core/systems/biome_scene.py`) or
co-retiring (e.g. `entropy_engine` only consumed by `placement_engine`,
both archived together).

| File | Verified consumers (all legacy) | Superseded / replaced by |
|---|---|---|
| `placement_engine.py` | `cavern.py`, `shadowbox_dungeon.py` | `world_gen.py` honeycomb + flourish helpers, `stamp_world.stamp_at` |
| `entropy_engine.py` | `cavern.py`, `shadowbox_dungeon.py`, `placement_engine` (lazy import) | (no replacement — entropy randomization absorbed into world_gen) |
| `ghost_profile_engine.py` | `avatar_pipeline.py` (itself legacy-only) | `fingerprint_engine.py` is the live primitive; ghost-profile blending was avatar-creation-flow specific (now superseded by `pillars/` + `character_draft`) |
| `tree_builder.py` | `core/systems/biome_scene.py` (Panda3D) | `wireframe_mesh.py` `tree_top` built-in primitive |
| `pickup_system.py` | `creation_lab.py`, `simulation_theater.py`, `scenario_runner.py` (all legacy) | `PlayerState.inventory` tuple via `core/systems/player_state.py` |
| `object_ecology.py` | (zero consumers, zero tests) | (no replacement — DESIGNED-only, never built into the live pipeline; ecological tagging if needed will land via kind_config schema) |

Bound tests archived alongside: `test_placement.py`, `test_entropy.py`,
`test_ghost_profile.py`, `test_tree_builder.py`. (No tests existed for
`pickup_system` standalone or `object_ecology`.)

## Known downstream breakage (acceptable — legacy)

After this archive, `core/systems/avatar_pipeline.py` has a broken
import (`from core.systems.ghost_profile_engine import GhostProfileEngine`).
It is itself only consumed by Panda3D-era files (`creation_lab.py`,
`simulation_theater.py`). Its cleanup is part of A14 (legacy archive
batch) — left broken intentionally rather than expanding A7 scope.

Same pattern for `tests/test_fingerprint.py:92,102` and
`tests/test_design_key.py` — these import `GhostProfileEngine` lazily
inside test bodies. They will fail to RUN but still collect; the
failures are isolated and don't affect the live test suite (verified
post-archive: 157/157 cluster sweep green).

## A10 archived 2026-05-07 (closes feat/arpg-combat PR 1)

The audit's deferred A10 batch landed alongside ARPG combat PR 1.
Real-time Strike model (per `design_arpg_combat_v1`) doesn't reuse the
turn-based combat substrate; these files have no live consumers.

| File | Why retired |
|---|---|
| `combat.py` | Turn-based Participant + Formula. Not used by real-time Strike. |
| `combat_session.py` | Turn-based round wrapper. Same. |
| `attack_lib.py` | JSON→AttackDef cache for combat.py. |
| `encounter_builder.py` | Pack-pull for kind_config combat_profile (combat-shaped). |
| `crafting_engine.py` | Crafting recipes; only legacy callers. |
| `crafting_integration.py` | Bridge over idle ScenarioEngine + Inventory class (both archived). |
| `material_system.py` | Only consumer was archived `entity_template.py`. |
| `interaction_engine.py` | Only Panda3D-era callers. |
| `campaign_engine.py` | Only Panda3D-era callers (creation_lab archived). |
| `dungeon_campaign.py` | Only Panda3D-era callers. |
| `session_boundary.py` | No live importer; was a bound test only. |
| `grace_handler.py` | No live importer; pure-Python orphan. |

Bound tests archived: `test_combat.py`, `test_combat_session.py`,
`test_crafting.py`, `test_encounter_builder.py`, `test_grace_handler.py`,
`test_interactions.py`, `test_material_system.py`.

## A14 already closed in earlier commit (a3bde33)

The full Panda3D-era archive (21 source modules + 10 top-level entries
+ 17 bound tests) landed there. Combined with this A10 archive, the
live `core/systems/` directory is now substantially clean — no
turn-based combat substrate, no Panda3D imports.

See audit doc `.claude/audit_2026-05-06.md` for the full disposition map.
