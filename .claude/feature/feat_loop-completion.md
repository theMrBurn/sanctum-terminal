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
- **PR 3** — **Consequences engine + reflective-mode state machine + AC predicates + minimal fridge kind + stub rule.** Replaces the original "death-only regen" minimal scope after the 2026-05-01 design conversation that produced `design_reflective_loop`. HP=0 enters reflective mode (the fridge); rule satisfied + commit returns to active. No perma-death (`design_virtual_hallucination`). World regen still HP=0-gated (`design_death_only_regen`), now expressed as one effect in the consequences engine. The reflective rule is consumer #1; quest reward dispatch (already shipped in PR 1) becomes consumer #2 to prove the abstraction.
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

## Order
PR 3 → PR 4 → (UAT gate) → PR 5 → PR 6. Confirmed 2026-05-01.

## PR 3.5 UAT outcome (2026-05-01)
Voluntary path validated end-to-end: walk to fridge → F engage → arrows + ENTER place magnets → C commit → DONE toast → back to HUB. Brain logs clean (`engage_fridge: rule=compose_three pool_size=31`, no errors).

HP=0 forced path **not validated organically** — no damage source exists in V1 beyond the `damage_self` debug cmd, and there's no key binding for it in vector terminal. The substrate is identical to the voluntary path (one extra consequence row routes the entry); we'll debug if it fails once an organic damage path lands (combat, environmental hazards). Per user 2026-05-01: "we can debug if it fails when hooked to an HP zero event."

PR 3.5 is functionally shipped. The loop is live.

## PR 5 trigger
PR 5 (destructive collapse) lands only when ALL of these hold:
- PR 3 passes scenario UAT (death triggers regen, active quests survive)
- PR 4 passes scenario UAT (bearing prefix renders, journal toggle works)
- Tests rewritten green for both
- Two consecutive sessions on this branch without revert

This stops the dual-route in `mission_complete_trigger` from rotting into permanence. Confirmed 2026-05-01.

## UAT bracketing (navigation)
Clip-through failures (walls cosmetic, FPS collision bug, creatures clipping) **do not count** against PR 3/PR 4 verdict. They're known-deferred and tracked separately. UAT verdict is on quest mechanics + regen behavior + HUD legibility only. Confirmed 2026-05-01.

## Deferred-pile policy
Everything in the deferred pile stays "deferred" until definitively superseded or shipped. No "abandoned" status — items are alive until proven otherwise. Confirmed 2026-05-01.

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
