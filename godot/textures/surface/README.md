# Surface texture library

Drop tileable albedo + normal pairs here. Register them in
`godot/kind_config.json` under `_global.surface_library` and they become
available for any kind, class, or biome plane to reference by name.

## Current entries

| Name              | Albedo                         | Normal                           | Intended use                        |
|-------------------|--------------------------------|----------------------------------|-------------------------------------|
| `default`         | `res://world_grain.png`        | `res://world_grain_normal.png`   | Legacy baseline / global fallback   |
| `stone_rough`     | `res://stone_128.png`          | `res://world_grain_normal.png`   | Boulders, geological kinds          |
| `stone_weathered` | `res://world_grain.png`        | `res://world_grain_normal.png`   | Mega columns, structural kinds      |
| `organic_soft`    | `res://organic_64.png`         | `res://world_grain_normal.png`   | Fungus, moss, organic_flora         |
| `mineral_fine`    | `res://noise_64.png`           | `res://world_grain_normal.png`   | Crystal bases, mineral drip         |

Normals all point at `world_grain_normal.png` as a placeholder — replace
with per-material normals as they're authored/sourced.

## Adding a new surface

1. Drop `<name>.png` and `<name>_normal.png` into this folder (or repo root
   for legacy placement; any `res://` path works).
2. Add an entry to `kind_config.json` → `_global.surface_library`:
   ```json
   "my_surface": {
     "albedo": "res://textures/surface/my_surface.png",
     "normal": "res://textures/surface/my_surface_normal.png",
     "grain_scale": 0.15,
     "grain_strength": 0.6,
     "normal_strength": 1.2
   }
   ```
3. Reference it from a kind or class:
   ```json
   "boulder": { "class": "geological", "surface": "my_surface" }
   ```
4. Or from a biome plane in `core/systems/biome_data.BIOME_PLANES`:
   ```python
   "material": { "surface": "my_surface", "color_base": [...] }
   ```

## Resolution order

When rendering a kind, the material resolver walks:

1. `kinds[<kind>].surface` — explicit per-kind override
2. `_class_defaults[<class>].surface` — class-wide default
3. `"default"` — global fallback, always points at `world_grain.png`

Per-surface `grain_scale` / `grain_strength` / `normal_strength` act as
defaults; any kind can override them via its own `grain_scale` etc. fields.
