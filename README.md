# SANCTUM TERMINAL

A procedural RPG engine seeded by real life. Your inputs become the world.

**Stack:** Python 3.12 / Panda3D / pytest / SQLite

---

## Quick Start

```bash
make test        # 939 tests
make dungeon     # playable 7-Door Dungeon
make viewer      # entity template viewer
make creation    # creation lab
make theater     # scripted quest auto-play
```

## Architecture

```
Interview → Ghost → Fingerprint → Encounter → Campaign → World

core/systems/
  avatar_pipeline.py      Interview → Ghost → Fingerprint → design_key()
  encounter_engine.py     7 verbs, 0.45 threshold, 60s cooldown
  scenario_engine.py      7 scenario types, base-7
  campaign_engine.py      Wildermyth conductor, Metroid solvability
  entity_template.py      8 JSON skeletons, deep hierarchy, named sockets
  material_system.py      14 materials, per-register color/texture/emission
  billboard_renderer.py   Anno Mutationem sprite-on-skeleton rendering
  geometry.py             7 primitives (vertex-colored + UV-mapped variants)
  dungeon_grid.py         Discrete NSEW movement
  corridor_scene.py       8 doors, 4 tier detail pools
  atmosphere_engine.py    Fog/heat/moisture, ghost blend
  paper_doll.py           15-part layered Monk (billboard sprites)
  devlog.py               Chained SHA256 audit log
```

## Design Pins

- 1 unit = 1 meter. EYE_Z = 6.0. Walk = 1.67 m/s
- Base-7 atoms x Base-60 relationships x Base-1 naming
- 3D environment + 2D pixel art characters (Anno Mutationem)
- 4 visual registers: survival / tron / tolkien / sanrio
- TDD always. `make test` before commit.

## Visual Pipeline

**Rendering:** Shadowbox multi-plane parallax (depth slices, FBO compositing)
**Characters:** Billboard sprite quads on entity template skeletons
**Environment:** Textured primitives with per-register material system
**Textures:** System Shock fidelity (~96px), nearest-neighbor filtering

## Consent

- Never asks for PII, financial data, or health information
- No data leaves vault without explicit user action
- Experience is never punishing

---

*The game doesn't tell you who to be. It shows you who you already are.*
