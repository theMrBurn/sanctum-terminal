# spec: kitbash / greeble procedural-asset subsystem

**Status:** DRAFT — prep / not yet ratified. Inventory + fork-locking done (this is the
"draft the spec before code" step). 2026-07-28.
**Host:** `sanctum-nethack/` (peers Pickup/Interaction/Scenario/Encounter/Vault in `core/systems/`
+ `core/vault.py`). *Naming tangle:* this project's `pyproject.toml` names the package
`sanctum-terminal`; a separate `sanctum-terminal/` dir also exists — the peers pin the home here.

---

## Decisions locked (asked + answered)

1. **Architecture: HYBRID — a renderer-agnostic assembly CORE + two backends.** Build the assembly
   *logic* once (socket CSP + signal-driven selection + reproducibility ledger); it produces a
   renderer-independent `AssemblyResult`. Two backends consume it:
   - **Wireframe backend (LIVE, build first):** greebles = registered `WireframeMesh` primitives
     socket-composed onto a base, emitted to the **vector terminal** (the live surface). Reuses the
     two active prior-art specs (below) — no duplication.
   - **Blender→glTF backend (CAPABILITY, dormant Godot):** the max-capability path, built via the
     Blender **binary** headless (Decision 3), feeding the paused Godot client.
2. **Provenance: reconciled, not "all-in-vault."** The original all-in-vault call is superseded by the
   hybrid: **PARTS provenance reuses the existing wireframe pipeline** (`config/wireframe_meshes.json`
   registry + per-mesh `provenance.json` sidecars — do NOT re-implement in vault); the **ASSEMBLY
   ledger** (which combination was assembled) is the one new piece and lives in **`vault`** as a
   deterministic `provenance_hash` table — renderer-agnostic, so ONE ledger serves both backends.
3. **Blender = the BINARY, not `pip bpy`.** Drive headless: `blender --background --python assemble.py`.
   Verified present: **Blender 4.5.12 LTS, headless `bpy` runs, official glTF exporter available**
   (`bpy.ops.export_scene.gltf`). Rationale: the `pip bpy` wheel is pinned to Python 3.11 (host is
   3.12) and is Python-only (Julia can't call it); the binary is host-Python-independent and invokable
   identically from Python (`subprocess`) and Julia (`run`). Reuse Blender's exporter or the existing
   hand-rolled `tools/export_glb.py`.

## Premise corrections (the brief was written against infrastructure that isn't there)

- **No `panda3d-gltf`.** `tools/export_glb.py` hand-rolls a glTF binary writer (Panda Y-forward →
  glTF Y-up). The brief's "export via panda3d-gltf" is false; use the Blender exporter or that file.
- **No `bpy`/Blender existed before this task** (`core/systems/blender.py` is a *"World Blender"*
  compositor, unrelated). Now installed as a binary (Decision 3).
- **`Entropy`/`Atmosphere` are nodes** (`EntropyEngine`/`AtmosphereEngine`), backed by
  `core/systems/{entropy,atmosphere}_engine.py`; signals like `entropy_jitter` are what selection reads.
- **signal_map nodes are DOCUMENTATION, not a router.** Verified: `placement_engine.py` reads only
  `data["placement_engine"]["object_categories"]`; nothing in Python reads `nodes`/`connections`/
  `emits`/`consumes`. Declaring `KitbashEngine` auto-wires nothing — **Persona C wires the signal flow
  by hand** (trace how a live consumer receives entropy/atmosphere values and mirror it). Still declare
  the node in the canonical signal_map for doc-consistency (guarded by `tools/signal_map_sync.py`).
- **signal_map single source of truth = `sanctum-nethack/config/signal_map.json`** (the three POC
  copies were byte-identical across three repos; `tools/signal_map_sync.py` guards them: `--check`
  default, `--write` to reconcile).

## Prior art this REUSES (do not duplicate — both active, both for the live wireframe surface)

- **`spec_open_source_primitive_pipeline.md`** — CC0 ingest (Kenney/Quaternius — the brief's sources),
  the `config/wireframe_meshes.json` name→path registry, per-mesh `provenance.json` sidecars (license +
  edit-log, reproducible), edit primitives (recenter/rescale/axis_swap/merge/decimate), the
  `tools/import_obj.py` CLI + validation (license hard-fail). **This IS the wireframe parts library.**
- **`spec_workroom_primitives.md`** — the wireframe primitive set + mesh-edit op-log + seed composition
  (`corner_l` = two cubes glued). **This is the wireframe backend's socket-composition substrate.**

---

## Architecture

```
KitbashCore   (renderer-agnostic · pure Python · deterministic)
  sockets      named attach points on a base = (type, scale_class)
  CSP          per socket, query parts compatible by type + scale  → candidate set
  selection    EntropyEngine/AtmosphereEngine state → weight        (hi entropy = scavenged/mismatched;
                                                                     stable = uniform) — seeded, no bare RNG
  → AssemblyResult = { base_id, [(socket, part_id)], signal_snapshot }
  ledger       vault.assemblies : provenance_hash = sha256(base:sorted_parts:sockets:signal)[:16]
                                  INSERT OR IGNORE  → reproducible-from-ledger (the acceptance bar)
        │
        ├─►  WireframeBackend  (LIVE, first)   parts = registered WireframeMesh (prior-art registry +
        │                                       provenance.json); compose via seed/edit-op model →
        │                                       vector terminal
        └─►  BlenderBackend    (CAPABILITY)    parts = OBJ/mesh; socket-detect on Blender empties /
                                               vertex groups; instance + decimate; glTF export via the
                                               Blender binary → Godot (dormant)
```

## 1. The core (renderer-agnostic) — `core/systems/kitbash_engine.py`

- `class KitbashEngine` (peer to `InteractionEngine`, `EncounterEngine`). Pure logic; **no renderer,
  no bpy import** — fully unit-testable headless.
- **Socket model:** a base declares named attach points `(name, socket_type, scale_class)`. Backend-
  neutral: a wireframe base names them in data; a Blender base carries them as empties/vertex groups
  (`SKT_<type>_<n>`), detected by the Blender backend and normalized to the same tuple.
- **CSP (not scatter):** for each socket, select parts whose `socket_types` ∋ the socket type AND
  `scale_class` compatible → candidate set; reject incompatible pairs (the test's rejection case).
- **Selection:** a pure function of the consumed signal state (§3) + a seed; high entropy biases
  cross-category "scavenged/mismatched", stable biases uniform same-kit. Any tie-break RNG is seeded
  from signal/seed so the hash reproduces the exact assembly. No bare `random()`.
- **Ledger (vault):** `assemblies` table in `vault._ensure_schema()`, matching vault idioms
  (`CREATE TABLE IF NOT EXISTS`, `provenance_hash TEXT UNIQUE NOT NULL`, `INSERT OR IGNORE`).
  `provenance_hash = sha256(f"{base_id}:{sorted_part_ids}:{socket_bindings}:{signal_snapshot}")[:16]`
  — time-free (NOT `ScenarioEngine._hash()`, which mixes `time.time()` and is "useless for replay").
  **Reproducible-from-the-ledger-entry-alone is the acceptance bar**, not visual output. One ledger
  serves both backends (it records part IDs + sockets, renderer-agnostic).

## 2. Parts provenance (reuse, per backend — see Decision 2)

- **Wireframe parts:** the existing `config/wireframe_meshes.json` registry + `provenance.json`
  sidecars (`spec_open_source_primitive_pipeline.md`). License metadata (CC0 source/url/credit) and
  append-only/edit-log discipline already live there — **reuse, don't fork into vault.**
- **Blender/3D parts:** deferred with the Blender backend (dormant consumer). When built, mirror the
  same registry+sidecar shape (or a vault `parts` table) — decide then, not now.
- Import tooling **refuses a part missing license metadata** (image_scan's "refuse over guess", already
  the prior-art rule).

## 3. Signal-driven selection (wired BY HAND — no auto-router)

`KitbashEngine` consumes `EntropyEngine`/`AtmosphereEngine` signals (e.g. `entropy_jitter`).
Since no loader auto-routes signal_map nodes, Persona C **wires this in Python**: trace how a live
consumer obtains those values today and pass them in. Record the signal snapshot in the ledger so
selection is reproducible from it. Declare the `KitbashEngine` node in the canonical signal_map (docs).

## 4. Backends

**Wireframe (LIVE, first):** consume `AssemblyResult` → resolve each part to a registered
`WireframeMesh` → socket-compose onto the base via the seed/edit-op composition model
(`spec_workroom_primitives.md`) → emit to the vector terminal. No new render code — reuses the
wireframe renderer + registry + edit primitives. This is where kitbash first becomes *visible*.

**Blender→glTF (CAPABILITY):** `blender --background --python assemble.py -- <AssemblyResult>` →
detect sockets (empties/vertex groups) → instance the chosen greebles → decimate → export glTF (the
official exporter, or `tools/export_glb.py`). Headless; feeds dormant Godot. Mind the Panda/Blender→
glTF axis convention (see tests).

## 5. Persona decomposition (for the build orchestrator)

- **A — the core + vault assembly ledger.** Socket model, CSP, `AssemblyResult`, `provenance_hash`,
  `assemblies` DDL in `_ensure_schema()`, INSERT OR IGNORE, round-trip reproduce. Pure Python, no
  renderer. (sanctum-architect / data-layer.)
- **B — wireframe backend (LIVE).** `AssemblyResult` → registered `WireframeMesh` socket-composition
  via the prior-art registry/provenance/edit-primitives → vector terminal. (render-engineer.)
- **C — signal integration (by hand).** Entropy/Atmosphere → selection weighting in Python; declare the
  `KitbashEngine` node in canonical signal_map. (sanctum-architect.)
- **D — Blender→glTF backend (CAPABILITY, parallelizable/deferrable).** bpy-binary socket-detect,
  instance, decimate, glTF export. (render-engineer — owns the mesh path.)

Build order: **A → B → C** first (a live, reproducible wireframe result), **D** in parallel or after
(the capability path for dormant Godot).

## 6. Tests (TDD, per project convention)

- **pytest; headless mandatory** — `conftest.py` forces `window-type none` + null audio and tears down
  the Panda3D `base` singleton (autouse). Blender-backend tests shell out to the binary headless.
  (pytest is NOT a declared dep in nethack's `pyproject.toml` — ambient `.venv`.)
- **Core determinism / reproducibility (acceptance bar):** fixed base + fixed signal snapshot + fixed
  parts snapshot → deterministic `AssemblyResult`, **reproducible from the ledger entry alone** (re-run
  from the row → identical parts + bindings + hash). Renderer-agnostic → tested without any backend.
  Tag `TEST`; the schema add is a `MIGRATION` (old vault loads after the bump).
- **Compatibility rejection:** socket/greeble matching rejects incompatible type/scale pairs — against
  a **small fixture parts table**, not the full library.
- **Coordinate cross-reference (AGENTS.md line 27):** the Blender-backend axis conversion must pin
  *both* sides of the convention (two silent coordinate bugs shipped here before this rule).

## 7. Hard-rule compliance

- **Air-gap / no-LLM-in-production:** bpy + SQLite + wireframe are deterministic — compliant; keep the
  `openai|anthropic|gpt|claude` grep clean.
- **No hardcoded tunables:** entropy thresholds, scale bands, decimation ratios → named consts at file
  top (AGENTS.md line 18). **Single-source-of-truth:** scale/category recipes in the config idiom.

## 8. Open risks

1. **Blender install — DONE + verified** (4.5.12 LTS, headless, glTF exporter). No longer a blocker.
2. **~~signal_map auto-wiring~~ RESOLVED** — declarative, not a router; Persona C wires by hand.
3. **~~Prior-art conflict~~ RESOLVED** — hybrid reuses the wireframe pipeline for parts; vault holds
   only the new assembly ledger.
4. **Blender-parts registry deferred** — the 3D backend's parts library is unspecified until Godot
   revives (accepted; wireframe backend leads).
5. **How live consumers obtain entropy/atmosphere values** — Persona C must trace this before wiring
   (the one remaining code-reading unknown; not user-blocking).

## Build status (2026-07-28) — COMPLETE

All in-scope layers built + independently verified (every test run by the orchestrator, not just
self-reported). 30 kitbash tests + 85 wireframe tests + 45 vault tests green; full suite collects 3012.

- **A — core + vault ledger** ✅ `core/systems/kitbash_engine.py`, `assemblies` table.
- **B — wireframe backend (LIVE)** ✅ `kitbash_wireframe_backend.py`; wires to the real terminal path
  via `wireframe_edits.replay` (`replay == compose` asserted).
- **C — signal wiring** ✅ `kitbash_signals.py`; injects the live `AtmosphereEngine`
  (`entropy_jitter` → selection); `KitbashEngine` node in the canonical signal_map.
- **D — Blender→glTF backend (CAPABILITY)** ✅ `tools/kitbash_assemble.py` + `kitbash_blender_backend.py`;
  produces a real `.glb` (Blender 4.5.12 binary, headless), axis convention pinned off-disk.
- **E — wireframe ingestion registry** ✅ (the dependency B assumed) `wireframe_mesh.py` (`resolve_mesh`/
  `get_registered`/OBJ writer), `wireframe_ingest_edits.py` (6 edit primitives), `tools/import_obj.py`
  (CC0-license-gated ingest + `provenance.json` sidecars), `config/wireframe_meshes.json`.
- **B↔E rewire** ✅ `registered_parts()`/`all_parts()`/`meshes_for()`/`scale_map()` — a real ingested
  mesh is greebled end-to-end (`tests/test_kitbash_registry_greeble.py`: ingest → registry → part →
  assemble → compose → terminal-ready op-log), self-cleaning.

**Remaining = the two brief-excluded items only:** sourcing/curating a real greeble art library (the
pipeline is proven with a synthetic fixture; real CC0 assets are unsourced), and sprite/banner
extraction (reuse the 7-layer banner mandate + `tools/sketch_to_sprite.py`). Also: the *live* vector-
terminal RENDER was proven via the `replay == compose` seam, not executed against a running client.

## Out of scope (per brief)

Sourcing/curating the initial parts library; sprite/banner extraction (reuse the 7-layer banner
mandate + `tools/sketch_to_sprite.py` once this exists).
