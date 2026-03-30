# SANCTUM TERMINAL — Refactor & Base-7 Audit

## Current State

**~15,000 lines** across core + tests + root modules
**718 tests** passing
**26 system modules** in core/systems/
**4 root-level apps** (creation_lab, main, room_lab, SimulationRunner)

---

## Problem 1: creation_lab.py is a god object (992 lines)

It owns: rendering, input, lighting, fog, HUD, environment building,
compound spawning, biome cycling, register cycling, interaction state
callbacks, encounter callbacks, pickup callbacks, crafting, scenario
creation, activity inference, fingerprint ticking, blend refresh,
glow pulse, floating labels, camera clamping, mouse look.

**That's 19 responsibilities in one file.**

### Extraction plan:

| Extract to | Lines | What moves |
|------------|-------|-----------|
| `core/systems/lab_environment.py` | ~120 | `_build_environment()`, `_apply_environment_register()`, `_update_lighting()`, `_update_fog()`, `ENVIRONMENT_REGISTERS` |
| `core/systems/lab_hud.py` | ~50 | `_update_hud()`, HUD text creation |
| `core/systems/lab_controls.py` | ~40 | `setup_controls()`, `update_key_map()`, mouse look |
| `core/systems/compound_spawner.py` | ~100 | `_spawn_compound()`, `_rebuild_compounds()`, `_load_compounds()` |
| Move glow + labels | ~60 | `_on_interaction_state()`, `_create_label()`, `_glow_pulse_task()` already belong in InteractionEngine callbacks |

**Target:** creation_lab.py drops to ~300 lines (init + game loop + delegation).

---

## Problem 2: SimulationRunner.py has two classes in one file (337 lines)

`Simulation` (the headless game loop) and `ScenarioRunner` (the test harness)
share a file. They should be separate.

### Extraction plan:

| Extract to | What moves |
|------------|-----------|
| `core/systems/simulation.py` | `Simulation` class |
| `core/systems/scenario_runner.py` | `ScenarioRunner` class |

`SimulationRunner.py` becomes a thin entry point or is deleted.

---

## Problem 3: Four root-level apps with duplicated patterns

`creation_lab.py`, `main.py`, `room_lab.py`, `SimulationRunner.py` all:
- Create a ShowBase
- Set up camera, lighting, input
- Run a game loop
- Duplicate movement code

### Fix:

Extract shared patterns into `core/app_base.py`:
- Camera setup (FOV, position, mouse look)
- Movement (WASD + clamping)
- Lighting boilerplate
- Game loop skeleton

Each app becomes a thin subclass.

---

## Problem 4: Dead code in core/attic/ still imported

| File | Imported by | Status |
|------|------------|--------|
| `biome_registry.py` | `utils/VoxelFactory.py` | Active (utility) |
| `spawn_engine.py` | `SimulationRunner.py` (fallback) | Semi-dead |
| `seed_engine.py` | Ignored test only | Dead |
| `observer.py` | Ignored test only | Dead |

### Fix:
- Delete `seed_engine.py` and `observer.py`
- Move `spawn_engine.py` fallback out of SimulationRunner
- Keep `biome_registry.py` until VoxelFactory is refactored

---

## Problem 5: Geometry functions in biome_renderer.py (414 lines)

`_make_box_geom`, `_make_wedge_geom`, `_make_spike_geom`, `_make_arch_geom`,
`_make_plane_geom`, `_noisy_color` are geometry utilities, not biome rendering.
They're imported by: biome_renderer, primitive_factory, creation_lab, tree_builder, biome_scene.

### Fix:

Extract to `core/systems/geometry.py`. Clean import path.
`biome_renderer.py` drops to ~80 lines (just BiomeRenderer class).

---

## Base-7 Math Audit

The design pins reference base-7 indirectly through the system architecture.
Current state of the 7-element patterns:

### 7 Primitive Types ✓
BLOCK, SLAB, PILLAR, PLANE, WEDGE, SPIKE, ARCH

### 7 matters that need auditing:

| System | Count | Target 7? | Status |
|--------|-------|-----------|--------|
| Primitive types | 7 | ✓ | Aligned |
| Biomes | 10 | No | Could be 7 primary + 3 transitional |
| Fingerprint dimensions | 20 | No | Could be 7 core + derived |
| Ghost profiles | 10 | No | Could be 7 archetypes + 3 hybrid |
| Encounter verbs | 5 | No | Could add CRAFT + OBSERVE = 7 |
| Scenario types | 5 | No | Could add DEFEND + TRADE = 7 |
| Visual registers | 4 | No | Could add 3 more = 7 |

### Recommendation:

Don't force base-7 where it breaks design. The primitives are naturally 7.
The other systems have their own logic for their counts. If base-7 matters
philosophically, here's what aligns naturally:

- **7 primitives** ✓ (already done)
- **7 encounter verbs**: add CRAFT (making) + OBSERVE (watching) to THINK/ACT/MOVE/DEFEND/TOOLS
- **7 scenario types**: add DEFEND (survive) + TRADE (exchange) to fetch/escort/hunt/key/switch
- **7 core fingerprint dimensions**: exploration, crafting, observation, combat, precision, endurance, social (derive the other 13 from these)

The rest (biomes, profiles, registers) serve different purposes and shouldn't be constrained to 7.

---

## Execution Order

1. **Extract geometry.py** (biggest import cleanup, most shared)
2. **Extract lab modules** (creation_lab → 300 lines)
3. **Split SimulationRunner** (two classes → two files)
4. **Delete dead code** (seed_engine, observer)
5. **Base-7 alignment** (verbs + scenarios if desired)

Each step is independently committable and testable.

---

## What NOT to refactor

- `encounter_engine.py` (286 lines) -- well-sized, clear responsibility
- `scenario_engine.py` (248 lines) -- same
- `fingerprint_engine.py` (114 lines) -- compact
- `ghost_profile_engine.py` (164 lines) -- compact
- `avatar_pipeline.py` (75 lines) -- tiny, clean
- `interaction_engine.py` (189 lines) -- well-bounded

These are the right size. Leave them alone.

---

_This plan is the contract. Execute in order. Test after each step._
