"""Crosshair-driven object interaction — the NetHack/Doom move.

Each frame, look for an entity under the crosshair that carries an
`_interactions` field. If found, render a tiny prompt ("F examine")
near the crosshair. F key sends `interact_request` to brain; brain
emits the response text as a StateEvent toast.

This is the "F = do the obvious thing" model classic adventures
used. One verb per kind (V1: examine). Adding more verbs is a
brain handler + UI prompt extension, not architecture.
"""
from __future__ import annotations

import math
from typing import Any

import pyray as rl

from clients.vector_terminal import hud, input_map


# Pick range — close-proximity only. Per UAT 2026-05-15: 8m felt
# like "examine across the room"; 2m means "I'm RIGHT next to this."
PICK_RANGE_M: float = 2.0
PICK_ALIGN_MIN: float = 0.92      # tight: only when looking ~directly at it


def pick_interactable(
    manifest: dict, camera,
) -> tuple[str, list[str]] | None:
    """Return (thing_name, available_verbs) for the entity under the
    crosshair, or None if nothing interactable is in front of the
    player.

    Picks the closest entity within PICK_RANGE_M whose camera-forward
    alignment is at least PICK_ALIGN_MIN and which carries an
    `_interactions` list."""
    cam_pos = camera.position
    fx = camera.target.x - cam_pos.x
    fy = camera.target.y - cam_pos.y
    fz = camera.target.z - cam_pos.z
    fmag = math.sqrt(fx * fx + fy * fy + fz * fz)
    if fmag < 1e-6:
        return None
    fx /= fmag; fy /= fmag; fz /= fmag

    best: tuple[str, list[str]] | None = None
    best_score = -1.0
    for ent in manifest.get("entities", []) or []:
        verbs = ent.get("_interactions")
        thing = ent.get("_thing")
        if not verbs or not thing:
            continue
        # Brain (x, y_forward, z_up) → raylib (x, y_up, z_forward)
        ex = float(ent.get("x", 0.0))
        ey = float(ent.get("z", 0.0))
        ez = float(ent.get("y", 0.0))
        dx = ex - cam_pos.x
        dy = ey - cam_pos.y
        dz = ez - cam_pos.z
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist > PICK_RANGE_M or dist < 0.05:
            continue
        align = (dx / dist) * fx + (dy / dist) * fy + (dz / dist) * fz
        if align < PICK_ALIGN_MIN:
            continue
        score = align - (dist / PICK_RANGE_M) * 0.2
        if score > best_score:
            best_score = score
            best = (str(thing), list(verbs))
    return best


# Verb → input-map action binding. Add new verbs by extending this
# dict + binding the action in input_map.DEFAULT_BINDINGS. The brain
# handler decides what each verb actually DOES.
_VERB_KEYS: dict[str, str] = {
    "examine": "interact",          # F
    "pickup":  "interact_pickup",   # P
    "kick":    "interact_kick",     # N
}


def maybe_send_interact(
    client,
    camera,
    pick: tuple[str, list[str]] | None,
) -> bool:
    """For each verb the picked thing declares, check the matching key.
    Send a cmd for the first matching press (one verb per frame max).

    Kick sends an additional `direction` field — player's facing
    converted to brain coords (x=lateral, y=forward) — so the brain
    can offset the thing AWAY from the player.

    Returns True if a cmd was sent."""
    if pick is None:
        return False
    thing_name, verbs = pick
    if not verbs:
        return False
    for verb in verbs:
        action = _VERB_KEYS.get(verb)
        if action is None:
            continue
        if not input_map.pressed(action):
            continue
        cmd: dict[str, Any] = {
            "cmd":        "interact_request",
            "thing_name": thing_name,
            "verb":       verb,
        }
        if verb == "kick":
            cmd["direction"] = _player_facing_brain_xy(camera)
        client.send(cmd)
        return True
    return False


def _player_facing_brain_xy(camera) -> list[float]:
    """Player's facing direction in brain (x_lateral, y_forward) coords.
    Used by kick to push things AWAY from the player."""
    fx_raylib = camera.target.x - camera.position.x
    fz_raylib = camera.target.z - camera.position.z
    mag = math.sqrt(fx_raylib * fx_raylib + fz_raylib * fz_raylib)
    if mag < 1e-6:
        return [0.0, 1.0]
    # raylib x = brain x; raylib z = brain y (forward in our convention)
    return [fx_raylib / mag, fz_raylib / mag]


_VERB_KEY_LABEL: dict[str, str] = {
    "examine": "F",
    "pickup":  "P",
    "kick":    "N",
}


def draw_prompt(
    pick: tuple[str, list[str]] | None,
    screen_w: int,
    screen_h: int,
    color,
) -> None:
    """Render '[F] examine [P] pickup [N] kick — thing_name' below
    the crosshair when looking at an interactable. Shows ALL verbs the
    target supports so the player can see their options."""
    if pick is None:
        return
    thing_name, verbs = pick
    if not verbs:
        return

    # Build the prompt string: "[F] examine [P] pickup — longsword"
    parts: list[str] = []
    for v in verbs:
        key = _VERB_KEY_LABEL.get(v)
        if key is None:
            continue                # client doesn't render verbs it can't bind
        parts.append(f"[{key}] {v}")
    if not parts:
        return
    text = "  ".join(parts) + f"  —  {thing_name.replace('_', ' ')}"

    font = hud.font()
    text_w = rl.measure_text_ex(font, text, 16, 1.0).x
    cx = screen_w // 2
    cy = screen_h // 2
    x = int(cx - text_w / 2)
    y = cy + 24                          # below the crosshair

    pad = 6
    rl.draw_rectangle(
        x - pad, y - 2, int(text_w) + pad * 2, 22,
        (0, 0, 0, 200),
    )
    rl.draw_text_ex(font, text, rl.Vector2(x, y), 16, 1.0, color)
