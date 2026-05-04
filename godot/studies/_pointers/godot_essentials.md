# godot-essentials — pointer

**Origin**: https://gitlab.com/godot-tools/godot-essentials
**License**: MIT
**Godot version**: 4.2 (works in 4.6)

## Why not copied locally

Large utility library; we don't want to clone 50+ components just to maybe
use 3 of them. We pull individual components from origin as needed.

## Already absorbed

✅ **typed_text.gd** (2026-04-16, commit 46339f3) — ported to `godot/ui/typed_text.gd`

## Still available to cherry-pick

| Component | Status | Trigger |
|---|---|---|
| GlobalEventBus | Wait | N≥5 signal emitters (currently 3) |
| GameGlobals | Arch-skip | Brain owns state |
| AudioManager / MusicManager | Wait | Audio-is-last memory |
| SaveManager / SavedGame | Arch-skip | Brain owns persistence |
| SceneTransitionManager | Wait | Scene transitions become visible |
| FSM / HSM | Alt exists | `mannequiny/` study has simpler version |
| FootstepManager3D | Wait | Paired with souls_like footfall work |
| Math Wizards (Vector/Camera/String/Input/Node) | Grab-as-needed | Per function |
| HealthComponent | Arch-skip | Brain owns HP |
| Inventory / InteractableArea | Wait | FPS controller work activates |
| Destructibles | Wait | Destructible props become a need |
| GodotEnvironment (.env loader) | Wait | Config secrets needed |
| UUID | Grab-as-needed | When unique IDs are needed |
| Achievements | Wait | Late-game |

## Pull procedure

When a component is needed:
1. Visit origin URL, find the file in `autoload/` or `components/`
2. Copy into our repo with attribution in file header
3. Strip unused dependencies (e.g. InputWizard → native Input)
4. Add to `godot/ui/`, `godot/utils/`, or `godot/components/` as fits
5. Update pile memory with ✅ absorbed marker
