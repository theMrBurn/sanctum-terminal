# ChaffGames FPS Template — borrow notes

**Origin**: https://github.com/chafmere/Godot4-FPS-Template
**License**: MIT (see LICENSE)
**Godot version**: 4.5+

## Why it's here

Mature weapon architecture: **Weapon_Resource** schema. Matches our
config-as-code pattern (e.g. `encounters.json`). Component-heavy, modular,
designed for swap-in/swap-out of art/animation.

## Key features

- Resource-based weapon system (`Weapon_Resource` as schema)
- State machine for weapon management (idle/firing/reloading/switching)
- Hit-scan AND projectile firing options (per-weapon)
- Spray profile customization per weapon
- Multiple movement options
- 4 sample weapons included
- String-reference animations (swap animations without breaking logic)

## The Weapon_Resource pattern

This is the gold. Just like our encounters declare data-first in
`encounters.json`, weapons declare:
- Damage, range, fire rate
- Hit-scan vs projectile
- Spray profile
- Animation string keys
- Ammo type

Then behavior is driven by the data. **Direct architectural match to our
encounter primitive.** When weapons land, model them the same way.

## What to extract when adopted

1. **Weapon_Resource class definition** — the schema shape
2. **Weapon state machine** — idle/fire/reload/switch transitions
3. **String-reference animation pattern** — placeholder-friendly swapping

## Translation to our conventions

Weapons should eventually live in `config/weapons.json` (or a section of
kind_config.json), parallel to encounters:
- Brain reads weapons authoritatively
- Godot reads via manifest
- Resource schema matches JSON structure 1:1

## Pair with

- `immersive_sim/` — controller base that weapons hook into
- `cobra_fps/` — recoil/feel on top of the resource firing logic
