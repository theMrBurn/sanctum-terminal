# SANCTUM_SESSION.md
> Unreliable narrator. The live hash is the particle trail.

---
SESSION ARC (2026-04-13 ~11:15 → 2026-04-13 ~13:00, ~1.75h active):

Pick up from a511834 on feat/render-manifest. Sandbox — do NOT merge.

DECAL_PROJECTOR primitive → shadow_lab anchor (K) at slot (-2, 0). Config
schema in kind_config.json carries layers[], projection (vector/max_distance),
multiplier (fan/spread_deg/jitter), animation (drift/rotate/pulse). Universal
`_attach_decal_projector(host, cfg)` helper attaches Decal children to any
Node3D. Shadow orbs + creatures consume the same primitive. Drift animation
proven (horizontal ellipse, decals track parent). Prism fan ring mechanic
wired (tilt+yaw around vertical), tight at spread_deg=60 — tuning deferred.

BATS-AS-DECAL → doctrine proven. bat kind_config gets `decal_projector` with
`hide_source: true`. On spawn, all MeshInstance3D descendants hidden via
`_hide_mesh_children` recursive sweep; decal(s) attached via helper. Flock
at encounter_test reads as ~6 soft circles drifting on the floor under
invisible cruisers. Shadow-IS-entity moved from pin to proof.

ELEMENTAL REACTIONS wire → cast → config lookup → manifest event → Godot
pulse. `_global.reaction_patterns` library (fire/ice/electric/light tints,
durations, energies). Per-kind `elemental_reactions` block on
crystal_cluster (all 4), mega_column (electric/light), giant_fungus
(fire/light), bat (ice/light). Brain `pending_casts` queue resolved against
manifest.entities within CAST_REACTION_RADIUS_M=8m. Godot `_apply_reaction_event`
spawns unshaded emissive sphere, tweens scale + alpha over pattern duration.
Stateless by design — state/variety/chains deferred until encounters demand
them.

FOG DISABLED (main.gd:_update_atmosphere) to chase Sable's flat-color look.
Killed per-fragment atmospheric attenuation that painted gradients across
large surfaces. Verdict: better, still not Sable (darkness hides flatness
more than per-fragment math).

FALSE START: pushed giant_fungus onto facet-palette (use_vertex_colors:false
+ widened color_shadow/accent + band_strength bump). Broke the organic
register — fungi read as quarried stone. Reverted + pinned
`feedback_flora_vertex_colors.md`: flora stays on vertex-color path.

Cleaning pass before commit: hardcoded literals extracted to named consts
(REACTION_PULSE_* in main.gd, CAST_REACTION_RADIUS_M hoisted to module-level
in brain_server.py), pattern-level overrides for spawn_radius/height_offset/
scale_peak plumbed through _apply_reaction_event so adding new visual
shapes is pure config.

NEXT: iso dev camera on a fresh branch cut from this commit. Iso compresses
every future visual audit into one-screen comparison.

---
SESSION ARC (2026-04-12 ~20:00 → 2026-04-12 ~23:30, ~3.5h active):

Pick up from a511834 on feat/render-manifest. Sandbox — do NOT merge.

Phase 5.5 collision → cast input → drape kinds → bat flight →
shadow-IS-the-entity headline pin.

PHASE 5.5 — CREATURE COLLISION: rats now bounce off scenery. New
`_push_out_of_collision(pos, radius)` helper mirrors the player's XZ
push-out, applied after flee-move and home-return in `_update_creatures`.
Radius sourced from `kind_config.physics.collision_radius`. Memory
note that pots were "embedded in surface" was stale — GLBs are
authored BASE-origin, no lift needed. Re-confirmed with
project_creature_collision_pending.md (now resolved).

CAST INPUT END-TO-END: 4 input actions (1/2/3/4 → fire/ice/electric/
light). `_send_cast_event(element)` mirrors `_send_tag_event`, payload
`{cmd: "cast_event", cast: {tag_id (negative), element, origin, direction}}`.
Brain `expedition_engine.on_cast_event(cast, t)` appends to tag_log;
`_tag_matches_accepts` already checks `element` first so casts flow
through the same deposit_intent path as tags. New `EXPEDITION_CLASS`
env var picks the class (default anomaly_hunt; set cast_trial to test).

DRAPE KINDS off legacy GLB onto recipe path. `_family_scatter_tissue`
extended with `layout: "drape"` param (single line — inverts strand
Z so the mesh hangs downward from y=0; ceiling-anchored entities
drape below their origin without Godot-side z math). Three kinds
landed: dead_log via rock_lobed elongation=6 flatness=0.3 (3-4m
prone logs), hanging_vine + ceiling_moss via scatter_tissue drape.

COLLISION AUDIT: 7 obstacles had radii smaller than visuals. Bumped
mega_column 5→8 (asymmetric upright variant scales sx_col up to
base_s × 0.85), column 4→5.5, crystal_cluster 1→2.2, dead_log
0.8→2.0, giant_fungus 1.2→1.4. horizon_form/mid/near → 0
(atmospheric, shouldn't collide). Test contract updated.

BAT KIND + FLIGHT: first creature with `behavior_mode: "flight"`.
New dispatch branch in `_update_creatures` → `_update_flight_creature`.
Soft-steer toward waypoint placed ~18m ahead of player heading,
vertical bob, altitude clamp to 5-11m cruise band, GLB visual banks
into turns. Spawn lifts flight kinds to random cruise altitude so
they don't pop from floor. Flight skips `_push_out_of_collision`
(cruising above clutter). Player can't catch them — waypoint
regenerates ahead when proximity closes.

DEBUG GAUNTLET (4 silent failures, each uncovered the next):
1. Bat had no `render` block in kind_config → `KIND_PROPS` filtered
   it silently → brain shipped zero bats → encounter slot was empty.
2. Bat fell through `_family_creature_small` else-branch to placeholder
   sphere → "fat rats floating around like bubbles" (user, approvingly).
   Pinned as `feedback_floating_bubbles.md`: silhouette + drift > anatomy.
3. Bat geometry baked but wings were sub-meshes inside the GLB →
   couldn't animate per-frame. Removed wings from `_build_bat`,
   rebaked body-only.
4. Wings now Godot-native: procedural quads as `bat_wing_L/R` child
   Node3Ds. World-meter dimensions from kind_config.

STOP-MOTION FLAP — the OG sprite-flip trick. Three discrete poses
(`BAT_WING_POSES = [-31°, 0°, +31°]`). Phase advances at `flap_hz × 3`
per second. Right wing trails left by one pose so the silhouette is
asymmetric mid-cycle. Pure snap, never tween. Per-bat phase offset
on spawn so the flock isn't unison. flap_hz 9 → ~27 pose changes/sec
(fast bat-flap; user can dial down).

ENCOUNTER_TEST — second authored anchor at slot (0, 2), world center
(0, 32). 4 corner mega_columns, center crystal+firefly, 6 bats.
Refactored hub instantiation into shared `_instantiate_authored()`
helper. KEY_J teleports there.

THE HEADLINE PIN — SHADOW IS THE ENTITY (`design_shadow_is_entity.md`):

User saw the bat-bodies-as-bubbles, asked about using them to occlude
light sources for projected shadow effects. The conversation cascaded
into a phase-shifting design inversion:

  Conventional rendering: object exists → light hits it → shadow follows.
  This inverts: object exists for behavior/collision/manifest only. The
  renderer NEVER draws the geometry in the player's FOV. A projected
  silhouette decal — anchored to the nearest surface — IS what the
  player sees.

The prism multiplier seals it. One entity emits N silhouette decals
fanned by angle from a virtual light vector → flock of 5 bats from
1 entity, free. Free swarms. Spiders skitter as one entity throwing
six leg-decals around itself. Grass tufts pinwheel as a rotating fan
of grass-blade silhouettes from a single root. The phrasing "filter
that through a prism to create multiple bats from a single source" is
the user's — and it IS the architecture.

Why it's load-bearing:
- Plato's Cave at the engine level. Player only sees shadows. Locks
  the secret-endgame doctrine into the rendering substrate.
- Bypasses Metal's broken per-pixel shading. Decals are the lighting;
  this extends decals to BE the entity layer too.
- Cheaper than mesh rendering at distance — silhouettes don't need
  LOD, don't need shadow-receivers, don't need per-pixel anything.
- Free destructibility — peel a silhouette off, the entity disappears
  without geometry mutation. Pairs natively with atom-skin destruction.

User's lighting lean: let surfaces do the work, avoid beams entirely.
Decision happens after feeling the silhouette register live next session.
Bat is the test fixture (cheapest case, already abstract). If bats
read as "creatures cast as shadows" → generalize to rats, spiders,
even grass.

NEXT SESSION: prototype the bat-as-decal projection. Hide bat GLB,
attach Decal child with bat-silhouette texture, project onto nearest
surface using existing OmniLight registry. See project_next_session.md
for the build path in order.

Magic-show wins along the way: feedback_floating_bubbles.md (silhouette
+ drift > anatomy), the OG sprite-flip flap loop, the encounter_test
slot as a clean iteration fixture for future creature work.

---
SESSION ARC (2026-04-12 ~13:00 → 2026-04-12 ~18:45, ~5.75h active):

Creature visibility hunt → orb pipeline → GLB swap → kind_config refactor.

THE INVISIBLE-CREATURE SAGA: brain shipped rats/pots/chests for hours,
Godot rendered nothing. Cause was layered: scale collapsed by
inherited ent.sx (0.12 for rats), then by hardcoded y=1.0 lifting
atoms below ground at remote tiles, then by `set_surface_override_material`
+ `no_depth_test` breaking billboard mode on Metal, then by GLB renders
ignoring `ent.sx` entirely (using `bounds.scale × sv` instead). Each
fix uncovered the next. Six rounds of "this should work — see screens."

ORB → GLB SWAP: orb pipeline always owns BEHAVIOR (parent Node3D,
flee/scatter state machine). Visual primitive is a swappable child:
`CREATURE_USE_GLB_PATH = true` loads per-kind GLB scaled by
`bounds × kind_config.world_scale_mult`. Pinned in
design_creature_render_arch.md. Cost a session to discover.

KIND_CONFIG REFACTOR (5 phases, all shippable independently):
1. Move `godot/kind_config.json` → `config/kind_config.json` + symlink
   + brain reader (`core/systems/kind_config.py`)
2. Migrate `physics.collision_radius` from `biome_data.HARD_OBJECTS`
3. Migrate `render.scale/color/emissive` from KIND_PROPS (×2 dupes)
4. Migrate `behavior` block from `main.gd CREATURE_KINDS`
5. Delete literal duplicates → derived shims; `HARD_OBJECTS` and
   both `KIND_PROPS` now derive from kind_config

Single source of truth achieved. 1557 tests passing (3 pre-existing
unrelated failures). Schema + reader + 4 migration scripts +
5 new tests pinned in design_kind_config_single_source.md.

DEFERRED to Phase 5.5 (project_creature_collision_pending.md):
- Rats clip walls (movement loop has no collision check)
- Pots embedded in floor (GLB origin at center, not base)

Magic-show wins along the way: red orb fixture
(design_red_orb_fixture.md), config-as-code feedback loop
(feedback_no_hardcoded_tunables.md).

---
SESSION ARC (2026-04-11 ~23:00 → 2026-04-12 ~00:30, ~1.5h active, ~53h cumulative arc):

Pick up from 7ba9532 on feat/render-manifest. Sandbox — do NOT merge
to main. SANCTUM_SESSION.md is allowed to drift — treat the manifest
as an unreliable narrator. This hash is the particle trail.

Twenty-five commits. Opened with the buttress hunt, closed with the
expedition engine + vertex color pipeline fix + Sable-style lighting.

THE WARM-TAN MYSTERY: solved. It was always the buttress. Godot 4
MultiMesh replaces mesh vertex colors — no workaround. Vertex-color
kinds now render as individual MeshInstance3D. sRGB→linear pow(2.2)
in shader. Authored palettes reach pixels for the first time.

EXPEDITION ENGINE: ANOMALY_HUNT class, biome-agnostic schema with
symbolic anchors, full loop end-to-end (tag → deposit → portal →
quit → session log). Two successful completions. 69/69 tests.

SABLE LIGHT: per-object step(), warm amber tint at 12m. Proved the
rules: never smoothstep, never per-fragment, never animate radius,
one layer at a time. Torch flicker, light sheet, motes, cycling,
banner tinting — all tried, all killed. The identity is "lit or not."

NEXT: atmospheric layers one at a time from this clean baseline.
Dust motes first (smallest, gust-synced). Then crystal sconces.
Then palette tuning. Always one variable, always screenshot between.

---
SESSION ADDENDUM (2026-04-12 ~00:30 → ~03:00, ~2.5h, creature
primitives + Sable light tuning + atom-cluster architecture):

Extended the session into creature ghost sprite primitives and
the atom-cluster architecture. Key additions:

CAST_TRIAL expedition class — second recipe with element-gated
deposits (fire/ice/electric/light). Engine generalized: accepts
filters work on both tag_reason and element. 78/78 tests.

CREATURE_SMALL family builder — build_rat (340 tris, composed
from spheres/hemispheres/cylinders) + build_chest (60 tris).
Three palette variants: rat, rat_ice, rat_fire. Staged configs
for spider, bat, slime (placeholder sphere meshes).

ATOM-CLUSTER ARCHITECTURE — creatures rebuilt as mote arrangements
(15 heptagonal atoms for rat, 10 for pot, 8 for chest) instead of
smooth geometry. The construction IS the destruction: scatter the
atoms = destroy the creature. Clay pot = destructible test fixture
with scatter physics + gravity + fade.

SABLE LIGHT TUNING — smoothstep on per-OBJECT distance (6-22m
range). Extended wash, no pop, no per-surface gradient. Tint peaks
at avatar FOV center.

BLOCKED: _spawn_creatures silently errors in Godot. Brain delivers
creature entities (confirmed via tags). Godot never completes the
spawn function. Next session: check Godot debugger for the error.

H = teleport to hub spawn (working). F-keys don't work on Mac.
HUD font bumped 14→24.

HEAD: 7b5675b. Design docs: atom skin destruction + elemental
reaction table + skin definition helper all pinned as memories.
Read design_thoughts.txt at session start — FPS/ISO dual camera
+ Xenogears insight + vector composite skin are the next trajectory.

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
SESSION ADDENDUM (2026-04-10 ~12:00 → ~12:30, ~30min, atom doctrine
+ visual confirmation):

Three things landed back-to-back, closing the spore_pod loop.

  TWO MORE WINS:

  9. ATOM DOCTRINE COMPLIANCE — Caught mid-loop by user observation
     ("we have an Atom Mote structure, didn't we??"). The puffball
     warts had been built as scattered_quads — flat 4-vertex square
     billboards — which violates design_heptagonal_mote.md and
     design_meta_pixel_mote.md. The doctrine says small bright
     markers should be heptagonal atoms (7-sided, prime, non-tiling,
     no rotational sub-symmetry with environmental shapes). Added
     heptagon_billboard() and scattered_heptagons() primitives to
     gen_kind_mesh.py and swapped the wart call in build_puffball.
     Each heptagon = 7 perimeter vertices, fan-triangulated from
     vertex 0 (5 triangles per heptagon). Apron sections reduced
     8 → 6 to free triangle budget for the heptagonal overhead.
     quad_billboard / scattered_quads kept in the library — toadstool
     spots still use them (separately committed kind, not in scope).
     Puffball is the first kind to align with the atom mote doctrine
     at the geometry level.
  10. VISUAL CONFIRMATION — Loop closed. User screenshotted single
      puffballs from 1-2m distance after the heptagon regen + reload.
      All five visual regions readable: dome body, cream wart speckles
      on the upper surface, dark center pore, and a tonal variation
      across the body (the Z-graded crown halo, subtle but present).
      User: "if that's it, it matches the visual language from the
      very good Toadstool rendering." That confirmation is the proof
      that the toadstool recipe scales — composed primitives + vertex
      regions + heptagonal atoms + cream marker speckles work as a
      consistent fungal family across kinds with completely different
      silhouettes.

  CREAM REGISTER IS INTENTIONAL: Initially noted as a gamma-shift
  side effect (SPORE_POD_BODY source RGB (95, 65, 80) was meant to be
  dusty mauve; trimesh → glTF → Godot pipeline shifts brighter to
  cream / light grey on display). User then refined the mycelium
  camouflage doctrine on the spot: *"i like how its distinct, it
  should mimic SHAPE but not color, it has no idea what the stone
  color is, unless it somehow understands chemestry, and i don't
  think we need to render something that deep. it stands out, while
  being a part of the scene."* That makes the cream the CORRECT body
  color for the spore_pod, not an accident to be corrected. The
  mycelium camouflage memory was rewritten to lock this in:
  fungal kinds mimic SHAPE grammar of geological kinds, not color.
  The fungus has no chemistry sense; it borrows form, never pigment.
  Lithops inverted — same shape, distinct pigment. Chromatic mismatch
  is the reveal. This refinement applies to every future fungal kind
  including crystal_cap.

  POLYCOUNT (post-heptagon swap):
    spore_pod_v0  509 tris  bounds 1.22 × 1.11 × 0.33
    spore_pod_v1  539 tris  bounds 1.41 × 1.24 × 0.36
    spore_pod_v2  569 tris  bounds 1.68 × 1.11 × 0.36
    spore_pod_v3  524 tris  bounds 1.43 × 1.24 × 0.38
  All within budget (150-600). bounds.json scale: 1.22.

  PINNED DISCOVERY (this addendum):
    The atom doctrine is the kind of architectural principle that
    has to be ENFORCED at the primitive level — not at the kind
    level. If the gen_kind_mesh primitive library has both
    quad_billboard and heptagon_billboard available, kinds will
    grab whichever they reached for first. The doctrine isn't
    self-enforcing unless the wrong primitive is removed or
    deprecated. Long-term: rename quad_billboard to something
    discouraging (legacy_quad_billboard?) or just delete it once
    every consuming kind is migrated. For now, the only consumer
    of quad_billboard is build_toadstool's spots — those stay until
    the toadstool gets its own atom doctrine pass.

  NEXT STEP: Commit this loop, then pivot to monolith. The recipe
  loop is now battle-tested — read kind, compose primitives, vertex
  regions, hand-tuned variants, eyes-on iteration with one variable
  per change. Apply to monolith next, then boulder, then crystal_cap.

---
Live hash. Updated 2026-04-10 ~12:30. Closing on the spore_pod loop
proper. HEAD: 42c2528. The puffball reads, the recipe scales,
the atom doctrine holds. Cream-register puffballs are now visual
citizens of the same family as the toadstool. Pivoting to monolith
next.

---
SESSION ADDENDUM (2026-04-10 ~12:30 → ~13:00, ~30min, autonomous
run — monolith glyphs + tooling commit):

User instruction: *"yes, lets start the loop, if the trajactory is
explicit in the backup documents, lets go until you loose sync or
drift too far."* Executed two more loops autonomously following the
trajectory in this addendum, stopped at the boulder drift point.

TWO MORE WINS:
  11. MONOLITH HEPTAGONAL GLYPHS — Applied the toadstool recipe's
      missing ingredient (Recognition Marker, #6) to the monolith.
      Built monolith_glyphs() helper that scatters heptagonal
      atom-doctrine billboards across the front and back faces of
      the body slab, with deterministic per-variant glyph_seed so
      each variant carries a unique carving pattern. Added new
      SLAB_GLYPH_COLOR (95, 82, 68) — brighter than SLAB_BODY_COLOR
      for value contrast, same hue family (monolith is real stone,
      no chromatic mismatch needed unlike the fungal mimics). Atom
      doctrine compliant from the start — no scattered_quads
      regression repeated. Per-variant glyph counts: v0 6f+4b dense,
      v1 5f+3b sparse-tall, v2 7f+4b weathered (broken variant
      carries the most marks since it has no capital), v3 4f+2b
      larger-fewer. Polycount 66-86 tris (was 24-36), all distinct
      face counts. The wide-narrow-wide composition was already
      structurally correct; this commit adds the surface marker
      that makes the silhouette read as MONUMENT not generic standing
      stone. Commit: 6affdc7.
  12. TOOLING COMMIT — Three small fixes that eliminate three classes
      of recurring friction. (a) `make meshes` target runs
      gen_kind_mesh.py --all to regenerate every authored kind in
      one shot, eliminating the invisible-build-step problem. (b)
      `make brain` and `make brain-cavern` now declare `meshes` as
      a prerequisite AND set SANCTUM_STAMP=1 explicitly, so the brain
      server can never launch with stale GLBs again AND can never
      regress to the slow TileExchange path again. (c) .gitignore
      additions for *.baseline, godot/meshes/pre_repair_backup/, and
      .claude/ — all three were untracked clutter that kept showing
      in git status. They're recovery artifacts and tooling state,
      not source. Commit: a30a08f.

DRIFT POINT — BOULDER LOOP DEFERRED:
  Stopped before attempting boulder. Reasons:
  - The existing godot/meshes/boulder_v0..v3.glb files have 13 unique
    vertex colors and 216 faces each, generated by something I can't
    trace (no make_rock script in tools/, no build_boulder in
    gen_kind_mesh.py).
  - Replacing them with a new build_boulder() means a blind
    architectural decision: the existing visual vs my proposed
    multi-lobe composition, without seeing either rendered.
  - main.gd has per-instance scaling for boulder (lines 815-823) that
    expects a roughly cubic mesh — a new builder with very different
    bounds could break that scaling.
  - The trajectory says "multi-lobe composition, value contrast crown,
    ground apron, mossy upper surface vertex grading" — explicit
    enough to implement, but not explicit enough to choose between
    "replace existing GLBs" vs "augment alongside" vs "leave alone."

  This is the kind of decision that needs user input. Stopping the
  autonomous loop here and reporting back, per the original
  instruction *"until you loose sync or drift too far."*

WHAT'S NOW TRUE:
  - 4 commits landed since the morning-after triage:
      7a70fa6  spore_pod puffball rewrite + 5 vertex regions
      42c2528  heptagonal warts + mycelium shape-not-color refinement
      6affdc7  monolith heptagonal glyphs + atom doctrine
      a30a08f  make meshes target + brain defaults + gitignore
  - 17/17 gen_kind_mesh tests still passing.
  - .claude/, *.baseline, pre_repair_backup/ no longer in git status.
  - `make brain-cavern` now does the right thing automatically:
    regenerates GLBs, sets SANCTUM_STAMP=1, launches in stamp_world
    mode. The "regression that bit hard" can no longer recur via
    Makefile launch.
  - Brain server still running in stamp_world mode from the earlier
    manual launch (it predates the Makefile change but uses the same
    env var, so it's equivalent).

PINNED DISCOVERIES (this addendum):
  - Atom doctrine compliance is *easier* when applied from the start
    of a kind loop than as a retrofit. Monolith glyphs were authored
    as heptagonal atoms from the first commit; spore_pod warts had
    to be retrofitted from quads → heptagons in a second commit.
    Same end state, half the work when you start right.
  - The drift point is the right place to stop. Boulder is genuinely
    ambiguous (existing implementation, unclear authoring path) and
    pushing through it autonomously would require guessing about
    user intent. The discipline is "stop and ask" not "guess and
    apologize later." Saved the loop discipline a wrong-direction
    iteration.
  - Tooling debt compounds silently. Three separate frictions
    (regen step, brain mode, gitignore clutter) all came from
    "we'll do it later" decisions made in earlier commits. Doing
    them as one focused commit is cheap; doing them inline with
    every kind loop would be hostile.

NEXT SESSION — BOULDER + CRYSTAL_CAP:
  1. Read MEMORY.md + this live hash
  2. Verify HEAD on feat/render-manifest (a30a08f)
  3. Discuss boulder approach with user before touching it. Three
     options: (a) replace existing boulder GLBs with new build_boulder
     in gen_kind_mesh, (b) leave existing boulder alone and add
     features in main.gd's boulder rendering branch, (c) defer
     boulder entirely and skip to crystal_cap. User picks.
  4. Apply chosen boulder approach with the standard recipe loop:
     read current state, propose ONE change, regen, screenshot,
     iterate one variable at a time, commit.
  5. crystal_cap (TBD) — the pending mycelium camouflage pair.
     Crystal-cluster spawn grammar with fungal silhouette. NOT
     crystal blue (chromatic mismatch is mandatory per the refined
     mycelium camouflage doctrine). Possibly a new mycelium_spire
     stamp.

---
Live hash. Updated 2026-04-10 ~13:00. Closing on the autonomous run.
HEAD: a30a08f. Two more kind loops landed (monolith glyphs + tooling
fixes), boulder explicitly deferred at the drift point. Four commits
since the morning-after triage. The recipe is now battle-tested
across three kinds (toadstool by author, spore_pod by retrofit,
monolith by atom-doctrine-from-the-start). Brain server still
running in stamp_world mode. Reload Godot to see the new monolith
glyphs in action; the spore_pod loop is fully closed visually. Next
session opens with the boulder fork choice.

---
SESSION ADDENDUM (2026-04-10 ~13:05 → ~13:55, ~50min, the recipe
sweep — boulder + toadstool + doorframe land in one continuous
arc, every authored kind now recipe-compliant):

User came back from monolith visual confirmation with new tag
screenshots showing the monolith glyphs reading clearly in-engine
(carved heptagonal marks visible on the body, the wide-narrow-wide
silhouette finally reading as MONUMENT). User picked Option A on
the boulder fork choice ("its A for sure"), opening the second
loop of the recipe sweep. Three more loops landed back-to-back,
closing the gen_kind_mesh authored set into full recipe + atom
doctrine compliance.

THREE MORE WINS:
  13. BOULDER VIA GEN_KIND_MESH — Replaced the legacy
      boulder_v0..v3.glb (origin: untraceable, no make_rock script
      in tools/, no build_boulder in gen_kind_mesh.py) with a
      recipe-aligned build_boulder() composed via the same primitive
      library every other authored kind uses. Multi-lobe composition
      (1 main icosphere + 2 secondary at overlapping offsets), Z-graded
      vertex coloring (BOULDER_BASE → BOULDER_CROWN linearly across
      the body, then a moss overlay above moss_threshold lerping
      toward BOULDER_MOSS scaled by moss_strength). The moss is the
      recognition marker — value+hue contrast against the stone body
      that says "this rock has been sitting here long enough to grow
      a coat." Base apron annulus for fake contact shadow. Roughly
      cubic bounds (1.17-1.31m wide × 0.75-0.86m tall) keep main.gd's
      per-instance scaling working without breaking the existing
      boulder placement logic. Boulder is REAL stone, NOT a fungal
      mimic, so the mycelium camouflage doctrine does not apply
      (palette stays in the cavern grey-brown family). Per-variant
      weathering stages: newer fall (sparse moss) → typical settled
      → long-settled mossy → asymmetric main lobe. 304 tris/variant,
      4x smaller GLB than the legacy file (7100 vs 26608 bytes).
      KIND_BUILDERS dict updated to include boulder so make meshes
      regenerates it alongside the other authored kinds. Commit:
      38a75a5.
  14. TOADSTOOL ATOM-DOCTRINE RETROFIT — Replaced the toadstool's
      scattered_quads cap spots with scattered_heptagons. The
      toadstool was the LAST kind in gen_kind_mesh.py still using
      square quad billboards for surface markers (originally authored
      before the atom doctrine landed). Spore_pod got the heptagon
      swap in 42c2528, monolith got heptagonal glyphs from the start
      in 6affdc7, and now toadstool is brought into compliance.
      ZERO behavioral changes other than the geometry of the spots:
      same hash-driven placement, same TOADSTOOL_SPOT_CREAM color,
      same per-spot size variation, same spot count per variant.
      Polycount goes from ~280 → 290-320 tris per variant (within
      the 150-500 budget). Both fungal kinds now share the same
      atomic surface marker primitive. Commit: 626f00a.
  15. DOORFRAME LINTEL RUNES — Adds heptagonal carved runes to the
      doorframe lintel face. Closes the recipe gap on the last kind
      in the gen_kind_mesh authored set. New helper doorframe_runes()
      scatters heptagonal billboards across the front and back faces
      of the lintel, with deterministic per-variant rune_seed and
      front-face bias (player approaches the doorway from the front).
      New palette constant DOORFRAME_RUNE_COLOR (75, 62, 48) brighter
      than DOORFRAME_LINTEL_COLOR for value contrast, same warm stone
      hue family. Per-variant rune counts: v0 dense (5+2), v1 fewer
      tall (4+2), v2 most wide-gateway (7+3), v3 worn ruined (3+1).
      Polycount went 60 flat → 80-110 per variant, all distinct face
      counts. Commit: 1a4a099.

THE GEN_KIND_MESH AUTHORED SET IS NOW FULLY RECIPE-COMPLIANT:
  toadstool   ✅ heptagonal cap spots
  spore_pod   ✅ heptagonal warts on puffball
  doorframe   ✅ heptagonal lintel runes
  monolith    ✅ heptagonal body glyphs
  boulder     ✅ multi-lobe + Z-grading + moss (real stone, no
              fungal markers needed)

All five kinds follow the toadstool recipe. All four marker-bearing
kinds use the same scattered_heptagons primitive. The atom doctrine
holds across the entire authored set. The mycelium camouflage
doctrine has its first implemented pair (spore_pod ↔ boulder
shape-grammar mimicry, distinct palette). The make meshes target
regenerates everything in one command. The make brain-cavern target
auto-launches in stamp_world mode. The .gitignore is clean of
defensive cruft.

EIGHT COMMITS SINCE THE MORNING-AFTER TRIAGE:
  1a4a099  feat: doorframe lintel runes — atom doctrine recognition marker
  626f00a  feat: toadstool atom-doctrine retrofit — heptagonal cap spots
  38a75a5  feat: boulder via gen_kind_mesh — multi-lobe with mossy upper grading
  36ef749  docs: SANCTUM addendum — autonomous run progress, boulder drift point
  a30a08f  chore: tooling commit — make meshes target, brain defaults, gitignore
  6affdc7  feat: monolith heptagonal glyphs — atom doctrine recognition marker
  42c2528  feat: heptagonal warts on puffball + mycelium shape-not-color refinement
  7a70fa6  feat: spore_pod puffball — boulder-mimic with 5 vertex regions

WHAT'S NOW TRUE — FULL CHECKPOINT:
  - 5 authored kinds, all recipe-compliant
  - 4 atom-doctrine-compliant marker-bearing kinds
  - Atom doctrine enforced from the primitive level (heptagon_billboard,
    scattered_heptagons in the gen_kind_mesh library)
  - Mycelium camouflage doctrine refined to "shape only, not color"
    and pinned as design memory (design_mycelium_camouflage.md)
  - Tooling regression-proof: make brain-cavern does the right thing
    automatically, make meshes regenerates everything, .gitignore
    handles defensive cruft
  - 17/17 mesh tests passing
  - Working tree clean
  - Brain server still running in stamp_world mode

PINNED DISCOVERIES (this final addendum):
  - The recipe, the atom doctrine, and the mycelium camouflage
    refinement all converged into a single cohesive visual system
    for the cavern. Five kinds, three doctrines, one primitive
    library, one builder pattern. The morning-after triage was the
    inflection point — three cohesive doctrines emerged from
    investigating one rough night.
  - Sweep commits land faster than initial commits. The toadstool
    retrofit was a 5-minute commit because the doctrine, the
    primitive, and the test budget were all already in place. The
    second time you apply a doctrine to a kind, it's almost free.
  - "Refine and commit" as a forward-momentum framing works well
    when there's a clear backlog of small refinements queued from
    earlier doctrine landings. Three retrofits in 50 minutes
    because each was ONE swap or ONE addition with no design
    decisions.
  - Stopping at the drift point worked. When the user came back
    they had complete information about boulder, picked Option A
    decisively, and the loop landed clean. No wasted iterations
    on guessed-wrong implementations.

NEXT SESSION — CRYSTAL_CAP + WIDE VISUAL PASS:
  1. Read MEMORY.md + this live hash
  2. Verify HEAD on feat/render-manifest (1a4a099 + the doc commit)
  3. Reload Godot in stamp_world mode (brain auto-launches via
     make brain-cavern with everything wired in)
  4. Wide visual pass through the cavern with fresh eyes — tag
     anything that still feels off after all five kinds got the
     recipe + atom doctrine treatment
  5. Decide on crystal_cap next:
     - Silhouette: fungal but NOT cap+stem (toadstool already owns
       that), NOT dome cluster (puffball owns that)
     - Palette: fungal hue family but NOT crystal blue (chromatic
       mismatch is mandatory per refined mycelium camouflage)
     - Composition: must follow the toadstool recipe (composed
       primitives, vertex regions, heptagonal markers, hand-tuned
       variants)
     - Spawn grammar: borrows from crystal_cluster (vertical spike
       cluster, multi-form upright)
     - Stamp: possibly a new mycelium_spire stamp
  6. Execute crystal_cap loop with the standard recipe pattern
  7. After crystal_cap lands, the cavern will have its first full
     mycelium camouflage pair (spore_pod ↔ boulder grammar AND
     crystal_cap ↔ crystal_cluster grammar) plus a complete
     atom-doctrine-compliant authored kind set

---
Live hash. Updated 2026-04-10 ~14:00. Closing on the recipe sweep.
HEAD: 1a4a099. Eight commits since the morning. Five recipe-compliant
authored kinds. Four heptagonal-marker kinds. One mycelium camouflage
pair. The doctrine system is coherent and the tooling is regression-
proof. This is a baseline. Pushing to origin to mark it.

---
SESSION ADDENDUM (2026-04-10 ~14:00 → ~17:30, ~3.5h active, ~51h
cumulative arc — the clean-room normalization sweep, Option 4
refinement, perf telemetry, weighted mega stamps, and the hub PoC
trajectory pivot):

Opened with the recipe sweep baseline from the morning and a user
question: "are the non-compliant kinds rendering like the established
ones?" Closed with the cavern's starting point now an authored
hand-crafted hub the player emerges through. Between: twelve commits,
three architectural additions, one Dr. Seuss detour, one per-kind
revert, one perf measurement run that proved 7-14× headroom over 60fps
floor, and a project-scope pivot from "procedural cavern with mega
anchors" to "authored hub + procedural periphery." First build of the
hub landed with "it all works, no notes" feedback from user — no
iteration needed. This session went further than any prior one in
terms of architectural reach and trajectory change.

PRIOR SESSION RECONCILIATION:
  ~~1. Read MEMORY.md + this live hash~~ — done, multi-round
  ~~2. Verify HEAD on feat/render-manifest~~ — ca1c38e was baseline
  ~~3. Reload Godot in stamp_world mode~~ — done, multi-round
  ~~4. Wide visual pass with fresh eyes~~ — completed via
     normalization sweep then superseded by hub PoC
  crystal_cap — STILL DEFERRED (pending user silhouette+palette input,
     not blocking other work; grammar host crystal_cluster now locked
     to the new crystal_spike family, pair will plug in cleanly)

TWELVE COMMITS, chronological from ca1c38e:
  f63b7b3  fix: boulder use_vertex_colors flag — unblock moss-grading render
  a03915d  chore: recipe schema blocks on compliant 5 kinds (informational)
  a929a6a  feat: build_kind dispatcher + LEGACY_BUILDERS / FAMILY_BUILDERS split
  c75dcc2  feat: tapered_vertical family — stalagmite, column, mega_column, buttress
  9d3259d  feat: rock_lobed family — rubble, cave_gravel, bone_pile
  fd332b5  feat: crystal_spike family — crystal_cluster (Tier 1 anchor)
  24f015e  feat: flora_composed family — giant_fungus (Tier 1 anchor)
  94b8b6b  feat: scatter_tissue family — grass_tuft, leaf_pile, twig_scatter, moss_patch
  902f1d9  fix: Option 4 refinement — revert mega structures, fix grass numbers
  67cc760  feat: perf telemetry — FPS, frame time, draw calls in HUD + tag sidecar
  3a583de  feat: weighted stamp selection — mega anchors now dominate
  a32644e  feat: origin hub — authored starting expedition point

THE ARC IN THREE PHASES:

  PHASE 1 — CLEAN-ROOM NORMALIZATION SWEEP (~14:00 → ~15:30)

    Starting point: 5 kinds compliant via the morning's recipe sweep,
    13 other kinds (stalagmite, column, mega_column, buttress,
    crystal_cluster, filament, exit_lure, giant_fungus, rubble,
    cave_gravel, bone_pile, grass_tuft, leaf_pile, twig_scatter,
    moss_patch, and legacy extract_meshes leftovers) still on the
    facet-palette path with no vertex colors, no atoms, no composed
    primitives. User: "we've got to normalize all of these, so whatever
    order you see fit, the pattern needs to match our established
    visual language."

    Went through an options review ending at "Option 3 Refined" — a
    backwards-compatible dispatcher split where the 5 compliant kinds
    stay byte-identical in LEGACY_BUILDERS and new kinds route through
    FAMILY_BUILDERS with family primitives ported from
    core/systems/ambient_life.py (the legacy Panda3D authoring source).
    Six steps committed in order:

    STEP 1 — BOULDER P0 CONFIG FLIP. build_boulder painted vertex
    colors but kind_config.json inherited use_vertex_colors: false
    from geological class default. Shader was reading facet palette
    and throwing away the moss grading. One-line fix, verified via
    shasum + test pass.

    STEP 2 — SCHEMA EXTENSION. Added informational `recipe` blocks
    (tier, family, variant_count, bounds, variant_spread, apron,
    atoms, family_params) to the 5 compliant kinds. Dispatcher-
    agnostic — the field is documentation, the LEGACY_BUILDERS
    registry is truth for those kinds. 17/17 tests still passing.

    STEP 3 — DISPATCHER SKELETON. Added build_kind(name) dispatcher
    + LEGACY_BUILDERS registry (existing 5) + FAMILY_BUILDERS (empty)
    + _all_known_kinds() loader that unions legacy + config-declared
    kinds whose family is registered. The dispatcher routes
    legacy-first: if a name is in LEGACY_BUILDERS it takes that
    path regardless of config. Otherwise it looks up recipe.family.
    Verified: all 20 legacy GLBs regenerate byte-identical via
    shasum diff.

    STEPS 4-8 — FIVE FAMILY BUILDERS. Each step added ONE family
    primitive + its consumer config rows + a test class, committed,
    legacy-byte-identity re-verified. The families:

      tapered_vertical — stalagmite, column, mega_column, buttress
        revolved noisy profile with flare + 3-stop Z gradient +
        heptagonal atoms on spine. First family, sets the pattern.

      rock_lobed — rubble, cave_gravel, bone_pile
        multi-icosphere cluster with per-axis bounds fit (so
        bone_pile can be elongated 1.8× along one axis). Tier 2
        tissue, no atoms.

      crystal_spike — crystal_cluster
        leverages _build_tapered_vertical_instance as the spire
        sub-primitive with crystalline params (sharp taper, zero
        flare, low noise, few facets). Composes 3 leaning main
        spires + 4 satellite spires. Design Law #13 applied at
        family level — primitive inversion via parameter variation.

      flora_composed — giant_fungus
        stem (via tapered_vertical helper) + hemisphere cap +
        heptagonal atom ring on cap dome. New color_cap field
        in kind_cfg for explicit cap override.

      scatter_tissue — grass_tuft, leaf_pile, twig_scatter, moss_patch
        crossed-quad dome scatter. Billboard primitives. Tier 2.
        Cheapest path in the pipeline.

    After step 8: 96/96 tests passing, all 5 families with real
    consumers, 13 new kinds dispatched through the new path, legacy
    5 byte-identical throughout the entire sweep. Brain restarted
    in SANCTUM_STAMP=1 mode with the new meshes loaded.

  PHASE 2 — OPTION 4 REFINEMENT (~15:30 → ~16:00)

    User walked the normalized cavern and tagged 17 screenshots. The
    feedback was generous — "kind of a cool effect but we regressed
    grass, and my mega structures are gone, so no more wandering
    through an expressive claustrophobic cavern.. its a weird (in a
    good way) Doctor Suess env." The clean-room sweep had produced
    a whimsical forest of tall thin cones because tapered_vertical's
    parameterized approach couldn't carry the character of the legacy
    make_rock erosion grooves that columns/mega_columns had.

    Diagnosis: per-kind granular rather than wholesale revert. The
    crystals and giant_fungus were working (user validated them).
    The tissue kinds were fine but grass_tuft/leaf_pile/etc. had
    been given the wrong cross_width_frac numbers — they rendered
    as flat plates instead of blades. Shape primitive was correct;
    numbers were wrong. The stalagmite/column/mega_column reverts
    were the real fix.

    OPTION 4 LANDED in one commit:
    - grass_tuft: cross_width 0.08→0.015, count 10→18, planes 3→2
    - leaf_pile: cross_width 0.12→0.04, count 8→14, jitter 15°→45°
    - twig_scatter: cross_width 0.22→0.03, count 6→10
    - moss_patch: cross_width 0.10→0.025, count 12→22, jitter 0°→30°
    - stalagmite/column/mega_column: git checkout ca1c38e to restore
      pre-sweep byte-identical legacy GLBs + recipe blocks removed
      from kind_config so dispatcher skips them + removed from
      TestTaperedVerticalFamily parametrize list
    - buttress stayed on the new family path (no legacy state to
      restore to — buttress_v*.glb was introduced by the sweep)
    - crystal_cluster and giant_fungus stayed on new family path
      (user validated visually)
    - tapered_vertical family primitive stayed in code, now with
      buttress as direct consumer + crystal_spike using it internally

    Result: 78/78 tests passing (-18 from removing three kinds'
    parametrize entries), legacy 5 still byte-identical, reverted 3
    byte-identical to ca1c38e via shasum diff. Dr. Seuss preserved
    in c75dcc2's history for future cherry-pick.

  PHASE 3 — PERF TELEMETRY + WEIGHTED STAMPS + HUB POC (~16:00 → ~17:30)

    User asked two questions after Option 4 landed: "are we wasting
    object placement and total count available to view being lost in
    the overlapping of the mega structures" and "how much overhead do
    we have for additional stuff??" Neither was answerable without
    telemetry, so perf instrumentation came first.

    PERF TELEMETRY COMMIT (67cc760):
    Added _read_perf() in main.gd reading Godot's Performance
    singleton. HUD overlay gained seven new field types:
      fps, frame_ms, physics_ms, draw_calls, render_objects,
      render_tris (with K/M suffix), static_mem
    Tag sidecar JSON gained a "perf" block with the full snapshot.
    Lazy reads — only triggered when an overlay field requests them.
    Fields added to kind_config.json > _global > screenshot_overlay.

    USER TAGGED A BOUNDARY WALK (8 tags, radius 40m from spawn):
    Data extraction:
      fps range:       399 – 851   (avg 558, 1s smoothed)
      frame_ms range:  3.77 – 25.78 (TIME_PROCESS, per-frame)
      draw_calls:      52 – 76
      render_objects:  132 – 162
      triangles:       7.7K – 10.7K per frame
      static_mem:      73 – 96 MB
    Translation: we're 7-14× over 60fps floor, GPU is asleep (0.1%
    of tri budget), CPU spikes on update frames (22-25ms _process)
    are MultiMesh rebuilds not render work. Massive headroom for
    more entities, denser stamps, bigger render_horizon, or all
    three at once.

    WEIGHTED STAMP SELECTION COMMIT (3a583de):
    stamp_world's rng.choice(CAVERN_STAMPS) was uniform across 16
    entries of which only 3 were mega stamps — 19% mega rate, ~1.7
    mega per view. Added `weight` field to stamp recipes (default 1)
    + _weighted_pick helper. Mega stamps at weight 4 pushes share to
    48% (empirically verified via 1600-slot sample: 47.9%). Player
    now sees ~4.3 mega anchors per view instead of 1.7.

    User's response: "i like that density, what i am experiencing is
    this, upon spawn, im in a cluster of them at wherever i am on the
    map." That cluster experience was the seed of the trajectory
    pivot — the complaint turned into a design opportunity.

    ORIGIN HUB POC COMMIT (a32644e):
    User: "could we lean into this situation, and build literal arches
    to emmerge through?? lets look at the stack, and see if we can
    build a logical solution, turn this starting qr code stamp into
    the literal starting point that has everything somebody would need
    on a whole expedition, can we change the project scope and
    trajectory to make that happen as our short term proof of concept?
    - using everything we have now, with this as the new baseline
    starting point?"

    A formal project-scope pivot request, with the constraint that
    the PoC use only what we already have. Planned in depth before
    writing code (see feedback_plan_before_code.md). Three moves
    proposed, user blessed ("you are blessed"), executed in one
    session with no iteration.

    MOVE 1 — ORIGIN_HUB stamp in biome_data.py. 57 members at ~30m
    footprint centered at world (0, 0), using all 17 in-scene kinds.
    Layout:
      Center: mega_column axis mundi + crystal beacon + 3 fireflies
      N arch: doorframe + two mega_column flankers
      E arch: column + two buttresses
      S arch: doorframe + two monoliths (ancient gate)
      W arch: column pair + mega_column backer
      NE quadrant: toadstool grove (food/warmth)
      SE quadrant: spore_pod + giant_fungus (forage/fungal partner)
      SW quadrant: bone_pile + crystal (relic/memento mori)
      NW quadrant: boulder alcove + crystal (shelter/beacon)
      Inner floor: moss_patch/grass_tuft/cave_gravel
      Perimeter: 8 stalagmites between arches (visual walls)
    Each arch uses DIFFERENT gateway grammar so the player learns
    the visual vocabulary by walking through all four.

    MOVE 2 — stamp_world origin override + hub-adjacency filter.
    New _instantiate_hub() emits ORIGIN_HUB members at world (0, 0)
    (not slot center) when called for slot (0, 0) in cavern biome.
    The 8 adjacent slots exclude mega stamps from their weighted
    pool so the hub silhouette survives against its surroundings.
    Everything beyond the 9-slot neighborhood uses the weighted
    pool unchanged (still 48% mega share).

    MOVE 3 — spawn at south arch (main.gd). _aim_spawn_heading now
    branches on biome: cavern forces camera to world (0, -14, EYE_HEIGHT)
    facing +Y (rotation.y = PI, 8° upward tilt). Non-cavern falls
    back to _legacy_landmark_aim(). Light pipes + banner cylinders
    extracted into shared _finalize_spawn_scene() helper called by
    both branches.

    FIRST BUILD LANDED WITH "IT ALL WORKS, NO NOTES" from user on
    first reload. No iteration cycles, no screenshot rounds. The
    plan absorbed the risk up front — see PINNED DISCOVERIES below.

WHAT'S NOW TRUE — FULL CHECKPOINT:
  - 18 kinds dispatchable through build_kind()
      * 5 legacy (toadstool, spore_pod, doorframe, monolith, boulder)
      * 13 family-dispatched (buttress, crystal_cluster, giant_fungus,
        rubble, cave_gravel, bone_pile, grass_tuft, leaf_pile,
        twig_scatter, moss_patch)
      * 3 reverted-to-legacy-GLBs (stalagmite, column, mega_column) —
        no recipe block, dispatcher skips, Godot loads committed GLBs
  - 5 family builders, all with real consumers
      * tapered_vertical (buttress + crystal_spike helper)
      * rock_lobed (rubble, cave_gravel, bone_pile)
      * crystal_spike (crystal_cluster)
      * flora_composed (giant_fungus)
      * scatter_tissue (grass_tuft, leaf_pile, twig_scatter, moss_patch)
  - 78/78 gen_kind_mesh tests passing
  - Perf telemetry in HUD + tag sidecar (FPS, frame_ms, draw_calls,
    objects, triangles, memory)
  - Weighted stamp selection at 48% mega share across the cavern
    (excluding hub neighborhood)
  - Origin hub authored at slot (0, 0): 57 members, 17 kinds, 4
    cardinal arches, 4 provision quadrants, walkable interior
  - Spawn at south arch (0, -14) facing north into hub
  - 9-slot hub neighborhood has mega stamps filtered out
  - Everything outside the neighborhood runs weighted stamp pool
  - Brain-cavern entity count: ~4200 (hub adds ~57, adjacent slots
    quieter, rest unchanged)
  - Measured perf headroom: 400-850 fps = 7-14× over 60fps floor
  - Legacy 5 still byte-identical to pre-sweep hashes (ca1c38e)

ARCHITECTURAL SHIFTS:
  - tools/gen_kind_mesh.py: gained LEGACY_BUILDERS + FAMILY_BUILDERS
    split, build_kind() dispatcher, 5 family primitives, _load_kind_config
    cached reader, _all_known_kinds() union. ~500 lines added.
  - core/systems/biome_data.py: gained ORIGIN_HUB (57-member authored
    composition), weight field on 3 mega stamps.
  - core/systems/stamp_world.py: gained _instantiate_hub,
    _weighted_pick, hub origin override, 9-slot adjacency mega filter.
  - godot/kind_config.json: gained recipe blocks on all new kinds,
    color_cap field for flora_composed, new overlay fields for perf.
  - godot/main.gd: split _aim_spawn_heading into biome branches +
    _finalize_spawn_scene helper, added _read_perf, added 7 HUD
    field types, added perf block to tag sidecar.
  - tests/test_gen_kind_mesh.py: gained TestTaperedVerticalFamily,
    TestRockLobedFamily, TestCrystalSpikeFamily, TestFloraComposedFamily,
    TestScatterTissueFamily — 61 new assertions total.
  - Memory system: project_hub_poc.md, design_hub_and_spoke.md,
    feedback_plan_before_code.md, project_next_session.md rewritten.

PERF TELEMETRY NUMBERS (8-tag boundary walk, radius 40m from spawn):
  fps smoothed:     399 – 851  (avg 558, 7-14× over 60fps floor)
  frame_ms process: 3.77 – 25.78 (spikes on update frames only)
  draw calls:       52 – 76 (5-7% of comfort zone)
  render objects:   132 – 162 (1.5% of comfort zone)
  triangles/frame:  7.7K – 10.7K (0.1% of GPU budget)
  static memory:    73 – 96 MB (negligible)

  Headroom estimate: 7× current entity count before 60fps floor.
  Could double render_horizon AND tighten slot grid AND triple tissue
  density and still have 3× headroom remaining.

PROJECT TRAJECTORY PIVOT — "AUTHORED HUB + PROCEDURAL PERIPHERY":
  The cavern is no longer a flat procedural scatter. Spawn is an
  authored ritual: player emerges through the SOUTH arch of a
  hand-crafted hub at world (0, 0), facing north into the axis
  mundi mega_column. The hub is the physical expression of multiple
  pinned design memories converging into one concrete deliverable:
    - design_frame_composer (directed wandering, composed spatial frames)
    - design_spawn_macro_stamp (9x9 sketch AS the tile primitive)
    - design_journal_quest_pipeline (hub = ledger location, expedition
      = walking out and back)
    - design_path_memory (return trips free via pure-function world)
    - design_passive_pull_loop (axis mundi = peripheral pull center)
    - design_approach_reveal (hub visible as silhouette on return)
    - design_wayfinding (hub = the one guaranteed landmark)
  Pinned as project_hub_poc.md + design_hub_and_spoke.md.

PINNED DISCOVERIES (this session):
  - Plan deeply before code on trajectory-shifting moves. The hub
    PoC plan named every kind's role, every arch's grammar, every
    coordinate ahead of time, and what was explicitly out of scope.
    Implementation landed first-try with "no notes." Contrast with
    the earlier Option 3 sweep that produced Dr. Seuss: same plan
    shape but shallower depth. Plan shape was correct (backwards-
    compatible dispatcher split) but didn't pressure-test whether
    the family primitives could CARRY the visual character of the
    specific kinds they'd replace. Depth-of-plan correlates directly
    with first-build quality. Pinned as feedback_plan_before_code.md.
  - Per-kind granular revert beats wholesale revert. Option 1 from
    the options review was "full Tier 1 revert" — would have thrown
    away working crystals and fungus along with the failed columns.
    Option 4 ("per-kind based on visual evidence") preserved the
    wins and fixed only what was broken. The dispatcher architecture
    enabled this — legacy GLBs can coexist with family-dispatched
    kinds in the same pipeline.
  - Perf concerns often evaporate under measurement. User's intuitive
    concern was "are we wasting cycles on mega overlap" — the answer
    turned out to be "no, we're at 0.1% of GPU budget and MultiMesh
    is handling overlap for free." The cost of adding perf telemetry
    was trivial (~30 lines) and the payoff was unlocking confidence
    to pivot project scope. Measurement is cheap when the telemetry
    infrastructure already exists; add it early, use it often.
  - The stamp system was hub-ready and we didn't know it. Pure-
    function world = free path memory = return trips work. Stamp
    composition grammar = hand-authored hub uses the same recipe
    format as procedural stamps. Weighted selection = adjacent-slot
    filtering without touching the rest of the pool. The hub PoC
    required zero new engine concepts — only recombination of what
    already existed. The stack was designed for this without the
    designer knowing it.
  - "No notes" on first build is a signal worth capturing as memory.
    It means the plan absorbed all the risk. The memory system's
    whole point is to recognize these inflection moments and pin
    the patterns that produced them.

NEXT SESSION — OPEN-ENDED FROM THE HUB:
  The baseline is now the hub and the procedural periphery around it.
  Next moves are user-directed. Candidate threads, all clearly
  describable from the current state:

  VISUAL / SPATIAL
  - Walk the hub more, tag anything that should be refined
  - Author hubs for other biomes (outdoor forest spawn composition)
  - Tighten or loosen hub-adjacency transition based on feel
  - make_rock erosion port for tapered_vertical family so
    stalagmite/column/mega_column can rejoin the recipe path without
    losing character (explicitly deferred in Option 4 plan)
  - crystal_cap (pending mycelium pair with crystal_cluster, still
    needs user silhouette+palette decision)
  - Ceiling_moss + hanging_vine recipe (the 2 drape kinds still on
    legacy path, could be new family or scatter_tissue extension)

  SYSTEMS (downstream from hub)
  - Collision so player stops walking through mega_columns
  - Quest ledger at hub — provision quadrants as actual caches
  - Tension triggers at arch thresholds — crossing an arch toward
    periphery engages tension, crossing back dissipates
  - Save state: (seed, player_pos) hub-invariance guarantees
    persistence cheaply
  - Journal pipeline integration (design_journal_quest_pipeline
    finally gets wired)

  TOOLING / TELEMETRY
  - Incremental MultiMesh updates — the 20-25ms _process spikes on
    manifest updates are full rebuilds. Known Godot pattern: diff +
    partial update. Unlocks sustained 120+ fps target.
  - OccluderInstance3D for mega_columns — saves vertex work at
    higher density
  - Rolling FPS graph overlay — the HUD shows instant values, a
    graph would show spike patterns

  Pick whichever thread has the highest pull-through momentum.
  The plan-before-code discipline applies: if the move is trajectory-
  shifting, plan in depth first.

---
Live hash. Updated 2026-04-10 ~17:30. Closing on the clean-room
normalization sweep + hub PoC trajectory pivot. HEAD: a32644e. Twelve
commits since the morning recipe baseline. The cavern has an authored
starting point for the first time. 7-14× perf headroom measured.
The dispatcher architecture absorbs authored and procedural content
in the same pipeline. Every pinned design memory about spatial
composition now has a physical expression at slot (0, 0). First
build landed "no notes" — the plan absorbed the risk. This is the
new baseline. Stop here or pick up any of the NEXT SESSION threads.

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

## 2026-04-17 Session — The Physics Rig + Fade Tuning + Scout Loop Closure

Long arc that started on the FPS collision pending issue from the prior
session and ended with the cavern-as-overlay-substrate doctrine
(`design_north_star`) wired end-to-end via passive auto-arm. 15 commits.
Three commits-of-record: rig migration, fade pass-2 (the winner), scout
endless cavern with auto-arm. Plus a brain crash fix that explains
several "we lost the world" mid-session perceptions.

### Wins, in order of landing

1. **CharacterBody3D rig migration (2-commit landing, gated by feature flag)**
   The hand-rolled Camera3D + manual XZ sphere-distance push-out player
   was retired. New rig: `CharacterBody3D` (yaw + collide + move_and_slide)
   → `Neck Node3D` at `EYE_HEIGHT` (pitch + crouch lerp) → `Camera3D`
   (lean offset only). Real `StaticBody3D + CylinderShape3D` colliders
   emitted per-instance in `_create_multimesh_variant` (`r = brain_r,
   h = 6.0`, 80m spawn-radius cull). Floor + wall planes wrapped in
   `StaticBody3D` in `_spawn_plane`. `_player_pos / _player_yaw /
   _player_pitch / _teleport_player` helpers route ~20 read-write sites
   so `camera.global_position` / `player_rig.rotation` resolve correctly
   in either branch. Both paths shipped behind `USE_PHYSICS_RIG = true`
   (`6bbbf89`, plus `885315e` to fix a pitch-doubling regression where
   the legacy 10° `camera.rotation_degrees.x` stacked on top of neck
   pitch). After hours of UAT, the legacy branch was deleted as commit
   2 — net −154 lines, single canonical path (`4117b67`).

2. **Per-object distance fade-in with Bayer 4×4 dither (no more pop-in)**
   `kind_shader.gdshader` gained `fade_in_near` / `fade_in_far` uniforms.
   Per-OBJECT camera distance (`distance(instance_origin,
   CAMERA_POSITION_WORLD)`), `1.0 - smoothstep(near, far, d)` alpha,
   resolved via 4×4 Bayer ordered dither discard. Stays on the Metal
   opaque pipeline (per `platform_metal_no_shaders`). Replaces the
   render-horizon "wall" with gradual emergence. (`a380db4`)

3. **Per-class fade bands tiered by structural role (3-pass tune)**
   Anchors persist into fog, tissue fades aggressively. Pass 1 introduced
   the tier shape via `_class_defaults` in `kind_config.json`
   (structural 15/100, geological 5/50, organic 2/25, atmosphere 2/25,
   life 3/35, horizon 0/400) plus per-kind overrides for rubble +
   cave_gravel (`0815e7e`). Pass 2 widened all bands to fix a stepped
   dead zone at 25-50m (`6c9fe97`). Pass 3 — the winner — pushed tissue
   to 3/70 and atmosphere/life to 3/65 so three tiers overlap across
   the whole fog zone, killing the "wall of columns" silhouette
   isolation (`ed8391e`). `_create_kind_material` reads both fields and
   pipes them to the shader.

4. **Scout completion → endless cavern + manual `[P]` quest-accept hook**
   `ExpeditionEngine.on_walk_through` reaching `COMPLETE` now also nulls
   the brain's `expedition` ref. `world.get_manifest()` keeps streaming
   scenery — the cavern is the substrate, the scout was an overlay
   (per `design_north_star` + `design_journal_quest_pipeline`). New
   `{"cmd": "begin_scout"}` brain-side handler spins up a fresh engine
   on demand. Godot `KEY_P` sends the cmd, `_process_responses` handles
   the `scout_status` ack. `_on_expedition_resolution` toasts "Scout
   complete — [P] to begin another" instead of silent fade. (`89b3512`)

5. **Passive auto-arm via `lifecycle.auto_arm` config (no key press needed)**
   `BIOME_EXPEDITIONS[biome]` gained a `lifecycle.auto_arm` block with
   three trigger modes (`hub_return | complete | cooldown`), `hub_pos`
   + `hub_radius` for proximity gating, `cooldown_s` for dead-air
   minimum after EXPEDITION COMPLETE, and `rotation: [class_id]` for
   chained scouts. Brain reads it each camera tick; rising-edge
   detection so re-entering the hub re-arms instead of staying in the
   hub re-firing. Cavern wired to `hub_return` at (0, -14) with 12m
   radius and 5s cooldown. Outdoor declares `enabled: false` until
   its hub anchor lands. Manual `[P]` stays as override. (`d6d23c7`)

6. **Brain mid-write disconnect crash fix**
   `brain_server.py:1326` — when Godot reloaded a scene mid-stream, the
   brain's write hit `BrokenPipeError`, the handler `break`ed out of
   the outer `while True:` accept loop, and the whole brain process
   died. Other disconnect handlers (no-data, reset) correctly use
   `continue`; the write handler now matches. Reproduced multiple
   times this session before the fix landed; explains several "we
   lost the world" perceptions. Also clears `encounter` + `roaming`
   refs on disconnect so the next Godot connect gets fresh state for
   all three components. (`f66695b`)

7. **HUD heartbeat live (4 Hz overlay refresh)**
   Prior to this, `_update_hud()` only fired on entity rebuild + TCP
   state-change. When the player hovered in a tile (no rebuild) the
   HUD froze at its init reading — `Engine.get_frames_per_second()`
   returns 0/1 before the first frame, draw_calls = 0, looked like a
   dead engine. New `HUD_REFRESH_INTERVAL = 0.25` in `_process` ticks
   `_update_hud()` at 4 Hz. Cheap (one string build + Performance
   monitor reads). Verified the actual engine state matches the HUD
   reading via tag perf sidecars. (`6dc2965`)

8. **Aseprite Wizard plugin staged (sprite pipeline ready)**
   User is learning Aseprite for hero-object + character sprites.
   `viniciusgerevini/godot-aseprite-wizard` v9.8.0 (MIT) copied to
   `godot/addons/AsepriteWizard/`, intentionally NOT enabled in
   `project.godot` — user toggles via Editor → Project → Plugins
   when they sit back down. Once enabled, `.aseprite` files dropped
   into `godot/lib/sprites/` (or wherever) auto-import as
   `SpriteFrames` resources. Pinned as memory `user_sprite_pipeline`.
   Also staged `henriquelalves/SimpleGodotCRTShader` to
   `godot/studies/crt_shader/` (pointer-only, Phase 3 deferred).
   (`88acd51`)

9. **A/B-safe recipe meshes for stalagmite / column / mega_column**
   The recipe-coverage scoreboard had three holdouts on legacy
   hand-authored GLBs because earlier recipe attempts couldn't hold
   the erosion + flare profile. `_family_tapered_vertical` (used by
   buttress) actually does support that profile — needed only the
   wiring. `gen_kind_mesh.export_kind` gained an optional `output_name`
   parameter; recipe blocks added for the three kinds with
   `output_name: <kind>_recipe`. Generates `_recipe_v0..v3.glb` on
   disk alongside legacy GLBs without overwriting them. `MESH_ALIAS`
   in `main.gd` untouched — runtime stays on legacy. User flips
   `MESH_ALIAS` per-kind to A/B test. Documented in
   `godot/meshes/RECIPE_AB.md`. Recipe coverage 5/8 → 8/8
   dispatcher-ready. (`5886f7e`)

10. **Affinity-driven companion spawn recipes (schema upgrade)**
    Replaced fixed `COMPANION_SPAWNS` dict
    (`{comp:count, radius}`) with affinity-driven recipes:
    `{pool: [{kind, weight, max}], spawn_chance, radius_range,
    max_total}`. Adjacent anchors get varied companion mixes via
    weighted-random pool selection. Cavern + outdoor recipes both
    migrated; mega_column gains rare `crystal_cluster` pulls
    (weight 0.4), dead_log gains `leaf_pile` + `twig_scatter`,
    giant_fungus pulls `firefly`. Consumer in `ambient_life.spawn()`
    rewritten to roll `spawn_chance`, weighted-pick K members
    (eligibility-filtered by per-pool `max`), drop each at random
    distance in `radius_range`. Duplicate `COMPANION_SPAWNS` in
    `ambient_life.py` removed; now imports from `biome_data`
    (single source of truth). NOTE: this targets the legacy
    `ambient_life.spawn()` path. The live brain pipeline uses
    `CAVERN_FLOURISH_POOLS` via `RosterPool` in `world_gen.py`
    — that surface is the natural next refactor target if
    affinity-driven density should appear at runtime. The
    schema upgrade sets the shape; FLOURISH_POOLS migration would
    mirror it. (`07f4457`)

11. **Misc landings**
    - **Diagnostic `[RIG]` log** (`266439e`) — disposable per-second
      print of `_player_pos / rig.position / is_on_floor` to confirm
      the rig moves; flag flipped off once `pp` was confirmed shifting.
    - **Spawn pitch fix** (`885315e`) — see #1 above; called out
      separately because it landed as a hotfix between rig migration
      and the next visual change.

### Test state

- 1720 passing on this branch (+ 11 pre-existing failures unchanged
  by this session: 9 in test_kind_config / test_render_shells /
  test_screenshot_overlay / test_wall_planes, 1 in test_campaign_engine,
  1 in test_kind_config from a stale palette assertion). Verified by
  stashing the session diff and re-running the failing tests on
  baseline.

### Project Targets — Updated

Strikethroughs are this session's wins:

- ~~FPS collision pending (rig clipping through columns)~~ DONE — rig
  migration replaced manual push-out with `CharacterBody3D + StaticBody3D`
- ~~Pop-in at render horizon~~ DONE — distance fade with Bayer dither
- ~~Mid-distance dead zone (anchors arrive, tissue gone)~~ DONE — pass 2
  fade bands stack three tiers across the whole fog zone
- ~~Scout completion empties world (felt like procgen broke)~~ DONE —
  expedition is overlay; brain keeps streaming after COMPLETE
- ~~Manual quest-accept hook~~ DONE — `[P]` sends `begin_scout`
- ~~Passive scout re-arm on hub return~~ DONE — `lifecycle.auto_arm` config
- ~~Brain dies on Godot mid-write disconnect~~ DONE — `continue` not `break`
- ~~HUD frozen at init values~~ DONE — 4 Hz heartbeat in `_process`
- ~~Aseprite pipeline gate~~ READY — Wizard staged, waiting for first sprite
- ~~Recipe coverage scoreboard~~ DISPATCHER 8/8 — runtime 5/8 (A/B safe)
- ~~Companion spawn schema~~ DONE — pool/weights/chance/radius_range
- FLOURISH_POOLS migration to affinity schema — NEXT (mirrors COMPANION
  shape, but on the live brain pipeline path; 30-45 min)
- Auto-arm hub-return UAT — pending play test (no code; just verify
  the brain log prints `auto-armed scout: anomaly_hunt (trigger=hub_return)`
  on hub re-entry after a completed scout)
- crystal_cap silhouette + palette — gated on user sketch (Procreate)
- Vector composite skin PoC — gated on first Aseprite sprite drop
- Tension choreography rhythms — PARKED (framework built, choreography
  config + per-encounter signatures still deferred)

### Path Forward — Next Session

Three natural picks:

1. **FLOURISH_POOLS migration** — apply the affinity schema (pool +
   weights + chance) to `CAVERN_FLOURISH_POOLS` /
   `OUTDOOR_FLOURISH_POOLS` so the live brain pipeline gets the same
   emergent variety the legacy path now has. Mirror the shape. Test
   in-game by walking the same loop pre/post and looking for varied
   companion mixes per anchor.

2. **Hub-return verification + scout-loop UAT** — start a scout,
   complete 10 tags, walk through south arch, get the toast, walk
   back into hub, watch brain log for the auto-arm print. Closes
   the auto-arm loop with empirical evidence.

3. **First Aseprite sprite ingest** — once the user drops a first
   sprite into `godot/lib/sprites/`, enable the Aseprite Wizard
   plugin and import as SpriteFrames. Then start the Vector composite
   skin PoC (item 5 in design_thoughts.txt) — billboard sprite child
   on a primitive parent. Test on a single kind first (clay_pot or a
   specific decorative entity).

Procreate / Aseprite work is now the highest-leverage axis — sprite
authoring unlocks the Xenogears ISO state machine, the vector
composite skin PoC, and crystal_cap simultaneously. Code-side, the
configuration surface is in good shape after the affinity schema +
fade-band tiering. The visual cohesion the user has been chasing
"for what feels like weeks" landed in this session.

### Commit trail (this session)

```
07f4457 refactor: affinity-driven companion spawn recipes (pool + weights + chance)
5886f7e feat: A/B-safe recipe meshes for stalagmite/column/mega_column
4117b67 refactor: delete legacy Camera3D push-out path (commit 2/2)
f66695b fix: brain survives Godot mid-write disconnects (was killing whole loop)
88acd51 chore: stage Aseprite Wizard plugin + CRT shader study + palette audit doc
d6d23c7 feat: passive scout auto-arm via biome lifecycle config
89b3512 feat: scout completion loops back to endless cavern; [P] begins new scout
ed8391e tune: pass 2 fade bands — push tissue into midground, dead zone was real
6c9fe97 tune: widen + overlap fade bands so depth reads continuous
0815e7e feat: per-class fade-in bands — anchors persist, tissue fades aggressively
a380db4 feat: per-object distance fade-in with Bayer dither — no more pop-in
6dc2965 fix: refresh HUD overlay at 4 Hz so it stops lying about perf
266439e debug: log player pos + send rate to diagnose tile-streaming regression
885315e fix: rig-mode spawn pitch doubled to 18° via stacked camera+neck tilt
6bbbf89 refactor: native Godot physics for player (commit 1/2)
```
