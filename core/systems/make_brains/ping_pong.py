"""Ping-pong make-brain handler.

PR 3 stub + PR 4 ball physics. Owns:
  - Chamber geometry (constant for V1)
  - Active profile name
  - Vanilla + tennis_sim auto-seeding
  - Active ball state (PR 4 — None when no ball is in play)
  - BallisticsSolver lazily built per ball lifetime

Per `.claude/feature/feat_make-brain-ping-pong.md` PR 3-4.
"""
from __future__ import annotations

from typing import Any

from core.systems import make_brain_registry
from core.systems import volley_scoring
from core.systems.ballistics import (
    BallisticsParams, BallisticsSolver, MotionVector, chamber_walls,
)


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
    "_target":               "arcade — infinite rally, predictable, easy-to-hit",
    "ball_mass":             1.0,
    "ball_radius":           0.15,
    "ball_drag_coeff":       0.0,
    "ball_magnus_coeff":     0.0,
    "gravity_y":             0.0,
    "wall_restitution":      1.0,
    "coupling_factor":       1.0,
    "paddle_hitbox_radius":  0.6,
    "paddle_arm_length":     0.7,
    "swing_velocity":        12.0,
    "cube_size":             12.0,
    "serve_offset":          [0.0, 1.6, 1.5],
    # Wall-rally scoring — sustaining ≥long_rally_threshold contacts
    # awards a player point on rally end; below = opp point. Per AC PR 6.
    "long_rally_threshold":  10,
    # Out-of-bounds — rally ends when ball.y < this threshold
    # (1m behind player spawn). Player must strike before then.
    "out_of_bounds_y":       -1.0,
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
        # Ball state — None when no ball in play. Brain ticks on_tick(dt)
        # only when self.ball is not None.
        self.ball: MotionVector | None = None
        # Solver is rebuilt whenever active_profile changes; a value of
        # None forces lazy construction on next on_tick / on_serve.
        self._solver: BallisticsSolver | None = None
        self._solver_profile: str | None = None
        self._session_time: float = 0.0
        # Match state — tennis scoring per AC PR 6. wall_rally mode:
        # rally length crossing the long_rally_threshold awards a player
        # point on rally end; otherwise opp point.
        self.match: volley_scoring.MatchState = volley_scoring.new_match("wall_rally")
        self.rally_contacts: int = 0
        self.last_rally_outcome: dict | None = None    # for HUD/state events

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

    # -- solver -----------------------------------------------------------

    def _ensure_solver(self) -> BallisticsSolver:
        """Lazily build / rebuild the solver for the active profile."""
        if self._solver is not None and self._solver_profile == self.active_profile:
            return self._solver
        params = self.vault.profile_resolve(INSTANCE_ID, self.active_profile)
        walls = chamber_walls(
            tuple(CHAMBER_GEOMETRY["size"]),
            tuple(CHAMBER_GEOMETRY["origin"]),
        )
        self._solver = BallisticsSolver(BallisticsParams.from_profile(params), walls)
        self._solver_profile = self.active_profile
        return self._solver

    # -- ball lifecycle ---------------------------------------------------

    def on_serve(self) -> MotionVector:
        """Spawn a stationary ball at the active profile's serve_offset.

        Per AC §"Decisions locked" #4: Atari single-press serve. First
        press creates the ball; second press is the rally swing (PR 5).
        Resets rally contact counter so the next miss/score event
        scores fairly. Match state preserved (use volley_reset_match
        for a fresh match).
        """
        params = self.vault.profile_resolve(INSTANCE_ID, self.active_profile)
        offset = params.get("serve_offset") or [0.0, 1.6, 1.5]
        # Profile serve_offset is (lateral, vertical_eye_height, forward).
        # Brain space convention: x=lateral, y=forward, z=up. So map
        # offset[0] → x, offset[2] → y, offset[1] → z.
        self.ball = MotionVector(
            pos=(float(offset[0]), float(offset[2]), float(offset[1])),
            vel=(0.0, 0.0, 0.0),
            spin=(0.0, 0.0, 0.0),
            timestamp=self._session_time,
        )
        self.rally_contacts = 0
        return self.ball

    def clear_ball(self) -> None:
        """Remove the active ball (rally end, reset, etc.)."""
        self.ball = None

    def on_strike(
        self,
        paddle_pos:      tuple[float, float, float],
        paddle_normal:   tuple[float, float, float],
        paddle_velocity: tuple[float, float, float],
    ):
        """Apply a paddle strike to the active ball.

        Returns:
          - None on miss (no ball, or ball outside paddle_hitbox_radius)
          - ContactProfile on hit; self.ball is updated to the post-strike state.

        Hitbox check uses the active profile's `paddle_hitbox_radius`. This
        is brain-side authoritative — clients always send a strike attempt;
        brain decides hit/miss.
        """
        if self.ball is None:
            return None
        params = self.vault.profile_resolve(INSTANCE_ID, self.active_profile)
        hit_radius = float(params.get("paddle_hitbox_radius", 0.6))
        # Hit window: ball center within hit_radius from paddle position.
        dx = self.ball.pos[0] - paddle_pos[0]
        dy = self.ball.pos[1] - paddle_pos[1]
        dz = self.ball.pos[2] - paddle_pos[2]
        dist_sq = dx * dx + dy * dy + dz * dz
        if dist_sq > hit_radius * hit_radius:
            return None
        coupling = float(params.get("coupling_factor", 1.0))
        solver = self._ensure_solver()
        new_state, contact = solver.paddle_strike(
            self.ball,
            paddle_pos      = tuple(paddle_pos),
            paddle_normal   = tuple(paddle_normal),
            paddle_velocity = tuple(paddle_velocity),
            coupling        = coupling,
            friction        = coupling,        # V1: friction tracks coupling
        )
        self.ball = new_state
        self.rally_contacts += 1
        return contact

    def on_tick(self, dt: float, substeps: int = 4) -> list:
        """Advance ball physics by `dt`. Returns wall-contact records
        from the substep (for state-event emission later).

        Resolves rally on out-of-bounds (ball passes back-line without
        being struck). PR 6 — wall_rally scoring rule:
            rally_contacts ≥ long_rally_threshold → player point
            else                                  → opp point
        """
        self._session_time += dt
        if self.ball is None:
            return []
        solver = self._ensure_solver()
        new_state, contacts = solver.step(self.ball, dt, substeps=substeps)
        self.ball = new_state
        # Out-of-bounds resolution. Ball y past the back-line ends the
        # rally regardless of velocity.
        params = self.vault.profile_resolve(INSTANCE_ID, self.active_profile)
        out_y = float(params.get("out_of_bounds_y", -1.0))
        if self.ball.pos[1] < out_y:
            self._resolve_rally_out()
        return contacts

    def _resolve_rally_out(self) -> None:
        """Apply wall-rally scoring rule and clear the ball."""
        params = self.vault.profile_resolve(INSTANCE_ID, self.active_profile)
        threshold = int(params.get("long_rally_threshold", 10))
        if self.rally_contacts >= threshold:
            self.match = volley_scoring.point_player(self.match)
            winner = "player"
        else:
            self.match = volley_scoring.point_opp(self.match)
            winner = "opp"
        self.last_rally_outcome = {
            "winner":         winner,
            "rally_contacts": self.rally_contacts,
            "threshold":      threshold,
        }
        self.ball = None
        self.rally_contacts = 0

    # -- match-level reset hooks ----------------------------------------

    def reset_rally(self) -> None:
        """Discard active ball + rally counter; preserve match state."""
        self.ball = None
        self.rally_contacts = 0
        self.last_rally_outcome = None

    def reset_match(self) -> None:
        """Hard reset — fresh match, no ball, no rally."""
        self.ball = None
        self.rally_contacts = 0
        self.last_rally_outcome = None
        self.match = volley_scoring.new_match("wall_rally")

    # -- manifest --------------------------------------------------------

    def manifest_keys(self) -> dict[str, Any]:
        """Top-level keys merged into each manifest tick when this
        instance is active. Brain calls this from the manifest builder."""
        keys: dict[str, Any] = {
            "instance_id":    INSTANCE_ID,
            "active_profile": self.active_profile,
            "chamber":        dict(CHAMBER_GEOMETRY),
        }
        if self.ball is not None:
            params = self.vault.profile_resolve(INSTANCE_ID, self.active_profile)
            keys["ball"] = {
                "exists": True,
                "x":  self.ball.pos[0],
                "y":  self.ball.pos[1],
                "z":  self.ball.pos[2],
                "vx": self.ball.vel[0],
                "vy": self.ball.vel[1],
                "vz": self.ball.vel[2],
                "radius": float(params.get("ball_radius", 0.15)),
                "color":  [0.95, 0.95, 0.30],   # high-visibility yellow wireframe
            }
        else:
            keys["ball"] = {"exists": False}
        # Match state — tennis scoring snapshot for HUD + telemetry
        keys["match_state"] = {
            "points":         list(self.match.points),
            "games":          list(self.match.games),
            "sets_won":       list(self.match.sets_won),
            "set_winners":    list(self.match.set_winners),
            "match_winner":   self.match.match_winner,
            "server":         self.match.server,
            "mode":           self.match.mode,
            "rally_contacts": self.rally_contacts,
            "last_rally":     self.last_rally_outcome,
        }
        return keys


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
