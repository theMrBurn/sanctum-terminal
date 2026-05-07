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

from core.systems import activity_loop
from core.systems import make_brain_registry
from core.systems import volley_scoring
from core.systems.ballistics import (
    BallisticsParams, BallisticsSolver, MotionVector, chamber_walls,
)
from core.systems.activity_loop import ActivityClass


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
    # Tennis-court-ish proportions post-UAT 2026-05-04: narrow lateral
    # (12m), long forward axis (36m for reaction time on returns),
    # modest ceiling (8m). Player spawn at y=0 (center of long axis)
    # → 18m to front wall = 2.25s travel at 8 m/s = trackable rally.
    "size":   [12.0, 36.0, 8.0],
    "origin": [0.0, 0.0, 0.0],
    "color":  [0.55, 0.62, 0.72],
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
    # (3m behind player spawn). Player must strike before then.
    # Tuned post-UAT: needed more dive-save zone in the larger 24m chamber.
    "out_of_bounds_y":       -3.0,
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
# Brick Attack — horizontal row of breakable targets on the front wall.
# Player strikes ball forward; ball hits brick → brick destroyed +
# score. Hit threshold = WIN. R resets bricks + ball.
# Per V1 close-out 2026-05-04.
# ----------------------------------------------------------------------

# Chamber is 12 wide × 36 long × 8 tall (CHAMBER_GEOMETRY above), so
# front wall (north) is at brain y=+18, x∈[-6,+6], z∈[0,8]. Bricks
# fit in this rectangle at mid-height.

BRICK_SCORE         = 100
TARGET_ROUNDS_PER_SET = 10    # combat-math sample target per experimental set
                                # (down from 100 — 10 is enough signal,
                                # 100 takes hours of UAT)

# Floor-standing pins. Horizontal row 8m in front of player spawn,
# spanning the chamber width. Ball rolls forward on the floor (per
# vanilla gravity arc), hits pins, knocks them out. Per V1 close-out
# screenshot review 2026-05-04.
#
# Each brick's `hp` is the number of contacts required to destroy it.
# `max_hp` is the original; `hp` decrements on each contact. score is
# awarded when destroyed (hp → 0).

def _brick(x_min, x_max, hp=1, score=BRICK_SCORE):
    return {
        "x_min": x_min, "x_max": x_max,
        "y_min": 8.0,   "y_max": 8.8,
        "z_min": 0.0,   "z_max": 1.0,
        "score": score, "hp": hp, "max_hp": hp,
        "destroyed": False,
    }


# Control set — 6 bricks, all hp=1, threshold=600. Substrate baseline.
CONTROL_BRICKS: list[dict[str, Any]] = [
    _brick(-5.5, -4.0),
    _brick(-3.5, -2.0),
    _brick(-1.5,  0.0),
    _brick( 0.0,  1.5),
    _brick( 2.0,  3.5),
    _brick( 4.0,  5.5),
]
CONTROL_THRESHOLD = sum(b["score"] for b in CONTROL_BRICKS)   # 600

# Experimental v1 — every 3rd brick is a 3-HP "boss" pin worth 3× score.
# Pattern (left → right): N N H N N H. Total HP to clear: 4·1 + 2·3 = 10.
# Total threshold: 4·100 + 2·300 = 1000.
EXPERIMENTAL_V1_BRICKS: list[dict[str, Any]] = [
    _brick(-5.5, -4.0, hp=1, score=100),
    _brick(-3.5, -2.0, hp=1, score=100),
    _brick(-1.5,  0.0, hp=3, score=300),    # boss
    _brick( 0.0,  1.5, hp=1, score=100),
    _brick( 2.0,  3.5, hp=1, score=100),
    _brick( 4.0,  5.5, hp=3, score=300),    # boss
]
EXPERIMENTAL_V1_THRESHOLD = sum(b["score"] for b in EXPERIMENTAL_V1_BRICKS)   # 1000

BRICK_SETS: dict[str, dict[str, Any]] = {
    "control": {
        "label":     "Control (6 × 1-HP)",
        "bricks":    CONTROL_BRICKS,
        "threshold": CONTROL_THRESHOLD,
    },
    "experimental_v1": {
        "label":     "Exp v1 (every 3rd × 3-HP boss)",
        "bricks":    EXPERIMENTAL_V1_BRICKS,
        "threshold": EXPERIMENTAL_V1_THRESHOLD,
    },
}

DEFAULT_BRICK_SET = "control"


def _fresh_bricks_for(set_name: str) -> list[dict[str, Any]]:
    """Deep-ish copy of the named set's brick layout. Each brick's
    fields (hp, destroyed) reset to fresh."""
    layout = BRICK_SETS.get(set_name) or BRICK_SETS[DEFAULT_BRICK_SET]
    return [dict(b) for b in layout["bricks"]]


def _threshold_for(set_name: str) -> int:
    layout = BRICK_SETS.get(set_name) or BRICK_SETS[DEFAULT_BRICK_SET]
    return int(layout["threshold"])


# Back-compat: keep the old names so any importers don't break.
DEFAULT_BRICKS = CONTROL_BRICKS
BRICK_WIN_THRESHOLD = CONTROL_THRESHOLD


def _fresh_bricks() -> list[dict[str, Any]]:
    """Legacy alias — returns fresh control-set bricks."""
    return _fresh_bricks_for(DEFAULT_BRICK_SET)


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
        # Solver is rebuilt whenever active_profile changes OR the row's
        # updated_at advances (console setter just mutated it). A value
        # of None forces lazy construction on next on_tick / on_serve.
        self._solver: BallisticsSolver | None = None
        self._solver_profile: str | None = None
        self._solver_updated_at: str | None = None
        self._session_time: float = 0.0
        # Match state — tennis scoring per AC PR 6. wall_rally mode:
        # rally length crossing the long_rally_threshold awards a player
        # point on rally end; otherwise opp point.
        self.match: volley_scoring.MatchState = volley_scoring.new_match("wall_rally")
        self.rally_contacts: int = 0
        self.last_rally_outcome: dict | None = None    # for HUD/state events
        # Per-rally peak telemetry — observed during on_tick + on_strike,
        # rolled into the active run's metrics on rally end. Per AC PR 8.
        self._rally_max_v: float = 0.0
        # Active vault.runs row for this session. Opened on first serve,
        # closed on reset_match / match_winner. None until first serve.
        self._run_id: str | None = None
        self._run_metrics: dict = {"rallies": [], "peak_max_v": 0.0,
                                   "peak_rally_length": 0}
        # State events emitted by the handler. Drained by the brain
        # manifest builder via drain_state_events(). Per AC PR 8.
        self._state_events: list[dict] = []
        # Brick Attack mode — horizontal row of breakable targets on
        # the front wall. Reset by reset_rally / reset_match.
        # Per V1 close-out 2026-05-04.
        self.bricks: list[dict[str, Any]] = _fresh_bricks()
        self.brick_score: int = 0
        self.brick_win: bool = False
        # Round telemetry — substrate observation rig for combat-math
        # extrapolation. A "round" = serve-fresh-bricks until win/reset.
        # Records per-round contacts + duration + outcome so the user
        # can derive: encounter HP → expected hits, expected time, etc.
        self.brick_round_id: int = 1
        self.brick_round_started_at: float = 0.0    # set on first serve, see on_serve
        self.brick_round_contacts: int = 0
        self.brick_round_log: list[dict] = []        # combined chronological log
        self._brick_round_open: bool = False        # first round opens lazily on first serve
        # Active brick set + per-set logs for combat-math experiments.
        # User can switch via console: `mode <set_name>`. Per-set logs
        # accumulate independently → control vs experimental compared.
        self.brick_set: str = DEFAULT_BRICK_SET
        self.brick_threshold: int = _threshold_for(self.brick_set)
        self.brick_round_log_by_set: dict[str, list[dict]] = {
            name: [] for name in BRICK_SETS
        }
        # Auto-reset after WIN — round logs immediately, then 2s celebration
        # delay (player sees WIN flash), then bricks restore + ball clears
        # + next round opens. Makes the 100-round experiment harness fully
        # automatic — no manual R between rounds.
        self._brick_auto_reset_at: float = 0.0
        self._brick_auto_reset_delay: float = 2.0    # seconds of WIN-flash before reset

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
        """Lazily build / rebuild the solver for the active profile.

        Cache key is `(profile_name, profile.updated_at)` so a console
        setter that mutates the profile params triggers an immediate
        rebuild on the next solver call. Per AC PR 7.
        """
        row = self.vault.profile_load(INSTANCE_ID, self.active_profile)
        updated_at = row["updated_at"] if row else None
        if (self._solver is not None
                and self._solver_profile == self.active_profile
                and self._solver_updated_at == updated_at):
            return self._solver
        params = self.vault.profile_resolve(INSTANCE_ID, self.active_profile)
        walls = chamber_walls(
            tuple(CHAMBER_GEOMETRY["size"]),
            tuple(CHAMBER_GEOMETRY["origin"]),
        )
        self._solver = BallisticsSolver(BallisticsParams.from_profile(params), walls)
        self._solver_profile = self.active_profile
        self._solver_updated_at = updated_at
        return self._solver

    # -- ball lifecycle ---------------------------------------------------

    def on_serve(self) -> MotionVector:
        """Spawn a stationary ball at the active profile's serve_offset.

        Per AC §"Decisions locked" #4: Atari single-press serve. First
        press creates the ball; second press is the rally swing (PR 5).
        Resets rally contact counter so the next miss/score event
        scores fairly. Match state preserved (use volley_reset_match
        for a fresh match). Opens a vault.runs row on the first serve
        of the session (PR 8 telemetry).
        """
        # Open a run on first serve (vault.runs lifecycle, PR 8).
        if self._run_id is None:
            self._run_id = self.vault.run_start(INSTANCE_ID, self.active_profile)
            self._emit_event("make_brain_started", run_id=self._run_id)
        # Open the first brick round lazily on first serve (so duration
        # starts when the player actually starts playing, not at boot).
        if not self._brick_round_open:
            self._start_brick_round()
            self._brick_round_open = True
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
        self._rally_max_v = 0.0
        self._emit_event("rally_started", profile=self.active_profile)
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
        self.brick_round_contacts += 1
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
        # Auto-reset after WIN delay — round was already logged when WIN
        # fired; this just spawns fresh bricks + clears ball so the next
        # round can begin without manual R press. Per V1 close-out
        # 2026-05-04 — fully automatic 100-round experiment harness.
        if (self._brick_auto_reset_at > 0.0
                and self._session_time >= self._brick_auto_reset_at):
            self._brick_auto_reset_at = 0.0
            self.bricks = _fresh_bricks_for(self.brick_set)
            self.brick_threshold = _threshold_for(self.brick_set)
            self.brick_score = 0
            self.brick_win = False
            self.ball = None
            self._start_brick_round()
            self._emit_event("brick_round_auto_reset", set=self.brick_set)
        if self.ball is None:
            return []
        solver = self._ensure_solver()
        new_state, contacts = solver.step(self.ball, dt, substeps=substeps)
        self.ball = new_state
        # Track peak speed for run telemetry (PR 8)
        speed = (new_state.vel[0]**2 + new_state.vel[1]**2 + new_state.vel[2]**2) ** 0.5
        if speed > self._rally_max_v:
            self._rally_max_v = speed
        # Brick Attack — sphere-vs-AABB overlap check after each tick.
        # Pins stand on the floor; ball rolling / bouncing forward
        # contacts them. Multi-HP bricks decrement hp on each contact
        # and only score (+ become destroyed) when hp reaches 0.
        # Ball is NOT reflected by brick contact (passes through) so
        # one strike can chain through multiple pins. Per V1 close-out
        # 2026-05-04 + experimental harness 2026-05-04.
        if not self.brick_win and self.ball is not None:
            params_now = self.vault.profile_resolve(INSTANCE_ID, self.active_profile)
            r = float(params_now.get("ball_radius", 0.15))
            bx, by, bz = self.ball.pos
            for brick in self.bricks:
                if brick["destroyed"]:
                    continue
                if (brick["x_min"] - r <= bx <= brick["x_max"] + r
                        and brick["y_min"] - r <= by <= brick["y_max"] + r
                        and brick["z_min"] - r <= bz <= brick["z_max"] + r):
                    # One contact = one HP decrement. Cooldown via
                    # ball-leaves-AABB: in V1 we just process one brick
                    # per tick step (break below); fast travel through
                    # a multi-HP brick still requires multiple ticks.
                    brick["hp"] = max(0, int(brick.get("hp", 1)) - 1)
                    if brick["hp"] <= 0:
                        brick["destroyed"] = True
                        self.brick_score += int(brick["score"])
                        # Activity-loop signal — HUNT class. Boss bricks
                        # (max_hp > 1) carry triple intensity to mark them
                        # as heavy moments. Per PR 9. Telemetry payload
                        # carries score + max_hp so post-hoc analysis can
                        # disambiguate boss-vs-normal contributions.
                        bmax_hp = int(brick.get("max_hp", 1))
                        activity_loop.emit_activity(
                            ActivityClass.HUNT,
                            intensity=3 if bmax_hp > 1 else 1,
                            primitive="brick_destroyed",
                            source_brain="ping_pong",
                            payload={
                                "score":  int(brick["score"]),
                                "max_hp": bmax_hp,
                            },
                        )
                        self._emit_event(
                            "brick_destroyed",
                            score=brick["score"],
                            total=self.brick_score,
                            max_hp=bmax_hp,
                        )
                        if self.brick_score >= self.brick_threshold:
                            self.brick_win = True
                            self._emit_event(
                                "brick_win", score=self.brick_score,
                                set=self.brick_set,
                            )
                            self._complete_brick_round("win")
                            # Schedule auto-reset for 2s from now —
                            # gives the player time to see the WIN
                            # flash before bricks restore.
                            self._brick_auto_reset_at = (
                                self._session_time + self._brick_auto_reset_delay
                            )
                    else:
                        self._emit_event(
                            "brick_damaged",
                            hp=brick["hp"],
                            max_hp=int(brick.get("max_hp", 1)),
                        )
                    break    # one brick contact per tick step
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
        # Append rally to run metrics + emit state events (PR 8 telemetry).
        rally_record = {
            "winner":   winner,
            "contacts": self.rally_contacts,
            "max_v":    round(self._rally_max_v, 3),
            "profile":  self.active_profile,
        }
        self._run_metrics["rallies"].append(rally_record)
        if self._rally_max_v > self._run_metrics.get("peak_max_v", 0.0):
            self._run_metrics["peak_max_v"] = round(self._rally_max_v, 3)
        if self.rally_contacts > self._run_metrics.get("peak_rally_length", 0):
            self._run_metrics["peak_rally_length"] = self.rally_contacts
            self._emit_event("peak_recorded",
                             metric="rally_length", value=self.rally_contacts)
        self._emit_event("rally_ended", winner=winner,
                         contacts=self.rally_contacts,
                         max_v=round(self._rally_max_v, 3))
        self._emit_event("score_changed",
                         points=list(self.match.points),
                         games=list(self.match.games),
                         sets_won=list(self.match.sets_won))
        # Match end → close the run.
        if self.match.match_winner is not None:
            self._close_run(terminal_state=(
                "won" if self.match.match_winner == "player" else "lost"
            ))
        else:
            # Persist incremental metrics so the row reflects in-progress
            # state if the brain crashes mid-match.
            self._persist_run_metrics()
        self.ball = None
        self.rally_contacts = 0
        self._rally_max_v = 0.0

    # -- match-level reset hooks ----------------------------------------

    def reset_rally(self) -> None:
        """Discard active ball + rally counter; preserve match state +
        round logs. Restores bricks for the active brick_set AND closes
        any in-progress round as 'aborted' before starting a fresh one."""
        if self.brick_round_contacts > 0 and not self.brick_win:
            self._complete_brick_round("aborted")
        self.ball = None
        self.rally_contacts = 0
        self._rally_max_v = 0.0
        self.last_rally_outcome = None
        self.bricks = _fresh_bricks_for(self.brick_set)
        self.brick_threshold = _threshold_for(self.brick_set)
        self.brick_score = 0
        self.brick_win = False
        self._start_brick_round()

    def reset_match(self) -> None:
        """Hard reset — fresh match, no ball, no rally, fresh bricks,
        full round-log wipe (BOTH sets). Closes the active run as 'aborted'."""
        if self.brick_round_contacts > 0 and not self.brick_win:
            self._complete_brick_round("aborted")
        if self._run_id is not None:
            self._close_run(terminal_state="aborted")
        self.ball = None
        self.rally_contacts = 0
        self._rally_max_v = 0.0
        self.last_rally_outcome = None
        self.match = volley_scoring.new_match("wall_rally")
        self._run_metrics = {"rallies": [], "peak_max_v": 0.0,
                             "peak_rally_length": 0}
        self.bricks = _fresh_bricks_for(self.brick_set)
        self.brick_threshold = _threshold_for(self.brick_set)
        self.brick_score = 0
        self.brick_win = False
        self.brick_round_id = 1
        self.brick_round_log = []
        self.brick_round_log_by_set = {name: [] for name in BRICK_SETS}
        self._start_brick_round()

    # -- experimental harness — set switching ----------------------------

    def switch_brick_set(self, name: str) -> None:
        """Switch the active brick layout. Closes any open round + spawns
        fresh bricks for the new set. Per-set logs are preserved across
        switches so you can compare datasets within a session."""
        if name not in BRICK_SETS:
            raise ValueError(
                f"unknown brick_set: {name} (known: {sorted(BRICK_SETS)})"
            )
        if self.brick_round_contacts > 0 and not self.brick_win:
            self._complete_brick_round("aborted")
        self.brick_set = name
        self.bricks = _fresh_bricks_for(name)
        self.brick_threshold = _threshold_for(name)
        self.brick_score = 0
        self.brick_win = False
        self.ball = None
        self.brick_round_id = 1
        self._brick_round_open = False    # next serve opens fresh round
        self._emit_event("brick_set_switched", set=name)

    def list_brick_sets(self) -> list[dict]:
        """Return [{name, label, threshold, total_hp, rounds_logged, ...}]
        for HUD / console listing."""
        out = []
        for name, layout in BRICK_SETS.items():
            bricks = layout["bricks"]
            log = self.brick_round_log_by_set.get(name) or []
            wins = [r for r in log if r.get("reason") == "win"]
            row = {
                "name":          name,
                "label":         layout["label"],
                "threshold":     int(layout["threshold"]),
                "total_hp":      sum(int(b.get("hp", 1)) for b in bricks),
                "rounds":        len(log),
                "wins":          len(wins),
                "active":        name == self.brick_set,
                "target":        TARGET_ROUNDS_PER_SET,
            }
            if wins:
                contacts = [int(r["contacts"]) for r in wins]
                durations = [float(r["duration_s"]) for r in wins]
                row["avg_contacts"]   = round(sum(contacts) / len(contacts), 2)
                row["avg_duration_s"] = round(sum(durations) / len(durations), 2)
            out.append(row)
        return out

    # -- brick-round lifecycle (combat-math observation rig) -------------

    def _start_brick_round(self) -> None:
        """Open a fresh round. Called after reset_rally / reset_match."""
        self.brick_round_started_at = self._session_time
        self.brick_round_contacts = 0

    def _complete_brick_round(self, reason: str) -> None:
        """Append a completed round to the active set's log + emit event +
        flush to vault.runs.metrics_json so the data survives crashes /
        brain restarts. Per V1 close-out 2026-05-04 — substrate
        observation rig must be durable for combat-math analysis."""
        duration = round(self._session_time - self.brick_round_started_at, 3)
        record = {
            "round_id":   self.brick_round_id,
            "set":        self.brick_set,
            "duration_s": duration,
            "contacts":   self.brick_round_contacts,
            "score":      self.brick_score,
            "reason":     reason,
            "ended_at":   round(self._session_time, 3),
        }
        self.brick_round_log.append(record)
        self.brick_round_log_by_set.setdefault(self.brick_set, []).append(record)
        # Persist into the active run's metrics — recoverable from
        # vault.db even if the brain crashes mid-experiment.
        rounds_by_set = self._run_metrics.setdefault("brick_rounds_by_set", {})
        rounds_by_set.setdefault(self.brick_set, []).append(record)
        self._persist_run_metrics()
        self._emit_event(
            "brick_round_ended",
            round_id=self.brick_round_id,
            set=self.brick_set,
            duration_s=duration,
            contacts=self.brick_round_contacts,
            reason=reason,
        )
        self.brick_round_id += 1

    def brick_round_summary(self, last_n: int | None = None,
                            set_name: str | None = None) -> dict:
        """Aggregate stats over the round log. last_n=None = all rounds.
        set_name=None = active set; pass a name to query that set."""
        if set_name is None:
            set_name = self.brick_set
        rounds = self.brick_round_log_by_set.get(set_name) or []
        if last_n is not None:
            rounds = rounds[-last_n:]
        wins = [r for r in rounds if r.get("reason") == "win"]
        if not wins:
            return {"sample": len(rounds), "wins": 0,
                    "avg_contacts": 0, "avg_duration_s": 0,
                    "min_contacts": 0, "max_contacts": 0}
        contacts = [int(r["contacts"]) for r in wins]
        durations = [float(r["duration_s"]) for r in wins]
        return {
            "sample":         len(rounds),
            "wins":           len(wins),
            "avg_contacts":   round(sum(contacts) / len(contacts), 2),
            "avg_duration_s": round(sum(durations) / len(durations), 2),
            "min_contacts":   min(contacts),
            "max_contacts":   max(contacts),
            "min_duration_s": round(min(durations), 2),
            "max_duration_s": round(max(durations), 2),
        }

    # -- run lifecycle internals ------------------------------------------

    def _close_run(self, terminal_state: str) -> None:
        """Persist final metrics + close the vault.runs row."""
        if self._run_id is None:
            return
        self.vault.run_end(
            INSTANCE_ID, self._run_id,
            terminal_state=terminal_state,
            metrics=self._run_metrics,
        )
        self._emit_event("make_brain_ended", run_id=self._run_id,
                         terminal_state=terminal_state)
        self._run_id = None

    def _persist_run_metrics(self) -> None:
        """Update the open run row's metrics_json so an in-progress run
        is recoverable if the brain crashes. No terminal_state set."""
        if self._run_id is None:
            return
        # vault.run_end sets ended_at + terminal_state; we want a
        # metrics-only update, so we write directly with run_end's API
        # using terminal_state=None (which keeps the row "open" per the
        # vault contract — but ended_at gets stamped regardless). To
        # avoid stamping ended_at mid-match, do a raw SQL update.
        import json as _json, sqlite3 as _sqlite
        with _sqlite.connect(self.vault.db_path) as conn:
            conn.execute(
                "UPDATE runs SET metrics_json = ? "
                "WHERE instance_id = ? AND run_id = ? AND ended_at IS NULL",
                (_json.dumps(self._run_metrics), INSTANCE_ID, self._run_id),
            )
            conn.commit()

    # -- state events -----------------------------------------------------

    def _emit_event(self, kind: str, **payload) -> None:
        import time as _time
        self._state_events.append({
            "kind":      kind,
            "timestamp": _time.time(),
            **payload,
        })

    def drain_state_events(self) -> list[dict]:
        """Brain manifest builder calls this each tick; events flow into
        the manifest's volley_state_events list."""
        out = self._state_events
        self._state_events = []
        return out

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
        # Telemetry preview — peaks observed during the open run, useful
        # for the HUD before vault.runs_peak_* aggregates run on demand.
        keys["run_metrics"] = dict(self._run_metrics)
        # Drain queued state events for client consumption (PR 8).
        keys["volley_state_events"] = self.drain_state_events()
        # Brick Attack state — items + score + win flag + round log +
        # per-set summaries (combat-math experimental harness).
        # Per V1 close-out 2026-05-04.
        live_round_duration = max(
            0.0, round(self._session_time - self.brick_round_started_at, 3)
        )
        keys["bricks"] = {
            "items":     [dict(b) for b in self.bricks],
            "score":     int(self.brick_score),
            "threshold": int(self.brick_threshold),
            "win":       bool(self.brick_win),
            "set":       self.brick_set,
            "round": {
                "id":         self.brick_round_id,
                "contacts":   self.brick_round_contacts,
                "duration_s": live_round_duration,
            },
            "log":     [dict(r) for r in self.brick_round_log[-10:]],   # last 10 only — HUD doesn't need 100
            "summary": self.brick_round_summary(last_n=10),
            "sets":    self.list_brick_sets(),
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
