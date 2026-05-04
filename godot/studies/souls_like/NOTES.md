# Souls-like template — borrow notes

**Origin**: https://github.com/catprisbrey/Cats-Godot4-Modular-Souls-like-Template
**License**: CC0 (Unlicense — copy freely)
**Godot version**: 4.2 (directly compatible with our 4.6)

## Why it's here

Modular sub-module goldmine. Each folder under `player/` and `enemy/` is an
independently extractable sub-system. Third-person template, but individual
modules are transferable to our FPS direction or iso-mode fallback.

## Extractable sub-modules (each a separate Tier 1 candidate)

### `player/player_targeting_system/`
Drova/Diablo-style lock-on + `gui_reticle.gd`. **Direct fit for iso-mode
fallback.** Trigger: when iso combat activates.

### `player/footfall_system/`
Surface-keyed footsteps via `footstep_sound_system.gd`. **Ties to
`reference_audio_osc` + biome_data.** Trigger: when audio layer lands.

### `player/item_system/`
Resource-based items: `item_resource.gd`, `item_object.gd`, `inventory_system.gd`.
**Matches our config-as-code philosophy.** Trigger: when inventory is needed.

### `player/equipment_system/`
Weapons + torch + weapon_streak trails + root-motion animation.
`equipment_resource.gd` as the data-driven weapon schema. Trigger: weapon work.

### `enemy/`
`health_system.gd`, `enemy_root_anim_tree.gd`, `enemy_area_target_sensor.gd`,
`patrol_point.gd`, `enemy_base_root_motion.gd`. Enemy AI state machine + sensor
+ patrol. Trigger: action-mode scouts land.

### `interactable objects/`
doors, levers, ladders, chests, spawn_site. Augments immersive_sim's
equivalents. Trigger: as interactions are added.

### `cameras/`
follow_cam + area_cam — third-person camera state machines. Reference when
camera work expands.

## What NOT to borrow

- The overall project structure (third-person assumption baked in)
- Demo level gridmap (geometry-specific)
- Weapon animations (tied to their specific rig)

## Integration order if adopted

1. item_system (data-driven, no movement assumption)
2. footfall_system (audio-ready, engine-agnostic)
3. player_targeting_system (iso-mode trigger)
4. equipment_system (depends on item_system)
5. enemy/* (pairs with action-mode scouts)
