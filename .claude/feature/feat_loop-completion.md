# Feature — feat/loop-completion

Branch name predates the pivot. Actual scope is the **async quest refactor** (see memory: `project_async_quest_refactor`). PRs 1+2 already on this branch; PRs 3-6 remain.

## How we got here (the arc this branch holds)

This file captures the whole arc, not just remaining scope. The branch name is a label; the work is the artifact.

- **L-series loop completion** — DRG-style 5-state loop (HUB → MISSION_SELECT → IN_MISSION → RESULTS → HUB) shipped, then UAT-rejected 2026-04-30. Modal state transitions broke the planner-roots contract (tasks live IN life, not outside it).
- **Pivot — async quest refactor** — Collapse to 2 states (CHARACTER_CREATION ↔ HUB), quests stack on persistent world, world regens only on HP→0. Plan blessed 2026-04-30.
- **PR 1 (shipped)** — Quest substrate: registry, predicates, brain wiring, J overlay, J3-min entry→quest bridge, async predicate tick. 4 commits.
- **PR 2 (shipped)** — Save schema V3: `active_quests` + `completed_quests` on PlayerState. V1→V2→V3 migration preserves everything.
- **Rode along** — StateEvent primitive, HUD identity block, Backspace abort, Reflection re-do, Days cascade, scenario ledger (vault.scenarios canonical), boot-time dynamic quest replay, the 5-layer AGENTS.md scaffolding itself.
- **Remaining** — PRs 3-6 below.

## In-scope
- **PR 3** — Death-only regen. `_check_death_and_regen(world)` after damage; HP→0 fires StateEvent + regen + HP restore. Active quests survive.
- **PR 4** — Vector terminal HUD active-quest rows + ASCII bearing prefix (`[NE]`). Predicates gain `target_position(world) -> (x,y) | None`. The gap user FELT during 2026-04-30 UAT walk.
- **PR 5** (destructive — last) — Collapse `MISSION_SELECT` / `IN_MISSION` / `RESULTS` from `game_state.py`, brain handlers, Godot UI. Rewrite `tests/test_loop_integration.py`.
- **PR 6** — Cleanup. Drop `hub_seed`, `mission_loot` (migrate to quest defs), regen call sites, schema validator entry.

## Out-of-scope
- FPS collision fix (5 suspects pinned — separate branch). Even if I trip over it.
- Creature collision Phase 5.5 (rats clip walls, pots embedded).
- Torch PRs 5-9 (deferred for loop completion priority — that's THIS branch, but pose UAT and downstream torch work is its own branch).
- Permanent Objects J4 / J5 / J6.1 / J7 (different subsystem, can run parallel).
- ExpeditionEngine → quests collapse. Has its own machinery and tests; phase later.
- Compass strip in HUD (deferred polish — bearing prefix only this branch).

## Definition of done
- [ ] **TEST** — `test_world_regen.py` enforces death-only behavior. `test_loop_integration.py` rewritten green for 2-state machine.
- [ ] **MIGRATION** — V2 save loads → V3 schema after brain restart. Verify still holds after PR 5 lands.
- [ ] **SCENARIO** — brain + vector terminal end-to-end: journal entry creates active quest → bearing prefix renders → travel completes predicate → StateEvent toast + passive reward drop → world does NOT regen.
- [ ] **VISUAL** — HUD active-quest rows render in vector terminal, up to 3 with `+N more`; J overlay still toggles.
- [ ] PR 5 is sequenced after PRs 3-4 are stable. No skipping.

## Hot-reload notes
- `core/systems/game_state.py`, `save_state.py`, `quests/predicates.py`, `config/quests.json` → brain restart.
- `clients/vector_terminal/{hud.py, journal.py, dial_input.py}` → vector terminal restart.
- `godot/main.gd` UI deletions (PR 5) → Godot restart.
- `kind_config.json` `mission_loot` removal (PR 6) → brain restart + Godot reconnect.

## Parallel-safe siblings
- **Permanent Objects journal** (J5 / J6.1 / J7) — `core/systems/journal/` subsystem; only intersects via `vault.py` public API. Worktree-safe.
- **Torch PRs 5-9** — `godot/` shaders + meshes only. No overlap with vector terminal HUD work in PR 4.
- **Creature collision Phase 5.5** — `config/kind_config.json` rows only. No overlap unless PR 6 touches the same rows (it shouldn't — `mission_loot` is the only kind_config target here).

## Acceptance criteria sequencing
PRs 3 → 4 → 5 → 6. Additive first, destructive last (the doctrine that held for 1+2). Land PR 5 only when 3-4 prove stable in scenario UAT. PR 6 is sweep-up after dust settles.
