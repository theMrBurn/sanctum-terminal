# Archived branches — 2026-05-04 baseline cleanup

After `feat/loop-completion` merged to main, the local branch list had
accumulated 30 stale experiment/feature branches from earlier sessions.
Each was tagged as `archive/<branch-name>` (preserves the SHA forever
even after the local branch is deleted) before the local branch was
removed.

## Recovery

- Restore one: `git checkout -b <name> archive/<name>`
- List all archive tags: `git tag --list 'archive/*'`
- Inspect a tag's tree without checkout: `git show archive/<name>`

Tags are local-only — not pushed to origin. If you ever want
network-durable archival, push tags with: `git push origin --tags 'archive/*'`.

## Inventory (alphabetical)

| Branch | Last commit | Date | Subject |
|---|---|---|---|
| `backup-pre-cleanup` | `b291871` | 2026-04-09 | docs: SANCTUM_SESSION 2026-04-08/09 — the simplification |
| `campaign-engine` | `7e59a9c` | 2026-03-30 | feat: CampaignEngine — Wildermyth conductor, procedural quest generation |
| `dungeon-crawl` | `4d59dec` | 2026-03-30 | feat: dungeon.py — playable 7-Door Dungeon, Wizardry first-person |
| `encounter-engine` | `efaccca` | 2026-03-29 | feat: EncounterEngine — resonance-gated, Dragon Quest style, Frieren model |
| `environment-registers` | `a7d85f9` | 2026-03-29 | feat: system-wide renderer — fog, vertex noise, ground subdivision |
| `feat/active-perception` | `afd0a39` | 2026-03-18 | feat: stabilize procedural sprite pipeline and 3x3 hydration |
| `feat/bio-lighting` | `29f2662` | 2026-04-03 | feat: density tuning, wake-at-fog, ambient boost, pop-in fixes |
| `feat/heads-up-refinement` | `3d3a6c7` | 2026-04-26 | chore: track godot import .uid for flame_billboard shader |
| `feat/heartbeat-daemon` | `2f6dd6d` | 2026-03-16 | FEAT: Integrated native dashboard monitoring via --watch flag |
| `feat/membrane-module` | `ee7f0a2` | 2026-04-01 | feat: full config watcher pipeline, magenta glow fix, watcher-safe reload |
| `feat/mission-ledger` | `0d78f02` | 2026-03-16 | feat: implement mission ledger and finalize flat-layout refactor |
| `feat/observer-viewport` | `ed33e7e` | 2026-03-17 | feat: stable observer viewport with shader-corrected HUD and circular culling |
| `feat/outdoor-biome` | `3de00fc` | 2026-04-03 | chore: reset ACTIVE_BIOME to cavern for main branch stability |
| `feat/performance-and-polish` | `563cbaf` | 2026-03-31 | perf: vsync off, light budget cap (8), fullscreen, smooth mote drift |
| `feat/render-manifest` | `0ce6795` | 2026-04-13 | feat: shadow_lab + decal_projector primitive, bats-as-decal, elemental wire |
| `feat/scout-refinement` | `23f568f` | 2026-03-16 | FEAT: Integrated System Progression, Hazard Math, and Adaptive Logic |
| `fingerprint-tick` | `1bf4f42` | 2026-03-29 | feat: compound objects in lab — torch + tome spawn, [R] cycles registers |
| `first-five-seconds` | `c20580a` | 2026-03-30 | feat: first five seconds — boot into VERDANT, quests in HUD, Monk in forest |
| `four-bridges` | `38b94b0` | 2026-03-29 | feat: 4 bridges wired live — encounters auto-fire, scenarios chain, depth consolidates |
| `interview-pipeline` | `a9f161d` | 2026-03-29 | feat: Vault unified query interface — scenarios + objects + relics |
| `iso-camera` | `e87a060` | 2026-04-26 | feat: Godot perf instrumentation + LIVE_PIPELINE_MAP |
| `readme-update-test` | `9b38983` | 2026-03-24 | voxel factory util |
| `readme-update-test-13208607048107374224` | `5fa971d` | 2026-03-24 | docs: verify jules connectivity timestamp |
| `refactor-audit` | `320b6fc` | 2026-03-29 | refactor: extract lab_environment.py — register data + build/lighting/fog |
| `refactor/perception-engine-sync` | `c6466d6` | 2026-03-22 | update from Jules |
| `sprite-atmosphere` | `1884871` | 2026-03-29 | feat: sprite pipeline + atmosphere wiring |
| `visual-refinement` | `d49bb28` | 2026-03-29 | feat: ModelLoader + Kenney reference models in biome scenes |
| `voxel-manufacturing-for-rendering` | `cea0947` | 2026-03-26 | P3: GraceHandler wired — SeedEngine, QuestEngine, boot_biome_scene, 198/198 |
| `wiring` | `3e160f8` | 2026-03-29 | feat: floating labels on REACHABLE — name + weight + use, billboard mode |
| `world-alive` | `84de51b` | 2026-03-29 | feat: shelf objects → Kenney models — 17 objects mapped to .glb references |

## Loose chronological clusters (for orientation)

- **March 16–22 (oldest):** `feat/heartbeat-daemon`, `feat/mission-ledger`, `feat/scout-refinement`, `feat/observer-viewport`, `feat/active-perception`, `refactor/perception-engine-sync` — dashboard / mission framework / observer-mode foundations.
- **March 24–30:** `readme-update-test*`, `voxel-manufacturing-for-rendering`, `refactor-audit`, plus the burst of single-word experiments (`encounter-engine`, `environment-registers`, `fingerprint-tick`, `four-bridges`, `interview-pipeline`, `sprite-atmosphere`, `visual-refinement`, `wiring`, `world-alive`, `campaign-engine`, `dungeon-crawl`, `first-five-seconds`).
- **March 31 – April 13:** `feat/performance-and-polish`, `feat/membrane-module`, `feat/bio-lighting`, `feat/outdoor-biome`, `feat/render-manifest`, `backup-pre-cleanup` — the chunky feature branches that fed into the main timeline before `feat/loop-completion`.
- **April 26 (most recent):** `feat/heads-up-refinement`, `iso-camera` — last branches before the loop-completion era.
