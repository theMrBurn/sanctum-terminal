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


def maybe_send_interact(
    client,
    pick: tuple[str, list[str]] | None,
) -> bool:
    """If F is pressed AND we have a pick AND it has interactions,
    send the first verb (V1: only `examine` is declared anyway).
    Returns True if a cmd was sent."""
    if pick is None:
        return False
    if not input_map.pressed("interact"):
        return False
    thing_name, verbs = pick
    if not verbs:
        return False
    verb = verbs[0]                      # V1: first verb is the default
    client.send({
        "cmd":         "interact_request",
        "thing_name":  thing_name,
        "verb":        verb,
    })
    return True


def draw_prompt(
    pick: tuple[str, list[str]] | None,
    screen_w: int,
    screen_h: int,
    color,
) -> None:
    """Render '[F] examine — thing_name' below the crosshair when
    looking at an interactable. Tiny + non-intrusive."""
    if pick is None:
        return
    thing_name, verbs = pick
    if not verbs:
        return
    verb = verbs[0]
    text = f"[F] {verb} — {thing_name.replace('_', ' ')}"

    font = hud.font()
    text_w = rl.measure_text_ex(font, text, 16, 1.0).x
    cx = screen_w // 2
    cy = screen_h // 2
    x = int(cx - text_w / 2)
    y = cy + 24                          # below the crosshair

    # Background pill
    pad = 6
    rl.draw_rectangle(
        x - pad, y - 2, int(text_w) + pad * 2, 22,
        (0, 0, 0, 200),
    )
    rl.draw_text_ex(font, text, rl.Vector2(x, y), 16, 1.0, color)
