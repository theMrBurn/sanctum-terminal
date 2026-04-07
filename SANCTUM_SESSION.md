# SANCTUM_SESSION.md
> Unreliable narrator. The live hash is the particle trail.

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
