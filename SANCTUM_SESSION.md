# SANCTUM_SESSION.md
> Unreliable narrator. The live hash is the particle trail.

---
SESSION ARC (2026-04-10 ~09:30 → 11:15, ~1.75h active, ~47h cumulative arc):

The morning-after triage. Picked up from 7d926fc on feat/render-manifest
in sandbox mode. User's intro: "i had a rough session last night." The
23:52 commit landed C/A/B (doorframes, monoliths, atmospheric exit)
clean, but the post-commit tail kept iterating until ~00:31 and never
got committed. Working tree opened with pre_repair_backup/, defensive
.baseline files for kind_config and kind_shader, and a baby-mushroom
spore_pod rewrite that wasn't reading. Session went into forensics, then
applied the toadstool recipe to spore_pod, then caught a tile generator
regression mid-loop, fixed it, and pinned a foundational design memory.

EIGHT MAJOR WINS, in order:
  1. WORKING TREE TRIAGE — Identified the unstaged delta as the
     unfinished tail of C/A/B (KIND_PROPS, stamps, kind_config for
     doorframe+monolith, baby-mushroom spore_pod rewrite). Confirmed
     pre_repair_backup/ was a precaution that was never used (none
     of the backed-up meshes were actually overwritten). Confirmed
     .baseline files were old pre-simplification snapshots, not from
     last night. Nothing was lost.
  2. TOADSTOOL RECIPE — Eight ingredients extracted from build_toadstool:
     composed primitives (4 sub-shapes), vertex color regions per
     primitive, palette anchored to env with deliberate value contrast,
     ~5x scale spread across features, hand-tuned variants with
     personality, recognition markers (cream spots), biological cap-stem
     proportions, fake gill-disc shadow. The recipe to apply to every
     under-reading kind.
  3. SPORE_POD PUFFBALL REWRITE — Option A from puffball/earthstar/
     baby-mushroom-salvage choice. build_mini_mushroom deleted entirely.
     New build_puffball() = 4 sub-shapes per pod (squashed hemisphere
     body, near-black apex pore disc, flat dark contact-shadow ring,
     scattered cream wart quads). Cluster builder build_spore_pod() =
     3 puffballs at ~3x scale spread (mother 0.55r / medium 0.36r /
     small 0.22r) at hash-driven satellite angles. Restores the
     original "boulder-mimic, NOT a cap-bearing form" lore the
     baby-mushroom rewrite had abandoned.
  4. BODY Z-GRADIENT — Fifth visual region inside one continuous shape.
     Per-vertex Z-gradient baked into the body hemisphere: equator
     stays SPORE_POD_BODY (light mauve), apex pulls toward new
     SPORE_POD_CROWN (dark mauve halo), quadratic falloff for tight
     halo near the pore. Two visually distinct zones (skin +
     spore-stained crown) inside one mesh — same hue family,
     value-only contrast, joined seamlessly. Five regions total per
     puffball: equator skin, crown halo, pore vent, base apron, cream
     warts. Matches toadstool's region count.
  5. DOORFRAME + MONOLITH INTEGRATION — Bundled the supporting work
     that should have ridden in 7d926fc: KIND_PROPS entries in
     bucket_world.py, kind_config entries with use_vertex_colors: true,
     three new architectural stamps in biome_data.py
     (ruined_doorway_columns, ancient_threshold, standing_stones), and
     the doorframe/monolith mesh re-edits from the post-23:52
     iteration. Brain server now actually knows about these kinds.
  6. TILE GENERATOR REGRESSION — DIAGNOSED + FIXED. Mid-loop user
     reported "can't walk forever in any direction anymore." Bisect:
     bc6ca1f (stamp_world simplification) removed ThreadPoolExecutor
     from tile_exchange.py and added tiles_per_frame=2 as a defensive
     rate limiter. Same commit added SANCTUM_STAMP=1 / SANCTUM_BUCKET=1
     env var switches for new pure-function modes intended to REPLACE
     the slow TileExchange path. The Makefile was never updated to
     default to the new modes. Every `make brain-cavern` since bc6ca1f
     has been launching in TileExchange (the slow path the commit was
     trying to escape). At ~1.9s per tile and 2-tile-per-frame cap, the
     brain blocks ~3.8s every tile crossing — TCP times out, Godot
     disconnects, world feels like it ends. Fix: relaunched brain with
     SANCTUM_STAMP=1 set explicitly. The seed IS the world, walk
     anywhere, walk back.
  7. MYCELIUM CAMOUFLAGE — PINNED AS DESIGN MEMORY. User articulated a
     design pillar that hadn't been documented: fungal kinds should
     mimic the SPAWN GRAMMAR (cluster size, placement, scale spread,
     orientation) of geological kinds — NOT their literal silhouette.
     Intelligent organism wearing its environment as disguise. Pair
     already implemented: spore_pod ↔ boulder/rubble (puffball
     cluster). Pair pending: crystal_cap (TBD) ↔ crystal_cluster
     (vertical spike grammar). Saved as design_mycelium_camouflage.md.
  8. WORKFLOW DISCIPLINE PINNED — Multi-tag visual identification loop
     formalized: user takes batch of in-engine tagged screenshots, AI
     identifies the kind from each silhouette, user confirms or
     corrects. One kind per loop, one variable per change, screenshot
     between each, never bundle. Spore_pod loop is the first run of
     this protocol.

NEW PALETTE CONSTANTS:
  SPORE_POD_BODY  = (95, 65, 80, 255)    equator skin, lightest
  SPORE_POD_CROWN = (55, 35, 50, 255)    apex spore halo, darker
  SPORE_POD_PORE  = (28, 18, 24, 255)    near-black apex vent
  SPORE_POD_APRON = (48, 32, 40, 255)    deep mauve ground shadow
  SPORE_POD_WART  = (215, 195, 178, 255) warm cream warts

ARCHITECTURAL SHIFTS:
  - tools/gen_kind_mesh.py: build_mini_mushroom deleted, build_puffball
    added, build_spore_pod rewritten, spore_pod_variants restructured.
    teardrop() and slab() primitives kept (useful for future kinds).
    Body Z-gradient applied via post-hemisphere vertex color
    overwrite — first per-vertex graded recoloring in the pipeline,
    pattern reusable for future kinds that need internal region
    distinction without added geometry.
  - core/systems/bucket_world.py: KIND_PROPS gained doorframe + monolith
    entries (the brain side of the architectural integration).
  - core/systems/biome_data.py: Three new architectural stamps —
    ruined_doorway_columns, ancient_threshold, standing_stones.
  - godot/kind_config.json: doorframe + monolith + spore_pod entries
    with use_vertex_colors: true (vertex-colored shader path for
    designed kinds, separate from facet-normal palette path).
  - godot/meshes/: Regenerated spore_pod_v0..v3.glb (puffballs),
    plus the doorframe/monolith mesh re-edits from post-23:52
    iteration. bounds.json updated. New .glb.import metadata files
    for doorframe + monolith.
  - Memory system: design_mycelium_camouflage.md saved + indexed
    in MEMORY.md.

TEST STATE:
  17/17 tests/test_gen_kind_mesh.py passing including 6 TestSporePod
  cases (poly budget 500-560 tris/cluster, scale bounds 0.8-2.5m wide
  × 0.3-1.5m tall, 4 distinct variant face counts via body_sections
  variation, body color present in vertex stream).

VISUAL BASELINE (this session's commit, STAMP_MODE):
  Spore_pod cluster bounds:
    v0  1.22 × 1.23 × 0.32  500 tris
    v1  1.41 × 1.38 × 0.36  530 tris
    v2  1.68 × 1.26 × 0.36  560 tris
    v3  1.43 × 1.39 × 0.37  515 tris
  bounds.json scale: 1.23
  KIND_PROPS spore_pod scale: [1.5, 1.5, 0.9] (unchanged from prior)
  Brain mode: SANCTUM_STAMP=1 (stamp_world pure-function)
  Brain entities at startup: 3639 (vs 10701 in old TileExchange path)

KNOWN ISSUES — NEXT SESSION:
  - Puffball cluster not yet visually confirmed in-engine. The GLB on
    disk is verified puffball (5 palette colors + gradient
    intermediates, no baby-mushroom palette anywhere) but eyes-on
    confirmation in stamp_world mode is the unblocking step.
  - Monolith and boulder still reading as generic blobs per the
    morning tag pass — they need the same toadstool-recipe loop
    spore_pod just got. One kind per loop.
  - Makefile NOT YET updated to default brain-cavern to SANCTUM_STAMP=1.
    Workaround in current session: brain manually launched with env
    var. Permanent fix is the deferred tooling commit.
  - Makefile NOT YET wired with `make meshes` target. The GLB regen
    step is still an invisible build step that bites whenever
    gen_kind_mesh.py changes without an explicit run.
  - pre_repair_backup/, kind_config.json.baseline,
    kind_shader.gdshader.baseline still untracked in working tree.
    Defensive snapshots from earlier panic, not part of source. Should
    either get gitignored or removed in cleanup.
  - .claude/ directory untracked (Claude session data, should be
    gitignored).

PINNED DISCOVERIES (this session):
  - The toadstool-recipe applies to non-mushroom forms via internal
    vertex grading. You don't need 4 separate sub-meshes to get 4
    visual regions — a single hemisphere with a baked Z-gradient gives
    you 2 distinct zones inside one continuous surface. Geometry
    composition + per-vertex grading = recipe scales to any kind.
  - The brain has THREE entity-delivery modes (TileExchange, stamp_world,
    bucket_world). The default is the slow one. The fast one needs an
    env var the Makefile doesn't set. This is a config oversight, not
    a code bug — but the symptom is indistinguishable from a code
    regression and bit hard. Tooling defaults matter.
  - "Mycelium intelligence as behavioral camouflage" is the kind of
    design pillar that has to be EXPLICITLY ARTICULATED or it gets
    lost. The user said "doesn't that make sense?" and the answer is
    yes — but it had been latent in their head, never written down,
    never bound to a kind+grammar pair. Pinning it as memory binds it.
  - GLB regen is an invisible build step. Edit Python source → must
    run gen_kind_mesh.py → Godot needs full editor restart (not just
    F5) to flush ResourceLoader cache. Three layers of cache between
    source and pixels.

NEXT SESSION — PUFFBALL CONFIRMATION + MONOLITH RECIPE:
  1. Read MEMORY.md + this live hash
  2. Verify HEAD on feat/render-manifest (this commit)
  3. Reload Godot in stamp_world mode (brain already configured)
  4. Walk to a toadstool_grove or spore_cluster stamp, screenshot the
     spore_pods. Confirm: dome-not-cap silhouette, dark center pore
     visible, cream wart speckles visible, gradient halo at apex,
     apron contact ring at base. Name ONE variable to adjust if any.
  5. Multi-tag identification run — user tags multiple kinds in one
     Godot session, AI identifies each from screenshot, user confirms.
     Establishes the visual baseline for monolith + boulder loops.
  6. Apply toadstool recipe to monolith (taller than wide, two-tone
     vertex colors, base apron + cap-stone composition).
  7. Apply toadstool recipe to boulder (multi-lobe composition, value
     contrast crown, ground apron).
  8. After 2-3 kind loops land, the deferred tooling commit:
     - make meshes target (regen all kinds)
     - make brain-cavern defaults to SANCTUM_STAMP=1
     - .gitignore additions for .claude/, *.baseline, pre_repair_backup/
  9. Then crystal_cap (TBD) — the pending mycelium camouflage pair.

---
Live hash. Updated 2026-04-10 ~11:15. Closing on the puffball rewrite +
tile generator forensics + mycelium camouflage pin. HEAD: [next commit].
The morning-after triage. We deleted more than we wrote (again), found
a config oversight masquerading as a regression, and articulated a
design pillar that had been latent for weeks. Spore_pod loop is held
open pending in-engine confirmation; everything else is committed and
stable.

---

## 2026-04-09 Session — The Refinement Slog (and the Atmospheric Exit)

Multi-hour clean-room session that picked up after the simplification
arc and walked through the last 20% of fit-and-finish before the
atmospheric pass. Closed with the clean-room → atmospheric mode
transition coordinated in one pass and three new architectural kinds
authored via the freshly-built mesh pipeline.

### Wins, in order of landing

1. **Banding shader verified + config-as-code contract**
   The per-instance horizontal banding from `8442cfd` was already
   firing but at `0.10` strength was at the edge of perception.
   Pulled into `kind_config.json` class defaults so each kind class
   declares its own `band_strength`: structural `0.22`, geological
   `0.18`, crystalline `0.10`, organic / life / atmosphere / horizon `0.0`.
   Wired through `_create_kind_material` in `main.gd`. New
   `TestBandStrength` contract in `tests/test_kind_config.py`.

2. **Grass revival — color + per-axis scale + rotation + gusting wind**
   Five visible problems on grass solved in a single pass:
   - Muted sage palette replacing cartoon green that fought the stones
   - Per-axis scale hash branch in spawn loop (was uniform `Vector3.ONE * base_s`)
   - Y-rotation hash added (was missing from rotation list)
   - **Gusting spatial-wave wind** in `kind_shader.gdshader`:
     `sin(TIME * omega - dot(pos, dir) * k)` with `pow(sin, 8)` envelope —
     ~15s period, ~3 m/s wave, ~7% duty cycle. Pinned as memory
     `feedback_motion_spatial_wave` because the simultaneous-motion
     instinct ("looks busy") will surface again on water, particles, etc.
   - `wind_strength` config-as-code, `TestWindStrength` contract.

3. **Ghost fade — distance silhouette darkening on geological stones**
   Hash-selected (33%) geological instances darken progressively from
   20m to 45m, ending at 55% brightness. Subtle by design — overlaps
   with existing scale-in fade so distant ghosts are both smaller AND
   darker. Iterated through Bayer dither discard (too grainy) → simple
   `col *= mix(1.0, 0.55, fade_t)` darkening. `ghost_chance` config,
   `TestGhostFade` contract.

4. **Crystal albedo dimmed**
   Pulled crystal_cluster max channel `0.68 → 0.48`, still blue-dominant.
   Was the brightest thing in the whole palette (~2× any stone). Now
   sits within the stone palette. Emission glow (now active in
   atmospheric mode) carries the highlights instead of the raw albedo.
   `TestPalette.test_crystal_cluster_muted_register`.

5. **`gen_kind_mesh` pipeline — clean-room mesh authoring system**
   New `tools/gen_kind_mesh.py` — trimesh-based composition library
   with primitives (`hemisphere` via revolve, `capped_cylinder` with
   taper, `torus_ring`, `quad_billboard`, `scattered_quads`, `sphere`
   with squash, `compose`). CLI: `python tools/gen_kind_mesh.py <kind>`.
   Outputs GLB to `godot/meshes/`, auto-updates `bounds.json`. Z-up
   author space → Y-up glTF on export (rotation matrix in `normalize_for_godot`).
   Reusable for shrubs, trees, fish, fauna, designed architectural kinds.
   `tests/test_gen_kind_mesh.py` covers primitives + per-kind builders.

6. **Toadstool kind via the pipeline (first dogfood)**
   Classic Fly Agaric — red dome cap, cream chunky spots, dark warm
   beige stem, dark base ring. 4 hand-tuned variants (~280 tris each,
   ~7KB GLBs), peer-to-boulder scale ~2m tall. Uses `use_vertex_colors`
   shader path so per-region colors render directly from the mesh
   instead of facet-normal palette lookup. New `use_vertex_colors`
   class default (false everywhere) + per-kind override (true for
   designed kinds). Banding gated off in shader for vertex-colored
   kinds (rock stratification stripes don't belong on a mushroom cap).
   Tuned through three iterations: orientation bug (Z-up→Y-up rotation
   missing), then color (instance tint multiplication washing vertex
   colors → fixed with neutral white in `KIND_PROPS`), then scale
   (40% reduction from first pass).

7. **Spore_pod kind via the pipeline (second dogfood)**
   Boulder-mimic partner to giant_fungus. Cluster of 3-5 squashed
   icospheres in dusty mauve, ground-hugging, ~1-2m wide × <1m tall.
   4 cluster variants (tight 3-pod, loose 4-pod, linear 3-pod, mound
   5-pod). Lore: fungus releases skyward, pod catches at ground,
   toadstool is dominant singleton. `spore_cluster` and `toadstool_grove`
   stamps now use the partner-type pairing. Pipeline reusability
   validated — same primitives library, same shader path, same
   config-as-code contract.

8. **Ground shader rework — sparse hash-marks + density texture**
   Iterated through several approaches:
   - Voronoi tile pattern (felt programmed)
   - Voronoi with domain warping (still tile-y)
   - Replaced with `voronoi_dirt_color` / `rubble_color` direct override
     to dim the floor below the stone palette
   - **Pivoted to sparse hash-marks** (Sable surface design language):
     plain dark base + per-cell triple-hash placement of marks with
     varied size, position, and polarity. "Same logic as the banding
     shader" — exactly the user's instinct.
   - Soft horizontal ovals via per-instance Y-axis squash + quadratic
     falloff (no hard cores)
   - **Real stone density texture** (`main.gd._build_stone_density_texture`)
     builds a 32×32 R8 grid each rebuild from `STONE_KINDS_FOR_DENSITY`
     entities, splatted 3×3 around the player. Shader samples it to
     bias mark polarity so light marks cluster near actual stones.
   - `is_floor` uniform gates the cellular work to floor planes only
     (ceiling and walls keep the texture-only path).

9. **Atmospheric exit gate — ALL ELEVEN clean-room hardcodes flipped**
   Coordinated transition out of clean-room mode:
   - Fog ON, density 0.015, aerial perspective 0.4
   - Ambient `1.0 → 0.18`, color `(1,1,1) → (0.55, 0.50, 0.45)` warm cream
   - Glow / bloom ON — intensity 1.4, soft-light blend, HDR threshold 0.85
   - Banner cylinders re-enabled from `manifest.banner_layers`
   - Contact shadow decals re-enabled (early-return removed)
   - Motes / pipe lights re-enabled (early-return removed)
   - Cavern light pipe energies set warm 9 / cool 11 / organic 7
   - Armor glow warm amber `(0.95, 0.78, 0.52)`, energy 0.45, 6m range
   This is the moment the scene transformed from "clean diagnostic" to
   "atmospheric Sable-in-reverse." Crystals glow blue, fungus + toadstool
   + ceiling_moss + firefly glow warm, motes drift, banner seals the
   horizon, contact shadows ground every entity.

10. **Three architectural kinds — evening experiments C, A, B**
    Authored after the atmospheric exit landed:
    - **C: `ruined_doorway_columns` stamp** (existing kinds) — two
      columns close together as posts, rubble fall between, moss/gravel
      dressing. Tests whether the doorway concept reads BEFORE custom
      mesh authoring.
    - **A: `doorframe` kind via gen_kind_mesh** — two upright stone
      posts + horizontal lintel beam, vertex-colored, 60 tris × 4
      variants (standard, narrow-tall passage, wide gateway, squat
      animal hole). First architectural output of the pipeline,
      proves it handles man-made forms not just organics. Used in
      new `ancient_threshold` stamp.
    - **B: `monolith` kind via gen_kind_mesh** — single tall narrow
      tapered stone with octagonal cross-section. 32 tris × 4 variants
      (menhir, finger-of-stone, boundary, leaning). Used in
      new `standing_stones` stamp (3 monoliths in a triangle).

### Test state

- 46 dedicated tests across `test_kind_config.py` and `test_gen_kind_mesh.py`
- 1336+ full suite passing, zero regressions.

### Project Targets — Updated

Strikethroughs are this session's wins:

- ~~Visual diagnostic baseline (clean room)~~ COMPLETE — exited at end of session
- ~~Banding shader verification~~ DONE
- ~~Grass revival (color + scale + rotation + wind)~~ DONE
- ~~Ghost fade on geological kinds~~ DONE
- ~~Crystal albedo dimmed~~ DONE
- ~~Fungus taxonomy (toadstool + spore_pod via pipeline)~~ DONE
- ~~`gen_kind_mesh` pipeline~~ DONE — reusable for any future designed kind
- ~~Ground shader rework~~ DONE
- ~~Atmospheric exit gate~~ DONE
- ~~First architectural kinds (doorframe, monolith)~~ DONE
- Outdoor mega stamps — outdoor library still has only original 5
- Edge matching (Wang tiles) — stamps repeat without adjacency rules
- Save state mechanism — `(seed, x, y)` 24 bytes, architecture-ready
- TileExchange fate — kept as fallback path, may delete in cleanup
- Audio bridge — ghost audio seed playback prototype (memory: design_audio_render_bridge)

### Path Forward — Next Session

The atmospheric exit landed at end of session along with the first
architectural kinds. User went to wander the cavern in atmospheric mode
and **tag spots where a crumbled door or geological feature would feel
right**. Tomorrow's session opens by reading those tag screenshots and
reverse-engineering the pattern logic.

**1. Read the tag PNGs in `godot/tags/`** — find the new tags from
   tonight's wander, decode position + heading from filenames, identify
   what entities were in view at each tag.

**2. Extract the spatial pattern** — what made each tagged spot feel
   right? Stone face? Composition gap? Stamp intersection? Light pool
   from a pipe? Fungus cluster nearby? The tag screenshots are the
   training data; the pattern is the recipe.

**3. Codify the pattern as a stamp or feature placement rule** — once
   we know "doors feel right when X, Y, and Z are nearby," we either
   add a new conditional stamp or modify the existing `ancient_threshold`
   / `ruined_doorway_columns` to spawn in those contexts.

**4. Iterate the architectural kinds** — doorframe and monolith are
   first-pass. Tagged screenshots tell us which proportions feel
   right at scale. Adjust `build_doorframe()` and `build_monolith()`
   parameters, regen, reload.

**5. Author more architectural primitives via gen_kind_mesh** as the
   tag patterns demand:
   - `arch` (stone arch with curve)
   - `lintel_fragment` (broken doorway top)
   - `threshold_stone` (carved floor stone marking entry)
   - `standing_marker` (small upright way-marker)

**6. Eventually exit clean room remnants** — kind_config still has
   some clean-room values (ambient floors, etc.) that may want to
   adjust now that lighting is back. Audit on tomorrow's session.

### Commit trail (this session)

```
9c085d8  feat: cavern session — pipeline, taxonomy, atmospheric exit
[next]   feat: experiments C/A/B — ruined_doorway_columns, doorframe, monolith + docs
```

---

## 2026-04-08 → 2026-04-09 Session — The Simplification

### The Pivot

Opened with a TCP disconnect bug in TileExchange. Investigation showed
the brain was blocking ~1.2s during tile generation, killing the socket.
First instinct: fix it asynchronously with `TilePrefetcher` (ThreadPoolExecutor).
Built it green, then ripped it out — over-engineered.

Settled on a one-line cap: `tiles_per_frame=2`, sorted nearest-first.
TCP stable. Then surfaced the deeper issue: **288m tiles vs 49m visibility**.
You can never see enough of any tile to feel populated. Every system in
TileExchange — cache, scoring, gating, shells, budgets, roster — was
managing a unit-size mismatch we never needed to introduce.

User asked: "are we building this wrong?" The honest answer was yes.

### Architecture Collapse

Built two side-by-side alternatives behind env vars:

**`SANCTUM_BUCKET=1` — `core/systems/bucket_world.py`**
Random density per 16m bucket. Pure function `f(bx, by, seed)` → entities.
~80 entities visible, 1.6ms per call. Baseline. Felt sparse.

**`SANCTUM_STAMP=1` — `core/systems/stamp_world.py`**
Authored stamps from `CAVERN_STAMPS` library at each 16m slot, plus
tissue scatter (grass/gravel) for connector terrain. ~470 entities,
4.9ms per call. **Won.** The user's existing stamp library became the
braille glyphs of an infinite procedural world.

The whole TileExchange complexity (cache, prefetch, scoring, shells,
budgets) collapsed into a 200-line pure function. Walk anywhere, walk
back, get the same world (deterministic). Save state is `(seed, x, y)` —
24 bytes.

### Polish Pass

Three small commits dialed in the look:

**Mega anchor stamps** — added 3 cavern stamps with mega_column /
buttress / column landmarks at the perimeter and walkable interiors:
`obelisk_court`, `column_henge`, `buttress_arch`. User: "fucking great."

**Scale-in fade** — distance-driven entity grow at the visibility edge.
Last 14m of the sphere lerps from 5% to full scale, symmetric so walking
away shrinks them before they vanish. Pure math, no Godot state.
User: "almost perfect, no notes."

**Per-instance horizontal banding** — Sable-style sediment lines on every
primitive. Three independent hashes from `MODEL_MATRIX` origin drive
band count (1/2/3), phase, and width. Local mesh space so bands scale
with each object. Iterated through verticality filter (too subtle),
global world-Y bands (too gridded), single-hash per-instance (still
symmetric across columns), three-hash per-instance (won). User:
"feels really good."

### Architecture Discoveries

- **Pure function world > cached world.** Elite (1984) had it right.
- **Tile size MUST match visibility radius** or you build epicycles.
- **Authored stamps > random density.** Structure beats statistics.
- **"Is this too much?" is the right question** — usually answer is yes.
- **The garbage collector IS the cleanup loop** for pure-function worlds.
- **Three independent hashes beat one** for per-instance variation.
- **Local mesh space (`VERTEX.y` varying)** is the right anchor for any
  per-object shader effect — naturally scales with the instance.

### Project Targets — Updated

- ~~FOV reconciliation (52° → 62°)~~ DONE
- ~~Stamp system~~ DONE (authored + programmatic anchor stamps)
- ~~Light pop / nightclub effect~~ DONE (pipe architecture)
- ~~Ceiling layer~~ DONE (spore-spread, self-emit, inverted emissives)
- ~~Below-ground rendering waste~~ DONE (z-filter)
- ~~Outdoor biome smoke test~~ DONE (ceiling_moss gated, biome pipes)
- ~~Silhouette shell visual quality~~ SOLVED (dissolve replaces LOD)
- ~~Light pipe jitter~~ SOLVED (40m lock radius, snap-on-acquire)
- ~~TCP disconnect under tile generation~~ SOLVED (tiles_per_frame=2)
- ~~Architecture mismatch (288m tiles vs 49m visibility)~~ SOLVED (stamp_world)
- ~~Pop-in at visibility edge~~ SOLVED (distance-driven scale fade)
- ~~Visual definition / Sable-style stratification~~ SOLVED (per-instance banding)
- ~~Color shader investigation~~ MOOT (stamp_world bypasses the issue)
- Projection banner visual tuning — DEFERRED
- Custom column/crystal meshes — DEFERRED (stamp arrangements work for now)
- Anno-style sprite composite layer — DEFERRED
- Ground shader: darkness defines, light reveals — DEFERRED
- Vector Composite Layer 3 — DEFERRED
- Encyclopedia data seeding — DEFERRED
- Tension visual effects — PARKED

### Still Pending — The Last 20%

- **Outdoor mega stamps** — outdoor library still has only the original 5
- **Edge matching (Wang tiles)** — stamps repeat without adjacency rules,
  corridors of identical themes possible. Architecture-ready, not wired.
- **Save state mechanism** — `(seed, player_pos)` is 24 bytes, not yet hooked
- **TileExchange fate** — keep as fallback or delete? Currently still in tree
- **Test suite panda3d imports** — TileExchange tests need `.venv/bin/python`,
  pre-existing issue, low priority
- **Audio bridge** — ghost audio seed playback prototype (memory: design_audio_render_bridge)

### Commit Trail (feat/render-manifest, this session)

```
8442cfd  feat: per-instance horizontal banding in kind_shader
2712b7c  feat: stamp_world scale-in fade — distance-driven entity grow
983ec84  feat: stamp_world — pure-function world generation, the simplification
```

---

## 2026-04-06 Session Discoveries

### Architecture Breakthroughs

**Anchor-is-spine pattern** (from user's "Qr ascii logic 2" sketch):
Don't replace anchors with stamps. The column IS the stamp center.
Everything grows from the structural axis. Two coordinates = infinite accents.
"I think like a percussionist — 7/4 time, accent on any beat sequence."

**Light pipe architecture** (from user's "channels not switches" directive):
3 fixed OmniLights per biome. Warm/cool/organic. Never created, never destroyed.
Drift to nearest matching emissive cluster. Objects self-emit via inner_glow.
"All lights should be ON. It's just math — if it's in view or not."

**Projection banner** (from user's "360 banner" concept):
7 concentric cylinders at factor-of-7 distances. Fake atmospheric depth.
"3D only for what's near. Everything else is projected."
"Think globally, not just for the cavern render."

**Macro stamp** (from user's "stamp progression from center 3" sketch):
The 9×9 sketch IS the tile primitive. Same macro stamp + biome config =
cavern chamber, island chain, coastline, forest edge. Position editing
generates any topography. Not yet implemented — next session's architecture.

### Techniques Proven

- **Self-emitting objects:** inner_glow dims ALBEDO (× 0.3), boosts EMISSION (× 3.0).
  Object IS the light. Reference: test_artifacts/Screenshot 2026-04-02 at 5.38.15 PM.png
- **Spore-spread model:** Ring 0 (colony center) → Ring 1 (growth front) → Ring 2 (settlement fringe).
  Ceiling_moss placement mirrors real fungal spore dispersal physics.
- **Radial density gradient:** _radial_factor() scales 0→1 from spawn center to edge.
  158 entities at center → 1947 at edges. Natural cave morphology.
- **Ground pattern inversion:** pow(grain, 2.5) concentrates brightness into piles.
  Dark negative space between. Reads as rubble deposits, not dusty tiles.
- **Filament tilt:** ±28° per-instance lean via position hash. Vine, not ladder.
- **Natural caustics:** Saturated RGB → amber/teal/violet. Cave, not nightclub.
- **Emissive clustering:** One light per cluster, not per entity. 35 entities → 5 lights.
- **Below-ground cull:** z < -0.5 filtered brain-side. Free 30%+ GPU.

### Project Targets

- ~~FOV reconciliation (52° → 62°)~~ DONE
- ~~Stamp system~~ DONE (authored + programmatic anchor stamps)
- ~~Light pop / nightclub effect~~ DONE (pipe architecture)
- ~~Ceiling layer~~ DONE (spore-spread, self-emit, inverted emissives)
- ~~Below-ground rendering waste~~ DONE (z-filter)
- ~~Outdoor biome smoke test~~ DONE (ceiling_moss gated, biome pipes)
- ~~Silhouette shell visual quality~~ SOLVED (dissolve replaces LOD — no silhouette mode at all)
- ~~Light pipe jitter~~ SOLVED (40m lock radius, snap-on-acquire, slow drift)
- Projection banner visual tuning — DEFERRED
- Custom column/crystal meshes — NEXT SESSION (primitives are the bottleneck)
- Anno-style sprite composite layer — NEXT SESSION (membrane nodes)
- Ground shader: darkness defines, light reveals — NEEDS REWORK (attempted, reverted)
- Vector Composite Layer 3 — DEFERRED
- Encyclopedia data seeding — DEFERRED
- Tension visual effects — PARKED

### Commit Trail (feat/render-manifest)
```
572efe1 feat: radial density gradient
9586bfe fix: filament tilt + ground pattern inversion
bfb7921 fix: outdoor biome smoke test
996a053 feat: projection banner — 7 concentric cylinders
2e42408 perf: cull below-ground entities
0248e3c perf: budget motes/decals/beams/drips
5742ca9 fix: remove stale is_beacon
da38a14 feat: light pipe architecture
042926e feat: wall plane depth + 4x mote density
5fbed69 feat: stamps + ceiling + self-emit + persistent lights
79934a6 feat: render shells, macro stamp grid, visual tuning
67cad04 fix: lighting pipeline overhaul — dissolve replaces LOD, pipes lock
```
