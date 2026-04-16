# Mannequiny — borrow notes

**Origin**: https://github.com/GDQuest/godot-3d-mannequin
**License**: MIT (see LICENSE)
**Godot version**: 3.5 (needs Godot 4 syntax port)

## Why it's here

Canonical GDQuest hierarchical state machine pattern. Compact (49 lines total)
and broadly applicable. Plus camera state machine as a concrete example of
applying the pattern.

## Key files

- `godot/src/Main/StateMachine/StateMachine.gd` (50 lines) — delegates engine
  callbacks to active state, `transition_to(path, msg)` API
- `godot/src/Main/StateMachine/State.gd` (49 lines) — base class with enter /
  exit / process / physics_process / unhandled_input virtuals
- `godot/src/Player/Camera/States/` — Default.gd, Aim.gd, Camera.gd — real
  usage example
- `godot/src/Player/Mannequiny.gd` — character state driver

## Godot 3 → 4 port checklist

- [ ] `yield(owner, "ready")` → `await owner.ready`
- [ ] `onready var state: State = get_node(initial_state) setget set_state`
  → `@onready var state: State = get_node(initial_state)` + property setter
- [ ] `export var initial_state := NodePath()` → `@export var initial_state: NodePath`
- [ ] `func _init() -> void` → same, but parent-class init semantics differ in 4
- [ ] `InputEvent` type hints → unchanged

## Integration candidates

Any node that has distinct modes benefits:

1. Player FSM when FPS controller lands (immersive_sim study has examples)
2. Camera state (first-person / iso / encounter-locked / cutscene)
3. Enemy AI (patrol / chase / attack / flee)
4. Game mode (menu / playing / paused / dialog / cutscene)

## What's NOT in the repo

**No `.blend` source.** Only the exported 1.8MB mannequiny-0.3.0.glb ships.
That GLB was NOT copied into this studies folder (binary). Pull from origin
if needed as a base for FPS arm-rig extraction.
