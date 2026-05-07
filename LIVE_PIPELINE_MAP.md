# Live Pipeline Map

**Read this before auditing, refactoring, or spawning subagents on this repo.**

The project pivoted from Panda3D rendering to a Python-brain → Godot-4.4-viewer architecture. Several pre-pivot files survive because legacy `make` targets still launch them. Treating those as live targets produces zero-leverage refactors. This file is the boundary.

---

## Live architecture (the pipeline that runs the game)

```
config/kind_config.json   ──┐
config/encounters.json    ──┤
core/systems/biome_data.py──┤
core/systems/stamp_world.py──┤
core/systems/...            ──┘
                              │
                              ▼
                       brain_server.py  ── TCP :9877 ──▶  godot/main.gd  (Godot 4.4 viewer)
```

### Live files (current pipeline reads these)

**Brain (Python, runs the world):**
- `brain_server.py` — TCP server, manifest assembly, per-frame loop
- `core/systems/biome_data.py` — `BIOME_REGISTRY` single source for biome config
- `core/systems/kind_config.py` — reader for `config/kind_config.json` (shared with Godot)
- `core/systems/kind_config_schema.py` — kind_config validator
- `core/systems/stamp_world.py` — pure-function world gen (`(seed, x, y) → entities`)
- `core/systems/encounter_session.py` — encounter logic, effect dispatch with param schemas (transitive deps: `encounter_engine.py`, `encounter_resolver.py`, `actor.py`, `encounter_config.py` — all live)
- `core/systems/expedition_engine.py` + `expedition_data.py` — biome-agnostic expedition framework
- `core/systems/spatial_wake.py` — wake-set / chain logic
- `core/systems/tension_cycle.py` — TensionCycle hibernate-pool, fully wired in brain_server
- `core/systems/spectrum.py` — per-biome hue drift (carved out of legacy ambient_life.py specifically to leave panda3d off the brain hot path)
- `core/systems/state_events.py` — universal player-feedback primitive
- `core/systems/activity_loop.py` — universal "what is the player doing" substrate (PR 9+10, on `feat/make-brain-ping-pong` branch)
- `core/systems/reflective/` — engagement primitive (HP=0 routing, fridge UI)
- `core/systems/consequences/` — effects + tick + hp_zero routing
- `core/systems/quests/` — async quest substrate
- `core/systems/journal/lexicon.py` — Permanent Objects journal (gensim/spaCy, parser_version regen)

**Godot (GDScript, renders the world):**
- `godot/main.gd` — viewer client, MultiMesh batching, manifest consumption
- `godot/kind_shader.gdshader` — per-kind shader (spatial wave motion, distance fade)
- `godot/ground.gdshader` — ground plane shader

**Exporters (offline manifest→disk path):**
- `godot_export.py` — JSON manifest exporter for the static-file path
- `renderer_bridge.py` — wgpu native-renderer bridge

**Configs:**
- `config/kind_config.json` — entity render/scale/color/recipe single source
- `config/encounters.json` — encounter postures, dialog verbs, paths, effects
- (Godot symlinks `kind_config.json` so the same file feeds both readers.)

### Live `make` targets

```
make brain          # Python brain, outdoor biome (default live test path)
make brain-cavern   # Python brain, cavern biome
make godot-export   # build static manifest.json for Godot to read
```

---

## Legacy (Panda3D-era — ARCHIVED 2026-05-07 audit A14)

All Panda3D-era files moved to `docs/archive/panda3d/`. The live pipeline (brain_server + vector terminal) is now panda3d-free in `core/systems/` and at root.

- **Source modules** in `docs/archive/panda3d/`: `ambient_life.py`, `atmosphere_engine.py`, `avatar_pipeline.py`, `billboard_renderer.py`, `biome_renderer.py`, `biome_scene.py`, `cavern_builder.py`, `consolidation.py`, `corridor_scene.py`, `door_animator.py`, `dungeon_grid.py`, `entity_template.py`, `glow_decal.py`, `lab_environment.py`, `postprocess.py`, `scenario_chain.py`, `scenario_engine.py`, `scenario_runner.py`, `shadowbox_scene.py`, `sprite_renderer.py`, `terrain_generator.py`
- **Top-level entries** in `docs/archive/panda3d/top_level/`: `cavern.py`, `creation_lab.py`, `dungeon.py`, `FirstLight.py`, `main.py`, `room_lab.py`, `shadowbox_dungeon.py`, `simulation_theater.py`, `SimulationRunner.py`, `template_viewer.py`
- **Bound tests** in `docs/archive/panda3d/tests/`: `test_atmosphere.py`, `test_avatar_pipeline.py`, `test_campaign_engine.py`, `test_design_key.py`, `test_door_animator.py`, `test_dungeon.py`, `test_entity_template.py`, `test_fetch_quest.py`, `test_glow_decal.py`, `test_postprocess.py`, `test_scenario_runner.py`, `test_session_boundary.py`, `test_shadowbox_scene.py`, `test_sprite_renderer.py`, `test_terrain.py`, `test_tick_efficiency.py`, `test_z_biome_scenes.py`

`sanctum_terminal.py` was **not archived** — it's a real headless ASCII alt-client (pure-Python, no panda3d, walks brain stamp_world directly). Reachable via `make terminal` / `make terminal-inline`.

### Still in `core/systems/` despite legacy-only callers (deferred to A10)

These don't import panda3d but their existing consumers were exclusively legacy: `combat.py`, `combat_session.py`, `attack_lib.py`, `crafting_engine.py`, `crafting_integration.py`, `material_system.py`, `interaction_engine.py`, `encounter_builder.py`, `campaign_engine.py`, `dungeon_campaign.py`, `session_boundary.py`, `grace_handler.py`. Disposition pending the `design_creature_engagement_v1` spec (audit A8 / A10).

### Pre-existing archived docs (Phase 1 reconciliation 2026-04-26)

- `docs/archive/panda3d/REFACTOR_PLAN.md` — Panda3D god-object decomposition plan
- `docs/archive/panda3d/VISUAL_LANGUAGE.md` — register/biome taxonomy from Panda3D era
- `docs/archive/panda3d/MATHEMATICAL_FOUNDATION.md` — 7/60/1 numerology + Panda3D code citations

---

## Rules for agents

1. **Before recommending a refactor, confirm the target is in the "Live files" list above.** If it imports `direct.showbase.ShowBase` or `panda3d.*`, it is legacy.
2. **`if biome ==` branches in legacy files do not count as audit findings.** They reach lookups in `biome_data.py` that the live brain already consumes via `BIOME_REGISTRY`. Refactoring legacy lookup sites is motion.
3. **`kind_config.json` and `BIOME_REGISTRY` are the canonical config sources.** New per-kind behavior goes in `kind_config.json` with a schema entry. New per-biome behavior goes in `BIOME_REGISTRY`.
4. **The brain → Godot wire format is JSON-line over TCP** (`brain_server.py:1360` ish). Manifest serialization changes need both ends.
5. **Performance claims need measurement, not citation.** The 22-25ms multimesh-rebuild "spike" was unverified for sessions; when measured it turned out to be 4.20ms max with high frequency. Frequency matters, not magnitude. Wire `PERF_LOG_ENABLED = true` in `main.gd` and read the heartbeats.

---

*Last updated: 2026-04-26 — created at the close of the force-multiplier audit session.*
