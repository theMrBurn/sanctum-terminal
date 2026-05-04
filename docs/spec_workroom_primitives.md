# Spec — workroom primitives library + terrain authoring

**Status:** DRAFT — for redline before any code lands.
**Companion:** `.claude/feature/feat_vector-workroom.md` (active feature spec).

## Premise

Today the workroom ships 5 axis-aligned primitives (cube, octahedron,
pyramid, spire, tetrahedron) and 5 mesh-edit verbs (move_vertex,
add_vertex, add_edge, remove_edge, subdivide_edge). User wants:

1. A primitive library big enough to build platforming geometry — ramps,
   stairs, platforms, curves.
2. A clear path to "bend a cube corner" — get the EDIT sub-mode usable.
3. Floor-attached / ground-anchored objects so terrain feels traversable.

This spec is a **menu**, not a build order. Items are tiered by cost/
benefit; the user picks what ships when. Math is included so any item
ports straight into `core/systems/wireframe_mesh.py` as a built-in.

## Coordinate convention

raylib (Y-up): X right, Y up, Z forward.
Brain (Z-up): X east, Y north, Z up.

Built-ins are authored in **raylib coords** so vertices read intuitively
when looking at the rendered output. The BUILD-mode cursor handles the
brain-axis swap when sending `seed_create`.

## Tier 1 — Right-angled platforming kit (~2 hours)

The minimum viable platforming set. All vertices listed in raylib coords
with mesh centered at origin (Y from 0 to 1 for "ground-resting"
objects so seeds at floor place correctly).

### `wedge` — right-angled ramp

Triangular cross-section in YZ extruded along X. Hypotenuse rises from
front-bottom to back-top.

```
6 vertices, 9 edges
v0 (-0.5, 0.0, -0.5)   front-bottom-left
v1 ( 0.5, 0.0, -0.5)   front-bottom-right
v2 (-0.5, 0.0,  0.5)   back-bottom-left
v3 ( 0.5, 0.0,  0.5)   back-bottom-right
v4 (-0.5, 1.0,  0.5)   back-top-left
v5 ( 0.5, 1.0,  0.5)   back-top-right

edges:
  bottom rect:  (0,1) (1,3) (3,2) (2,0)
  back rect:    (2,4) (3,5) (4,5)
  slope:        (0,4) (1,5)
```

Use: drop at floor level, scale to taste. `+/-` adjusts height of slope.

### `slab` — flat platform

Cube with Y compressed. Authored at full unit dims so `scale` controls
overall size; the slim Y is baked in (10× thinner than X/Z).

```
8 vertices, 12 edges (same topology as cube)
v0..v7 — same as cube but Y = 0 or 0.1 instead of -1 or 1
v0 (-0.5, 0.0, -0.5)
v1 ( 0.5, 0.0, -0.5)
v2 ( 0.5, 0.0,  0.5)
v3 (-0.5, 0.0,  0.5)
v4 (-0.5, 0.1, -0.5)
v5 ( 0.5, 0.1, -0.5)
v6 ( 0.5, 0.1,  0.5)
v7 (-0.5, 0.1,  0.5)

edges: 4 bottom + 4 top + 4 connecting = 12
```

Use: floor tile, foundation, thin platform. Stack at Y=0, 0.5, 1.0…

### `stair` — discrete N-step staircase

Parameterized by N steps, each rise R, run R (default 0.25/0.25, 4 steps
per unit). For N=4: ladder of 4 thin slabs at increasing Y+Z.

```
For N steps:
  4*(N+1) vertices  (each step has a top+bottom rect at offset Y/Z)
  Edges:
    horizontals: 4*N (top of each step, bottom of each step rear)
    verticals:   2*(N+1) (corners up the stair)
    risers:      2*N (the riser edges)
  Total: ~8*N + 2 edges

Vertex generator (in raylib coords, ground-anchored):
  for i in 0..N:
    z = -0.5 + i * (1/N)
    y = i * (1/N)
    emit (-0.5, y, z), (0.5, y, z), (-0.5, y, z + 1/N), (0.5, y, z + 1/N)
```

Use: discrete elevation. 4 steps reads as a stair; 8 steps reads
smoother.

### `corner_l` — L-shaped block (right-angle composition)

Two cubes glued at a corner, axis-aligned. Useful for room corners,
turrets, alcoves.

```
12 vertices, 20 edges
Composed of two unit cubes:
  cube A: corner at (-0.5, 0, -0.5), spans X=[-0.5, 0.5], Z=[-0.5, 0.5]
  cube B: corner at (-0.5, 0, 0.5), spans X=[-0.5, 0.0], Z=[0.5, 1.5]
Shared edge along X=[-0.5, 0.0] at Y=[0, 1], Z=0.5
Net: 12 unique vertices, 20 unique edges (after dedup)
```

Use: corners. Saves placing two seeds + fighting overlap.

## Tier 2 — Curves (~half-day if all are built; pick what's useful)

All parameterized by N (segment count). Default N=8 produces a clean
faceted look that matches the wireframe register.

### `cylinder(N)` — N-sided prism

```
2N vertices, 3N edges
For i in 0..N-1, theta = 2π * i / N:
  bottom: (R cos(theta), 0,   R sin(theta))   — index i
  top:    (R cos(theta), H,   R sin(theta))   — index N + i
edges:
  bottom ring:   (i, (i+1) mod N) for i in 0..N-1
  top ring:      (N+i, N + (i+1) mod N)
  vertical:      (i, N+i) for i in 0..N-1
```

Default R=0.5, H=1.0. Pillar use case.

### `cone(N)` — N base + 1 apex

```
N+1 vertices, 2N edges
v0..vN-1: base ring  (R cos(theta), 0, R sin(theta))
vN: apex             (0, H, 0)
edges:
  base ring:     (i, (i+1) mod N)
  apex spokes:   (i, N) for i in 0..N-1
```

Default R=0.5, H=1.0. Spire variant, also a basic tree primitive.

### `frustum(N, r_top, r_bottom)` — cylinder with different radii

Same topology as cylinder; vertices use `r_bottom` for bottom ring and
`r_top` for top ring. r_top=0 collapses to cone; r_top=r_bottom is a
cylinder.

```
2N vertices, 3N edges
```

Use: lighthouse, tapered pillar, mountain.

### `sphere(rings, segments)` — UV sphere

`rings` latitude bands, `segments` longitude slices.

```
Vertices:
  2 (poles) + (rings-1) * segments
Edges:
  Latitude:    rings - 1 rings × segments edges = (rings-1) * segments
  Longitude:   segments meridians × rings edges = segments * rings
  Pole spokes: 2 * segments

Vertex generator:
  v_north = (0, R, 0)
  for r in 1..rings-1:
    phi = π * r / rings
    for s in 0..segments-1:
      theta = 2π * s / segments
      x = R sin(phi) cos(theta)
      y = R cos(phi)
      z = R sin(phi) sin(theta)
      emit (x, y, z)
  v_south = (0, -R, 0)
```

Default `rings=4, segments=8` → 26 vertices, 56 edges. Heavy for the
wireframe budget — recommend `icosphere(0)` instead for most uses.

### `icosphere(K)` — subdivided icosahedron

Better topology than UV sphere (uniform face area, no pole pinching).
K=0 = raw icosahedron (12 verts, 30 edges); K=1 = 42 verts, 120 edges;
K=2 = 162 verts, 480 edges (over budget).

```
Base icosahedron at K=0:
  12 vertices: φ = (1+√5)/2 ≈ 1.618 (golden ratio)
  v0..v11 = (±1, ±φ, 0), (0, ±1, ±φ), (±φ, 0, ±1) — all permutations of sign
  scaled to unit radius
  30 edges (every vertex pair within 2/√(φ²+1) of each other)

Subdivision:
  for each edge (a, b), insert midpoint, normalized to unit radius
  for each face, replace with 4 sub-faces using the 3 new midpoints
  K=1 → 42 verts, 120 edges
```

Recommended default. Crisp at K=0, smooth-ish at K=1.

### `torus(R_major, R_minor, M, N)` — donut

`M` slices around major axis, `N` slices around minor axis.

```
M * N vertices, 2 * M * N edges
For i in 0..M-1, alpha = 2π * i / M:
  for j in 0..N-1, beta = 2π * j / N:
    x = (R_major + R_minor cos(beta)) cos(alpha)
    y = R_minor sin(beta)
    z = (R_major + R_minor cos(beta)) sin(alpha)
    emit (x, y, z), index = i * N + j

edges:
  major-direction: ((i*N+j), ((i+1)%M)*N + j)
  minor-direction: ((i*N+j), (i*N + (j+1)%N))
```

Default M=8, N=6 → 48 verts, 96 edges. Use sparingly.

### `arch(N)` — half-cylinder cut, extruded

A doorway-shaped wireframe. Half-circle in XY plane, extruded along Z.

```
2(N+1) vertices, 3N+2 edges
Half-circle vertices (N+1 of them):
  for i in 0..N, theta = π * i / N:
    front: (R cos(theta), R sin(theta), -0.5)
    back:  (R cos(theta), R sin(theta),  0.5)
edges:
  front arc:   (i, i+1) for i in 0..N-1
  back arc:    (N+1+i, N+1+i+1) for i in 0..N-1
  spanning:    (i, N+1+i) for i in 0..N
```

Default N=6, R=0.5. Doorways, bridges.

## Tier 3 — Bend-a-cube-corner (PR 5 EDIT sub-mode)

The mesh-edit verbs already ship (PR 3). PR 5 wires them to keys per the
locked AC. **Bend a cube corner is exactly `move_vertex`** on a cube
vertex — already tested in `test_wireframe_edits.py:test_move_vertex_relocates_target`.

The remaining work is the UI:

| Key (EDIT sub-mode) | Op | What it does |
|---|---|---|
| `TAB` | — | cycle vertex selection within the mesh |
| `ARROWS` | `move_vertex` | nudge selected vertex on XZ, 0.1m grid |
| `PgUp/PgDn` | `move_vertex` | nudge selected vertex Y, 0.1m |
| `J` then `TAB` then `J` | `add_edge` | join two selected vertices |
| `C` | `subdivide_edge` | cut selected edge in half (adds midpoint) |
| `N` | `add_vertex` | drop a free vertex at the cursor |
| `DEL` (on edge) | `remove_edge` | sever selected edge |
| `U` | (pop log) | undo last edit |

Per the AC: each edit mutates the seed's `mesh_edits` JSON list and
sends a `seed_update`. The brain replaces the list; the next manifest
re-emits the seed; the client cache notices the new log signature and
replays. Free undo, free persistence.

**Practical effect for "bend a cube corner":** select a cube seed,
`ENTER` → EDIT, `TAB` to vertex 0 (a cube corner), arrows + PgUp/PgDn
to drag it down/in. The cube becomes a wedge. The cube becomes a
deformed crystal. The cube becomes whatever you push it toward.

## Tier 4 — Terrain patch (the platforming ask)

This is the real "draw on the floor" answer. A **terrain patch** is a
new primitive: an N×N grid of vertices, all initially at Y=0, edges
forming a regular grid. It IS a piece of editable floor.

```
For an N×N patch (N=7 default — factor of 7):
  N² vertices: (x, 0, z) for x,z in regular grid spanning [-S/2, S/2]
  Edges:
    horizontal: N * (N-1)   ((i*N+j), (i*N+j+1))
    vertical:   N * (N-1)   ((i*N+j), ((i+1)*N+j))
    optional diagonals:     ((i*N+j), ((i+1)*N+j+1)) per quad
  Total without diagonals: 2N(N-1)
  With diagonals: 2N(N-1) + (N-1)²
```

Default 7×7 = 49 vertices, 84 grid edges (no diagonals) or 120
(diagonals). Sized to span 7m (matches biome 1m grid).

**Authoring**: place a `terrain_patch` seed at floor level. Enter EDIT
sub-mode. `TAB` cycles through the 49 grid vertices. Arrows shift the
selected vertex's Y up/down. Result: a sculpted terrain section —
hill, valley, ramp, basin, plateau, whatever.

**Why this works**:
- 49 vertices isn't enough to be a "real" heightmap, but it's plenty
  for low-poly platforming-style geometry.
- The same 5 mesh-edit verbs that work on a cube work on a terrain
  patch. **Zero new ops needed.** PR 5 unlocks this for free.
- Seeds are just dicts; a `base_mesh: "terrain_patch_7"` slots in
  next to cube without any rendering code change.

**Programmatic terrain authoring** layers cleanly on top:
- `terrain_macros.py:hill(center, radius, height)` — generates a
  `mesh_edits` list of `move_vertex` ops to push grid vertices up
  along a Gaussian.
- `terrain_macros.py:slope(direction, gradient)` — linear ramp.
- `terrain_macros.py:basin(center, radius, depth)` — inverse hill.

So the user's three asks merge: terrain editing IS mesh editing IS
ramp authoring, all on the same op log.

## Math reference table (consolidated)

| Primitive | Params | Vertices | Edges | Notes |
|---|---|---|---|---|
| cube ✓ | — | 8 | 12 | shipped |
| tetrahedron ✓ | — | 4 | 6 | shipped |
| octahedron ✓ | — | 6 | 12 | shipped |
| pyramid ✓ | — | 5 | 8 | shipped |
| spire ✓ | — | 9 | 16 | shipped |
| **wedge** | — | 6 | 9 | T1 — ramp |
| **slab** | — | 8 | 12 | T1 — flat platform |
| **stair(N)** | N=4 | 4(N+1) | 8N+2 | T1 — discrete elevation |
| **corner_l** | — | 12 | 20 | T1 — right-angle composition |
| cylinder(N) | N=8 | 2N=16 | 3N=24 | T2 |
| cone(N) | N=8 | N+1=9 | 2N=16 | T2 |
| frustum(N,rt,rb) | N=8 | 2N=16 | 3N=24 | T2 |
| sphere(R,S) | R=4,S=8 | 2+(R-1)S=26 | (R-1)S + RS + 2S = 56 | T2 — heavy |
| icosphere(K) | K=0 | 12 | 30 | T2 — recommended |
| icosphere(K=1) | K=1 | 42 | 120 | T2 — over budget for many seeds |
| torus(M,N) | M=8,N=6 | MN=48 | 2MN=96 | T2 |
| arch(N) | N=6 | 2(N+1)=14 | 3N+2=20 | T2 |
| **terrain_patch(N)** | N=7 | N²=49 | 2N(N-1)=84 | T4 |

Edge budget per seed for clean rendering: under 200 strongly preferred,
500 hard ceiling per `core/systems/wireframe_mesh.py:max-edges`.

## Phasing recommendation

| PR | Scope | Effort | Unlocks |
|---|---|---|---|
| **PR 4.5** | wedge + slab + stair as built-ins | ~2 hours + tests | Ramps + platforms today |
| **PR 5** | EDIT sub-mode wiring (locked AC) | ~half-day | Bend-a-cube-corner; terrain patch becomes useful |
| **PR 5.5** | terrain_patch built-in | ~1 hour | Floor-anchored elevation |
| **PR 5.6** | `tools/seed_macros.py` — wall, ring, staircase, hill, slope | ~half-day | Programmatic structures |
| **PR 6** | curves (cylinder, cone, icosphere(0), arch) | ~half-day | Doorways, pillars, decorative |
| **PR 6.5** | sphere, frustum, torus, icosphere(K=1) | ~half-day | Niche; defer until needed |

The dependency chain is **PR 4.5 → PR 5 → PR 5.5 → PR 5.6**. Each is
independently shippable. Curves (PR 6+) are pure additions — defer
until a use case demands them.

## What I'd ship next session

If picking one: **PR 4.5 (wedge + slab + stair)**. Smallest possible
slice, biggest immediate UX win — you can build platforming geometry
30 seconds after merge. Does NOT block PR 5 (mesh-edit UI) or anything
else.

If picking two: **PR 4.5 + PR 5**. The combination gives you both
"author from the kit" (Fallout pattern) and "edit the mesh" (Blender
pattern). Everything else from there is decoration.

## Out-of-scope explicitly

- **Bezier / spline primitives** — overkill for wireframe rendering at
  this resolution. If we ever add them, they're sampled to N segments
  and become a polyline, indistinguishable from `cylinder(N)`.
- **CSG (boolean ops)** — union/difference/intersection. Heavy math,
  no use case yet. Defer until a feature needs it.
- **NURBS surfaces** — same.
- **Actual heightmap textures (RGB → height)** — terrain_patch is the
  authoring surface; if you want to import a real heightmap, that's a
  separate spec (sister to `spec_open_source_primitive_pipeline.md`).
- **Collision against placed seeds** — V1 walks through them. Seeds
  are visual; the floor is the only collidable surface. Promotion to
  collidable is a separate feature.

## Open questions for redline

1. **Tier 1 ordering** — wedge first? Or all three (wedge + slab + stair) at once? They're each ~30 min standalone.
2. **Default N for curves** — 8 segments for cylinder/cone? Or factor of 7 (matches biome convention)?
3. **terrain_patch default size** — 7×7 spanning 7m? Or larger (16×16) to be useful for whole rooms? (Recommend 7×7 first — easier to author manually before macros.)
4. **Should `corner_l` ship at all** — or just compose two cubes via two `seed_create` calls? (My instinct: skip; composition handles it.)
5. **Do you want me to start with PR 4.5 right now**, or redline this first?
