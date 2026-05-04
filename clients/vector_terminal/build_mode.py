"""BUILD-mode state + input dispatch for the vector workroom.

Per `.claude/feature/feat_vector-workroom.md` PR 4. PLACE sub-mode only;
EDIT sub-mode lands in PR 5. State holds:
- whether BUILD is active at all
- a 1m-snapped XZ-plane cursor (raylib coords; ground level + Y offset)
- the currently-selected primitive name (TAB cycles)
- the currently-selected seed_id (None until something is placed)
- per-placement RGB color, scale, yaw — applied to next placement
  AND mutated on the selection (RGB / +- / <>) so users tune the seed
  they just dropped without re-typing every value.

`handle_input()` reads pyray each frame and returns:
- a list of brain command dicts to send (seed_create / update / delete)
- updated BuildState (in-place; the function mutates the passed instance)

Coordinate convention: raylib is Y-up (y=floor, z=forward); brain is
Z-up (z=floor, y=forward). The cursor lives in raylib coords; we convert
once when sending seed payloads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pyray as rl

from core.systems.wireframe_mesh import builtin_names, get_builtin
from clients.vector_terminal.wireframe_renderer import draw_wireframe
from clients.vector_terminal.seed_mesh_cache import SeedMeshCache


# ── Tunables ─────────────────────────────────────────────────────────

GRID_SNAP_M = 1.0           # XZ snap, AC #4
Y_STEP_M = 0.5              # PgUp/PgDn step
SCALE_STEP = 0.10           # +/-
YAW_STEP_DEG = 15.0         # < >
COLOR_STEP = 0.10           # RGB
INITIAL_CURSOR_FORWARD_M = 4.0   # spawn the cursor 4m in front of the camera

GHOST_ALPHA = 0.35          # ghost cursor transparency
SELECTION_GLOW_ALPHA = 1.0  # bright outline on the selected seed


# ── State ────────────────────────────────────────────────────────────


_PRIMITIVE_CYCLE: tuple[str, ...] = builtin_names()
# Order is alphabetical (`builtin_names()` returns sorted). Stable across
# sessions so muscle memory holds.


VERTEX_GRID_M = 0.1     # EDIT sub-mode arrow nudge


@dataclass
class BuildState:
    active: bool = False
    sub_mode: str = "place"          # "place" or "edit"
    cursor_x: float = 0.0
    cursor_y: float = 0.0            # raylib Y (vertical), 0 = ground
    cursor_z: float = INITIAL_CURSOR_FORWARD_M
    primitive_index: int = 0          # index into _PRIMITIVE_CYCLE
    selected_seed_id: int | None = None

    # Apply on next placement; also mutated by RGB / +- / <> when a seed
    # is selected so the same keys both pre-stage and post-edit.
    color_r: float = 0.7
    color_g: float = 0.7
    color_b: float = 0.7
    scale: float = 1.0
    yaw_deg: float = 0.0

    # EDIT sub-mode state — index into the selected seed's resolved mesh
    # vertex array. `edit_prev_vertex_idx` tracks the prior TAB target so
    # join/curve/remove_edge ops have an implicit edge endpoint pair
    # (prev → current). Reset whenever the selected seed changes.
    edit_vertex_idx: int = 0
    edit_prev_vertex_idx: int | None = None

    def selected_mesh(self) -> str:
        return _PRIMITIVE_CYCLE[self.primitive_index % len(_PRIMITIVE_CYCLE)]

    def cycle_primitive(self, step: int = 1) -> None:
        n = len(_PRIMITIVE_CYCLE)
        self.primitive_index = (self.primitive_index + step) % n


def enter_edit(state: BuildState) -> bool:
    """PLACE → EDIT. Requires `selected_seed_id` non-None — silently
    refuses if no seed is selected (caller can toast the user)."""
    if state.selected_seed_id is None:
        return False
    state.sub_mode = "edit"
    state.edit_vertex_idx = 0
    state.edit_prev_vertex_idx = None
    return True


def exit_edit(state: BuildState) -> None:
    """EDIT → PLACE."""
    state.sub_mode = "place"
    state.edit_prev_vertex_idx = None


# ── Coordinate conversion ────────────────────────────────────────────


def raylib_to_brain(x: float, y_up: float, z_fwd: float) -> tuple[float, float, float]:
    """raylib (x, y=up, z=forward)  →  brain (x, y=forward, z=up)."""
    return (x, z_fwd, y_up)


def brain_to_raylib(pos_x: float, pos_y: float, pos_z: float) -> tuple[float, float, float]:
    """brain (x, y=forward, z=up)  →  raylib (x, y=up, z=forward)."""
    return (pos_x, pos_z, pos_y)


# ── Toggle gating ────────────────────────────────────────────────────


def biome_allows_build(manifest: dict) -> bool:
    """V1 launched workroom-only. Per the user's `make brain-X` doctrine
    (each biome is a UAT entry point for the shared system surface),
    BUILD is now available in any biome the brain serves. The function
    stays for future per-biome opt-out (e.g. encounter biomes that
    shouldn't permit authoring) — V1 returns True for any non-empty
    biome name."""
    return bool(manifest.get("biome"))


def _initial_cursor(camera, yaw: float) -> tuple[float, float, float]:
    """Spawn the cursor INITIAL_CURSOR_FORWARD_M ahead of the camera on
    the floor plane, snapped to the grid."""
    import math
    fx = camera.position.x + math.sin(yaw) * INITIAL_CURSOR_FORWARD_M
    fz = camera.position.z + math.cos(yaw) * INITIAL_CURSOR_FORWARD_M
    fx = round(fx / GRID_SNAP_M) * GRID_SNAP_M
    fz = round(fz / GRID_SNAP_M) * GRID_SNAP_M
    return (fx, 0.0, fz)


def toggle_build(state: BuildState, manifest: dict, camera, yaw: float) -> bool:
    """Flip BUILD on/off; returns the new active flag. Outside workroom
    this is a silent no-op (returns existing state.active unchanged)."""
    if state.active:
        state.active = False
        return False
    if not biome_allows_build(manifest):
        return False
    cx, cy, cz = _initial_cursor(camera, yaw)
    state.cursor_x = cx
    state.cursor_y = cy
    state.cursor_z = cz
    state.active = True
    return True


# ── Selection ────────────────────────────────────────────────────────


def _seed_distance_xz(seed: dict, x: float, z: float) -> float:
    """raylib XZ distance to a seed's render position. Used for nearest-
    seed selection by `[` / `]`."""
    rx, _, rz = brain_to_raylib(
        float(seed.get("pos_x", 0.0)),
        float(seed.get("pos_y", 0.0)),
        float(seed.get("pos_z", 0.0)),
    )
    dx = rx - x
    dz = rz - z
    return (dx * dx + dz * dz) ** 0.5


def _seeds(manifest: dict) -> list[dict]:
    return list(manifest.get("seeds") or [])


def _find_selected(manifest: dict, sid: int | None) -> dict | None:
    if sid is None:
        return None
    for s in _seeds(manifest):
        if int(s.get("id", -1)) == int(sid):
            return s
    return None


def cycle_selection(state: BuildState, manifest: dict, step: int = 1) -> None:
    """Cycle selected_seed_id through seeds sorted by distance to cursor.
    `[` = closer, `]` = farther by current distance ranking."""
    seeds = _seeds(manifest)
    if not seeds:
        state.selected_seed_id = None
        return
    sorted_seeds = sorted(
        seeds,
        key=lambda s: _seed_distance_xz(s, state.cursor_x, state.cursor_z),
    )
    if state.selected_seed_id is None:
        state.selected_seed_id = int(sorted_seeds[0].get("id"))
        return
    ids = [int(s.get("id")) for s in sorted_seeds]
    try:
        idx = ids.index(int(state.selected_seed_id))
    except ValueError:
        state.selected_seed_id = ids[0]
        return
    state.selected_seed_id = ids[(idx + step) % len(ids)]


def adopt_seed_into_state(state: BuildState, seed: dict) -> None:
    """When a seed becomes the selection, copy its color/scale/yaw into
    state so subsequent +/-, RGB, <> ops reflect what the user sees."""
    state.scale = float(seed.get("scale", state.scale))
    state.yaw_deg = float(seed.get("yaw_deg", state.yaw_deg))
    state.color_r = float(seed.get("color_r", state.color_r))
    state.color_g = float(seed.get("color_g", state.color_g))
    state.color_b = float(seed.get("color_b", state.color_b))


# ── Input dispatch ───────────────────────────────────────────────────


def _clamp_color(v: float) -> float:
    return max(0.0, min(1.0, v))


def _clamp_scale(v: float) -> float:
    return max(0.05, min(20.0, v))


def handle_input(
    state: BuildState,
    manifest: dict,
    camera,
    yaw: float,
    cache=None,
) -> list[dict]:
    """Read pyray each frame; mutate state; return brain commands to send.

    Caller is responsible for:
    - Detecting B (toggle entry/exit) BEFORE calling this — we don't
      eat that key here so the caller can also gate on biome / other UI.
    - Forwarding returned commands to the brain socket.

    Only fires when state.active is True. Dispatches to the PLACE or
    EDIT sub-mode handler. EDIT needs a `cache` (SeedMeshCache) so it
    can resolve the selected seed's current mesh and compute relative
    vertex positions; PLACE ignores it.
    """
    if not state.active:
        return []
    if state.sub_mode == "edit":
        return _handle_input_edit(state, manifest, cache)
    if state.sub_mode != "place":
        return []

    cmds: list[dict] = []

    # ── Cursor movement ──
    if rl.is_key_pressed(rl.KeyboardKey.KEY_LEFT):
        state.cursor_x -= GRID_SNAP_M
    if rl.is_key_pressed(rl.KeyboardKey.KEY_RIGHT):
        state.cursor_x += GRID_SNAP_M
    if rl.is_key_pressed(rl.KeyboardKey.KEY_UP):
        state.cursor_z -= GRID_SNAP_M
    if rl.is_key_pressed(rl.KeyboardKey.KEY_DOWN):
        state.cursor_z += GRID_SNAP_M
    if rl.is_key_pressed(rl.KeyboardKey.KEY_PAGE_UP):
        state.cursor_y += Y_STEP_M
    if rl.is_key_pressed(rl.KeyboardKey.KEY_PAGE_DOWN):
        state.cursor_y -= Y_STEP_M

    # ── Primitive cycling ──
    if rl.is_key_pressed(rl.KeyboardKey.KEY_TAB):
        state.cycle_primitive(1)

    # ── Selection cycling ──
    if rl.is_key_pressed(rl.KeyboardKey.KEY_LEFT_BRACKET):
        cycle_selection(state, manifest, step=-1)
        sel = _find_selected(manifest, state.selected_seed_id)
        if sel is not None:
            adopt_seed_into_state(state, sel)
    if rl.is_key_pressed(rl.KeyboardKey.KEY_RIGHT_BRACKET):
        cycle_selection(state, manifest, step=1)
        sel = _find_selected(manifest, state.selected_seed_id)
        if sel is not None:
            adopt_seed_into_state(state, sel)

    # ── Place ──
    if rl.is_key_pressed(rl.KeyboardKey.KEY_SPACE):
        active_biome = str(manifest.get("biome", "workroom"))
        cmds.append(_compose_create(state, biome=active_biome))
        # Selection follows the just-placed seed once the manifest comes
        # back; we can't know its id yet, so leave selected_seed_id alone
        # — the brain ack carries the new id in PR 4.x if needed.

    # ── Delete ──
    if rl.is_key_pressed(rl.KeyboardKey.KEY_DELETE) and state.selected_seed_id is not None:
        cmds.append({"cmd": "seed_delete", "seed_id": int(state.selected_seed_id)})
        state.selected_seed_id = None

    # ── Scale (+/-) ──
    if (rl.is_key_pressed(rl.KeyboardKey.KEY_KP_ADD)
            or rl.is_key_pressed(rl.KeyboardKey.KEY_EQUAL)):
        state.scale = _clamp_scale(state.scale * (1.0 + SCALE_STEP))
        if state.selected_seed_id is not None:
            cmds.append(_compose_update(state, {"scale": state.scale}))
    if (rl.is_key_pressed(rl.KeyboardKey.KEY_KP_SUBTRACT)
            or rl.is_key_pressed(rl.KeyboardKey.KEY_MINUS)):
        state.scale = _clamp_scale(state.scale / (1.0 + SCALE_STEP))
        if state.selected_seed_id is not None:
            cmds.append(_compose_update(state, {"scale": state.scale}))

    # ── Yaw (< / >) ──
    # raylib's KEY_COMMA / KEY_PERIOD are the unshifted keys; "<" / ">"
    # are SHIFT+comma / SHIFT+period on US layouts. Bind on the unshifted
    # keys for convenience — UX matches Fallout settlement-build feel.
    if rl.is_key_pressed(rl.KeyboardKey.KEY_COMMA):
        state.yaw_deg = (state.yaw_deg - YAW_STEP_DEG) % 360.0
        if state.selected_seed_id is not None:
            cmds.append(_compose_update(state, {"yaw_deg": state.yaw_deg}))
    if rl.is_key_pressed(rl.KeyboardKey.KEY_PERIOD):
        state.yaw_deg = (state.yaw_deg + YAW_STEP_DEG) % 360.0
        if state.selected_seed_id is not None:
            cmds.append(_compose_update(state, {"yaw_deg": state.yaw_deg}))

    # ── Color channels (R / G / B) ──
    # Holding SHIFT decrements; tap alone increments. Tight loop, one
    # key per channel — matches the V5 acceptance item.
    shift = (rl.is_key_down(rl.KeyboardKey.KEY_LEFT_SHIFT)
             or rl.is_key_down(rl.KeyboardKey.KEY_RIGHT_SHIFT))
    sign = -1.0 if shift else 1.0
    if rl.is_key_pressed(rl.KeyboardKey.KEY_R):
        state.color_r = _clamp_color(state.color_r + sign * COLOR_STEP)
        if state.selected_seed_id is not None:
            cmds.append(_compose_update(state, {"color_r": state.color_r}))
    if rl.is_key_pressed(rl.KeyboardKey.KEY_G):
        state.color_g = _clamp_color(state.color_g + sign * COLOR_STEP)
        if state.selected_seed_id is not None:
            cmds.append(_compose_update(state, {"color_g": state.color_g}))
    if rl.is_key_pressed(rl.KeyboardKey.KEY_B):
        # `B` toggles BUILD mode at top-level; here we're already inside
        # BUILD mode, so `B` mutates blue. Caller's biome-gate keeps the
        # toggle from re-firing on the same press because we live inside
        # the `state.active` branch — caller checks B BEFORE entering us.
        state.color_b = _clamp_color(state.color_b + sign * COLOR_STEP)
        if state.selected_seed_id is not None:
            cmds.append(_compose_update(state, {"color_b": state.color_b}))

    return cmds


# ── Command composers ───────────────────────────────────────────────


def _compose_create(state: BuildState, biome: str = "workroom") -> dict:
    """Build a seed_create payload from the current cursor + state.
    `biome` defaults to workroom for back-compat; live callers pass the
    active manifest biome so seeds persist where the user authored them."""
    bx, by, bz = raylib_to_brain(state.cursor_x, state.cursor_y, state.cursor_z)
    return {
        "cmd": "seed_create",
        "payload": {
            "biome": biome,
            "kind": "wireframe_mesh",
            "base_mesh": state.selected_mesh(),
            "pos_x": bx, "pos_y": by, "pos_z": bz,
            "yaw_deg": state.yaw_deg,
            "scale": state.scale,
            "color_r": state.color_r,
            "color_g": state.color_g,
            "color_b": state.color_b,
        },
    }


def _compose_update(state: BuildState, fields: dict) -> dict:
    return {
        "cmd": "seed_update",
        "seed_id": int(state.selected_seed_id),
        "fields": dict(fields),
    }


# ── Rendering ────────────────────────────────────────────────────────


def _byte(v: float) -> int:
    if v < 0.0:
        v = 0.0
    elif v > 1.0:
        v = 1.0
    return int(round(v * 255.0))


def _seed_color_rgba(seed: dict, alpha: int = 255) -> tuple[int, int, int, int]:
    return (
        _byte(float(seed.get("color_r", 0.7))),
        _byte(float(seed.get("color_g", 0.7))),
        _byte(float(seed.get("color_b", 0.7))),
        alpha,
    )


def draw_seeds(manifest: dict, cache: SeedMeshCache) -> None:
    """Render every seed in the active biome's manifest. The mesh-edit
    log is replayed once per seed via `cache.resolve()`; cached when the
    log signature is unchanged across frames."""
    seeds = _seeds(manifest)
    for s in seeds:
        base_name = str(s.get("base_mesh", ""))
        base = get_builtin(base_name)
        if base is None:
            # Future: registry lookup for OBJ-imported meshes.
            continue
        try:
            mesh = cache.resolve(
                seed_id=int(s.get("id")),
                base_mesh_name=base_name,
                base_mesh=base,
                mesh_edits=s.get("mesh_edits") or [],
            )
        except (ValueError, TypeError):
            mesh = base  # corrupt log → fall back to base; skip silently V1
        rx, ry, rz = brain_to_raylib(
            float(s.get("pos_x", 0.0)),
            float(s.get("pos_y", 0.0)),
            float(s.get("pos_z", 0.0)),
        )
        draw_wireframe(
            mesh=mesh,
            position=(rx, ry, rz),
            scale=float(s.get("scale", 1.0)),
            color=_seed_color_rgba(s),
        )


def draw_ghost_cursor(state: BuildState) -> None:
    """Translucent preview of what SPACE would place. Drawn at the
    snapped cursor position with the current state's color/scale."""
    if not state.active or state.sub_mode != "place":
        return
    base = get_builtin(state.selected_mesh())
    if base is None:
        return
    color = (
        _byte(state.color_r),
        _byte(state.color_g),
        _byte(state.color_b),
        _byte(GHOST_ALPHA),
    )
    draw_wireframe(
        mesh=base,
        position=(state.cursor_x, state.cursor_y, state.cursor_z),
        scale=state.scale,
        color=color,
    )

    # Reticle on the floor — small bright cross marking the exact cell
    # so the snap-grid feels solid even when the ghost is small.
    bright = (255, 200, 100, 255)
    rl.draw_line_3d(
        rl.Vector3(state.cursor_x - 0.5, 0.02, state.cursor_z),
        rl.Vector3(state.cursor_x + 0.5, 0.02, state.cursor_z),
        bright,
    )
    rl.draw_line_3d(
        rl.Vector3(state.cursor_x, 0.02, state.cursor_z - 0.5),
        rl.Vector3(state.cursor_x, 0.02, state.cursor_z + 0.5),
        bright,
    )


def draw_edit_cursors(state: BuildState, manifest: dict, cache: SeedMeshCache) -> None:
    """Render the EDIT joint cursor + active-edge highlight on top of the
    selected seed. Bright cube at current vertex; dim cube at prev vertex
    (the "anchor" for join/curve/remove_edge); glowing line between them
    when a real edge connects the two."""
    if not state.active or state.sub_mode != "edit":
        return
    sel, mesh = _resolve_selected_mesh(state, manifest, cache)
    if sel is None or mesh is None:
        return
    n = len(mesh.vertices)
    if n == 0:
        return

    seed_pos_brain = (
        float(sel.get("pos_x", 0.0)),
        float(sel.get("pos_y", 0.0)),
        float(sel.get("pos_z", 0.0)),
    )
    sx, sy, sz = brain_to_raylib(*seed_pos_brain)
    scale = float(sel.get("scale", 1.0))

    def _world(v_local):
        return (
            sx + v_local[0] * scale,
            sy + v_local[1] * scale,
            sz + v_local[2] * scale,
        )

    # Current vertex — bright orange cube.
    cur_idx = state.edit_vertex_idx % n
    cur_world = _world(mesh.vertices[cur_idx])
    cur_marker = max(0.10, 0.12 * scale)
    rl.draw_cube_wires(
        rl.Vector3(*cur_world),
        cur_marker, cur_marker, cur_marker,
        (255, 200, 100, 255),
    )

    # Previous vertex — dimmer cube, only if set and != current.
    prev_idx = state.edit_prev_vertex_idx
    if prev_idx is not None and prev_idx != cur_idx and prev_idx < n:
        prev_world = _world(mesh.vertices[prev_idx])
        prev_marker = cur_marker * 0.8
        rl.draw_cube_wires(
            rl.Vector3(*prev_world),
            prev_marker, prev_marker, prev_marker,
            (180, 120, 60, 255),
        )
        # Active edge — bright line between prev and current. Reads
        # whether or not an actual mesh edge connects them; this is the
        # candidate edge that J / C / DEL will operate on.
        rl.draw_line_3d(
            rl.Vector3(*prev_world),
            rl.Vector3(*cur_world),
            (255, 220, 140, 255),
        )


def draw_selection_highlight(state: BuildState, manifest: dict, cache: SeedMeshCache) -> None:
    """Bright outline overlay on the selected seed."""
    if not state.active or state.selected_seed_id is None:
        return
    sel = _find_selected(manifest, state.selected_seed_id)
    if sel is None:
        return
    base_name = str(sel.get("base_mesh", ""))
    base = get_builtin(base_name)
    if base is None:
        return
    try:
        mesh = cache.resolve(
            seed_id=int(sel.get("id")),
            base_mesh_name=base_name,
            base_mesh=base,
            mesh_edits=sel.get("mesh_edits") or [],
        )
    except (ValueError, TypeError):
        mesh = base
    rx, ry, rz = brain_to_raylib(
        float(sel.get("pos_x", 0.0)),
        float(sel.get("pos_y", 0.0)),
        float(sel.get("pos_z", 0.0)),
    )
    # Slightly larger so the highlight reads as a halo around the seed.
    halo_scale = float(sel.get("scale", 1.0)) * 1.08
    draw_wireframe(
        mesh=mesh,
        position=(rx, ry, rz),
        scale=halo_scale,
        color=(255, 255, 255, 255),
    )


# ── HUD overlay ──────────────────────────────────────────────────────


def _resolve_selected_mesh(state: BuildState, manifest: dict, cache):
    """Get (seed_dict, resolved_mesh) for the currently-selected seed,
    or (None, None) if no selection / unknown base / cache missing."""
    if state.selected_seed_id is None or cache is None:
        return None, None
    sel = _find_selected(manifest, state.selected_seed_id)
    if sel is None:
        return None, None
    base_name = str(sel.get("base_mesh", ""))
    base = get_builtin(base_name)
    if base is None:
        return sel, None
    try:
        mesh = cache.resolve(
            seed_id=int(sel.get("id")),
            base_mesh_name=base_name,
            base_mesh=base,
            mesh_edits=sel.get("mesh_edits") or [],
        )
    except (ValueError, TypeError):
        mesh = base
    return sel, mesh


def _snap_to_vertex_grid(value: float) -> float:
    """0.1m snap for vertex moves in EDIT sub-mode."""
    return round(value / VERTEX_GRID_M) * VERTEX_GRID_M


def _set_vertex_idx(state: BuildState, new_idx: int, mesh) -> None:
    """Move the EDIT vertex cursor; previous index becomes the anchor
    for join/curve/remove_edge ops."""
    n = len(mesh.vertices)
    if n == 0:
        state.edit_vertex_idx = 0
        state.edit_prev_vertex_idx = None
        return
    state.edit_prev_vertex_idx = state.edit_vertex_idx
    state.edit_vertex_idx = new_idx % n


def _handle_input_edit(
    state: BuildState,
    manifest: dict,
    cache,
) -> list[dict]:
    """EDIT sub-mode dispatch — TAB cycles vertices, ARROWS bend, J/C/N/
    DEL/U operate on the selected seed's mesh-edit log."""
    cmds: list[dict] = []
    sel, mesh = _resolve_selected_mesh(state, manifest, cache)
    if sel is None or mesh is None:
        # The selection vanished (deleted by another path) — fall back
        # to PLACE so the user isn't stuck in EDIT with no anchor.
        exit_edit(state)
        return cmds

    n_verts = len(mesh.vertices)
    if state.edit_vertex_idx >= n_verts:
        state.edit_vertex_idx = 0

    edits_log = list(sel.get("mesh_edits") or [])

    # ── Vertex cycling ──
    if rl.is_key_pressed(rl.KeyboardKey.KEY_TAB):
        shift = (rl.is_key_down(rl.KeyboardKey.KEY_LEFT_SHIFT)
                 or rl.is_key_down(rl.KeyboardKey.KEY_RIGHT_SHIFT))
        step = -1 if shift else 1
        _set_vertex_idx(state, state.edit_vertex_idx + step, mesh)

    # ── Vertex move (arrows + PgUp/PgDn) — emits move_vertex ──
    dx = dy = dz = 0.0
    if rl.is_key_pressed(rl.KeyboardKey.KEY_LEFT):
        dx -= VERTEX_GRID_M
    if rl.is_key_pressed(rl.KeyboardKey.KEY_RIGHT):
        dx += VERTEX_GRID_M
    if rl.is_key_pressed(rl.KeyboardKey.KEY_UP):
        dz -= VERTEX_GRID_M
    if rl.is_key_pressed(rl.KeyboardKey.KEY_DOWN):
        dz += VERTEX_GRID_M
    if rl.is_key_pressed(rl.KeyboardKey.KEY_PAGE_UP):
        dy += VERTEX_GRID_M
    if rl.is_key_pressed(rl.KeyboardKey.KEY_PAGE_DOWN):
        dy -= VERTEX_GRID_M
    if dx != 0.0 or dy != 0.0 or dz != 0.0:
        cur = mesh.vertices[state.edit_vertex_idx]
        new_pos = (
            _snap_to_vertex_grid(cur[0] + dx),
            _snap_to_vertex_grid(cur[1] + dy),
            _snap_to_vertex_grid(cur[2] + dz),
        )
        edits_log.append({
            "op": "move_vertex",
            "i": int(state.edit_vertex_idx),
            "to": [new_pos[0], new_pos[1], new_pos[2]],
        })
        cmds.append(_compose_seed_update_edits(state, edits_log))

    # ── J — join (add_edge between prev → current) ──
    if rl.is_key_pressed(rl.KeyboardKey.KEY_J):
        prev = state.edit_prev_vertex_idx
        cur = state.edit_vertex_idx
        if prev is not None and prev != cur:
            edits_log.append({
                "op": "add_edge", "a": int(prev), "b": int(cur),
            })
            cmds.append(_compose_seed_update_edits(state, edits_log))

    # ── C — curve (subdivide_edge between prev → current at t=0.5) ──
    if rl.is_key_pressed(rl.KeyboardKey.KEY_C):
        prev = state.edit_prev_vertex_idx
        cur = state.edit_vertex_idx
        if prev is not None and prev != cur:
            a, b = (prev, cur) if prev < cur else (cur, prev)
            if (a, b) in tuple(
                (min(x, y), max(x, y)) for (x, y) in mesh.edges
            ):
                edits_log.append({
                    "op": "subdivide_edge",
                    "a": int(a), "b": int(b), "t": 0.5,
                })
                cmds.append(_compose_seed_update_edits(state, edits_log))

    # ── N — add a free vertex ──
    # Spawns a vertex at the current cursor's local-space position
    # (offset 0.2m forward from the currently-selected vertex). Selection
    # advances to the new vertex so subsequent arrows nudge it.
    if rl.is_key_pressed(rl.KeyboardKey.KEY_N):
        anchor = mesh.vertices[state.edit_vertex_idx]
        new_pos = (anchor[0], anchor[1] + 0.2, anchor[2])
        edits_log.append({
            "op": "add_vertex", "at": [new_pos[0], new_pos[1], new_pos[2]],
        })
        cmds.append(_compose_seed_update_edits(state, edits_log))
        # Advance selection to the new vertex (last index after replay).
        # We can't know the new index until the next manifest tick —
        # leave selection alone; user can TAB to it.

    # ── DEL — remove_edge (between prev → current) ──
    if rl.is_key_pressed(rl.KeyboardKey.KEY_DELETE):
        prev = state.edit_prev_vertex_idx
        cur = state.edit_vertex_idx
        if prev is not None and prev != cur:
            a, b = (prev, cur) if prev < cur else (cur, prev)
            if (a, b) in tuple(
                (min(x, y), max(x, y)) for (x, y) in mesh.edges
            ):
                edits_log.append({
                    "op": "remove_edge", "a": int(a), "b": int(b),
                })
                cmds.append(_compose_seed_update_edits(state, edits_log))

    # ── U — undo (pop last op from log) ──
    if rl.is_key_pressed(rl.KeyboardKey.KEY_U):
        if edits_log:
            edits_log.pop()
            cmds.append(_compose_seed_update_edits(state, edits_log))

    return cmds


def _compose_seed_update_edits(state: BuildState, edits_log: list) -> dict:
    return {
        "cmd": "seed_update",
        "seed_id": int(state.selected_seed_id),
        "fields": {"mesh_edits": list(edits_log)},
    }


def hud_lines(state: BuildState, manifest: dict) -> list[str]:
    """Compose the BUILD-mode HUD identity block. Drawn in place of the
    default character-sheet identity when `state.active`."""
    if not state.active:
        return []
    seeds_count = len(_seeds(manifest))
    selected_str = (
        f"#{state.selected_seed_id}" if state.selected_seed_id is not None
        else "—"
    )
    biome_label = str(manifest.get("biome", "?")).upper()
    lines = [
        f"{biome_label} — BUILD/{state.sub_mode.upper()}",
        f"KIND   {state.selected_mesh():<12} SCALE {state.scale:.2f}   YAW {int(state.yaw_deg)}°",
        f"COLOR  ({state.color_r:.2f}, {state.color_g:.2f}, {state.color_b:.2f})",
        f"CURSOR ({state.cursor_x:+.0f}, {state.cursor_y:+.1f}, {state.cursor_z:+.0f})  SEL {selected_str}",
        f"COUNT  {seeds_count} seed{'s' if seeds_count != 1 else ''}",
    ]
    # EDIT sub-mode appends a row — vertex cursor + edge count + log length
    # so the user has feedback for every TAB / J / C / U press.
    if state.sub_mode == "edit" and state.selected_seed_id is not None:
        sel = _find_selected(manifest, state.selected_seed_id)
        if sel is not None:
            edits = sel.get("mesh_edits") or []
            base = get_builtin(str(sel.get("base_mesh", "")))
            v_total = base.vertex_count() if base is not None else 0
            e_total = base.edge_count() if base is not None else 0
            prev_str = (
                str(state.edit_prev_vertex_idx)
                if state.edit_prev_vertex_idx is not None else "—"
            )
            lines.append(
                f"EDIT   v{state.edit_vertex_idx} of {v_total}   "
                f"prev {prev_str}   edges {e_total}   log {len(edits)}"
            )
    return lines
