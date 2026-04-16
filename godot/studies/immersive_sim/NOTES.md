# Immersive Sim Controller — borrow notes

**Origin**: https://github.com/LuisOtv/ImmersiveSimGodotController
**License**: MIT (see LICENSE)
**Godot version**: 4.1 (should port straight to 4.6)

## Why it's here

Dishonored/Cruelty Squad-style first-person controller. Matches user's
Hexen/Wizardry/Skyrim-Oblivion FPS north star. Modular architecture designed
for extension.

## Features inventory

- WASD movement + mouse look
- Lean (Q/E), crouch (CTRL)
- Pickup / drop (F/G)
- Animated doors, ladders, elevators
- Weapon framework with modular gun types, recoil, bullet spread
- Footsteps + weapon/door/elevator audio
- Dynamic HUD with crosshair + ammo counter
- Stealth elements

## What to extract when adopted

1. **Controller core** — movement + camera + lean + crouch skeleton
2. **Interaction system** — pickup/drop pattern (paired with pickup_place study)
3. **Door/ladder/elevator** — interactable animations, state-driven
4. **Audio hooks** — where footsteps + weapon sounds integrate

## What to SKIP

- Specific weapon models/animations (use our own)
- HUD styling (use our Carcosa/Rucker register)
- Stealth mechanics (not the current direction)

## Pair with

- `cobra_fps/` for polish layer (view bob, ADS, recoil feedback)
- `pickup_place/` for pickup/place refinement (blueprint validation)
- `fps_template/` for weapon resource architecture
