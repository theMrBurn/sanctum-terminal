# COBRA FPS Feel Kit — borrow notes

**Origin**: https://github.com/meatycurtains907/COBRA-FPS-Feelkit
**License**: MIT (see LICENSE)
**Godot version**: 4.5+

## Why it's here

FPS feel/juice layer. Pairs with immersive_sim as its polish companion.

## Features inventory

- View bob (camera sway while walking)
- Weapon sway (weapon lag behind camera rotation)
- Recoil (camera kick on fire)
- Hit feedback (crosshair pulse, damage indicator)
- ADS (aim down sights)
- 4 preset profiles: Twitchy, WW2, Arcade, **Exploration** (non-combat movement)

## The Exploration preset

Relevant for our dialog-first direction. Softer view bob, no combat-oriented
recoil/sway, designed for non-shooter first-person traversal. Good starting
profile while gameplay is still parley-based.

## What to extract

1. **View bob curves** — the specific bob profile for walk/sprint/crouch
2. **Weapon sway math** — camera-relative lag for weapon position
3. **Recoil stack** — how kicks stack + decay on rapid fire
4. **Exploration preset values** — tuned numbers for non-combat FPS movement

## Pair with

- `immersive_sim/` — COBRA is feel on top of immersive_sim's controller skeleton
- `fps_template/` — recoil integrates with weapon resource definitions
