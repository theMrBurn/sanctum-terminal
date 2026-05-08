"""strike_renderer — per-mode visualization for in-flight ARPG combat Strikes.

Per `feat_arpg-combat.md` PR 2 (initial sphere render) + PR 6 (per-mode
polish: SHOT trail, HELD hitbox glow, WHIP tether chain).

Reads `manifest.active_strikes` and dispatches to the per-mode draw
helper. The brain stamps mode-specific fields into each strike entry
(held_phase, hitbox_pos, player_pos, etc.) so the client doesn't have
to recompute physics state.
"""
from __future__ import annotations

import math
from typing import Any

import pyray as rl

from clients.vector_terminal import config as cfg
from clients.vector_terminal import distance_fade


# Sphere render constants
_SHOT_BALL_SCALE = 1.2
_SHOT_BALL_SLICES = 8

_HELD_HITBOX_SLICES = 6
_HELD_GLOW_SLICES = 4

_WHIP_BALL_SCALE = 1.3
_WHIP_BALL_SLICES = 8
_TETHER_SEGMENTS = 8


def draw_strikes(manifest: dict[str, Any], camera) -> None:
    """Draw all active strikes from the manifest. Call inside
    `begin_mode_3d` so spheres composite with world geometry.
    """
    strikes: list[dict[str, Any]] = manifest.get("active_strikes") or []
    if not strikes:
        return

    cam_x = camera.position.x
    cam_y = camera.position.y
    cam_z = camera.position.z

    for s in strikes:
        mode = str(s.get("mode", "shot"))
        if mode == "shot":
            _draw_shot(s, cam_x, cam_y, cam_z)
        elif mode == "held":
            _draw_held(s, cam_x, cam_y, cam_z)
        elif mode == "whip":
            _draw_whip(s, cam_x, cam_y, cam_z)
        else:
            # Unknown mode — fall back to ball render
            _draw_shot(s, cam_x, cam_y, cam_z)


def _amber_intensity(pos_x: float, pos_y: float, pos_z: float,
                      cam_x: float, cam_y: float, cam_z: float
                      ) -> tuple[int, int, int, int]:
    """Phosphor-amber RGBA per distance from camera."""
    dx = pos_x - cam_x
    dy = pos_y - cam_y
    dz = pos_z - cam_z
    dist = (dx * dx + dy * dy + dz * dz) ** 0.5
    intensity = distance_fade.intensity(dist)
    return (
        int(cfg.AMBER_RGB[0] * intensity),
        int(cfg.AMBER_RGB[1] * intensity),
        int(cfg.AMBER_RGB[2] * intensity),
        255,
    )


def _brain_to_raylib(bx: float, by: float, bz: float) -> rl.Vector3:
    """Brain (x, y_forward, z_up) → raylib (x, y_up, z_forward)."""
    return rl.Vector3(bx, bz, by)


# ── SHOT ──────────────────────────────────────────────────────────────


def _draw_shot(s: dict[str, Any], cam_x: float, cam_y: float, cam_z: float) -> None:
    """SHOT mode — wireframe sphere at ball position. Future PR adds
    a trail (currently the ball position alone reads as a streak when
    moving fast in low-frame-flicker terminal aesthetic)."""
    try:
        x = float(s.get("x", 0.0))
        y = float(s.get("y", 0.0))
        z = float(s.get("z", 0.0))
        r = float(s.get("ball_radius", 0.3))
    except (TypeError, ValueError):
        return
    pos = _brain_to_raylib(x, y, z)
    color = _amber_intensity(pos.x, pos.y, pos.z, cam_x, cam_y, cam_z)
    rl.draw_sphere_wires(pos, r * _SHOT_BALL_SCALE,
                         _SHOT_BALL_SLICES, _SHOT_BALL_SLICES, color)


# ── HELD ──────────────────────────────────────────────────────────────


def _draw_held(s: dict[str, Any], cam_x: float, cam_y: float, cam_z: float) -> None:
    """HELD mode — read as a SWING, not a static sphere.

    Phase-aware visualization that conveys arc + reach + impact:

      - wind_up: nothing visible (player commits, weapon hasn't extended)
      - active:  a bright LINE from player to hitbox position +
                 small impact sphere at the hitbox tip. This reads
                 as a weapon extending forward, not a floating ball.
      - cooldown: faint trailing line + sphere fading.

    Per-verb sweep direction (V2 polish): SLASH should sweep horizontally
    during active, HACK should sweep top-down, STAB/PUNCH straight
    forward. V1 PR 9 ships fixed-position line; per-verb sweep is V2.
    """
    try:
        # Player position is the base of the swing — current_state.pos
        px = float(s.get("x", 0.0))
        py = float(s.get("y", 0.0))
        pz = float(s.get("z", 0.0))
        # Hitbox tip position (player + forward × reach)
        hx = float(s.get("hitbox_x", px))
        hy = float(s.get("hitbox_y", py))
        hz = float(s.get("hitbox_z", pz))
        r  = float(s.get("ball_radius", 0.4))
    except (TypeError, ValueError):
        return

    phase = str(s.get("held_phase", "active"))
    if phase == "wind_up":
        return                                       # nothing to render yet

    base_pos = _brain_to_raylib(px, py, pz)
    tip_pos  = _brain_to_raylib(hx, hy, hz)
    color = _amber_intensity(tip_pos.x, tip_pos.y, tip_pos.z,
                             cam_x, cam_y, cam_z)

    # Phase modulates intensity
    if phase == "active":
        alpha = 255
        tip_radius_mult = 1.0
    else:                                           # cooldown
        alpha = 110
        tip_radius_mult = 0.7

    # Blade line — segment from player base to tip. Use cube-segment
    # chain like WHIP for visual continuity (raylib has no native
    # thick line in 3D); 5 segments along the swing length.
    blade_segs = 5
    blade_color = (color[0], color[1], color[2], alpha)
    for i in range(blade_segs):
        t = (i + 0.5) / blade_segs
        sx = base_pos.x + (tip_pos.x - base_pos.x) * t
        sy = base_pos.y + (tip_pos.y - base_pos.y) * t
        sz = base_pos.z + (tip_pos.z - base_pos.z) * t
        seg_pos = rl.Vector3(sx, sy, sz)
        # Thinner segments toward tip → reads as a blade tapering.
        seg_size = 0.10 + (1.0 - t) * 0.04
        rl.draw_cube_wires(seg_pos, seg_size, seg_size, seg_size, blade_color)

    # Tip impact sphere — concentrated at the hitbox center.
    tip_color = (color[0], color[1], color[2], alpha)
    rl.draw_sphere_wires(tip_pos, r * tip_radius_mult,
                         _HELD_HITBOX_SLICES, _HELD_HITBOX_SLICES, tip_color)
    # Active phase: outer glow ring on impact
    if phase == "active":
        glow_color = (color[0], color[1], color[2], 70)
        rl.draw_sphere_wires(tip_pos, r * 1.5,
                             _HELD_GLOW_SLICES, _HELD_GLOW_SLICES, glow_color)


# ── WHIP ──────────────────────────────────────────────────────────────


def _draw_whip(s: dict[str, Any], cam_x: float, cam_y: float, cam_z: float) -> None:
    """WHIP mode — ball at current position + tether chain from player
    to ball. Tether rendered as a series of small cubes along the
    line (chain segments) for that "linked" feel."""
    try:
        bx = float(s.get("x", 0.0))
        by = float(s.get("y", 0.0))
        bz = float(s.get("z", 0.0))
        r  = float(s.get("ball_radius", 0.35))
    except (TypeError, ValueError):
        return
    ball_pos = _brain_to_raylib(bx, by, bz)
    color = _amber_intensity(ball_pos.x, ball_pos.y, ball_pos.z,
                             cam_x, cam_y, cam_z)

    # Tether chain — only draw if we have player_pos in the manifest entry
    px = s.get("player_x")
    py = s.get("player_y")
    pz = s.get("player_z")
    if px is not None and py is not None and pz is not None:
        try:
            anchor_pos = _brain_to_raylib(float(px), float(py), float(pz))
        except (TypeError, ValueError):
            anchor_pos = None
        if anchor_pos is not None:
            # Draw chain as a series of small cubes along anchor → ball.
            for i in range(_TETHER_SEGMENTS):
                t = (i + 1) / (_TETHER_SEGMENTS + 1)
                seg_x = anchor_pos.x + (ball_pos.x - anchor_pos.x) * t
                seg_y = anchor_pos.y + (ball_pos.y - anchor_pos.y) * t
                seg_z = anchor_pos.z + (ball_pos.z - anchor_pos.z) * t
                seg_pos = rl.Vector3(seg_x, seg_y, seg_z)
                seg_color = _amber_intensity(seg_x, seg_y, seg_z,
                                              cam_x, cam_y, cam_z)
                # Reduce segment alpha so chain reads thinner than ball
                seg_color_dim = (seg_color[0], seg_color[1], seg_color[2], 180)
                rl.draw_cube_wires(seg_pos, 0.08, 0.08, 0.08, seg_color_dim)

    # Ball itself — slightly larger sphere
    rl.draw_sphere_wires(ball_pos, r * _WHIP_BALL_SCALE,
                         _WHIP_BALL_SLICES, _WHIP_BALL_SLICES, color)
