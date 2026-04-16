# Simple Pick-Up and Place System — borrow notes

**Origin**: https://github.com/SamLawX/Godot-3D-A-Simple-Pick-up-and-Place-System
**License**: Unlicense (public domain — copy freely)
**Godot version**: 4.5.1

## Why it's here

Oblivion-style object manipulation. Direct fit for "pick up this skull and
place it on the altar" gameplay verb. Register-compatible with Carcosa ritual
imagery.

## Features

- Raycast detection (look-at highlighting)
- Outline shader on hover
- Pick up via input action
- Free rotation while held (rotation speed configurable)
- **Blueprint validation** — green highlight for valid placement, red for invalid
- Spherical collision check prevents clipping
- Grounded placement (no floaters)

## The blueprint validation pattern

The valuable piece. When placing:
1. Object preview shown as a semi-transparent ghost at placement location
2. Raycast + spherical collision check validates the spot
3. Color cue (green/red) tells the player whether the drop will succeed
4. Click commits, invalid drops rejected

Useful for any placement interaction: altar rituals, crafting stations, key
insertion, lever activation.

## What to extract

1. **Outline shader** — useful beyond pickup (any hoverable prop)
2. **Blueprint validation logic** — collision + color feedback
3. **Pickup state machine** — free-hand / aiming / released

## Pair with

- `immersive_sim/` — controller base; its built-in pickup is simpler than this
  one's. Swap in this validation layer for better feel.
