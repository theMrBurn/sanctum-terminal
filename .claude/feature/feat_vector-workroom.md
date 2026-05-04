# Feature — feat/vector-workroom

**Status:** PRs 1-5 SHIPPED 2026-05-02. PR 6 = user UAT in progress.
**Branch:** Lives on `feat/loop-completion` (sibling spawn deferred —
artifacts hold the truth per `feedback_artifacts_capture_arcs`).

## PR-by-PR ship log

| PR | Scope | Tests | Status |
|---|---|---|---|
| PR 1 | vault.world_seeds + brain seed_* commands + manifest emission | 35/35 (T1+T2) | ✅ |
| PR 2 | workroom biome at slot (-3,0) — flat 1m grid floor + single moon | smoke ✅ + M1 ✅ | ✅ |
| PR 3 | wireframe_edits.py op library + replay + seed_mesh_cache | 26/26 (T3) | ✅ |
| PR 4 | BUILD/PLACE FSM — TAB/SPACE/DEL/+/-/<>/RGB/[]/PgUp/PgDn | 19/19 (T4 PLACE) | ✅ |
| PR 4.5 | Tier 1 platforming kit — wedge / slab / stair built-ins | 9/9 | ✅ |
| PR 5 | BUILD/EDIT FSM — ENTER toggle, TAB/arrows/J/C/N/DEL/U mesh edits | 12/12 (T4 EDIT) | ✅ |
| PR 6 | UAT pass — author 5 mixed seeds, restart brain, verify S1-S3 | hands-on | 🟡 |

**Test totals:** 119/119 workroom-related green.

## Premise

A dedicated **clean-room biome slot** + **build mode** in the vector
terminal where the user can CRUD primitive instances by walking up to a
spot, picking a kind, placing it, **reshaping its mesh structure** by
bending edges + joining vertices + adding curves, and seeing results
in real time. All instances persist as **seeds** (with their structural
edits) in `vault.db` so authoring survives brain restarts and
accumulates across sessions.

V1 is about **structural mesh authoring**. Procedural skins and noise
patterns are V2. The user is bending wireframe wires and connecting
them at joints — that's the unlocked verb. RGB color is the only
shading control in V1.

This is also the **modding interface** half of `design_north_star`
(Phase 3 teaches modding) — the workroom is what's eventually surfaced.

## Decisions locked (the 6 open questions)

| # | Question | Locked answer |
|---|----------|---------------|
| 1 | Biome slot | `(-3, 0)` named `workroom`, mirrors shadow_lab pattern at `(-2, 0)`. |
| 2 | Wayfinding | **Debug teleport V1.** Organic path-from-spawn deferred. |
| 3 | Cursor metaphor | **XZ-plane cursor** (Fallout-style). Camera-forward raycast not in V1. |
| 4 | Grid snap | **1m placement grid V1.** Single value — nail one, then the dial for 6m / 41m / vertex-fine 0.1m comes after. |
| 5 | V1 authoring scope | **Structural mesh manipulation + RGB color.** Skin cycling and noise are V2. The verbs are *bend, join, curve, pattern* — not *skin*. |
| 6 | `B` outside workroom | ~~Silent no-op.~~ **REVISED 2026-05-02: BUILD is biome-agnostic.** Per `make brain-X` doctrine each biome is a UAT slice of the same shared system surface. BUILD now works in any non-empty biome; seeds persist keyed on the active biome. Workroom remains the canonical clean-room sandbox; cavern/outdoor become real authoring surfaces. The `biome_allows_build` helper stays as a per-biome opt-out hook for the future (e.g. encounter biomes). |

## Surface — single biome slot, two-key entry

- **Biome slot `(-3, 0)` named `workroom`** in `BIOME_REGISTRY`.
  Authored hand-built scene: flat ground, neutral 1m grid floor, no
  entities, single moon for orientation. Reachable V1 by debug
  teleport (`/teleport workroom` brain command, or whichever debug
  surface already exists for biome jumping — confirm during PR 2).
- **Key `B`** toggles BUILD mode while inside `workroom`. Outside,
  silent no-op.
- **Key `ENTER`** in BUILD mode toggles PLACE ↔ EDIT sub-modes on the
  current selection.

## Sub-mode FSM

```
walk → B → BUILD/PLACE ──ENTER──→ BUILD/EDIT
                ↑                       │
                └────────ENTER──────────┘
                ↑                       ↑
                B/ESC                   B/ESC
                ↓                       ↓
                walk                    walk
```

PLACE sub-mode = move cursor + drop primitives + select existing.
EDIT sub-mode = move/add vertices + add/remove edges + subdivide edges
on the currently-selected seed.

## Persistence model — vault.world_seeds with mesh-edit log

New table in `vault.db`. Named `world_seeds` to avoid collision with
the existing `user_seeds` table (lexicon category overrides — different
concept). Brain commands and manifest key remain `seed_*` / `seeds:` —
the disambiguation is internal-only.

```sql
CREATE TABLE IF NOT EXISTS world_seeds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    biome       TEXT    NOT NULL,                -- "workroom" V1, any biome later
    kind        TEXT    NOT NULL,                -- "wireframe_mesh" V1
    base_mesh   TEXT    NOT NULL,                -- "spire", "cube", … registry name
    pos_x       REAL    NOT NULL,
    pos_y       REAL    NOT NULL,
    pos_z       REAL    NOT NULL,
    yaw_deg     REAL    NOT NULL DEFAULT 0,
    scale       REAL    NOT NULL DEFAULT 1.0,
    color_r     REAL    NOT NULL DEFAULT 0.7,
    color_g     REAL    NOT NULL DEFAULT 0.7,
    color_b     REAL    NOT NULL DEFAULT 0.7,
    mesh_edits  TEXT    NOT NULL DEFAULT '[]',   -- ordered op-log, see §"Mesh-edit ops"
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_world_seeds_biome ON world_seeds(biome);
```

- `base_mesh` is a registry name (`spire`, `cube`, future Kenney imports).
- `mesh_edits` is a JSON array of edit ops applied in order to the
  base mesh at render time. **Append-only log = free undo (pop last)
  + replayable across migrations + diffable in a PR.**
- No `skin` / `params` columns V1. Add them when V2 lands.

Migration is idempotent ALTER TABLE per existing `_ensure_schema`
pattern in `core/vault.py`. No data migration needed (V1 ships empty).

## Mesh-edit ops (the structural verbs)

Each op is a pure function `(WireframeMesh, op_dict) -> WireframeMesh`.
New module `core/systems/wireframe_edits.py`. The op log replay is
deterministic — same base + same log = same final mesh.

| op               | payload                                  | verb                                            |
|------------------|------------------------------------------|-------------------------------------------------|
| `move_vertex`    | `{i: int, to: [x,y,z]}`                  | **bend** — relocate joint, adjacent edges flex |
| `add_vertex`     | `{at: [x,y,z]}`                          | drop a free joint not yet wired                |
| `add_edge`       | `{a: int, b: int}`                       | **join** two joints with a wire                 |
| `remove_edge`    | `{a: int, b: int}`                       | sever a wire (joints stay)                      |
| `subdivide_edge` | `{a: int, b: int, t: float}`             | **curve** — split a wire at fraction t,         |
|                  |                                          | adds midpoint vertex, edge becomes 2 edges      |

Out-of-scope V1: vertex deletion (orphan-vertex semantics get hairy —
defer until needed), face concept (we're wires not surfaces),
boolean ops, mirror, array. **Pattern** as a verb (the 5th in the
user's list — *bend, join, curve, pattern*) is reserved for V1.5 once
the four core verbs are nailed.

## Brain ↔ client contract

Four new commands to `brain_server.py` dispatch (matches the
`msg.get("cmd")` pattern at line 1649+):

| cmd            | payload                                                            | response                                  |
|----------------|--------------------------------------------------------------------|-------------------------------------------|
| `seed_create`  | `{biome, kind, base_mesh, pos, yaw, scale, color}`                 | `{ok, seed_id}` or `{ok: false, reason}` |
| `seed_update`  | `{seed_id, fields: {...partial...}}` (incl. `mesh_edits` whole list) | `{ok}` or `{ok: false, reason}`         |
| `seed_delete`  | `{seed_id}`                                                        | `{ok}`                                    |
| `seed_list`    | `{biome}`                                                          | `{ok, seeds: [...]}`                      |

For mesh edits, the client appends to `mesh_edits` locally and sends
the whole updated list via `seed_update`. Server replaces. Atomic per
edit. (Append-only log + full-replace write = simpler than per-op
deltas; the log is small.)

Brain emits seeds for the active biome in the **manifest** as a new key
`seeds: [...]` alongside existing `horizon_objects: [...]`. Vector
terminal renders them through the existing `_RENDERERS` dispatch. The
mesh-edit log is replayed against `base_mesh` on the client at render
time (caches per seed, invalidates on update).

## Input bindings (vector terminal, BUILD mode active)

### PLACE sub-mode
```
ESC          exit BUILD (B is repurposed to blue inside BUILD —
             use ESC to exit; B outside BUILD enters BUILD)
ENTER        toggle to EDIT sub-mode (requires a selected seed)
TAB          cycle base_mesh selection (cube → octahedron → pyramid → slab → spire → stair → tetrahedron → wedge)
ARROWS       move cursor on XZ plane, snapped to 1m grid
PgUp/PgDn    raise/lower cursor Y by 0.5m
SPACE        place a new seed at cursor → seed_create
SHIFT+SPACE  duplicate-and-nudge the selected seed
[ / ]        cycle selection through nearby seeds
+ / -        scale current selection ±10%
, / .        rotate current selection ±15° yaw (the unshifted < / > keys)
R G B        cycle red / green / blue channels of selection ±10%
             SHIFT+R/G/B reverses (decrement)
DEL          delete current selection → seed_delete
F5           force-flush vault    (V1: writes are sync, no-op)
F9           reload manifest      (V1: no-op; reserved)
```

### EDIT sub-mode (operating on the selected seed's mesh)
```
B / ESC      exit BUILD entirely
ENTER        return to PLACE sub-mode
TAB          cycle vertex selection within the seed (the "joint" cursor)
ARROWS       move selected vertex on XZ, 0.1m grid
PgUp/PgDn    move selected vertex Y by 0.1m  ← bend
J            "join" — start an edge from selected vertex; second TAB+J = add_edge
C            "curve" — subdivide selected edge (adds midpoint vertex)
N            add a new free vertex at cursor position
DEL          remove selected edge (must have edge selected, not vertex)
U            undo last mesh edit (pop last op from log)
```

Inputs not bound (`Q`, `E`, `1-9`, etc.) are reserved for V2.

## Renderer contract

- Seeds render via the existing `_RENDERERS` dispatch in
  `clients/vector_terminal/horizon_objects.py`. The `kind` key drives
  which renderer fires. V1 only ships `kind: "wireframe_mesh"`.
- Per seed: client maintains a cache `(seed_id, edits_count) → resolved_mesh`.
  When the manifest re-emits a seed with a different log length, cache
  invalidates and the log replays against `base_mesh`.
- Cursor rendering (PLACE): transparent ghost of selected primitive at
  cursor, `alpha=0.35`.
- Joint/edge cursor (EDIT): the selected vertex draws as a small bright
  cube (~0.15m); the selected edge highlights with a brighter color.
- HUD overlay (BUILD mode active):
  ```
  WORKROOM — BUILD/PLACE
  KIND   spire     SCALE 1.20    YAW 0°
  COLOR  (0.7, 0.4, 0.2)
  CURSOR (12, 0, -6)
  COUNT  14 seeds
  ```
  EDIT sub-mode adds a second line:
  ```
  EDIT   v3 of 9   edges 16   log_len 4
  ```
- HUD reverts to default identity block when BUILD off.

## Definition of done — definitive AC

Each item below MUST hold for the feature to ship.

### TEST
- [ ] **T1** — `tests/test_vault_seeds.py` covers schema migration on
  existing vault.db, then CRUD round-trip (create → list → update →
  list → delete → list), counts and field values match across each.
- [ ] **T2** — `tests/test_seed_commands.py` covers the four brain
  command handlers: valid payloads succeed, missing required fields
  fail with `ok: false`, unknown `seed_id` on update/delete returns
  `ok: false`, biome filter on `seed_list` is honored.
- [ ] **T3** — `tests/test_wireframe_edits.py` covers each of the 5
  ops applied to a known base mesh: `move_vertex`, `add_vertex`,
  `add_edge`, `remove_edge`, `subdivide_edge`. Determinism: same base
  + same log = same final mesh, replayable in any order
  preserves order-dependence semantics correctly.
- [ ] **T4** — `tests/test_workroom_input.py` (input mode FSM) covers:
  B toggles only in workroom; ESC exits; ENTER swaps PLACE↔EDIT;
  selection cursor is bounded; SPACE constructs a `seed_create`
  payload with the right kind/pos/yaw/scale/color; J / C / N / DEL
  in EDIT sub-mode each construct the right edit-op-and-update.
- [ ] **T5** — All test suites green together; no regression in
  existing vault tests.

### MIGRATION
- [ ] **M1** — Existing pre-migration `vault.db` (loaded from a real
  user save) opens cleanly, picks up the new `seeds` table on first
  brain boot, never touches existing rows. Reverse boot (newer DB on
  older code) is **not** a goal — V1 is forward-only.

### VISUAL
- [ ] **V1** — Walk to workroom biome via debug teleport. HUD displays
  "WORKROOM" identity. Ground is flat 1m grid.
- [ ] **V2** — Press `B`. HUD switches to BUILD/PLACE overlay. FPS
  movement freezes. Ghost cursor visible on the 1m grid floor.
- [ ] **V3** — `TAB` cycles primitives — visible ghost shape changes
  between cube / spire / octahedron / tetrahedron / pyramid.
- [ ] **V4** — `SPACE` drops a real seed. Visible at cursor. Walk
  away, walk back — still there (proof manifest re-emits seeds).
- [ ] **V5** — `R G B` cycles the SELECTED instance's color channels.
  Edge color changes within one frame.
- [ ] **V6** — `ENTER` switches to EDIT sub-mode. A bright cube
  marks the selected vertex. `TAB` cycles to the next vertex in the
  mesh. The cube moves with the cursor.
- [ ] **V7** — In EDIT, `ARROWS` moves the selected vertex; the
  edges connecting it visibly bend (the "wire bending" verb).
- [ ] **V8** — In EDIT, `J` then `TAB` then `J` adds a new edge
  between two selected vertices. The new wire renders.
- [ ] **V9** — In EDIT, `C` subdivides the currently selected edge —
  a new joint appears at midpoint and the edge becomes two segments.
- [ ] **V10** — In EDIT, `U` undoes the last mesh edit; the mesh
  reverts to its prior shape.
- [ ] **V11** — `DEL` removes the SELECTED seed. Disappears
  immediately; HUD count drops by one.

### SCENARIO
- [ ] **S1** — Place 5 primitives with mixed kinds and varied RGB
  colors. Apply at least one `move_vertex`, one `add_edge`, one
  `subdivide_edge` to one of them. Exit BUILD. Walk away. Kill brain.
  Restart brain (`python3 brain_server.py outdoor 9877`). Walk to
  workroom slot. All 5 still rendered with original kind/pos/scale/
  color, AND the modified one still has its bent vertices and added
  edges (mesh-edit log replays cleanly across restart).
- [ ] **S2** — Place 1 seed, edit (move_vertex twice + add_edge).
  Press `U` three times. Mesh reverts to base. Delete seed. Re-enter
  workroom. Zero seeds. (Proves no zombie state, undo is clean.)
- [ ] **S3** — Place 1 seed in `workroom` biome. Walk to a different
  biome (e.g., `outdoor`). Seed does NOT render there. (Biome scoping.)

### Out-of-scope (V1)
- Authoring outside `workroom` biome (V2 — promote-to-biome workflow).
- Skin cycling on seeds (V2 — once skins consolidate as their own
  feature).
- Noise / procedural texture authoring (separate feature; see
  `feat_noise-consolidation.md` if it lands).
- Pattern verb (5th of the user's verbs — bend/join/curve/pattern).
  V1.5 once the 4 core verbs are nailed.
- Multi-grid dial (1m / 6m / 41m / 0.1m). V1 ships fixed 1m place +
  0.1m vertex.
- Vertex deletion (orphan-vertex semantics deferred).
- Face/surface authoring (we're wires not surfaces).
- Multi-select / box-drag.
- Param sliders for continuous tuning (discrete keystrokes V1).
- Authoring outside the wireframe_mesh kind (creature meshes, banner
  layers, macro stamps, kind_config — separate authoring surfaces).
- Godot client — vector terminal is canonical (`design_brain_ground_truth`).

## Phasing — PR breakdown

### PR 1 — vault.world_seeds + brain commands
- Add `world_seeds` table + idempotent migration in `core/vault.py`.
- Helpers: `vault.world_seed_create / world_seed_update / world_seed_delete / world_seeds_by_biome`.
- Brain dispatch: `seed_create / seed_update / seed_delete / seed_list` handlers.
- Manifest emits `seeds: [...]` for the active biome.
- T1 + T2 + M1 green.

### PR 2 — workroom biome
- Register `workroom` biome at slot `(-3, 0)` in `BIOME_REGISTRY`.
- Authored ground + 1m grid + boundary hints. No entities. Single moon.
- Debug teleport surface confirmed.
- V1 green.

### PR 3 — `wireframe_edits.py` op library
- New module `core/systems/wireframe_edits.py` with 5 ops.
- Each op is a pure function returning a new WireframeMesh.
- `replay(base_mesh, log) -> WireframeMesh` helper.
- Client cache layer in `clients/vector_terminal/wireframe_renderer.py`
  (or a sibling module) — `(seed_id, log_len) → resolved_mesh`.
- T3 green.

### PR 4 — vector terminal BUILD mode FSM (PLACE only)
- New `clients/vector_terminal/build_mode.py` with state class.
- Toggle key `B`, ESC alias, biome-gated.
- Cursor state, selection state, ghost-cursor render.
- All PLACE-sub-mode bindings.
- TAB / SPACE / DEL / +/- / <> / [ / ] / RGB → seed_create / seed_update / seed_delete.
- T4 (PLACE half) + V2–V5 + V11 green.

### PR 5 — EDIT sub-mode wiring
- ENTER toggles PLACE↔EDIT. EDIT sub-mode bindings.
- Joint cursor (vertex selection, edge selection).
- TAB cycles vertices. ARROWS / PgUp/PgDn move selected vertex (writes
  `move_vertex` op).
- J wires up `add_edge` (two-step: first J selects start, second J
  closes after a TAB).
- C wires up `subdivide_edge`. N wires up `add_vertex`. DEL on edge
  → `remove_edge`. U pops last op.
- Each edit fires `seed_update` with the appended log.
- Render path replays the log on each manifest tick; cache invalidates.
- T4 (EDIT half) + V6–V10 green.

### PR 6 — UAT pass
- Author session: place 5 mixed primitives, edit one heavily.
- Restart brain (mid-session).
- Verify S1 / S2 / S3 hand-on-keyboard.
- Pin learnings to memory (`project_vector_workroom_v1` + any
  surprises that warrant a feedback memory).

## Hot-reload notes
- `core/vault.py` schema changes → brain restart.
- `core/systems/biome_data.py` workroom registration → brain restart.
- `core/systems/wireframe_edits.py` → brain + vector terminal restart
  (both consume).
- `clients/vector_terminal/build_mode.py` → vector terminal restart.
- `brain_server.py` command dispatch → brain restart.

## Parallel-safe siblings
- `feat/loop-completion` — disjoint files except for `brain_server.py`
  dispatch (additive). Merge order: whoever lands first gets a clean
  diff; the other rebases the dispatch entries.
- `feat/noise-consolidation` (if it lands) — disjoint.
- Permanent Objects journal queue (J4/J5/J6.1/J7) — disjoint vault tables.
- `docs/spec_open_source_primitive_pipeline.md` — eventually feeds
  registered OBJ meshes to the workroom's TAB cycle. Disjoint code paths.

## Acceptance signature

Once T1–T5 + M1 + V1–V11 + S1–S3 all hold and PR 6 UAT passes, the
feature is shipped. Pin `project_vector_workroom_v1` memory at that
point with:
- the seed-table contract + biome slot
- the 5 mesh-edit ops + replay determinism guarantee
- the input-binding map
so downstream features (V2 skin authoring, V1.5 pattern verb, banner
layer authoring, macro_stamp authoring, multi-grid dial) extend
cleanly without re-litigating the substrate.
