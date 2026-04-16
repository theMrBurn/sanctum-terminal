# GPU Cellular Automata — borrow notes

**Origin**: https://github.com/bruce965/godot-gpu-cellular-automata
**License**: MIT (see LICENSE)
**Godot version**: 3.2 (needs port to 4.x)

## Why it's here

Real implementation path for `design_membrane_system` + `project_elemental_wire`
memories. Full falling-sand + material-reactions simulator, not just Conway's
Game of Life.

## Key files

- `cellular_automata.gd` (76 lines) — ping-pong viewport orchestration
- `simulation.shader` (273 lines) — the material physics + morphing rules
- `render.shader` — screen display shader
- `CellularAutomata.tscn` — scene structure (Simulation/Viewport + Render node)

## Materials + rules (all in simulation.shader)

- **Powders** (sand) — fall, slide diagonally
- **Liquids** (water, lava) — fall, spread horizontally
- **Gases** (fire, steam) — random drift
- **Morphing**: water+lava→steam, lava+water→stone, grass+fire→fire, fire→air decay, steam→water in cold air

## Port-to-4 checklist

When promoted to actual integration:

- [ ] Viewport → SubViewport (class renamed in 4.x)
- [ ] `render_target_update_mode` API may have changed values — verify
- [ ] `$Path/Node` syntax still works in 4.x
- [ ] Shader `shader_type canvas_item` unchanged
- [ ] `texelFetch` + `TEXTURE` + `UV` unchanged
- [ ] Test ping-pong feedback at lower resolutions first

## Integration candidates in this project

1. **Membrane overlay**: Attach a CA surface to specific entities (rock, moss)
   where state spreads (wetness, corrosion, flame).
2. **Elemental reactions**: Replace current single-shot `reaction_events`
   in `brain_server.py:1100-1143` with a CA that actually simulates the
   water-dousing-fire propagation over frames.
3. **Ambient atmosphere**: Low-resolution CA driving fog/steam billboards
   or decals.

Don't port until one of these three needs goes active.
