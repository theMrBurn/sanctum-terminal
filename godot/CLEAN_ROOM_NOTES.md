# Clean Room Notes — Inspiration Findings 2026-04-09

Running notes from inspiration study (14 reference shots + Fly Agaric GIF +
3 Panda3D test artifacts). Capture technique ideas surfaced during fungus
work but not yet actioned. **Do not implement without explicit user direction.**

## Shader architecture ideas

### Vertex color support in kind_shader
- Add feature flag `use_vertex_colors: bool` per kind in `kind_config.json`
- When true, shader reads `COLOR` varying from mesh vertex data instead of
  computing 3-color palette from facet normals
- Required for Fly Agaric style toadstool (red cap + white spots + dark ring)
- Required for any kind with "designed" color regions rather than
  facet-driven stratification
- Clean addition: just an `if (use_vertex_colors > 0.5)` branch in fragment()

### 4th color slot (optional)
- Current palette: base / shadow / accent
- Adding "ring" or "detail" color would enable things like:
  - Dark band at base of column (ground contact zone)
  - Moss halo around boulder (biological contact)
  - Cap rim on mushroom
- Trade: more config surface, more uniforms

## Mesh authoring ideas

### Procedural mesh generation for toadstool
- Python script in `tools/` that writes GLB with vertex colors
- Parameters: cap_radius, cap_height, stem_radius, stem_height,
  spot_count, spot_radius, ring_height, ring_thickness
- Outputs 4 variants with hash-driven parameter variation
- No manual 3D tool needed
- Same pipeline for future procedural kinds

### Stacked primitive composition
- Toadstool = hemisphere (cap) + cylinder (stem) + torus (ring) + spots
- Spawn-time assembly into multi-mesh
- Alternative to baked GLB — gives full config control
- Cost: spawn complexity, multi-mesh per instance

## Observations for future passes

### Fly Agaric defines clean-room fungus aesthetic
- Low-poly faceted dome cap (8-12 facets)
- Hard-edge color zones (no gradient)
- Big chunky spots (8-12, each 1-2 polys)
- Slight taper on stem
- Dark base ring grounding to earth
- Target poly budget: ~60-80 triangles, ~100KB GLB

### Scale baseline from existing kinds
- `stalagmite` 9KB / 4.5m — simple tapered spire (lower bound)
- `boulder` 26KB / 5.0m — noisy organic (low-mid)
- `giant_fungus` 86KB / 4.9m — composite (mid)
- `crystal_cluster` 148KB / 4.8m — multi-facet cluster (upper bound)
- Target for toadstool: 60-130KB at 6-7m wide × 6-8m tall (landmark scale)

### Species variation via palette, not geometry
- "A LOT OF MUSHROOMS" pattern: same mesh, different cap colors = species
- Already supported via `color_base` override per kind
- Means we can have `red_cap_toadstool`, `blue_cap_toadstool` etc. sharing
  one GLB with different palettes

## Other clean-room items surfaced (not actioned)

### Crystal colors need darkening (still task #8)
- 0.66 max channel in accent is ~2× any stone
- Target: 0.48 max, preserve blue hue
- Revisit when emission pass begins (pipes back on)

### Ground shader rework (still task #9)
- Panda3D reference shows Voronoi polygon tiles
- "Darkness defines, light reveals" — dark base with bright rubble patches
- Biggest deferred clean-room item
- Reference: test_artifacts/Screenshot 2026-04-02 at 11.28.55 PM.png

### Moss hanging from ceiling
- Real cave photos show moss drapes hanging down
- ceiling_moss + hanging_vine should emphasize this more
- Drape geometry — tendrils not disks

### Mote atmosphere (deferred to atmospheric pass)
- Floating orb cave reference validates strong bloom on tiny lights
- Memory says motes are DORMANT behind early return
- Part of "exit clean room" pass, not clean room work

### Cave entrance framing
- Cartoon entrance assets show stylized rock mouth framing
- Future: "entrance_stamp" as a special stamp type for cave mouths
- Not clean room — this is stamp-library work

### Dark polygonal wireframe aesthetic
- Confirms low-poly direction is valid
- Our outline is broken on Metal (memory: platform_godot_outline_broken)
- When outline is fixed, that aesthetic becomes available
