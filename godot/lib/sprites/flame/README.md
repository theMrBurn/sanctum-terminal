# Flame sprites

Drop-zone for flame billboard textures sourced from sketches.

## Workflow

1. Sketch a flame in Freeform / Procreate on iPad
2. Export as PNG to `~/Desktop/`
3. Run:
   ```
   python3 tools/sketch_to_sprite.py \
     ~/Desktop/your_flame.png \
     godot/lib/sprites/flame/flame_NAME.png
   ```
4. Reference the result from `kind_config.json` via a flame subpart:
   ```json
   {"family": "flame", "scale": [0.4, 0.4, 0.6],
    "sprite": "lib/sprites/flame/flame_NAME.png",
    "color": [1.0, 0.6, 0.2], "emission": 2.0,
    "offset": [0.0, 0.0, 1.05]}
   ```

The `sprite` path is relative to the Godot project root (`godot/`). The
loader resolves it as `res://lib/sprites/flame/...`.

## Behavior

- If `sprite` is present and the file exists → billboard with that texture
  (Godot's `BaseMaterial3D.BILLBOARD_ENABLED`, alpha transparency, additive
  blend, emission baked from the same texture)
- If `sprite` is missing or path doesn't resolve → procedural shader
  (`flame_billboard.gdshader`) — current behavior pre-sprites

Same `family: "flame"` schema, two backends. Per design_crud_substrate.
