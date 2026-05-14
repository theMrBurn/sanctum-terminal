"""Thing-tune mode — live-tune library/things/*.json in the workroom.

The B-mode equivalent for composite Things. While tune_active is True
the user's input keys nudge a selected part's rel_position / rel_size
/ rotation_deg via `thing_edit` brain commands; ENTER persists the
mutated thing back to its JSON file via `thing_save`.

Part selection is crosshair-based: the entity closest to the camera-
forward ray (and tagged with `_thing` + `_role`) is the active target.

Edit step sizes are intentionally small (1% bbox) so nudges read as
adjustments, not jumps. Hold a key and step accumulates per-frame.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pyray as rl

from clients.vector_terminal import input_map


# Step sizes
POSITION_STEP = 0.01      # 1% of bbox per nudge — fine-grained
SIZE_STEP     = 0.01
ROTATION_STEP = 5.0       # degrees


@dataclass
class TuneState:
    active: bool = False
    locked_thing: str | None = None   # name of currently-tuned thing
    locked_role:  str | None = None   # name of currently-tuned part role
    last_pick_t:  float = 0.0


def toggle(state: TuneState) -> None:
    """Flip tune_active. On enter, lock is cleared so the first frame
    in tune mode picks fresh from the crosshair."""
    state.active = not state.active
    if not state.active:
        state.locked_thing = None
        state.locked_role = None


def pick_part_under_crosshair(
    manifest: dict, camera, max_range_m: float = 8.0,
) -> tuple[str, str] | None:
    """Return (thing_name, part_role) of the nearest thing-derived
    entity along camera-forward, or None if no candidate is in range.

    Uses simple ray-direction dot-product picking: entity scores high
    if its world position is closely aligned with the camera's
    forward vector, and within max_range_m of the camera.
    """
    cam_pos = camera.position
    cam_target = camera.target
    fx = cam_target.x - cam_pos.x
    fy = cam_target.y - cam_pos.y
    fz = cam_target.z - cam_pos.z
    fmag = math.sqrt(fx * fx + fy * fy + fz * fz)
    if fmag < 1e-6:
        return None
    fx /= fmag; fy /= fmag; fz /= fmag

    entities = manifest.get("entities", []) or []
    best: tuple[str, str] | None = None
    best_score = -1.0
    for ent in entities:
        thing = ent.get("_thing")
        role  = ent.get("_role")
        if not thing or not role:
            continue
        # Brain coords are (x, y_forward, z_up); raylib is (x, z_forward, y_up).
        # Convert entity to raylib camera space:
        ex = float(ent.get("x", 0.0))
        ey = float(ent.get("z", 0.0))            # raylib y = brain z (up)
        ez = float(ent.get("y", 0.0))            # raylib z = brain y (forward)
        dx = ex - cam_pos.x
        dy = ey - cam_pos.y
        dz = ez - cam_pos.z
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist > max_range_m or dist < 0.01:
            continue
        # Dot product of normalized direction with camera forward
        ndx = dx / dist; ndy = dy / dist; ndz = dz / dist
        align = ndx * fx + ndy * fy + ndz * fz
        if align < 0.85:           # must be roughly in front + center
            continue
        # Score: prefer closer + better-aligned
        score = align - (dist / max_range_m) * 0.3
        if score > best_score:
            best_score = score
            best = (thing, role)
    return best


def handle_input(
    manifest: dict,
    camera,
    state: TuneState,
) -> list[dict[str, Any]]:
    """Process one frame's input while tune mode is active. Returns
    a list of brain command dicts the caller should send."""
    if not state.active:
        return []

    cmds: list[dict[str, Any]] = []

    # Refresh the lock from the crosshair if not yet locked, OR if
    # the user is actively re-aiming (no editing keys pressed).
    pick = pick_part_under_crosshair(manifest, camera)
    if pick is not None:
        state.locked_thing, state.locked_role = pick

    if state.locked_thing is None or state.locked_role is None:
        return cmds

    thing = state.locked_thing
    role  = state.locked_role

    # Player-relative axes — arrow keys feel intuitive regardless of
    # where the user is standing. Compute forward / right from the
    # camera's XZ projection in raylib space, convert to brain coords
    # (brain x=lateral matches raylib x; brain y=forward matches
    # raylib z). The thing-gallery is yaw=0, so world-brain = bbox-local.
    fwd_x = camera.target.x - camera.position.x       # raylib x
    fwd_z = camera.target.z - camera.position.z       # raylib z
    fwd_mag_xz = math.sqrt(fwd_x * fwd_x + fwd_z * fwd_z)
    if fwd_mag_xz < 1e-6:
        # Camera looking straight up/down — keep last-known facing as
        # +brain-Y so behavior is at least deterministic, not garbage.
        fb_x, fb_y = 0.0, 1.0
    else:
        fb_x = fwd_x / fwd_mag_xz                     # brain x component of facing
        fb_y = fwd_z / fwd_mag_xz                     # brain y component of facing
    # Player right vector. The brain→raylib axis swap (brain.y ↔ raylib.z)
    # effectively flips handedness, so the user's screen-right is the
    # CCW perpendicular to facing in brain XY, not the CW one. UAT
    # 2026-05-14: initial CW derivation made arrows feel reversed.
    rt_x, rt_y = -fb_y, fb_x

    # RIGHT arrow → "to my right"
    if input_map.pressed("tune_pos_x_plus"):
        cmds.append(_edit_cmd(thing, role, "rel_position",
                              [rt_x * POSITION_STEP, rt_y * POSITION_STEP, 0.0]))
    if input_map.pressed("tune_pos_x_minus"):
        cmds.append(_edit_cmd(thing, role, "rel_position",
                              [-rt_x * POSITION_STEP, -rt_y * POSITION_STEP, 0.0]))
    # UP arrow → "away from me" (forward in player frame)
    if input_map.pressed("tune_pos_y_plus"):
        cmds.append(_edit_cmd(thing, role, "rel_position",
                              [fb_x * POSITION_STEP, fb_y * POSITION_STEP, 0.0]))
    if input_map.pressed("tune_pos_y_minus"):
        cmds.append(_edit_cmd(thing, role, "rel_position",
                              [-fb_x * POSITION_STEP, -fb_y * POSITION_STEP, 0.0]))
    # PgUp / PgDn — world Z (up axis), always literal up/down
    if input_map.pressed("tune_pos_z_plus"):
        cmds.append(_edit_cmd(thing, role, "rel_position",
                              [0.0, 0.0, POSITION_STEP]))
    if input_map.pressed("tune_pos_z_minus"):
        cmds.append(_edit_cmd(thing, role, "rel_position",
                              [0.0, 0.0, -POSITION_STEP]))

    # Size — uniform 3-axis scale step
    if input_map.pressed("tune_size_plus"):
        cmds.append(_edit_cmd(thing, role, "rel_size",
                              [SIZE_STEP, SIZE_STEP, SIZE_STEP]))
    if input_map.pressed("tune_size_minus"):
        cmds.append(_edit_cmd(thing, role, "rel_size",
                              [-SIZE_STEP, -SIZE_STEP, -SIZE_STEP]))

    # Rotation
    if input_map.pressed("tune_rot_plus"):
        cmds.append(_edit_cmd(thing, role, "rotation_deg", ROTATION_STEP))
    if input_map.pressed("tune_rot_minus"):
        cmds.append(_edit_cmd(thing, role, "rotation_deg", -ROTATION_STEP))

    # Save
    if input_map.pressed("tune_save"):
        cmds.append({"cmd": "thing_save", "thing_name": thing})

    return cmds


def _edit_cmd(thing: str, role: str, field: str, delta) -> dict[str, Any]:
    return {
        "cmd":         "thing_edit",
        "thing_name":  thing,
        "part_role":   role,
        "field":       field,
        "delta":       delta,
    }


# ── HUD ─────────────────────────────────────────────────────────


def draw_hud(state: TuneState, manifest: dict, screen_w: int, color) -> None:
    """One-line top-corner indicator: TUNE mode + currently selected
    thing/part. Keep it small + non-intrusive."""
    if not state.active:
        return

    import pyray as rl
    from clients.vector_terminal import hud

    font = hud.font()
    line1 = "TUNE — U exit, ENTER save"
    if state.locked_thing and state.locked_role:
        line2 = f"  → {state.locked_thing} . {state.locked_role}"
    else:
        line2 = "  → (aim at a thing)"
    line3 = "  arrows/PgUp/PgDn=pos  +/-=size  ,/.=rot"

    x = screen_w - 360
    y = 8
    rl.draw_rectangle(x - 8, y - 4, 360, 60, (0, 0, 0, 200))
    rl.draw_text_ex(font, line1, rl.Vector2(x, y),       14, 1.0, color)
    rl.draw_text_ex(font, line2, rl.Vector2(x, y + 18),  14, 1.0, color)
    rl.draw_text_ex(font, line3, rl.Vector2(x, y + 36),  12, 1.0, color)
