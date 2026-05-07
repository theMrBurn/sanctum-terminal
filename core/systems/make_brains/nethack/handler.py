"""NetHackHandler — substrate hooks for the classic-NetHack make-brain.

PR 1 stub.  Owns identity constants, vault profile bootstrap, and the
manifest-keys shape every make-brain handler exposes.  Game logic
(turn loop, dungeon, combat) lands in PRs 2-8.

Spec: `.claude/feature/feat_make-brain-nethack.md`.
"""
from __future__ import annotations

from typing import Any


# ----------------------------------------------------------------------
# Identity (universal substrate keys)
# ----------------------------------------------------------------------

INSTANCE_ID:     str = "nethack"
ENTRY_POINT:     str = "terminal:nethack"      # standalone curses app, not a biome
DEFAULT_PROFILE: str = "vanilla"

STATE_EVENT_TYPES: tuple[str, ...] = (
    # Universal lifecycle (every make-brain emits these)
    "make_brain_started", "make_brain_ended", "profile_loaded",
    "peak_recorded",
    # NetHack-specific
    "level_descended", "monster_killed", "item_picked_up",
    "level_up", "player_died",
)


# ----------------------------------------------------------------------
# Vanilla profile — classic NetHack fighter defaults
# ----------------------------------------------------------------------

VANILLA_PARAMS: dict[str, Any] = {
    "_target":          "classic NetHack — fighter starter, V1 vertical slice",
    # Player starting stats — NetHack fighter
    "start_str":        16,
    "start_dex":        12,
    "start_con":        14,
    "start_int":        10,
    "start_wis":        10,
    "start_cha":        10,
    "start_hp":         12,
    "start_ac":         9,         # NetHack convention: lower = better, 10 = naked
    "start_weapon":     "dagger",  # d4 damage
    "start_armor":      "leather", # contributes to AC=9 from 10
    # Map dimensions
    "map_w":            80,
    "map_h":            24,
    # Dungeon-gen — classic Rogue 3x3 super-grid
    "supergrid_w":      3,
    "supergrid_h":      3,
    "min_room_w":       4,
    "min_room_h":       3,
    "max_room_w":       12,
    "max_room_h":       8,
    # FOV
    "fov_radius":       8,
    # Spawn count per level
    "monsters_min":     3,
    "monsters_max":     6,
}


# ----------------------------------------------------------------------
# Handler
# ----------------------------------------------------------------------


class NetHackHandler:
    """PR 1 stub — substrate-only.

    Owns:
      - vault profile bootstrap (vanilla seeded on first activate)
      - active_profile name
      - run lifecycle hooks (open on game start, close on death/quit)
      - state-events queue (drained by the renderer / telemetry tap)

    Game state (level, player, monsters) lands in PR 2+.
    """

    INSTANCE_ID:       str = INSTANCE_ID
    ENTRY_POINT:       str = ENTRY_POINT
    DEFAULT_PROFILE:   str = DEFAULT_PROFILE
    STATE_EVENT_TYPES: tuple[str, ...] = STATE_EVENT_TYPES

    def __init__(self, vault):
        self.vault = vault
        self.active_profile: str = DEFAULT_PROFILE
        self._run_id: str | None = None
        self._run_metrics: dict[str, Any] = {
            "depth_reached":    1,
            "monsters_killed":  0,
            "items_picked_up":  0,
            "turns":            0,
            "level":            1,
            "xp":               0,
        }
        self._state_events: list[dict] = []
        self._ensure_default_profiles()

    # -- profile bootstrapping ------------------------------------------

    def _ensure_default_profiles(self) -> None:
        """Seed vanilla on first boot. Idempotent across restarts."""
        if self.vault.profile_load(INSTANCE_ID, "vanilla") is None:
            self.vault.profile_save(
                INSTANCE_ID, "vanilla",
                params=VANILLA_PARAMS,
                notes="classic NetHack fighter defaults — V1 PR 1 seed",
            )

    # -- run lifecycle (game start / end) -------------------------------

    def start_run(self) -> str:
        """Open a vault.runs row for a new game. Returns the run_id.

        Called by the entry-point at game start, after profile load.
        """
        if self._run_id is not None:
            return self._run_id
        self._run_id = self.vault.run_start(INSTANCE_ID, self.active_profile)
        self._run_metrics = {
            "depth_reached":    1,
            "monsters_killed":  0,
            "items_picked_up":  0,
            "turns":            0,
            "level":            1,
            "xp":               0,
        }
        self._emit_event("make_brain_started", run_id=self._run_id)
        return self._run_id

    def end_run(self, terminal_state: str, **extra_metrics) -> None:
        """Close the active run. terminal_state ∈ {died, quit, won}.

        Game logic calls this on YASD (PR 8), on user quit, or on the
        currently-unimplemented win condition.
        """
        if self._run_id is None:
            return
        metrics = dict(self._run_metrics)
        metrics.update(extra_metrics)
        self.vault.run_end(
            INSTANCE_ID, self._run_id,
            terminal_state=terminal_state,
            metrics=metrics,
        )
        self._emit_event("make_brain_ended",
                         run_id=self._run_id,
                         terminal_state=terminal_state)
        self._run_id = None

    # -- state events ---------------------------------------------------

    def _emit_event(self, kind: str, **payload) -> None:
        import time as _time
        self._state_events.append({
            "kind":      kind,
            "timestamp": _time.time(),
            **payload,
        })

    def drain_state_events(self) -> list[dict]:
        out = self._state_events
        self._state_events = []
        return out

    # -- manifest -------------------------------------------------------

    def manifest_keys(self) -> dict[str, Any]:
        """Substrate snapshot — what the entry-point / telemetry tap reads.

        PR 1 returns identity + run state only.  Game-state keys (level,
        player, monsters, log) get added here in later PRs.
        """
        return {
            "instance_id":          INSTANCE_ID,
            "active_profile":       self.active_profile,
            "run_id":               self._run_id,
            "run_metrics":          dict(self._run_metrics),
            "nethack_state_events": self.drain_state_events(),
        }
