# SANCTUM_SESSION.md
> Unreliable narrator. The live hash is the particle trail.

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
