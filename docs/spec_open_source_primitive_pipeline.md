# Spec — open-source primitive ingestion + edit pipeline

**Status:** DRAFT — for redline by user before any code lands.
**Scope owner:** vector terminal (canonical client, per `design_brain_ground_truth`).
**Companion:** `~/Desktop/wireframe_and_texture_resources.txt` (asset URLs + algorithm refs).

## Premise

The wireframe substrate already ships:
- `core/systems/wireframe_mesh.py` — `WireframeMesh` + 5 built-in primitives + `parse_obj()` / `load_obj()`.
- `clients/vector_terminal/wireframe_renderer.py:draw_wireframe` — pure edge iteration.
- `clients/vector_terminal/horizon_objects.py:_draw_wireframe_mesh` — manifest entries with `mesh:` (built-in) or `obj_path:` (file).
- 329 Kenney nature-kit OBJs already physically present at `assets/kenney/nature-kit/Models/OBJ format/*.obj`. Pack ships with `License.txt` (CC0).

What's missing is the **mechanism** between "OBJ exists on disk" and "the engine consumes it as a registered, validated, art-directed primitive." Today the only way is to hand-author an `obj_path` string into a config row, and there's no edit primitive — every Kenney mesh comes in at its native scale, origin, and edge-count, which won't match how the engine wants to render it.

Existing `tools/` (`extract_meshes.py`, `gen_kind_mesh.py`, `repair_meshes.py`, `subdivide_meshes.py`, `bake_edge_color.py`) all target the **Godot/GLB pipeline**, which is on hold per `design_brain_ground_truth`. None of them apply here. This spec defines the vector-terminal-flow pipeline cleanly without disturbing the legacy Godot tooling.

## Decisions (proposed — flag any that need to change)

### D1 — Asset directory layout

```
assets/
  kenney/
    nature-kit/                 ← keep Kenney's native pack structure
      Models/OBJ format/*.obj   ← raw, untouched, never edited in place
      License.txt               ← upstream license file lives next to source
  quaternius/
    rpg-characters/
      ...
  ...
  derived/                      ← OUR cleaned/edited meshes
    spire/                      ← one folder per registered mesh name
      mesh.obj                  ← cleaned OBJ committed to git
      provenance.json           ← sidecar (see D2)
```

**Rules:**
- Raw vendor packs go in `assets/<vendor>/<pack>/...` matching their native structure. Never edited.
- Derived/cleaned meshes go in `assets/derived/<name>/mesh.obj` with a sidecar.
- `assets/derived/` is the only path code reads — vendor folders are raw input only.

### D2 — Provenance sidecar schema

Per derived mesh, `provenance.json`:

```json
{
  "name": "spire",
  "source": {
    "vendor": "kenney",
    "pack": "nature-kit",
    "path": "Models/OBJ format/tree_pineTallA.obj",
    "license": "CC0",
    "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
    "credit": "Kenney (www.kenney.nl)"
  },
  "edits": [
    {"op": "recenter", "mode": "bottom_center"},
    {"op": "rescale",  "target_height": 4.0},
    {"op": "axis_swap", "from": "y_up", "to": "y_up"}
  ],
  "stats": {
    "vertex_count": 31,
    "edge_count": 47,
    "bounds": [[-0.5, 0.0, -0.5], [0.5, 4.0, 0.5]]
  },
  "imported_at": "2026-05-02T17:42:00-07:00",
  "import_tool_version": "1.0.0"
}
```

This makes the ingest reproducible (an edit log, not a state file), enforces credit (CC-BY etc. show up in `tools/list_meshes.py`), and gives validation a place to spot drift if the file is hand-edited.

### D3 — Mesh registry — single source of truth

`config/wireframe_meshes.json`:

```json
{
  "spire":            {"path": "assets/derived/spire/mesh.obj"},
  "tree_pine_small":  {"path": "assets/derived/tree_pine_small/mesh.obj"},
  "stone_small_a":    {"path": "assets/derived/stone_small_a/mesh.obj"}
}
```

Manifest consumers (currently `horizon_objects`, future ground entities, future creatures) reference meshes by **name**, not path:

```python
{"kind": "wireframe_mesh", "mesh": "tree_pine_small", "azimuth": 240.0, ...}
```

`mesh:` already works for built-ins (`cube`, `spire`, etc.). The registry extends the same key — `get_builtin(name)` falls through to `get_registered(name)` which loads from the registry. **`obj_path:` becomes deprecated** and logs a warning; it still works for one branch's grace period, then is removed.

### D4 — Edit primitives (composable, OBJ-in/OBJ-out, pure functions)

Each is a function `(WireframeMesh, **kwargs) -> WireframeMesh`. Composition order matches `provenance.json` `edits` log so re-running is deterministic.

| op             | params                       | behavior                                                                 |
|----------------|------------------------------|--------------------------------------------------------------------------|
| `recenter`     | `mode: centroid \| bottom_center \| origin` | translate verts so the chosen point is at (0,0,0)              |
| `rescale`      | `target_height \| target_diag \| factor` | uniform scale to target metric                                  |
| `axis_swap`    | `from, to`                   | rotate verts so up-axis matches `to` (typical: `z_up` → `y_up`)         |
| `merge_vertices` | `epsilon: 1e-6`            | collapse vertices within ε; rewires edges; dedups                        |
| `decimate_edges` | `target_count`             | remove shortest edges first until count hit (preserves silhouette)       |
| `bounds_clip`  | `min, max`                   | drop verts outside box (post-merge fixup)                                |

**Non-goal V1:** mesh smoothing, face triangulation, normal generation, UV remap. None of those matter for wireframe rendering.

### D5 — Ingest CLI

`tools/import_obj.py` — single entry, declarative flags, idempotent.

```bash
.venv/bin/python tools/import_obj.py \
    --source assets/kenney/nature-kit/Models/OBJ\ format/tree_pineTallA.obj \
    --name spire \
    --recenter bottom_center \
    --rescale-height 4.0 \
    --axis-swap y_up \
    --merge-vertices 1e-6 \
    --max-edges 200
```

Output:
- `assets/derived/spire/mesh.obj` (cleaned)
- `assets/derived/spire/provenance.json` (sidecar)
- Updates `config/wireframe_meshes.json` (atomic write, sorted keys)
- Prints stats + any validation warnings

Idempotent: re-running with same flags produces identical output. Re-running with different flags produces a new mesh; `provenance.json` `edits` is the log of what was applied.

### D6 — Validation rules

Hard fail (ingest aborts):
- Source file missing or malformed.
- Vendor license unknown (no `License.txt` in the pack root, no `--license` override).
- Resulting edge count > `--max-edges` (default 500).
- Resulting bounds zero (degenerate mesh).

Soft warn (ingest proceeds, prints):
- Edge count > 200 (rendering budget threshold).
- Vertex count > 100.
- Bounds aspect ratio > 10:1 (suggests axis_swap was wrong).
- Manifold-broken (edges shared by ≠2 faces — informational only; wireframe rendering doesn't care).

Boot-time validation (in `wireframe_meshes.py:get_registered`):
- Every registry entry's path must exist on disk.
- File hash matches stats from `provenance.json` (catches uncontrolled hand-edits).

### D7 — Consumer surfaces

| Surface                  | Today                                           | After spec                                |
|--------------------------|-------------------------------------------------|-------------------------------------------|
| `horizon_objects`        | `mesh:` (built-in only) or `obj_path:`          | `mesh:` resolves built-ins → registry      |
| Ground entity rendering  | not wired                                        | manifest gains `wireframe_mesh: <name>` for kinds that opt in |
| Creature rendering       | GLB via `kind_config.json`                       | optional `wireframe_mesh: <name>` field; client picks GLB vs wireframe |

This unifies one resolution function (`resolve_mesh(name) -> WireframeMesh`) across all consumer surfaces.

### D8 — Tooling beyond ingest

`tools/list_meshes.py` — print all registered meshes, source, license, edge count. Used to credit vendors in shipped builds + audit licensing.

`tools/preview_mesh.py <name>` — single-mesh raylib viewer (rotates the mesh on a turntable). Smoke-test edits without booting the full vector terminal.

`tools/migrate_obj_paths.py` — one-shot: scan `biome_data.py` for `obj_path:` rows and rewrite to `mesh:` registry references. Run once per branch that consumes the new pipeline.

## Phasing

**PR 1** — registry + name resolution.
- `config/wireframe_meshes.json` (empty).
- `core/systems/wireframe_mesh.py:get_registered(name)` reads registry, loads OBJ on demand, caches.
- `_resolve_mesh()` in `horizon_objects.py` falls through built-in → registry.
- Tests: registry round-trip, missing mesh returns None, cache hit.

**PR 2** — edit primitives.
- New module `core/systems/wireframe_edits.py`.
- 5 ops from D4. Each is pure-function, fully tested.
- Tests cover: composition order, idempotency, edge cases (single vertex, degenerate face).

**PR 3** — ingest CLI.
- `tools/import_obj.py`.
- Provenance sidecar generation.
- Atomic registry update.
- Tests: ingest a fixture OBJ, verify all outputs match expected.

**PR 4** — port one Kenney asset.
- Pick `tree_pineTallA.obj` → register as `tree_pine_tall`.
- Wire into `OUTDOOR_HORIZON_OBJECTS` replacing the built-in `spire`.
- UAT: see real Kenney tree on the southwest horizon.

**PR 5** — validation + listing tools.
- `list_meshes.py`, `preview_mesh.py`.
- Boot-time validation in `get_registered`.

**PR 6** — deprecate `obj_path`.
- One-warning grace window.
- `migrate_obj_paths.py` if there are existing rows to convert.
- Final removal in a follow-up branch.

## Open questions (need user input before any code)

1. **Storage:** `assets/derived/` committed to git as cleaned OBJs, or generated at install time from raw + provenance? (Recommendation: commit. Reproducible + readable diffs + no boot-time work.)
2. **Naming:** Do registered mesh names follow vendor-prefix convention (`kenney_tree_pine_tall`) or cleaned canonical (`tree_pine_tall`)? (Recommendation: canonical, since provenance has the vendor.)
3. **Vendor packs in git:** keep Kenney's `nature-kit` raw OBJ pack in the repo (~10 MB), or in `.gitignore` with a `scripts/setup_assets.sh` to pull on first clone? (Recommendation: gitignore raw, commit `License.txt` only — derived meshes are what code actually reads.)
4. **Scope of axis-swap:** is `y_up` already the engine convention, or do we need to confirm against the renderer? (`raylib` is y-up positive; need a one-paragraph confirmation either way.)
5. **What about creature meshes?** GLB pipeline still wins for creatures with rigging; wireframe is for static props. Is that boundary acceptable, or do we want wireframe creatures too? (Recommendation: defer creatures; props-only V1.)
6. **Edge-count budget:** the 200/500 numbers in D6 are guesses. Do we have profiling data on draw_line_3d throughput to set them empirically? (Recommendation: instrument once before PR 4 ships.)

## Out-of-scope (explicitly)

- **Edge skins / procedural texturing** — the rendered look. That's a separate spec (sketch lives in `core/systems/edge_skins.py` / `tests/test_edge_skins.py` on disk uncommitted; decision pending).
- **GLB / Godot pipeline** — frozen until Godot revival arc.
- **Animation, rigging, material maps** — wireframe doesn't use them.
- **Mesh authoring inside the engine** — we ingest, we don't author. Authoring lives in Blender / Procreate / external tools.

## Acceptance criteria for the spec itself

This spec is approved when the user has:
1. Initialed each of D1–D8 (or annotated changes).
2. Answered the 6 open questions.
3. Confirmed phasing order.

Then PR 1 lands first, on its own branch (NOT `feat/loop-completion`).
