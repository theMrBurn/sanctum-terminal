# Feature — feat/arpg-combat

**Status:** V1 spec locked 2026-05-07 (user pivot from creature_engagement-only direction).
**Branch:** TBD — pick at PR 1 commit time. Probably fresh `feat/arpg-combat-v1` off main since this is a substrate-level shift, parallel-safe with `feat/creature-engagement` but doesn't strictly depend on it.
**Spec:** `~/.claude/projects/-Users-themrburn-git-sanctum-terminal/memory/design_arpg_combat_v1.md`.

## Premise

Cash in the load-bearing claim of `feat/make-brain-ping-pong`: **tennis math = combat math**. Every weapon use spawns a Strike — a moving sphere with ContactProfile properties — that traverses space via the existing BallisticsSolver and resolves on contact. Three modes:

- **WHIP** — tethered ball, swing arc, retracts
- **SHOT** — direct projectile, point-and-launch
- **HELD** — wielded weapon, persistent, optional shot combo

Strike against env = damage. Strike against creature = trigger that creature's engagement (per `design_creature_engagement_v1`). One combat primitive, two narrative outcomes — `design_wont_tolerate` #5 honored.

## Decisions locked

| # | Question | Locked answer |
|---|---|---|
| 1 | One Strike primitive or three separate primitives? | **One.** Mode flag dispatches behavior. Reuses ping-pong substrate maximally. |
| 2 | Geometry support in V1? | **Sphere only.** Visual reshape via wireframe mesh wrap per weapon. Capsule + blade geometries are V2. |
| 3 | Strike-on-creature behavior? | **Triggers engagement.** Per `design_wont_tolerate` #5 — no HP damage to creatures. Strike opens the kind's engagement_type from `design_creature_engagement_v1`. |
| 4 | Combo weapons (held primary + shot secondary)? | **Yes, V1.** Single vault.profiles row carries two mode handlers. fire_staff ships PR 5 as proof. |
| 5 | Where does weapon config live? | **`vault.profiles` with `instance_id="weapon"`.** Reuses make-brain substrate. Hot-reloadable via existing console save/load. |
| 6 | Damage formula? | **`damage = strike.kinetic_energy × profile.coupling × (1 / target.hardness)`.** Hardness from kind_config (default 1.0). Direct generalization of brick HP drain. |
| 7 | Activity-loop integration? | **HUNT for melee + ranged_thrown/bow; SOLVE for magic_staff/wand.** Magic emits SOLVE — wizard-heavy player gets puzzle-shaped tension pacing via the activity loop's TensionCycle consumer. |
| 8 | First slice (V1 PR 2)? | **SHOT mode.** Closest to ping-pong substrate; ball really flies; ball + trail already render. throwing_axe is the first weapon. |
| 9 | A10 disposition (combat.py et al.) | **RETIRE in PR 1.** Turn-based combat substrate doesn't apply to real-time Strike model. Files archived per audit A10. |
| 10 | Multi-target per swing? | **Held mode only, V1.** A held swing's arc CCDs each frame; multiple creatures/env in arc all take impact. Shot mode dies on first contact (V1); ricochet is V2. |
| 11 | Charge-and-release? | **Out of V1.** Stage 3 of ping-pong's deferred motion envelopes covers this; revisit when those land. |

## In-scope (V1)

- New `core/systems/strike.py` — Strike dataclass + factory + mode dispatch
- `core/systems/ballistics.py` — `WallPlane.interaction_kind` extension (reflect | absorb | passthrough)
- `core/systems/weapons/` — per-weapon-class handlers (melee_blade, melee_blunt, melee_tether, ranged_thrown, ranged_bow, magic_staff, magic_wand)
- `vault.profiles` weapon rows for: throwing_axe, iron_sword, chain_whip, fire_staff
- New `vault.combat_sessions` table — per-strike record (mirrors vault.runs but per swing)
- Brain dispatch wires player input (LMB/RMB/keys) → strike.spawn(weapon, camera_state)
- Vector terminal: `clients/vector_terminal/strike_renderer.py` — renders Strikes in flight (ball, chain, weapon-mesh)
- Manifest exposes active Strikes for client rendering
- Activity-loop integration: HUNT/SOLVE per `weapon_class` on Strike resolution
- A10 retirement: combat.py + combat_session.py + attack_lib.py + encounter_builder.py archived
- StateEvent emission per Strike outcome

## Out-of-scope (V1)

- Capsule + blade geometries (V2)
- Ricochet (V2)
- Charge-and-release (Stage 3)
- Dual-wield, parry, block, dodge (V2)
- Status effects / DoT / stuns / `apply_effect` resolution (V2)
- Per-creature flavor-routing of engagement_type via Strike kind (V2)
- Multi-creature engagements (per creature_engagement_v1 spec)

## Phasing — PR breakdown

### PR 1 — Strike primitive + WallPlane extension + A10 retirements
- New `core/systems/strike.py`:
  - `@dataclass(frozen=True) class Strike` per spec
  - `def spawn(weapon_profile, mode, camera_state, source_actor) -> Strike`
  - Stub dispatch table for the 3 modes
- `core/systems/ballistics.py`:
  - Extend `WallPlane` with `interaction_kind: Literal["reflect", "absorb", "passthrough"]` (default "reflect" preserves V1 ping-pong)
  - `BallisticsSolver._reflect` extended: absorb stops + records contact; passthrough records + continues with energy loss
- A10 retirement: archive 12 files to `docs/archive/orphans_2026-05/`
- Update LIVE_PIPELINE_MAP — A10 section retired.
- T1 (test_strike): construction + factory + mode dispatch.
- T2 (test_ballistics): WallPlane absorb + passthrough.

### PR 2 — SHOT mode end-to-end
- `core/systems/weapons/ranged_thrown.py` handler
- `vault.profiles` row: `(weapon, throwing_axe)`
- Brain dispatch — primary input → `weapon.on_use` → spawns Strike → BallisticsSolver runs flight → `_resolve_strike_contact`
- Manifest exposes `active_strikes: list[StrikeManifest]`
- Vector terminal: `clients/vector_terminal/strike_renderer.py` reads + renders ball + trail
- StateEvents: `strike_landed`, `strike_missed`
- Activity-loop: HUNT intensity 1
- T3: full lifecycle (spawn → fly → env contact → smash; spawn → fly → creature contact → engagement open)
- S1: throw axe at pot, pot smashes; throw at rat, engagement opens

### PR 3 — HELD mode + iron_sword
- `core/systems/weapons/melee_blade.py` handler
- HELD-mode dispatch: each frame during swing arc, swept-sphere CCD; multi-hit possible
- vault.profiles seeded
- LMB triggers swing
- strike_renderer renders weapon-mesh + impact glow
- T4: HELD lifecycle, multi-hit
- S2: cluster of pots, swing sword, multiple smash events

### PR 4 — WHIP mode + chain_whip
- `core/systems/weapons/melee_tether.py` handler
- WHIP-mode dispatch: ball at tether forward, swing-arc velocity, retract animation
- vault.profiles seeded
- strike_renderer renders ball + linked-line tether segments
- T5: WHIP lifecycle (spawn → arc → contact → retract)
- S3: swing whip in arc, multiple hits + retract

### PR 5 — Combo weapon (fire_staff)
- `core/systems/weapons/magic_staff.py` — `on_primary` (held) + `on_secondary` (shot)
- vault.profiles seeded with combo profile
- LMB primary, RMB secondary
- Activity-loop: HUNT primary, SOLVE secondary
- T6: combo handler test
- S4: equip fire_staff, swing held, RMB to fire bolt, both resolve

### PR 6 — Vector terminal strike_renderer polish
- Per-mode visual: SHOT (ball+trail), HELD (mesh+glow), WHIP (ball+chain segments)
- Multi-Strike rendering with z-order
- StateEvent toasts route through existing renderer
- T7: render-side unit tests
- V1 (visual UAT): each mode looks distinct + readable

### PR 7 — vault.combat_sessions + activity-loop integration
- New `vault.combat_sessions` table per spec
- Helpers: `combat_session_open`, `combat_session_close`, `combat_sessions_by_weapon`
- Activity-loop emit per weapon_class table
- Memory pin `project_arpg_combat_v1` shipped
- T8: telemetry tests
- S5: full-loop UAT, all weapon profiles, env + creatures, activity counters reflect properly

## Hot-reload notes
- `core/systems/strike.py` / `ballistics.py` — brain restart
- `core/systems/weapons/*.py` — brain restart
- `vault.profiles` weapon rows — live reload via console save/load
- `vault.combat_sessions` schema — brain restart
- `clients/vector_terminal/strike_renderer.py` — vector terminal restart
- `kind_config.json` hardness fields — already supports hot reload

## Parallel-safe siblings
- `feat/creature-engagement` — disjoint code paths, both extend brain dispatch additively. Whoever lands first wins clean diff.
- A13 (blender V1) — disjoint files
- Memory consolidation Phase 4 — disjoint

## Acceptance signature

V1 shipped when:
- T1–T8 + M1 + V1 all hold
- SCENARIOs S1–S5 all pass
- All three modes feel distinct (kinetic, projectile, weighted)
- LIVE_PIPELINE_MAP updated
- Pin `project_arpg_combat_v1` memory at ship time documenting:
  - Final weapon catalog (4 V1: throwing_axe, iron_sword, chain_whip, fire_staff)
  - vault.combat_sessions schema
  - Strike dispatch table
  so V2 (capsule/blade geometry, ricochet, parry/block, dual-wield, status effects) extends cleanly.

## Risks pinned during planning

- **Per-frame swept-CCD cost in HELD mode.** 0.4s arc × 60Hz = 24 swept-sphere tests per swing. ~50 nearby entities → ~1200 CCD checks. Acceptable per ping-pong's substep budget (4-8 substeps × 60Hz proven). Mitigation if cost climbs: spatial-hash filter env candidates before swept test.
- **WHIP tether visual.** Vector terminal hasn't rendered linked-line segments before. New primitive — line-strip primitive needed to read as chain rather than disconnected dots.
- **Mode coverage for creatures.** All three modes need to trigger engagements correctly. Edge case: WHIP retract during engagement-open — V1 answer: retract completes silently; engagement opens after retract.
- **Combo weapon input dispatch.** LMB/RMB convention works for keyboard + mouse; controllers via input_map abstraction (already shipped) when bindings land.
- **Damage formula tuning.** First-pass formula may give weird scales (hand-throw axe ~10kg·m²/s² vs swung sword ~150). Tuning per weapon in vault.profiles. UAT will surface.
- **A10 retirement scope.** Same accept-and-flag posture as feat/creature-engagement PR 1's plan. Whichever branch ships first lands A10; the other rebases.

## Cross-references

- `design_arpg_combat_v1` (memory pin) — locked spec
- `design_creature_engagement_v1` — companion (creatures don't take HP; Strike triggers engagement)
- `project_make_brain_ping_pong_v1` — substrate this branch harvests
- `design_wont_tolerate` #5 — Strike triggers engagement, not damage
- `project_activity_loop_v1` — HUNT/SOLVE feeds from combat
- `design_north_stars_gameplay` — Hades-like is the gameplay pillar this serves
