# godot — AGENTS.md

Godot 4.4 viewer on Apple Silicon Metal. Consumes brain manifest over TCP :9877.

## Owns
- `godot/main.gd`, `main.tscn` — viewer client, MultiMesh batching
- `godot/*.gdshader` — per-kind shader, ground, sky, post
- `godot/lib/`, `meshes/`, `stamps/`
- `godot/kind_config.json` — symlink to `../config/kind_config.json` (single source)

## Reads (does not own)
- Brain manifest (TCP or `data/live_assets/manifest.json`)

## Subsystem rules (Metal)
- No per-pixel lighting via `setShaderAuto` — broken on Metal. Decals ARE the lighting.
- CanvasLayer post-process dead on Metal. Use compositor or per-material rim.
- MultiMesh cannot pass vertex colors. Colored kinds → individual MeshInstance3D + sRGB→linear `pow(2.2)`.
- Vertex colors stay ON for fungi. Facet palette → stone; vertex colors → organic.
- 3 fixed OmniLights per biome. Objects self-emit. No per-entity lights.
- `step()` per object. Never smoothstep. Never per-fragment. Never animate radius.
- Vertex displacement ≤ 0.15. Low-freq noise only.
- `clear_color` must match biome ground palette. Never black.

## Render doctrine
- Cheat everywhere — fake what the player can't verify.
- Decal projector + vertical shaft for every light cast.
- Cap vertical geometry at fog height (render dome).
- Brain ships ground truth; render hints stay client-side.

## Hot-reload
- `.gd` edits hot-load. `.gdshader` / `.tscn` edits → Godot restart.
- Symlinked `kind_config.json` reload requires re-connect to brain.
- Perf: `PERF_LOG_ENABLED` const in `main.gd:97`. Toggle for measurement only.

## Acceptance criteria
- VISUAL always (screenshot UAT)
- TEST if logic-bearing GDScript (rare)

## Touch test
Brain serves manifest, Godot connects on :9877, no shader errors in 30s.
