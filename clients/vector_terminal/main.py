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
from clients.vector_terminal import ball as ball_renderer  # noqa: E402
from clients.vector_terminal import banner  # noqa: E402
from clients.vector_terminal import build_mode  # noqa: E402
from clients.vector_terminal import chamber as chamber_renderer  # noqa: E402
from clients.vector_terminal import console as volley_console  # noqa: E402
from clients.vector_terminal import horizon_objects as horizon_renderer  # noqa: E402
from clients.vector_terminal import input_map  # noqa: E402
from clients.vector_terminal import journal  # noqa: E402
from clients.vector_terminal import reflective as reflective_overlay  # noqa: E402
from clients.vector_terminal.seed_collision import compute_floor_height  # noqa: E402
from clients.vector_terminal.seed_mesh_cache import SeedMeshCache  # noqa: E402
from clients.vector_terminal import silhouette as silhouette_renderer  # noqa: E402
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
    show_journal = False
    journal_state = journal.JournalState()
    reflective_state = reflective_overlay.ReflectiveState()
    build_state = build_mode.BuildState()
    seed_mesh_cache = SeedMeshCache()
    # Per-session cast counter — drives the negative `tag_id` namespace
    # that distinguishes elemental casts from telemetry tags brain-side.
    # Reset on session start; not persisted.
    cast_id_counter: int = 0
    click_pings: list[float] = []         # timestamps; fade over CLICK_PING_DURATION
    interact_flashes: list[tuple[float, float, float, float]] = []  # (t_start, x, y, z) raylib

    # Make-brain ping_pong: paddle motion history. 5-frame ring buffer of
    # (paddle_pos_brain, time). Paddle is a virtual point at
    # paddle_arm_length along camera forward; finite-difference across
    # the window gives the paddle velocity at strike time. Per AC PR 5.
    # Default arm length matches profile vanilla; tracked here as a
    # constant since the client doesn't know per-profile params yet
    # (profile params live brain-side; client passes raw kinematic state).
    paddle_history: list[tuple[tuple[float, float, float], float]] = []
    PADDLE_ARM_LENGTH = 0.7
    PADDLE_HISTORY_LEN = 5

    # Volley console — backtick-toggled overlay for live profile tuning.
    # Per `feat_make-brain-ping-pong.md` PR 7.
    console_state = volley_console.ConsoleState()

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

        # Journal overlay — async quest log per `project_async_quest_refactor`.
        # Open via J anywhere, anytime; toggle quests active/available;
        # ESC closes from inside (J also closes via the same toggle below).
        # Reflective overlay takes priority over everything except dial.
        # When active, it consumes ARROW / ENTER / BKSP / C / ESC so
        # other handlers don't fight it.
        reflective_block = last_manifest.get("reflective") or {}
        reflective_active = bool(reflective_block.get("active")) and not dial_active
        if reflective_active:
            action, payload = reflective_overlay.handle_input(
                last_manifest, reflective_state
            )
            if action == "place" and payload is not None:
                client.send({"cmd": "place_magnet", "magnet": payload["magnet"]})
            elif action == "remove" and payload is not None:
                client.send({"cmd": "remove_magnet", "index": payload["index"]})
            elif action == "commit":
                client.send({"cmd": "commit_reflective"})
            elif action == "abort":
                client.send({"cmd": "abort_reflective"})

        # Volley console — backtick toggles open/close. Trumps everything
        # else so the user can dismiss it from any state. ESC also closes.
        if input_map.pressed("console_toggle"):
            volley_console.toggle(console_state)
        if console_state.open:
            volley_console.consume_chars(console_state)
            if rl.is_key_pressed(rl.KeyboardKey.KEY_ESCAPE):
                volley_console.close(console_state)
            else:
                submitted = volley_console.handle_editing(console_state)
                if submitted is not None and submitted.strip():
                    client.send({
                        "cmd": "console_exec",
                        "payload": {"line": submitted.strip()},
                    })

        # World does not pause — overlay only suspends ENTER/UP/DOWN/ESC.
        journal_active = show_journal and not dial_active and not reflective_active
        if journal_active:
            action, qid = journal.handle_input(last_manifest, journal_state)
            if action == "close":
                show_journal = False
            elif action == "toggle" and qid:
                client.send({"cmd": "journal_toggle_quest", "quest_id": qid})

        # J toggles the journal regardless of whether it's currently open
        # (journal_active intercepts ESC + ENTER + UP/DOWN, but J always
        # cycles the visibility flag). Suspended while a dial is active —
        # the dial owns the modal foreground.
        if (not dial_active and not reflective_active
                and not console_state.open
                and input_map.pressed("journal_toggle")):
            show_journal = not show_journal

        # B toggles BUILD mode (vector-workroom PR 4). Biome-gated: silent
        # no-op outside `workroom`. Only fires WHEN NOT IN BUILD — once
        # inside, B is repurposed as the blue color-channel binding via
        # `build_mode.handle_input`. ESC is the inside-BUILD exit.
        if (not build_state.active
                and not dial_active and not journal_active and not reflective_active
                and not console_state.open
                and input_map.pressed("build_toggle")):
            build_mode.toggle_build(build_state, last_manifest, camera, yaw)

        # ESC inside BUILD exits to walk mode rather than closing the app.
        # Outside BUILD, ESC closes the app (existing behavior).
        if (build_state.active
                and input_map.pressed("state_back")):
            build_state.active = False
        elif (not dial_active and not journal_active and not reflective_active
                and not build_state.active
                and input_map.pressed("state_back")):
            break

        # ENTER toggles PLACE↔EDIT sub-mode while BUILD is active.
        # Eaten BEFORE the per-frame BUILD dispatch so the same press
        # doesn't propagate to PLACE input or other handlers. Requires
        # a selected seed for the PLACE→EDIT transition; silently
        # refuses otherwise.
        if (build_state.active
                and input_map.pressed("submode_toggle")):
            if build_state.sub_mode == "place":
                build_mode.enter_edit(build_state)
            else:
                build_mode.exit_edit(build_state)

        # BUILD-mode input dispatch — runs only while active. Returns a
        # list of brain commands (seed_create/update/delete). Sub-mode
        # branches inside `handle_input` (PLACE vs EDIT). Crucially,
        # runs BEFORE the FPS-movement / equip / interact handlers
        # below; the `build_state.active` gate suspends them.
        if build_state.active:
            build_cmds = build_mode.handle_input(
                build_state, last_manifest, camera, yaw, cache=seed_mesh_cache,
            )
            for cmd in build_cmds:
                client.send(cmd)

        delta = rl.get_mouse_delta()
        if not dial_active and not build_state.active and not console_state.open:
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
        if not dial_active and not build_state.active and not console_state.open:
            if input_map.held("move_forward"):
                mx += flat_forward[0]
                mz += flat_forward[2]
            if input_map.held("move_back"):
                mx -= flat_forward[0]
                mz -= flat_forward[2]
            if input_map.held("move_right"):
                mx += right[0]
                mz += right[2]
            if input_map.held("move_left"):
                mx -= right[0]
                mz -= right[2]
        mag = math.sqrt(mx * mx + mz * mz)
        if mag > 0:
            sprinting = input_map.held("sprint")
            speed = cfg.MOVE_SPEED * (cfg.SPRINT_MULTIPLIER if sprinting else 1.0)
            step = speed * dt
            camera.position.x += mx / mag * step
            camera.position.z += mz / mag * step

        # Vertical physics — jump impulse + gravity. Floor is dynamic:
        # `compute_floor_height` reads workroom seeds and returns the top
        # of the highest walkable surface under the player's XZ within
        # STEP_HEIGHT_MAX of current camera Y. Falls back to EYE_HEIGHT
        # when no seed surface applies. This is what makes ramps/stairs/
        # platforms traversable without lateral collision against walls.
        floor_y = compute_floor_height(
            seeds=last_manifest.get("seeds") or [],
            world_x=camera.position.x,
            world_z=camera.position.z,
            current_y=camera.position.y,
            ground_y=cfg.EYE_HEIGHT,
            cache=seed_mesh_cache,
        )

        # SPACE in BUILD/PLACE drops a seed (handled by build_mode), so it
        # must NOT also trigger jump here. Jump is only available when
        # standing on the current floor (any walkable surface).
        if (not dial_active
                and not build_state.active
                and not console_state.open
                and input_map.pressed("jump")
                and abs(camera.position.y - floor_y) < 0.05):
            vy = cfg.JUMP_VELOCITY
        camera.position.y += vy * dt
        vy -= cfg.GRAVITY * dt
        if camera.position.y <= floor_y:
            camera.position.y = floor_y
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

        # Make-brain ping_pong: track paddle motion for finite-difference
        # velocity at strike time. Paddle is a virtual point at
        # PADDLE_ARM_LENGTH along camera forward; recorded in BRAIN space
        # (x lateral, y forward, z up) so the brain doesn't need to
        # convert. Per AC PR 5 ("Client computes paddle_vel as
        # camera_angular_velocity × paddle_arm_length, sampled over a
        # short window"). Finite-difference of the paddle position is
        # equivalent to the cross-product formulation and avoids the
        # right-vector sign trap.
        forward_brain = (forward[0], forward[2], forward[1])
        paddle_pos_brain = (
            camera.position.x + forward_brain[0] * PADDLE_ARM_LENGTH,
            camera.position.z + forward_brain[1] * PADDLE_ARM_LENGTH,
            camera.position.y + forward_brain[2] * PADDLE_ARM_LENGTH,
        )
        paddle_history.append((paddle_pos_brain, now))
        if len(paddle_history) > PADDLE_HISTORY_LEN:
            paddle_history.pop(0)

        if (not dial_active and not reflective_active and not build_state.active
                and not console_state.open and not journal_active):
            # ENTER drives state transitions (HUB → MISSION_SELECT, etc.) but
            # MUST yield to the journal overlay — there ENTER is the toggle.
            if input_map.pressed("confirm"):
                state = str(last_manifest.get("game_state", {}).get("state", "HUB"))
                target = smart_enter_target(state)
                if target is not None:
                    client.send({"cmd": "state_transition_request", "target": target})

            if input_map.pressed("equip_cycle"):
                inv = last_manifest.get("player", {}).get("inventory", [])
                equipped = last_manifest.get("player", {}).get("equipped")
                nxt = next_inventory_name(inv, equipped)
                if nxt is not None:
                    client.send({"cmd": "equip_request", "name": nxt})

            if input_map.pressed("light_cycle"):
                client.send({"cmd": "light_cycle"})

            if input_map.pressed("tension_toggle"):
                client.send({"cmd": "tension_toggle"})

            if input_map.pressed("inventory_toggle"):
                show_inventory_modal = not show_inventory_modal

            if input_map.pressed("hud_toggle"):
                show_hud = not show_hud

            if input_map.pressed("noclip_toggle"):
                noclip = not noclip

            # Volley resets (PR 6). R = reset current rally (preserves
            # match score). SHIFT+R = reset entire match. Only meaningful
            # in volley_chamber; no-op in other biomes.
            if (last_manifest.get("instance_id") == "ping_pong"
                    and input_map.pressed("reset_rally")):
                if input_map.held("sprint"):
                    client.send({"cmd": "volley_reset_match"})
                else:
                    client.send({"cmd": "volley_reset_rally"})

            # K = damage_self debug. Each press deals 99 damage, sufficient
            # to push HP to 0 in one tap — exposes the forced reflective
            # chain end-to-end (REFLECT toast → fridge UI → commit →
            # respawn chain → regen world + restore HP). Per
            # `design_virtual_hallucination`: HP=0 is just a respawn
            # condition, never perma-death framing.
            if input_map.pressed("damage_self_debug"):
                client.send({"cmd": "damage_self", "amount": 99})

            # PR 5 collapse (2026-05-02): the Backspace IN_MISSION → HUB
            # abort path is dead — IN_MISSION no longer exists. Free
            # exploration replaces "out in a mission"; there's no modal
            # state to abort from. Backspace is unbound here for now.

            if input_map.pressed("fire_primary"):
                click_pings.append(now)
                # Telemetry tag — preserved for the screenshot/marking
                # workflow. Decoupled from gameplay so the same click
                # can register both a position tag and a smash hit.
                client.send({
                    "cmd": "tag_event",
                    "tag": {
                        "action": "primary",
                        "x": camera.position.x,
                        "y": camera.position.z,  # manifest y from raylib z
                    },
                })
                # Make-brain ping_pong: fire_primary serves when no ball,
                # strikes when a ball is in play (Atari single-press, AC
                # decision #4). Paddle velocity comes from finite-
                # differencing the paddle_history ring buffer over the
                # last few frames — a quick mouse flick → high velocity,
                # standing still → near-zero. Per AC PR 5.
                if last_manifest.get("instance_id") == "ping_pong":
                    _ball = last_manifest.get("ball") or {}
                    if not _ball.get("exists"):
                        client.send({"cmd": "volley_serve"})
                    elif len(paddle_history) >= 2:
                        pos_old, t_old = paddle_history[0]
                        pos_new, t_new = paddle_history[-1]
                        dt_window = max(t_new - t_old, 1e-6)
                        paddle_velocity = (
                            (pos_new[0] - pos_old[0]) / dt_window,
                            (pos_new[1] - pos_old[1]) / dt_window,
                            (pos_new[2] - pos_old[2]) / dt_window,
                        )
                        client.send({
                            "cmd": "volley_strike",
                            "payload": {
                                "paddle_pos":      list(pos_new),
                                "paddle_normal":   list(forward_brain),
                                "paddle_velocity": list(paddle_velocity),
                            },
                        })
                        # Visual feedback at the paddle position. Reuse
                        # the existing flash primitive (raylib coords).
                        interact_flashes.append(
                            (now, pos_new[0], pos_new[2], pos_new[1])
                        )
                # Smash — first ARPG combat verb. If the click lands on
                # an entity within melee range, fire `kind_destroyed`.
                # Brain emits a StateEvent + advances any quest watching
                # that kind + filters the entity out of subsequent
                # manifests. Misses (no entity in range) are silent.
                smash_target = entity_at_crosshair(
                    camera.position.x, camera.position.y, camera.position.z,
                    forward[0], forward[1], forward[2],
                    last_manifest.get("entities", []),
                    cfg.INTERACT_RANGE_M,
                    cfg.INTERACT_RADIUS_HEURISTIC,
                )
                if smash_target is not None:
                    sx = float(smash_target.get("x", 0.0))
                    sy = float(smash_target.get("y", 0.0))   # manifest forward
                    sz = float(smash_target.get("z", 0.0))   # manifest up
                    # Visual flash at the hit position (existing primitive).
                    interact_flashes.append((now, sx, sz, sy))
                    # Some entity ids are strings (e.g. roaming orbs use
                    # `orb#N`); only forward int-able ids so the brain's
                    # destroyed_entity_ids ledger stays clean. Smash on a
                    # string-id entity still emits the kind_destroyed
                    # event for quest progression — just doesn't drop
                    # the entity from the world.
                    raw_id = smash_target.get("id")
                    payload = {
                        "cmd": "kind_destroyed",
                        "kind": str(smash_target.get("kind", "")),
                    }
                    try:
                        payload["entity_id"] = int(raw_id)
                    except (TypeError, ValueError):
                        pass
                    client.send(payload)

            if input_map.pressed("interact"):
                target = entity_at_crosshair(
                    camera.position.x, camera.position.y, camera.position.z,
                    forward[0], forward[1], forward[2],
                    last_manifest.get("entities", []),
                    cfg.INTERACT_RANGE_M,
                    cfg.INTERACT_RADIUS_HEURISTIC,
                )
                if target is not None:
                    target_kind = str(target.get("kind", ""))
                    pillar_id = dial_input.pillar_id_from_kind(target_kind)
                    if target_kind == "fridge":
                        # Voluntary fridge engagement. Brain validates
                        # game_state == HUB and refuses if not.
                        client.send({"cmd": "engage_fridge"})
                    elif pillar_id is not None:
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
                for i, slot_action in enumerate(input_map.SLOT_ACTIONS):
                    if i >= len(options):
                        break
                    if input_map.pressed(slot_action):
                        action = action_for_key_index(options, i)
                        if action:
                            client.send({"cmd": "encounter_action", "action": action})
                        break
            else:
                # No active encounter → KEYS 1-4 are elemental cast slots
                # (fire / ice / electric / light). Brain dispatches via
                # `cast_event` cmd, finds nearest entity within
                # CAST_REACTION_RADIUS_M, fires whatever
                # kind_config.elemental_reactions[element] mapping says.
                # Picks: torch on log → fire spreads, ice on water → freeze,
                # electric on metal → charge, light on shadow → reveal.
                cast_press = None
                if input_map.pressed("slot_1"):
                    cast_press = "fire"
                elif input_map.pressed("slot_2"):
                    cast_press = "ice"
                elif input_map.pressed("slot_3"):
                    cast_press = "electric"
                elif input_map.pressed("slot_4"):
                    cast_press = "light"
                if cast_press is not None:
                    cast_id_counter += 1
                    # Coord swap: raylib (X, Y=up, Z=fwd) → brain (X, Y=fwd, Z=up).
                    origin_brain = (
                        camera.position.x,
                        camera.position.z,
                        camera.position.y,
                    )
                    direction_brain = (
                        forward[0],
                        forward[2],
                        forward[1],
                    )
                    client.send({
                        "cmd": "cast_event",
                        "cast": {
                            "tag_id": -cast_id_counter,
                            "element": cast_press,
                            "trajectory": "straight",
                            "origin": list(origin_brain),
                            "direction": list(direction_brain),
                        },
                    })

        for msg in client.poll():
            if msg.get("unchanged"):
                continue
            # Command acks carry a "cmd" field. console_exec acks feed the
            # overlay scrollback; other acks pass silently for now (their
            # side effects show up in the next manifest).
            cmd_ack = msg.get("cmd")
            if cmd_ack == "console_exec":
                if msg.get("ok"):
                    output = msg.get("output") or []
                    volley_console.append_output(console_state, output)
                else:
                    volley_console.append_output(
                        console_state, [f"err: {msg.get('reason', '?')}"]
                    )
                continue
            if cmd_ack:
                continue                       # other acks: silent (PR 7 scope)
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

        # Banner compositing — 7 camera-anchored cylinders per
        # `design_banner_compositing`. Drawn before entities so the
        # cylinders sit behind world geometry. `now` drives the
        # breathing oscillation in demo mode.
        banner.draw_banner_layers(last_manifest, camera, now)

        # Distance-only horizon objects — moon, sun, aurora, lightning,
        # mountain ridges, stars per `design_banner_layer_taxonomy`.
        # Camera-anchored, render on the outermost banner cylinder.
        # `now` drives chrono kinds (aurora drift, lightning flashes,
        # sun drift). Static kinds (moon, ridge, stars) ignore it.
        horizon_renderer.draw_horizon_objects(last_manifest, camera, now)

        # Make-brain chamber wireframe — 12-edge cube outline for
        # volley_chamber. Reads `manifest.chamber`; silent no-op for
        # legacy biomes. Per `feat_make-brain-ping-pong.md` PR 3.
        chamber_renderer.render(last_manifest)

        # Active ball — wireframe sphere from manifest.ball. Silent
        # no-op when no ball in play. Per PR 4.
        ball_renderer.render(last_manifest)

        # World seeds — vector-workroom feature. Rendered before entities
        # so close-up entities can occlude distant seeds. Each seed's
        # mesh-edit log is replayed via `seed_mesh_cache`; cache is
        # invalidated by log signature change.
        build_mode.draw_seeds(last_manifest, seed_mesh_cache)
        if build_state.active:
            build_mode.draw_selection_highlight(
                build_state, last_manifest, seed_mesh_cache,
            )
            if build_state.sub_mode == "place":
                build_mode.draw_ghost_cursor(build_state)
            elif build_state.sub_mode == "edit":
                build_mode.draw_edit_cursors(
                    build_state, last_manifest, seed_mesh_cache,
                )

        for ent in last_manifest.get("entities", []):
            if class_for(str(ent.get("kind", ""))) in cfg.SKIP_ENTITY_CLASSES:
                continue
            # Per `design_banner_layer_taxonomy` — dispatch on the brain-
            # assigned render_mode. Outer shells render as silhouettes
            # projected onto the banner cylinders; atmosphere mode skips
            # entity rendering (entity contributes to layer tint via
            # later brain aggregation).
            render_mode = str(ent.get("render_mode", "geometry"))
            if render_mode == "geometry":
                _draw_entity(ent, camera)
            elif render_mode in ("silhouette", "hint"):
                silhouette_renderer.draw_silhouette(ent, camera, render_mode)
            # else: atmosphere mode — skip entity rendering entirely.

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
            if build_state.active:
                hud.draw_build_overlay(
                    build_mode.hud_lines(build_state, last_manifest), amber,
                )

        # Volley console — drawn last so it sits over the HUD when open.
        # Backdrop already sets its own alpha, so it composes cleanly.
        volley_console.render(
            console_state,
            rl.get_screen_width(),
            rl.get_screen_height(),
            amber,
            None,
        )

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

        if show_journal and not dial_active and not reflective_active:
            journal.draw_journal_overlay(
                last_manifest,
                journal_state,
                rl.get_screen_width(),
                rl.get_screen_height(),
                amber,
            )

        if reflective_active:
            reflective_overlay.draw_overlay(
                last_manifest,
                reflective_state,
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
    # `kind` is the BEHAVIORAL identifier (engage handlers, kind_class
    # filters). `visual_kind` is the per-biome alias the brain may set
    # via `BIOME_REGISTRY[biome]["fixture_aliases"]` so the same hub
    # fixture (pillar_reflection / fridge) renders as biome-appropriate
    # geometry without changing the gameplay verb. Falls back to `kind`.
    kind = str(ent.get("kind", ""))
    visual_kind = str(ent.get("visual_kind") or kind)
    bx, by, bz = bounds_for(visual_kind)
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
    recipe = recipe_for_kind(visual_kind)
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
