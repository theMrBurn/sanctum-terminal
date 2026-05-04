# Tier 1 studies library

Version-controlled reference collection of Godot assets/plugins audited and
promoted to Tier 1 of the plugin pile (see
`~/.claude/projects/-Users-themrburn-git-sanctum-terminal/memory/project_plugin_pile.md`).

## What this directory is

A read-only-ish library of external code we might want to port, cherry-pick, or
study. **Not production code.** Not imported by `main.tscn` or the brain
pipeline. Keeps reference material close enough to grep, side-by-side diff, and
not lose if upstream repos vanish.

## What this directory is NOT

- Not a list of plugins we've installed
- Not addons (those land in `godot/addons/` if any ever do)
- Not portable — most items here are Godot 3.x snapshots that won't run in our 4.6 project without port

Anything actually absorbed moves OUT of `studies/` and into the real codebase
(e.g. `godot/ui/typed_text.gd` is the first absorb; it lives outside studies/).

## Copy policy

Each subfolder holds `.gd`, `.gdshader`, `.tres`, and small `.tscn` files from
the origin repo. Binary assets (PNG, GLB, WAV, OGG, large bundled scene data)
are **NOT** copied — pull them from the origin URL in the per-item README if
ever needed. License file preserved where present.

## Index

| Folder | Origin | License | Godot version | Status |
|---|---|---|---|---|
| `gpu_ca/` | bruce965/godot-gpu-cellular-automata | MIT | 3.2 | Pinned Tier 1 — port candidate for membrane_system |
| `souls_like/` | catprisbrey/Cats-Godot4-Modular-Souls-like-Template | CC0 | 4.2 | Pinned Tier 1 — sub-modules (targeting, footfall, item, equipment, enemy AI) |
| `mannequiny/` | GDQuest/godot-3d-mannequin | MIT | 3.5 | Tier 2 reference — StateMachine/State pattern, 49 lines |
| `immersive_sim/` | LuisOtv/ImmersiveSimGodotController | MIT | 4.1 | Pinned Tier 1 — FPS controller, lean/crouch/pickup |
| `cobra_fps/` | meatycurtains907/COBRA-FPS-Feelkit | MIT | 4.5 | Pinned Tier 1 — FPS feel/juice |
| `fps_template/` | chafmere/Godot4-FPS-Template | MIT | 4.5+ | Pinned Tier 1 — Weapon_Resource architecture |
| `pickup_place/` | SamLawX/Godot-3D-A-Simple-Pick-up-and-Place-System | Unlicense | 4.5.1 | Pinned Tier 1 — Oblivion-style object manipulation |

## Deferred (pointer-only, no local copy)

| Item | Origin | Why not copied |
|---|---|---|
| starter-kit-fps (Kenney) | KenneyNL/Starter-Kit-FPS | CC0 asset pack; pull assets directly when placeholder geometry needed |
| terminal-emulator | andrea-calligaris/terminal-emulator | Phase 3 deferred — revisit at endgame milestone |
| godot-essentials | gitlab: godot-tools/godot-essentials | Partially absorbed; remainder pulled from origin per-component |

See individual per-folder READMEs for what each study contains and what specific
patterns are worth extracting.
