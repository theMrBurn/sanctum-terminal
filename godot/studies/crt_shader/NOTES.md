# SimpleGodotCRTShader — study notes

**Source:** https://github.com/henriquelalves/SimpleGodotCRTShader
**License:** MIT (see LICENSE in this dir)

## Why staged

Per `project_plugin_pile.md` Tier 3 — earmarked for the Phase 3 terminal reveal aesthetic (`design_north_star`: "Phase 3 teaches modding. The terminal was always real."). The shader fakes a CRT scanline + curvature look that pairs naturally with the terminal-emulator plugin (also Tier 1, also Phase 3 deferred) when the player crosses the modding threshold and the in-fiction "terminal" surfaces as a real interactive element.

## What's here

- `CRTShader.gdshader` — the full-screen post-process shader (canvas_item, screen-texture-based)
- `ShaderScreen.material` — pre-configured ShaderMaterial wrapping the shader
- `CRTFrame.png` — bezel/CRT frame overlay sprite
- `crt_shader.gd` / `crt_screen.gd` — example scripts wiring the shader to a Sprite2D / SubViewport
- `plugin.cfg` — original repo's plugin manifest. **NOT registered** in this project — kept for reference only.

## Why pointer-only / not enabled

1. **Phase 3 deferred.** No use until the terminal-emulator hub appears.
2. **Metal compatibility unknown.** Per `platform_metal_no_shaders` the project's Metal pipeline doesn't tolerate per-pixel screen-texture effects well — outline shader is currently disabled for the same reason. CRT may need the same compositor-based path or a per-material approach.
3. **Hint-screen-texture path.** This shader uses `hint_screen_texture` which currently returns white on this Metal/Godot 4 setup (per outline-shader debug). Will need the compositor approach when activated.

## When to wire

- Triggered by Phase 3 milestone — terminal reveal moment.
- Or earlier as a **secondary camera mode** for the iso/observer view (Plato's cave aesthetic — watching events through a CRT-mediated screen).

## Staging convention

Code copied here as the canonical reference; if/when activated, contents move to `godot/post_process/crt/` (or wherever fits) and `studies/crt_shader/` becomes a pointer file like the other Phase-3-deferred items.
