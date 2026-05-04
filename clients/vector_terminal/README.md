# Vector Terminal — V1 walking skeleton

Standalone first-person wireframe renderer that subscribes to the brain
manifest stream on TCP 9877. Same brain, second client. Renders the
world as amber #FFB000 wireframe cubes on pure black. WASD + mouse
look, no collision (free-flight), period-correct CRT terminal aesthetic.

> **Do not run alongside Godot.** Both clients send camera updates to
> the brain on the same port. The brain will accept whichever connection
> arrived last, but having both windows open at once is undefined
> behavior — and the brain creates a fresh expedition state per
> connection, so swapping clients mid-session resets the run.

## Install

From the repo root:

```bash
python3 -m pip install -r clients/vector_terminal/requirements.txt
```

This installs `raylib` (which provides the `pyray` Python binding).

## Run

Brain first, in one terminal:

```bash
python3 brain_server.py cavern 9877
```

Vector terminal in another:

```bash
python3 -m clients.vector_terminal.main
```

A 1280×720 window opens. Mouse is captured automatically.

## Controls

| Key | Action |
| --- | --- |
| W / A / S / D | Free-flight movement (no collision) |
| Mouse | Look |
| **ENTER** | Smart state transition: HUB → MISSION_SELECT → IN_MISSION → ... → HUB |
| Esc | Close window |

ENTER is state-aware — one keypress fires the appropriate
`state_transition_request` based on the brain's current `game_state.state`.
This matches the multi-step launch flow Godot uses
(`godot/main.gd:5142-5163`) without requiring V1 to expose a separate
mission-select picker.

## Tests

```bash
python3 -m pytest clients/vector_terminal/tests/
```

Pure-logic only: TCP message parsing, kind→bounds lookup, world_revision
diff detection. Renderer / camera math / socket lifecycle are out of scope
for V1 tests — they're verified interactively with the live brain.

## V2+ deferred

HUD overlay, event stream, crosshair label, encounter target highlight,
playable_envelope clamp, boot sequence, fail-mode reconnect, full input
set (encounter actions, equip, etc.), distance culling, custom per-kind
wireframe recipes. See `project_vector_terminal_campaign` memory for the
full V1→V4 plan.

## Assets

`assets/` is reserved for VT323.ttf (Google Fonts, SIL OFL) used by V2's
HUD. V1 doesn't render any text. Drop the `.ttf` there manually — the
V1 build doesn't pull it in.
