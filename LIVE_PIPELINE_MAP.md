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
- `core/systems/encounter_session.py` — encounter logic, effect dispatch with param schemas
- `core/systems/encounter_resolver.py` — dialog/action resolution tables
- `core/systems/expedition_engine.py` + `expedition_data.py` — biome-agnostic expedition framework
- `core/systems/ambient_life.py` — creature spawn + behaviors
- `core/systems/spatial_wake.py` — wake-set / chain logic
- `core/systems/tension_cycle.py` — TensionCycle hibernate-pool

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

## Legacy (Panda3D-era — DO NOT treat as live targets)

These files predate the Godot pivot. Only `make cavern` (and a few unused targets) reach them. Refactoring their internals does not affect the live pipeline.

- `cavern.py` — 94KB, Panda3D `ShowBase`. Last edit 2026-04-03. Has 13 `if biome ==` conditionals; pre-2026-04-26 audit flagged for `BIOME_REGISTRY` refactor — skipped because legacy.
- `core/systems/cavern_builder.py`
- `creation_lab.py`
- `dungeon.py`
- `FirstLight.py`
- `room_lab.py`
- `shadowbox_dungeon.py`
- `simulation_theater.py`
- `SimulationRunner.py`
- `template_viewer.py`
- `sanctum_terminal.py`

These files import `direct.showbase.ShowBase` or `panda3d.core` directly. They are launchable via specific `make` targets but no longer share state with `brain_server.py` or the Godot viewer.

### Archived docs (Phase 1 reconciliation 2026-04-26)

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
