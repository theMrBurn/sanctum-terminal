# SANCTUM TERMINAL — Visual Language Specification

## Principle

The visual register is atmosphere-driven, not texture-driven.
Flat-shaded geometry + fog + vertex noise + lighting = the entire aesthetic.
No textures. No normal maps. Color, shape, and depth do the work.

Art direction target: Another World → Flashback → Anno Mutationem.
Not Minecraft (too coarse). Not photorealism (wrong medium).
The sweet spot: recognizable silhouettes, atmospheric depth, color economy.

---

## System-Wide Visual Floor

Every object, biome, and scene must meet these minimums:

| Parameter           | Value                    | Why                                    |
|---------------------|--------------------------|----------------------------------------|
| Vertex noise        | ±12% brightness per vert | Breaks flat-face Minecraft look        |
| Fog                 | Linear, 15-100m range    | Depth + atmosphere, hides draw limit   |
| Ground subdivision  | 12×12 minimum            | Height/color variation, not flat sheet  |
| Primitives/object   | 2-4 minimum              | Readable silhouette at 5m distance     |
| Colors/object       | 2-3 max                  | Color economy, not rainbow             |
| Face shading        | 5 levels (0.3-1.0)       | Directional readability                |

---

## Register Palettes

Four visual registers. Same geometry, different skin.
AtmosphereEngine will eventually drive register selection from ghost blend.

### Survival (default)
- **Feel:** The Long Dark, warm earth, quiet tension
- **Background:** Near-black warm (0.05, 0.04, 0.04)
- **Floor:** Dark brown (0.14, 0.12, 0.10)
- **Fog:** Warm dark (0.06, 0.05, 0.05), range 20-80m
- **Sun:** Warm white (1.4, 0.94, 0.82)
- **Emission:** Objects ≤ 0.2 (fire only)
- **Contrast:** Medium
- **Saturation:** Low

### TRON
- **Feel:** TRON Legacy, digital void, edge-lit geometry
- **Background:** Near-black blue (0.0, 0.0, 0.02)
- **Floor:** Deep blue-black (0.02, 0.02, 0.04)
- **Fog:** Dark cyan (0.0, 0.02, 0.04), range 15-60m (tighter)
- **Sun:** Cool blue-white (0.2, 0.5, 0.8)
- **Emission:** Objects 0.2-1.0 (everything edge-lit)
- **Grid:** Bright cyan (0.0, 0.35, 0.55)
- **Contrast:** Extreme (dark base, bright edges)
- **Saturation:** Zero base, high edge

### Tolkien
- **Feel:** Moria, Rivendell, golden-hour medieval
- **Background:** Deep warm brown (0.04, 0.03, 0.02)
- **Floor:** Warm earth (0.18, 0.14, 0.08)
- **Fog:** Warm dark (0.05, 0.04, 0.03), range 25-90m (wider)
- **Sun:** Deep gold (1.2, 0.85, 0.55)
- **Emission:** Objects ≤ 0.1 (crystals only)
- **Contrast:** Medium-low
- **Saturation:** Low-medium, warm bias

### Sanrio
- **Feel:** Pastel dream, soft glow, kawaii
- **Background:** Soft mauve (0.35, 0.28, 0.32)
- **Floor:** Pastel pink (0.85, 0.70, 0.78)
- **Fog:** Pink haze (0.40, 0.32, 0.38), range 30-100m
- **Sun:** Soft pink-white (1.0, 0.85, 0.90)
- **Emission:** Objects 0.1-0.5 (soft glow everywhere)
- **Contrast:** Low
- **Saturation:** High, pink/lavender bias

---

## Biome Visual Signatures

10 biomes, each defined by floor color, fog color, scatter density, vegetation.

| Biome    | Floor           | Fog             | Trees | Scatter type        |
|----------|-----------------|-----------------|-------|---------------------|
| VOID     | Near-black      | Black           | No    | Remnant (sparse)    |
| NEON     | Dark purple     | Purple haze     | No    | Remnant + geology   |
| IRON     | Rust brown      | Warm brown      | No    | Geology + remnant   |
| SILICA   | Sand beige      | Warm white      | No    | Geology             |
| FROZEN   | Ice blue-white  | White           | No    | Geology             |
| SULPHUR  | Dark yellow     | Yellow haze     | No    | Geology             |
| BASALT   | Dark red-black  | Dark red        | No    | Geology (dense)     |
| VERDANT  | Forest green    | Green haze      | Yes   | Flora + geology     |
| MYCELIUM | Purple-dark     | Purple          | Yes   | Flora + geology     |
| CHROME   | Silver-grey     | White           | No    | Remnant + geology   |

---

## Object Primitive Budget

How many primitives per object class for readable silhouettes:

| Object class    | Primitives | Example                              |
|-----------------|------------|--------------------------------------|
| Pickup item     | 2-3        | Torch (pillar+wedge+spike)           |
| Furniture       | 3-4        | Workbench (slab+pillar×4)            |
| Scatter (small) | 2          | Boulder (block+wedge), stump         |
| Scatter (tall)  | 3          | Crystal spire (pillar+spike+spike)   |
| Tree            | 3-5        | Trunk+canopy+branches (existing)     |
| Structure       | 5-8        | Building (blocks+slab+arch)          |
| Creature        | 4-6        | Body+head+legs+tail                  |
| Vehicle         | 5-8        | Chassis+wheels+cab                   |

---

## Compound Blueprint Schema

Every object in the game follows this format:

```json
{
  "object_id": {
    "grammar": [
      {"primitive": "TYPE", "role": "name", "scale": [w,h,d], "color": "palette_key",
       "parent": "parent_role", "offset": [x,y,z]}
    ],
    "registers": {
      "survival": {"palette_key": {"base": [r,g,b], "edge": [r,g,b], "emission": 0.0}},
      "tron":     {"palette_key": {"base": [r,g,b], "edge": [r,g,b], "emission": 0.0}},
      "tolkien":  {"palette_key": {"base": [r,g,b], "edge": [r,g,b], "emission": 0.0}},
      "sanrio":   {"palette_key": {"base": [r,g,b], "edge": [r,g,b], "emission": 0.0}}
    },
    "tags": ["fingerprint_dimension_1", "fingerprint_dimension_2"],
    "encounter_verb": "THINK|ACT|MOVE|DEFEND|TOOLS",
    "weight": 0.0,
    "use_line": "One sentence shown on REACHABLE label.",
    "description": "Flavor text.",
    "category": "tool|knowledge|geology|flora|fauna|remnant|relic",
    "biome_scatter": false,
    "silhouette": "vertical_crowned|horizontal_layered|compact_heavy|etc"
  }
}
```

---

## Geometry Types

7 primitive types, 4 real shapes + 3 scale aliases:

| Type    | Geometry           | Vertex count | Use case                      |
|---------|--------------------|-------------|-------------------------------|
| BLOCK   | Box                | 24          | Bodies, crates, boulders      |
| SLAB    | Box (flat)         | 24          | Tables, covers, platforms     |
| PILLAR  | Box (tall)         | 24          | Trunks, handles, columns      |
| PLANE   | Subdivided quad    | (n+1)²     | Ground, water, walls          |
| WEDGE   | Triangular prism   | 18          | Roofs, ramps, slopes, caps    |
| SPIKE   | Square pyramid     | 16          | Crystals, flames, thorns      |
| ARCH    | Segmented half-ring| ~72         | Doorways, bridges, rings      |

---

## Color Economy Rules

- **2-3 named colors per object** (e.g., "wood", "fiber", "fire")
- **Each color has base + edge + emission** per register
- **Face shading provides 5 brightness levels** (0.3, 0.5, 0.6, 0.7, 1.0)
- **Vertex noise adds ±12%** per vertex on top of face shading
- **Edge color only visible when emission > 0** (TRON/Sanrio registers)
- **Never more than 4 distinct hues in view** -- atmosphere unifies

---

## Silhouette Readability Test

An object passes readability if:
1. At 50% render scale, you can name what it is
2. Against any background color, the shape reads
3. From 5m camera distance (game default), parts are distinguishable

If it fails any of these, add primitives until it passes.

---

## Import Pipeline (Hybrid)

For objects that need professional proportions:
1. Source: Kenney.nl CC0 packs, Quaternius free models
2. Format: .obj → Panda3D loader
3. Integration: `setColorScale()` applies register palette to imported models
4. Rule: imported models are nouns (torch, chair), compounds are adjectives (scatter, procedural)

---

## What This Document Does NOT Cover

- Shader code (Metal-compatible via `setShaderAuto()`)
- Animation (future -- not in scope yet)
- UI/HUD design (separate concern)
- Sound design (separate concern)
- Post-processing (bloom, color grading -- future)

---

_This is a living document. Update when visual decisions are made._
_The register system is proven. The visual floor is the contract._
