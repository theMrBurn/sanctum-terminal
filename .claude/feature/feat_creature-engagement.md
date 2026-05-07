# Feature — feat/creature-engagement

**Status:** V1 spec locked 2026-05-07 (audit ask A8). Implementation pending.
**Branch:** TBD — pick at PR 1 commit time. Probably bundled on a fresh `feat/creature-engagement-v1` branch off main since this is a substrate-level shift, not a continuation of an existing arc.
**Spec:** `~/.claude/projects/-Users-themrburn-git-sanctum-terminal/memory/design_creature_engagement_v1.md` + `docs/spec_creature_engagement.md`.

## Premise

Replace direct `encounter_session.on_camera` dispatch for creature kinds with a kind_config-driven engagement-type lookup. Each engagement type is its own make-brain (reusing the substrate from `feat_make-brain-ping-pong`), giving free per-type telemetry + profile tuning + StateEvent declarations.

V1 ships **one engagement type wired end-to-end** (compose_three, leveraging the already-shipped reflective state machine). Subsequent PRs add types as content rather than substrate work.

The load-bearing claim: **engagement primitive (reflective shape) × make-brain (substrate) × kind_config (binding) is the right architecture for creature interactions and modding**. Per `design_north_star` Phase 3, this registry is the eventual mod surface.

## Decisions locked

| # | Question | Locked answer |
|---|---|---|
| 1 | One engagement TYPE per kind, or instance variation? | **Per-kind for V1.** Instance variation lives in `rule_args` (e.g. `target_count: 5`). |
| 2 | Reuse REFLECTIVE state or add ENGAGEMENT state? | **Add ENGAGEMENT** — REFLECTIVE stays for HP=0 fridge; ENGAGEMENT is creature contact. ~30 LOC for the new state-machine row. |
| 3 | World freezes during engagement? | **No, world keeps running.** Matches async-quests doctrine. Overlay captures input but ambient + roaming continue. |
| 4 | engagement_type identity in code | **Each is a registered make-brain.** Reuses make_brain_registry.register / dispatch. |
| 5 | Kind binding location | **kind_config.json** new `engagement` slot per kind. Schema validated. |
| 6 | Engagement registry hot-reloadable? | **Yes**, V2. V1 reloads on brain restart only. |
| 7 | Cairn verb gating | **Spec'd, deferred to V2.** V1 shows all options. |
| 8 | First engagement type to ship | **`compose_three`** — reuses fridge state machine. Lowest substrate cost. First creature kind: **rat → compose_three w/ rat_postures pool**. |
| 9 | Activity-loop integration | **engagement-completed → emit_activity per type table** (see v1 pin). Win paths only; fail = NOT YET, no penalty signal. |
| 10 | combat.py / combat_session.py / attack_lib.py / encounter_builder.py disposition | **RETIRE in this branch** — none of these will be wired under engagement primitive. They go to `docs/archive/orphans_2026-05/` as part of PR 1 prep. Closes A10's deferral. |

## In-scope (V1)

- New game state `ENGAGEMENT` (sibling of REFLECTIVE) + transition rules
- `kind_config.engagement` schema slot + validator + migration
- `compose_three` make-brain wrapper (state_machine reused, registered via make_brain_registry)
- `vault.engagements` table — per-engagement instance log
- Brain dispatch: contact → engagement_type lookup → make_brain dispatch
- Vector terminal: read manifest.engagement_state, render engagement_type's overlay
- First kind binding: `rat → compose_three` with custom pool + on_win loot
- Activity-loop integration: SOLVE intensity 2 on win
- Test coverage: schema validator, dispatch routing, end-to-end SCENARIO

## Out-of-scope (V1)

- Cairn verb gating (V2)
- Engagement type catalog beyond `compose_three` (PR 6 adds rhythm_three; further types are content PRs)
- Hot-reload registry (V2)
- Per-instance variation (rule_args is V1 knob; per-instance overrides are V2)
- Multi-creature engagements (one-at-a-time per V1)
- Engagement during quest predicate evaluation ordering optimizations (default ordering inherited from existing quest tick)

## Phasing — PR breakdown

### PR 1 — kind_config schema + first binding + A10 retirements
- Add `engagement` slot to `core/systems/kind_config_schema.py` per spec.
- Idempotent migration in `core/systems/kind_config_migrations.py` — existing kind_config entries get no `engagement` field (defaults to None).
- Edit `config/kind_config.json`: add `engagement: {engagement_type: "compose_three", rule_args: {...}}` to `rat`.
- A10 retirement (closes that deferred ask): move to `docs/archive/orphans_2026-05/`:
  - `core/systems/combat.py`, `combat_session.py`, `attack_lib.py`, `encounter_builder.py`
  - `core/systems/crafting_engine.py`, `crafting_integration.py`, `material_system.py`
  - `core/systems/interaction_engine.py`
  - `core/systems/campaign_engine.py`, `dungeon_campaign.py`
  - `core/systems/session_boundary.py`, `grace_handler.py`
  - Bound tests for each
- Update LIVE_PIPELINE_MAP — A10 section retired.
- T1: schema validator accepts/rejects `engagement` slots.
- M1: kind_config migration idempotent re-run.

### PR 2 — `compose_three` make-brain wrapper
- New `core/systems/make_brains/compose_three.py` — handler class wraps existing `reflective/state_machine.py` calls.
- Registers with `make_brain_registry.register(instance_id="compose_three", ...)` declaring state_event_types.
- Profile params: target_count, max_attempts, max_pool_size.
- vault.profiles seeded with `(compose_three, default)`.
- T2: handler init + state machine round-trip with seeded profile.

### PR 3 — `vault.engagements` table
- New schema in `core/vault.py`: `engagements(id, instance_id, agent_id, kind, started_at, ended_at, terminal_state, metrics_json)`.
- Helpers: `engagement_open`, `engagement_close`, `engagements_by_kind`.
- Mirrors vault.runs but for engagement-instance grain.
- T3: schema migration idempotent; CRUD round-trip.

### PR 4 — Brain dispatch wiring
- `BrainWorld.tick` — when `roaming_pool.detect_contact(camera)` returns an agent with `kind_config[kind].engagement` populated, dispatch to that engagement_type's make-brain handler instead of `encounter_session.on_camera`.
- New game-state row `ENGAGEMENT`; transition on dispatch + on resolve.
- Manifest emits `engagement_state: {type, kind, agent_id, ...}` while active.
- StateEvents: `engagement_open`, `engagement_won`, `engagement_lost`, `engagement_aborted`, `engagement_fled` per the spec table.
- T4: contact → dispatch → state transition; resolve → state transition back.

### PR 5 — Vector terminal routing
- `clients/vector_terminal/main.py` — read `manifest.engagement_state.type`; route to a per-type overlay function.
- For `compose_three`: reuse existing `clients/vector_terminal/reflective.py` overlay (the fridge UI).
- New file `clients/vector_terminal/engagement.py` — dispatcher that maps engagement_type → overlay function.
- Engagement input handlers (commit, abort) wire through the existing make_brain_commands `console_exec`-style path.
- T5: dispatcher routes correctly; overlay renders without crash.
- V1 (visual UAT): walk into a rat → fridge-shaped overlay opens with rat-posture pool → commit closes the engagement → loot drops.

### PR 6 — `rhythm_three` make-brain + boulder_pixie kind
- New `core/systems/make_brains/rhythm_three.py` — timing buffer state machine.
- New `clients/vector_terminal/rhythm_overlay.py` — beat-bar UI.
- `boulder_pixie` kind added to kind_config with `rhythm_three` engagement.
- T6: rhythm timing math + overlay renders; SCENARIO walks through.
- Proves multi-type architecture works.

### PR 7 — Activity-loop integration
- Each engagement-handler emits `activity_loop.emit_activity(...)` on win per the v1-pin table.
- compose_three win → SOLVE intensity 2.
- rhythm_three win → HUNT intensity 2.
- Telemetry payload carries kind + engagement_type + duration_ms.
- T7: emit-on-win verified for both engagement types.
- SCENARIO 7: walk into rat, win compose_three, see SOLVE counter advance + (if past threshold) reward StateEvent toast.

## Hot-reload notes
- `core/vault.py` (engagements table) → brain restart.
- `core/systems/kind_config_schema.py` → brain restart.
- `core/systems/make_brains/compose_three.py` / `rhythm_three.py` → brain restart.
- `clients/vector_terminal/engagement.py` / overlay files → vector terminal restart.
- `config/kind_config.json` engagement bindings → brain reload via existing kind_config hot-reload (already supported).

## Parallel-safe siblings
- Audit asks A13 (blender V1), Phase 4 memory consolidation — disjoint files.
- The `feat/creature-engagement` branch IS the closing of A10 (retires the combat/crafting/etc. cluster). Bundling that into PR 1 keeps it on this branch; rebasing later branches against main expects A10 retirements landed.

## Acceptance signature

V1 shipped when:
- T1–T7 + M1 + V1 all hold
- SCENARIO: brain in cavern → walk to rat → compose_three engagement opens → resolve win → loot drops + activity_loop SOLVE counter advances
- SCENARIO: brain in cavern → walk to boulder_pixie → rhythm_three engagement opens → resolve win → activity_loop HUNT advances
- LIVE_PIPELINE_MAP updated to reflect the new engagement substrate
- Pin `project_creature_engagement_v1` memory at ship time documenting:
  - Final engagement-type list shipped
  - kind_config schema slot example
  - vault.engagements contract
  - First kind bindings
  so V2 (verb gating, hot-reload, more types) extends cleanly.

## Risks pinned during planning

- **State-machine reuse vs new substrate.** Reusing reflective state_machine couples ENGAGEMENT to REFLECTIVE's evolution. If REFLECTIVE adds rules that don't apply to creature engagement, we'd need to fork. Mitigation: V1 only uses the AC-validated commit primitive; if reflective grows orthogonal logic later, fork at that point.
- **Make-brain proliferation.** Each engagement_type = a make-brain instance. After 5-7 types, the registry has lots of entries. Acceptable per `feedback_factor_of_7` if we cap at 7; document the cap.
- **kind_config schema migration.** First time a kind_config schema bump lands. Migration framework exists in `kind_config_migrations.py`; this exercises it.
- **vault.engagements vs vault.runs grain.** Two telemetry tables for similar things. Documented distinction: runs = make-brain *session*, engagements = make-brain *instance per agent*. Resist merging unless analysis pulls one out.
- **A10 retirement scope.** PR 1 retires 12 files. Cascading legacy breakage expected (some legacy-only consumer chains will break further). Same accept-and-flag posture as A14 commits — broken legacy = legacy.
