# SANCTUM TERMINAL
### Sovereign Architect — Living Development Log

---

## PHILOSOPHY

Humans are biological logic and execution engines — we analyze, adapt,
and execute. Each of us runs a base OS with exchangeable, customizable,
adaptable thought and behavior modules. We share a perceived reality
but experience it through entirely unique 1:1 perception filters:
belief systems, moral code, trauma response, physical capability.

Current economic systems ignore this. A system built for profit
extraction cannot produce equity — its purpose IS its output.
A gun built for destruction cannot be a peacekeeping tool.

The alternative: measure a sustainable economy by two variables.

  Speed of information:  request ↔ response latency
  Energy to satisfy it:  calories, joules, cognitive load

The balance between those two = sustainable value exchange.
Not profit. Not markets. Throughput efficiency of human needs.

Sanctum Terminal models this — passively, invisibly, under the hood.
The player never sees the math. They feel the world respond to it.

---

## WHAT THIS GAME IS

A procedural RPG engine seeded by real life. Your inputs become the world.
The more you put in, the richer and more complex your experience becomes.
No permadeath. No fixed skill trees. No prescribed story.
The world mirrors you — then gamifies it.

Scope is contained by traditional turn-based RPG structure.
The philosophy lives inside that container, not on top of it.
Dragon Quest holds the frame. The rest fills it.

---

## DESIGN INFLUENCES

| Influence | What We Take |
|---|---|
| Persona / Dragon Quest | Calendar structure, social sim, turn combat |
| Wildermyth | Organic skill emergence from what you actually do |
| Reincarnated as a Slime | Absorption/mutation — skills combine unexpectedly |
| No Man's Sky | Open exploration, make-your-own-fun |
| Cyberpunk 2077 / Shadowrun | Aesthetic, tone, wearable tech interface |
| Fallout | Traversal feel, world responsiveness |
| Octopath / YIIK / Anno Mutationem | Visual target — bold, lo-fi, neon, intentional PS1/PS2 |

---

## PASSIVE SYSTEMS (under the hood)

These run silently. The player never sees raw values.
Communication happens through atmosphere, not metrics.
Numbers surface only when the player deliberately consults
the wearable terminal for a specific operation.

**Information/Energy Balance (ObserverSystem)**
- `move_delta_mag` = information request velocity
- `heat` = energy expenditure — accumulates with activity, dissipates at rest
- `resolve_scout` = transaction validator — can current capacity handle this request?
- Sensors nominal = operating within capacity (equity)
- Sensors degraded = overextended (exploitation / burnout)
- World response: fog density, shader intensity, encounter difficulty, terminal latency

**Volume / Information Density**
- Each location has a deterministic `loc_key` (adler32 hash of position)
- Data spires = information density at that coordinate
- Gold spires = high-value information nodes (rare, emergent)
- Biome temperature/moisture = continuous perception shift across information space

**Character as Economic Model**
- `impact_rating` = caloric/cognitive cost of a real-world commitment
- `vibe` = perception filter applied by this specific human
- `archetypal_name` = the information request itself
- Skills are temporary and permanent stat modifiers until criteria are satisfied
- Skill mutation = emergent recombination, not a fixed upgrade tree

---

## GAME VISION

**Player is fixed at `0,0,0` — the world moves through them.**
Biome atmospheres and encounters pass over the player based on
real-world context and quest state. Location doesn't change map
coordinates — map coordinates change to reflect location.

**Character generation:**
You start at your current age as your level.
The interview answers shape what those levels already built.
Natural attributes + learned skills + inherited skills + morphing skills.
Real-time mirror — if it's day, you're playing in daylight.
If it's raining, it's raining in the game.

**HUD:**
Minimal ambient layer — health, biome state, active quest pulse.
Wearable terminal (Pip-Boy / hand terminal style) on demand.
Main viewport + minimap minimum.

**No permadeath.**
You don't die in real life until you actually do.

---

## PERMANENT OBJECTS / QUEST ENGINE

Relics are real life inputs:

| Field | Meaning |
|---|---|
| `archetypal_name` | The information request — what this commitment is |
| `vibe` | Perception filter — how it feels to this specific person |
| `impact_rating` | Energy cost (1–10) — cognitive/caloric weight |

Impact tiers scale atmosphere intensity, rotation speed,
and encounter density simultaneously:

| Rating | Tier | World Response |
|---|---|---|
| 1–3 | Surface | Ambient, atmospheric, low stakes |
| 4–6 | Dungeon | Structured challenge |
| 7–10 | Boss | Major zone, alters overworld |

---

## ARCHITECTURE
```
REAL WORLD                         GAME WORLD
──────────────────────             ──────────────────────────
Interview pipeline    ──┐
Weather API           ──┤──► QuestEngine ──► BiomeRegistry ──► VoxelFactory ──► FirstLight
GPS / location        ──┤         │
Time of day           ──┤         └──► vault.db (relics / quest objects)
vault.db (finances)   ──┘

ObserverSystem runs passively beneath all of the above.
Heat / throughput balance informs atmosphere without surfacing to the player.
```

**Resolution order for every voxel state:**
1. QuestEngine override (boss tier forces biome)
2. ObserverSystem modifiers (heat/throughput adjusts atmosphere)
3. BiomeRegistry noise fallback (temperature + moisture)

---

## DEV ENVIRONMENT

| Component | Detail |
|---|---|
| Machine | MacBook Pro 14" 2023, M2 Pro, 16GB RAM |
| OS | macOS Tahoe 26.3.1 |
| Display | 50" 4K 3840x2160 |
| IDE | VS Code + Claude Code extension |
| Python | 3.12.13 (Native ARM64) |
| Engine | Panda3D + Pygame |
| Linting | Trunk — ruff, bandit, isort, trufflehog, shellcheck |
| Tests | pytest 9.0.2 |
| GPU | Apple M2 Pro — Metal backend, no CUDA |
| Dependency mgmt | .venv — always activated before any command |
| Security | Atomic SQLite transactions, absolute path resolution |

---

## FINANCIAL SNAPSHOT

| Reserve | Amount | Status |
|---|---|---|
| Aegis Shield | $10,000.00 | Untouchable stability floor |
| Liquid Cache | $5,700.00 | Available for relic acquisition |

Asset sync: `tools/importer.py` · `data/vault.db`

---

## PROJECT STRUCTURE
```
sanctum-terminal/
├── config/
│   └── manifest.json          # All tunable values — no magic numbers in code
├── core/
│   ├── engine.py              # SanctumTerminal — main coordinator
│   ├── input_handler.py       # WSAD + process_input + AutoPlay interface
│   ├── vault.py               # Runtime cache + SQLite sync
│   ├── viewport.py
│   └── systems/
│       ├── biome_registry.py  # 10x biomes, quest-gated
│       ├── observer.py        # ObserverTask → ObserverSystem (pending)
│       ├── quest_engine.py    # THE HEARTBEAT — global state authority
│       └── volume.py          # Information density + voxel hydration
├── data/
│   ├── live_assets/           # Processed, manifest-indexed assets
│   └── vault.db               # SQLite — relics + quest state
├── exports/                   # Raw vmax / obj exports
├── infra/
│   └── loader.py              # SystemLoader — asset scanning + dispatch
├── tests/
│   ├── test_active_pipeline.py
│   ├── test_biome_stack.py
│   ├── test_interactions.py
│   ├── test_quest_engine.py   # 35 contracts — QuestEngine
│   ├── integration/
│   └── unit/
│       ├── test_input.py      # 21 contracts — InputHandler
│       └── test_observer.py   # BLOCKED — pending ObserverSystem
├── tools/
│   ├── daemon.py
│   └── importer.py
├── utils/
│   └── VoxelFactory.py        # QuestEngine-first biome state
├── FirstLight.py              # Panda3D ShowBase — renderer + inject_relic
└── SimulationRunner.py        # Headless test harness + AutoPlay interface
```

---

## INFRASTRUCTURE STANDARDS

- No magic numbers in code — all values from `config/manifest.json`,
  DB, or derived calculation
- Full files or method swaps only — no granular snippets
- TDD — tests written red before implementation
- `trunk check` clean before any commit
- All classes injectable — accept `db_path`, `config`, `quest_engine` as params
- Parametrize test fixtures — no hardcoded dicts
- Metal-compatible shaders only — `setShaderAuto()` via Panda3D
- Passive systems stay passive — philosophy under the hood,
  never surfaced unless deliberately consulted
- Always run inside `.venv`
- File writes via `python3 << PYEOF` when VS Code paste fails

---

## REFACTOR MAP

- ✅ Phase A: DB moved to `/data`
- ✅ Phase B: Logic moved to `core/` · tools in `tools/`
- ✅ Phase C: Game code isolated from infra
- ✅ Phase D: Modular systems — QuestEngine, BiomeRegistry, VoxelFactory
- ⏳ Phase E: Config-driven values — `config/manifest.json` expansion
- ⏳ Phase F: ObserverSystem — port from legacy, wire into passive layer
- ⏳ Phase G: Interview pipeline — in-world wearable terminal
- ⏳ Phase H: Skill system — absorption, mutation, character seed

---

## SESSION LOG

### 2026-03-26 — Session 1: The Heartbeat
**Baseline:** 0/7 tests passing (collection errors)
**Closed:** 59/61 passing (2 remaining: headless camera)

**Delivered:**
- `core/systems/quest_engine.py` — 35 contracts green
- `core/systems/biome_registry.py` — 10x biomes, quest-gated
- `utils/VoxelFactory.py` — QuestEngine-first, asset pipeline
- `core/vault.py` — SQLite sync added
- `core/input_handler.py` — mapping, active_keys, process_input
- `tests/unit/test_input.py` — 21 contracts green
- `SimulationRunner.py` — headless-safe, loop decomposed
- `FirstLight.inject_relic` — RelicDict + legacy string support
- `conftest.py` — Panda3D singleton teardown fixed
- `trunk` — all new files clean
- `README.md` — living project bible established
- Philosophy integrated — information/energy balance model documented
- Legacy `ObserverSystem` and `Volume` identified as
  existing implementations of the economic model

**Deferred to Session 2:**
- SimulationRunner headless camera → 61/61
- `config/manifest.json` — config-driven values (P1)
- `AutoPlayController` stub (P2)
- `ObserverSystem` port from legacy (P3)
- Interview pipeline (P4)
- Skill system schema (P5)

---

*Append a new session block after every milestone.*
*Format: date · baseline · closed · delivered · deferred.*