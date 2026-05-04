"""Ping-pong make-brain handler.

V1 (PR 3): stub — registers with make_brain_registry, owns the chamber
geometry constants, auto-inserts vanilla + tennis_sim profiles. Real
gameplay logic (serve / strike / scoring / runs) lands in PRs 4–8.

Per `.claude/feature/feat_make-brain-ping-pong.md` PR 3.
"""
from __future__ import annotations

from typing import Any

from core.systems import make_brain_registry


# ----------------------------------------------------------------------
# Identity (universal substrate keys — declared as constants so the
# manifest emission and registration agree)
# ----------------------------------------------------------------------

INSTANCE_ID:    str = "ping_pong"
ENTRY_POINT:    str = "biome:volley_chamber"
DEFAULT_PROFILE: str = "vanilla"

STATE_EVENT_TYPES: tuple[str, ...] = (
    # Universal lifecycle (every make-brain emits these)
    "make_brain_started", "make_brain_ended", "profile_loaded",
    "peak_recorded",
    # Stage-3 prereq — emitted shape pinned now, renderer respects deferred
    "time_scale_changed",
    # Volley-specific
    "ball_spawned", "ball_struck", "ball_settled",
    "rally_started", "rally_ended", "score_changed",
)


# ----------------------------------------------------------------------
# Chamber geometry — 12×12×12 wireframe cube. Origin sits at the bottom-
# center of the cube (floor at y=0, ceiling at y=12). Player spawns at
# the cube's interior center (camera height ≈ 1.6m).
# ----------------------------------------------------------------------

CHAMBER_GEOMETRY: dict[str, Any] = {
    "size":   [12.0, 12.0, 12.0],   # cube is symmetric, but kept as a list for arcade-tunability
    "origin": [0.0, 0.0, 0.0],      # bottom-center
    "color":  [0.55, 0.62, 0.72],   # cool wireframe
}


# ----------------------------------------------------------------------
# Vanilla / tennis_sim profile params
# Per AC §"Vanilla profile params (arcade defaults)" + "Tennis-sim preset"
# ----------------------------------------------------------------------

VANILLA_PARAMS: dict[str, Any] = {
    "_target":              "arcade — infinite rally, predictable, easy-to-hit",
    "ball_mass":            1.0,
    "ball_radius":          0.15,
    "ball_drag_coeff":      0.0,
    "ball_magnus_coeff":    0.0,
    "gravity_y":            0.0,
    "wall_restitution":     1.0,
    "coupling_factor":      1.0,
    "paddle_hitbox_radius": 0.6,
    "paddle_arm_length":    0.7,
    "swing_velocity":       12.0,
    "cube_size":            12.0,
    "serve_offset":         [0.0, 1.6, 1.5],
}

TENNIS_SIM_PARAMS: dict[str, Any] = {
    "_target":           "tennis sim — Mehta wind-tunnel coefficients",
    "ball_mass":         0.058,
    "ball_radius":       0.0335,
    "ball_drag_coeff":   0.55,
    "ball_magnus_coeff": 0.175,
    "gravity_y":         -9.81,
    "wall_restitution":  0.85,
}


# ----------------------------------------------------------------------
# Handler
# ----------------------------------------------------------------------


class PingPongHandler:
    """Stub for V1 PR 3. Real strike/serve/score wiring lands in PR 4+.

    Owns:
      - Chamber geometry (constant for V1)
      - Active profile name (string — params come from vault on load)
      - Auto-seeding of vanilla + tennis_sim on first boot
    """

    INSTANCE_ID:    str = INSTANCE_ID
    ENTRY_POINT:    str = ENTRY_POINT
    DEFAULT_PROFILE: str = DEFAULT_PROFILE
    STATE_EVENT_TYPES: tuple[str, ...] = STATE_EVENT_TYPES

    def __init__(self, vault):
        self.vault = vault
        self.active_profile = DEFAULT_PROFILE
        self._ensure_default_profiles()

    # -- profile bootstrapping ---------------------------------------------

    def _ensure_default_profiles(self) -> None:
        """Seed vanilla + tennis_sim if absent. Idempotent across boots."""
        if self.vault.profile_load(INSTANCE_ID, "vanilla") is None:
            self.vault.profile_save(
                INSTANCE_ID, "vanilla",
                params=VANILLA_PARAMS,
                notes="arcade defaults — V1 PR 3 seed",
            )
        if self.vault.profile_load(INSTANCE_ID, "tennis_sim") is None:
            self.vault.profile_save(
                INSTANCE_ID, "tennis_sim",
                params=TENNIS_SIM_PARAMS,
                parent_profile="vanilla",
                notes="Mehta wind-tunnel coefficients — dial-up preset",
            )

    # -- manifest --------------------------------------------------------

    def manifest_keys(self) -> dict[str, Any]:
        """Top-level keys merged into each manifest tick when this
        instance is active. Brain calls this from the manifest builder."""
        return {
            "instance_id":    INSTANCE_ID,
            "active_profile": self.active_profile,
            "chamber":        dict(CHAMBER_GEOMETRY),
        }


# ----------------------------------------------------------------------
# Activation — call from brain boot when biome=volley_chamber.
# Idempotent (won't re-register if already registered, e.g. across
# restarts in a long-running test process).
# ----------------------------------------------------------------------


def activate(vault) -> "make_brain_registry.MakeBrainSpec":
    """Register PingPongHandler with make_brain_registry. Returns the spec."""
    try:
        return make_brain_registry.get(INSTANCE_ID)
    except LookupError:
        pass
    handler = PingPongHandler(vault)
    return make_brain_registry.register(
        instance_id       = INSTANCE_ID,
        entry_point       = ENTRY_POINT,
        default_profile   = DEFAULT_PROFILE,
        state_event_types = STATE_EVENT_TYPES,
        handler           = handler,
    )
