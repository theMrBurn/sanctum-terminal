"""Vector terminal V1 — first-person wireframe renderer.

Subscribes to the brain manifest stream on TCP 9877. Renders entities,
floor/ceiling grids, and envelope ring as amber wireframes against pure
black with Battlezone-style distance falloff. WASD + mouse free-flight,
no collision. ENTER fires a state-aware transition request. Esc closes.

Run from repo root:  python3 -m clients.vector_terminal.main
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

# Allow `python3 -m clients.vector_terminal.main` from repo root, AND
# `python3 clients/vector_terminal/main.py` (direct invocation) by ensuring
# the repo root is on sys.path before we import core.systems.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pyray as rl  # noqa: E402

from clients.vector_terminal import config as cfg  # noqa: E402
from clients.vector_terminal import dial_input  # noqa: E402
from clients.vector_terminal import hud  # noqa: E402
from clients.vector_terminal import state_events as state_events_renderer  # noqa: E402
from clients.vector_terminal.collision import resolve_collisions  # noqa: E402
from clients.vector_terminal.envelope import clamp_to_envelope  # noqa: E402
from clients.vector_terminal.inputs import action_for_key_index, next_inventory_name  # noqa: E402
from clients.vector_terminal.kind_bounds import bounds_for, class_for  # noqa: E402
from clients.vector_terminal.manifest_io import ManifestClient  # noqa: E402
from clients.vector_terminal.recipes import recipe_for_kind, WireframeRecipe  # noqa: E402
from clients.vector_terminal.targeting import entity_at_crosshair  # noqa: E402
from clients.vector_terminal.world_revision import WorldRevisionTracker  # noqa: E402


_NUM_KEYS = (
    "KEY_ONE", "KEY_TWO", "KEY_THREE", "KEY_FOUR", "KEY_FIVE",
    "KEY_SIX", "KEY_SEVEN", "KEY_EIGHT", "KEY_NINE",
)


def smart_enter_target(state: str) -> str | None:
    return cfg.ENTER_TARGETS.get(state)


def main() -> int:
    rl.init_window(cfg.WIDTH, cfg.HEIGHT, "Vector Terminal V1")
    rl.set_window_state(rl.ConfigFlags.FLAG_WINDOW_RESIZABLE)
    rl.set_target_fps(cfg.TARGET_FPS)
    rl.disable_cursor()
    hud.load_font()

    camera = rl.Camera3D(
        rl.Vector3(0.0, cfg.EYE_HEIGHT, 0.0),
        rl.Vector3(0.0, cfg.EYE_HEIGHT, 1.0),
        rl.Vector3(0.0, 1.0, 0.0),
        75.0,
        rl.CameraProjection.CAMERA_PERSPECTIVE,
    )

    yaw = 0.0
    pitch = 0.0
    vy = 0.0  # vertical velocity for jump
    noclip = False
    show_hud = True
    show_inventory_modal = False
    click_pings: list[float] = []         # timestamps; fade over CLICK_PING_DURATION
    interact_flashes: list[tuple[float, float, float, float]] = []  # (t_start, x, y, z) raylib

    client = ManifestClient(cfg.BRAIN_HOST, cfg.BRAIN_PORT)
    try:
        client.connect()
    except OSError as exc:
        print(
            f"[vector_terminal] cannot reach brain at "
            f"{cfg.BRAIN_HOST}:{cfg.BRAIN_PORT} — {exc}",
            file=sys.stderr,
        )
        rl.close_window()
        return 1

    revision = WorldRevisionTracker()
    last_manifest: dict = {}
    last_cam_send = 0.0

    # Dial state — local cursor synced to brain's default_index when a new
    # dial appears. last_dial_source detects when a fresh dial supersedes an
    # old one (different source = reset cursor to its default).
    selected_dial_idx = 0
    last_dial_source: str | None = None

    # StateEvent toast state — watermark suppresses historical events on
    # connect; new events become active toasts and expire by register-driven
    # duration. Per design_state_events.
    seen_event_id = 0
    active_toasts: list = []

    while not rl.window_should_close():
        dt = rl.get_frame_time()
        now = time.monotonic()

        # Detect active dial — when present, suspend normal input handlers.
        # The dial cursor + commit/cancel handlers run instead. Modal pattern
        # for character-creation pillars, latches, encounter dialog, etc.
        # Per `design_dial_input`.
        dial_prompt_data = last_manifest.get("dial_prompt")
        dial_active = dial_prompt_data is not None
        if dial_active:
            src = dial_prompt_data.get("source")
            if src != last_dial_source:
                selected_dial_idx = int(dial_prompt_data.get("default_index", 0))
                last_dial_source = src
            new_idx, dial_action = dial_input.handle_input(
                dial_prompt_data, selected_dial_idx)
            selected_dial_idx = new_idx
            if dial_action == "commit":
                client.send({"cmd": "dial_response",
                             "answer_idx": selected_dial_idx})
                last_dial_source = None
            elif dial_action == "cancel":
                client.send({"cmd": "dial_cancel"})
                last_dial_source = None
        else:
            last_dial_source = None

        if not dial_active and rl.is_key_pressed(rl.KeyboardKey.KEY_ESCAPE):
            break

        delta = rl.get_mouse_delta()
        if not dial_active:
            yaw -= delta.x * cfg.MOUSE_SENS
            pitch -= delta.y * cfg.MOUSE_SENS
            pitch = max(-math.pi / 2 + 0.01, min(math.pi / 2 - 0.01, pitch))

        cy = math.cos(yaw)
        sy_ = math.sin(yaw)
        cp = math.cos(pitch)
        sp = math.sin(pitch)
        forward = (cp * sy_, sp, cp * cy)
        flat_forward = (sy_, 0.0, cy)
        # Right vector — sign flipped relative to naive (cy, 0, -sy_) because
        # raylib's right-handed Y-up convention puts +X to the camera's left
        # when looking +Z. See pyray docs / godot/main.gd:5311-5345 for parity.
        right = (-cy, 0.0, sy_)

        mx = mz = 0.0
        if not dial_active:
            if rl.is_key_down(rl.KeyboardKey.KEY_W):
                mx += flat_forward[0]
                mz += flat_forward[2]
            if rl.is_key_down(rl.KeyboardKey.KEY_S):
                mx -= flat_forward[0]
                mz -= flat_forward[2]
            if rl.is_key_down(rl.KeyboardKey.KEY_D):
                mx += right[0]
                mz += right[2]
            if rl.is_key_down(rl.KeyboardKey.KEY_A):
                mx -= right[0]
                mz -= right[2]
        mag = math.sqrt(mx * mx + mz * mz)
        if mag > 0:
            sprinting = rl.is_key_down(rl.KeyboardKey.KEY_LEFT_SHIFT) or rl.is_key_down(rl.KeyboardKey.KEY_RIGHT_SHIFT)
            speed = cfg.MOVE_SPEED * (cfg.SPRINT_MULTIPLIER if sprinting else 1.0)
            step = speed * dt
            camera.position.x += mx / mag * step
            camera.position.z += mz / mag * step

        # Vertical physics — jump impulse + gravity. Floor at EYE_HEIGHT.
        if (not dial_active
                and rl.is_key_pressed(rl.KeyboardKey.KEY_SPACE)
                and abs(camera.position.y - cfg.EYE_HEIGHT) < 0.01):
            vy = cfg.JUMP_VELOCITY
        camera.position.y += vy * dt
        vy -= cfg.GRAVITY * dt
        if camera.position.y <= cfg.EYE_HEIGHT:
            camera.position.y = cfg.EYE_HEIGHT
            vy = 0.0

        if not noclip:
            new_x, new_z = resolve_collisions(
                camera.position.x,
                camera.position.z,
                last_manifest.get("entities", []),
                cfg.PLAYER_COLLISION_RADIUS,
                cfg.COLLISION_CULL_DIST,
            )
        else:
            new_x, new_z = camera.position.x, camera.position.z
        envelope = last_manifest.get("playable_envelope", {})
        new_x, new_z = clamp_to_envelope(
            new_x,
            new_z,
            float(envelope.get("radius", 0.0)),
            float(envelope.get("softness", 1.0)),
            dt,
        )
        camera.position.x = new_x
        camera.position.z = new_z

        camera.target = rl.Vector3(
            camera.position.x + forward[0],
            camera.position.y + forward[1],
            camera.position.z + forward[2],
        )

        if not dial_active:
            if rl.is_key_pressed(rl.KeyboardKey.KEY_ENTER):
                state = str(last_manifest.get("game_state", {}).get("state", "HUB"))
                target = smart_enter_target(state)
                if target is not None:
                    client.send({"cmd": "state_transition_request", "target": target})

            if rl.is_key_pressed(rl.KeyboardKey.KEY_E):
                inv = last_manifest.get("player", {}).get("inventory", [])
                equipped = last_manifest.get("player", {}).get("equipped")
                nxt = next_inventory_name(inv, equipped)
                if nxt is not None:
                    client.send({"cmd": "equip_request", "name": nxt})

            if rl.is_key_pressed(rl.KeyboardKey.KEY_L):
                client.send({"cmd": "light_cycle"})

            if rl.is_key_pressed(rl.KeyboardKey.KEY_T):
                client.send({"cmd": "tension_toggle"})

            if rl.is_key_pressed(rl.KeyboardKey.KEY_I):
                show_inventory_modal = not show_inventory_modal

            if rl.is_key_pressed(rl.KeyboardKey.KEY_H):
                show_hud = not show_hud

            if rl.is_key_pressed(rl.KeyboardKey.KEY_BACKSLASH):
                noclip = not noclip

            # Backspace = abort to HUB. Brain validates IN_MISSION → HUB
            # so this only does anything when we're actually in a mission.
            # Always-a-way-home navigation per the UAT-driven design directive.
            if rl.is_key_pressed(rl.KeyboardKey.KEY_BACKSPACE):
                state = str(last_manifest.get("game_state", {}).get("state", ""))
                if state == "IN_MISSION":
                    client.send({"cmd": "state_transition_request", "target": "HUB"})

            if rl.is_mouse_button_pressed(rl.MouseButton.MOUSE_BUTTON_LEFT):
                click_pings.append(now)
                client.send({
                    "cmd": "tag_event",
                    "tag": {
                        "action": "primary",
                        "x": camera.position.x,
                        "y": camera.position.z,  # manifest y from raylib z
                    },
                })

            if rl.is_key_pressed(rl.KeyboardKey.KEY_F):
                target = entity_at_crosshair(
                    camera.position.x, camera.position.y, camera.position.z,
                    forward[0], forward[1], forward[2],
                    last_manifest.get("entities", []),
                    cfg.INTERACT_RANGE_M,
                    cfg.INTERACT_RADIUS_HEURISTIC,
                )
                if target is not None:
                    pillar_id = dial_input.pillar_id_from_kind(str(target.get("kind", "")))
                    if pillar_id is not None:
                        # Any pillar entity — brain validates which states
                        # allow which pillars (e.g., reflection from HUB,
                        # the seven from CHARACTER_CREATION). Brain returns
                        # the dial_prompt in next manifest; the dial-active
                        # branch above processes from then on.
                        client.send({"cmd": "engage_pillar", "pillar": pillar_id})
                    else:
                        tx = float(target.get("x", 0.0))
                        ty = float(target.get("z", 0.0))
                        tz = float(target.get("y", 0.0))
                        interact_flashes.append((now, tx, ty, tz))
                        client.send({
                            "cmd": "tag_event",
                            "tag": {
                                "action": "interact",
                                "kind": str(target.get("kind", "")),
                                "x": float(target.get("x", 0.0)),
                                "y": float(target.get("y", 0.0)),
                            },
                        })

            encounter = last_manifest.get("encounter", {})
            options = encounter.get("action_options") or []
            if options:
                for i, key_name in enumerate(_NUM_KEYS):
                    if i >= len(options):
                        break
                    if rl.is_key_pressed(getattr(rl.KeyboardKey, key_name)):
                        action = action_for_key_index(options, i)
                        if action:
                            client.send({"cmd": "encounter_action", "action": action})
                        break

        for msg in client.poll():
            if msg.get("unchanged"):
                continue
            is_first_manifest = not last_manifest
            last_manifest = msg
            if is_first_manifest or revision.observe(msg.get("world_revision")):
                _teleport_to_spawn(camera, msg)
                yaw, pitch = _spawn_orientation(msg)

        # Advance state-event toasts — runs once per frame regardless of
        # whether new manifests arrived. Watermark + active list update.
        seen_event_id, active_toasts = state_events_renderer.update(
            last_manifest.get("state_events", []) or [],
            seen_event_id,
            active_toasts,
            now,
        )

        if now - last_cam_send >= cfg.CAM_UPDATE_DT:
            client.send(
                {
                    # Match Godot axis swap: cam_y = forward (raylib Z),
                    # cam_z = up (raylib Y). See godot/main.gd:2291-2297.
                    "cam_x": camera.position.x,
                    "cam_y": camera.position.z,
                    "cam_z": camera.position.y,
                    "heading": math.degrees(yaw),
                    "pitch": math.degrees(pitch),
                    "dt": now - last_cam_send,
                }
            )
            last_cam_send = now

        rl.begin_drawing()
        rl.clear_background(rl.BLACK)
        rl.begin_mode_3d(camera)

        _draw_floor_blockout(camera)
        _draw_floor_grid(camera)
        biome = str(last_manifest.get("biome", ""))
        if cfg.DRAW_CEILING_GRID and biome == "cavern":
            _draw_ceiling_grid(camera, cfg.CAVERN_CEILING_HEIGHT)
        _draw_envelope_ring(last_manifest.get("playable_envelope", {}), camera)

        for ent in last_manifest.get("entities", []):
            if class_for(str(ent.get("kind", ""))) in cfg.SKIP_ENTITY_CLASSES:
                continue
            _draw_entity(ent, camera)

        amber = (cfg.AMBER_RGB[0], cfg.AMBER_RGB[1], cfg.AMBER_RGB[2], 255)

        # Interact-flash brackets — drawn in 3D (depth-tested with the world).
        interact_flashes = [(t, x, y, z) for (t, x, y, z) in interact_flashes
                            if now - t < cfg.INTERACT_FLASH_DURATION]
        for t, fx_w, fy_w, fz_w in interact_flashes:
            age = (now - t) / cfg.INTERACT_FLASH_DURATION
            intensity = max(0.0, 1.0 - age)
            c = (int(255 * intensity), int(176 * intensity), 0, 255)
            r = 0.6 + age * 0.4  # bracket grows slightly as it fades
            rl.draw_cube_wires(rl.Vector3(fx_w, fy_w, fz_w), r, r, r, c)

        rl.end_mode_3d()

        if show_hud:
            hud.draw_hud(last_manifest, amber)
            hud.draw_encounter_panel(last_manifest, amber)
            hud.draw_crosshair(rl.get_screen_width(), rl.get_screen_height(), amber)

        # Click-ping rings at screen center — 2D, drawn after end_mode_3d.
        click_pings = [t for t in click_pings if now - t < cfg.CLICK_PING_DURATION]
        for t in click_pings:
            age = (now - t) / cfg.CLICK_PING_DURATION
            r_px = int(cfg.CLICK_PING_RADIUS_PX * age)
            intensity = max(0.0, 1.0 - age)
            c = (int(255 * intensity), int(176 * intensity), 0, 255)
            rl.draw_circle_lines(
                rl.get_screen_width() // 2,
                rl.get_screen_height() // 2,
                float(r_px),
                c,
            )

        if show_inventory_modal:
            hud.draw_inventory_modal(last_manifest, amber,
                                     rl.get_screen_width(),
                                     rl.get_screen_height())

        if dial_active:
            dial_input.draw_dial_overlay(
                dial_prompt_data,
                selected_dial_idx,
                rl.get_screen_width(),
                rl.get_screen_height(),
                amber,
            )

        if noclip:
            hud.draw_status_chip("NOCLIP", rl.get_screen_width(), amber)

        # State event toasts — drawn last so they're on top of HUD/dial/etc.
        state_events_renderer.draw(
            active_toasts,
            rl.get_screen_width(),
            now,
            amber,
        )

        rl.end_drawing()

    rl.close_window()
    client.close()
    return 0


def _intensity_for_distance(dist: float) -> float:
    """Battlezone-style phosphor falloff. Full intensity within NEAR_DIST,
    linear fade to MIN_GLOW at FAR_FADE, never fully dark."""
    if dist <= cfg.NEAR_DIST:
        return 1.0
    if dist >= cfg.FAR_FADE:
        return cfg.MIN_GLOW
    t = (dist - cfg.NEAR_DIST) / (cfg.FAR_FADE - cfg.NEAR_DIST)
    return max(cfg.MIN_GLOW, 1.0 - t * (1.0 - cfg.MIN_GLOW))


def _amber(intensity: float) -> tuple[int, int, int, int]:
    r, g, b = cfg.AMBER_RGB
    return int(r * intensity), int(g * intensity), int(b * intensity), 255


def _draw_entity(ent: dict, camera) -> None:
    kind = str(ent.get("kind", ""))
    bx, by, bz = bounds_for(kind)
    # Manifest is Z-up, raylib Y-up. Position swap: manifest (x, y, z) → raylib (x, z, y).
    # Scale swap matches: raylib (x, y, z) ← manifest (x, z, y) = (sx*bx, sz*bz, sy*by).
    px = float(ent.get("x", 0.0))
    py = float(ent.get("z", 0.0))
    pz = float(ent.get("y", 0.0))
    sxw = float(ent.get("sx", 1.0)) * bx
    syw = float(ent.get("sy", 1.0)) * by  # manifest forward
    szw = float(ent.get("sz", 1.0)) * bz  # manifest up
    dist = math.sqrt(
        (px - camera.position.x) ** 2
        + (py - camera.position.y) ** 2
        + (pz - camera.position.z) ** 2
    )
    intensity = _intensity_for_distance(dist)
    # Honor per-entity color from manifest (brain sets pillar palette, biome
    # tints, encounter highlights via r/g/b 0-1). Distance falloff modulates
    # intensity. Default to amber if entity didn't specify color.
    base_r = float(ent.get("r", cfg.AMBER_RGB[0] / 255.0))
    base_g = float(ent.get("g", cfg.AMBER_RGB[1] / 255.0))
    base_b = float(ent.get("b", cfg.AMBER_RGB[2] / 255.0))
    color = (
        max(0, min(255, int(base_r * 255 * intensity))),
        max(0, min(255, int(base_g * 255 * intensity))),
        max(0, min(255, int(base_b * 255 * intensity))),
        255,
    )
    recipe = recipe_for_kind(kind)
    heading = float(ent.get("heading", 0.0))
    _draw_recipe(recipe, px, py, pz, sxw, szw, syw, heading, color)


def _draw_recipe(
    recipe: WireframeRecipe,
    px: float, py: float, pz: float,
    rsx: float, rsy: float, rsz: float,
    yaw_deg: float,
    color,
) -> None:
    """Project a recipe's local-space vertices through scale + yaw + position.
    Two-pass render: black triangle fill (depth-only mass) then amber edges.
    The fill makes wireframes read as opaque — back edges and entities
    behind get occluded by the depth buffer."""
    cy = math.cos(math.radians(yaw_deg))
    sy_ = math.sin(math.radians(yaw_deg))
    transformed: list[tuple[float, float, float]] = []
    for vx, vy, vz in recipe.vertices:
        x = vx * rsx
        y = vy * rsy
        z = vz * rsz
        x_rot = x * cy + z * sy_
        z_rot = -x * sy_ + z * cy
        transformed.append((px + x_rot, py + y, pz + z_rot))

    if recipe.faces:
        # BLACK fills — hides back-faces via depth buffer (opacity) without
        # competing with edge color. Period-correct CRT vector aesthetic.
        # Tried dimmed-color fills earlier; they blurred geometry into a mass.
        for a, b, c in recipe.faces:
            ax, ay, az = transformed[a]
            bx, by, bz = transformed[b]
            cx2, cy2, cz2 = transformed[c]
            # Render double-sided by emitting both windings — avoids backface
            # culling rejecting faces with the wrong winding without needing
            # to disable culling globally.
            rl.draw_triangle_3d(
                rl.Vector3(ax, ay, az),
                rl.Vector3(bx, by, bz),
                rl.Vector3(cx2, cy2, cz2),
                rl.BLACK,
            )
            rl.draw_triangle_3d(
                rl.Vector3(ax, ay, az),
                rl.Vector3(cx2, cy2, cz2),
                rl.Vector3(bx, by, bz),
                rl.BLACK,
            )

    for a, b in recipe.edges:
        ax, ay, az = transformed[a]
        bx, by, bz = transformed[b]
        rl.draw_line_3d(rl.Vector3(ax, ay, az), rl.Vector3(bx, by, bz), color)


def _draw_floor_blockout(camera) -> None:
    """Opaque black plane just below y=0. Depth buffer occludes anything
    rendered below the walking plane — half-buried walls slice cleanly,
    fully subterranean entities disappear."""
    rl.draw_plane(
        rl.Vector3(camera.position.x, cfg.FLOOR_BLOCKOUT_Y, camera.position.z),
        rl.Vector2(cfg.FLOOR_BLOCKOUT_EXTENT, cfg.FLOOR_BLOCKOUT_EXTENT),
        rl.BLACK,
    )


def _draw_floor_grid(camera) -> None:
    """Wireframe floor at y=0, snapped to camera xz so it reads as infinite."""
    _draw_horizontal_grid(camera, 0.0, cfg.FLOOR_GRID_SPACING)


def _draw_ceiling_grid(camera, height: float) -> None:
    """Sparser ceiling grid — half resolution to reduce visual weight overhead."""
    _draw_horizontal_grid(camera, height, cfg.CEILING_GRID_SPACING)


def _draw_horizontal_grid(camera, y: float, spacing: float) -> None:
    cx = camera.position.x
    cz = camera.position.z
    snap_x = math.floor(cx / spacing) * spacing
    snap_z = math.floor(cz / spacing) * spacing
    extent = cfg.FLOOR_GRID_EXTENT
    n = int(extent / spacing)

    z0 = snap_z - extent
    z1 = snap_z + extent
    for i in range(-n, n + 1):
        x = snap_x + i * spacing
        # Use perpendicular distance from camera to this line as the depth cue.
        dist = abs(x - cx)
        color = _amber(_intensity_for_distance(dist))
        rl.draw_line_3d(rl.Vector3(x, y, z0), rl.Vector3(x, y, z1), color)

    x0 = snap_x - extent
    x1 = snap_x + extent
    for i in range(-n, n + 1):
        z = snap_z + i * spacing
        dist = abs(z - cz)
        color = _amber(_intensity_for_distance(dist))
        rl.draw_line_3d(rl.Vector3(x0, y, z), rl.Vector3(x1, y, z), color)


def _draw_envelope_ring(envelope: dict, camera) -> None:
    radius = float(envelope.get("radius", 0.0))
    if radius <= 0:
        return
    # Brain envelope is centered on world origin (per playable_envelope contract).
    segs = cfg.ENVELOPE_RING_SEGMENTS
    prev: rl.Vector3 | None = None
    for i in range(segs + 1):
        theta = 2.0 * math.pi * i / segs
        x = radius * math.cos(theta)
        z = radius * math.sin(theta)
        if prev is not None:
            mid_x = (x + prev.x) * 0.5
            mid_z = (z + prev.z) * 0.5
            dist = math.sqrt(
                (mid_x - camera.position.x) ** 2
                + (mid_z - camera.position.z) ** 2
            )
            color = _amber(_intensity_for_distance(dist))
            rl.draw_line_3d(prev, rl.Vector3(x, 0.0, z), color)
        prev = rl.Vector3(x, 0.0, z)


def _teleport_to_spawn(camera, manifest: dict) -> None:
    spawn = manifest.get("spawn", {}).get("location", {})
    camera.position.x = float(spawn.get("x", 0.0))
    camera.position.z = float(spawn.get("y", 0.0))
    camera.position.y = cfg.EYE_HEIGHT


def _spawn_orientation(manifest: dict) -> tuple[float, float]:
    spawn = manifest.get("spawn", {}).get("location", {})
    return (
        math.radians(float(spawn.get("heading_deg", 0.0))),
        math.radians(float(spawn.get("pitch_deg", 0.0))),
    )


if __name__ == "__main__":
    sys.exit(main())
