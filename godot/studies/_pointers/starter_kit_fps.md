# Kenney Starter Kit FPS — pointer

**Origin**: https://github.com/KenneyNL/Starter-Kit-FPS
**License**: MIT (code), CC0 (assets)
**Godot version**: 4.5 (originally 4.3)

## Why not copied locally

It's primarily a **CC0 asset pack** bundled as a Godot project. The code is a
simple FPS starter, but the *value* is the included public-domain sprites +
3D models that match user's already-owned Kenney kit aesthetic.

## How to pull when needed

1. Placeholder weapon/enemy/prop geometry: clone the origin repo, extract the
   specific asset files (`assets/`, `kenney/`, etc.), drop into our
   `godot/assets/placeholders/` (create when first used).
2. Keep license attribution with the placeholder folder.
3. Replace with real assets from Procreate/Blender pipeline as they land.

## What to NOT use

- The FPS player controller — `fps_template/` and `immersive_sim/` are better
  architectural references. Kenney's is simpler but Kenney-specific.

## Trigger

When weapon/enemy/prop placeholder geometry is needed during FPS prototyping.
