"""compose_three make-brain — creature-engagement engagement_type V1.

Per `.claude/feature/feat_creature-engagement.md` PR 2 and
`design_creature_engagement_v1`. Wraps the reflective compose primitive
(magnet pool + place-three + commit) into a make-brain so creature
kinds can bind it via `kind_config.engagement.engagement_type`.

V1 scope:
  - Holds per-session engagement state (one engagement-at-a-time per
    handler; rebound on each `begin`).
  - Reuses `reflective.magnets.compose_pool` for pool generation (the
    rule_args `pool` label is forward-compat; V2 swaps in per-pool
    dictionaries authored separately).
  - AC check is inline (`len(composed) >= target_count`) — the rule
    is structurally trivial so we don't drag in the full reflective
    predicate registry.

Distinct from REFLECTIVE state machine (HP=0 fridge): engagement is
agent-bound and triggered by creature contact (PR 4 dispatch).
"""
from __future__ import annotations

import random
from typing import Any

from core.systems import make_brain_registry
from core.systems.reflective import magnets


# ── Identity ──────────────────────────────────────────────────────────

INSTANCE_ID:     str = "compose_three"
ENTRY_POINT:     str = "creature_engagement"
DEFAULT_PROFILE: str = "default"

STATE_EVENT_TYPES: tuple[str, ...] = (
    # Universal lifecycle (every make-brain emits these)
    "make_brain_started", "make_brain_ended", "profile_loaded",
    "peak_recorded",
    # Engagement-specific (per design_creature_engagement_v1 trigger flow)
    "engagement_open", "engagement_won", "engagement_lost",
    "engagement_aborted",
)


# ── Default profile (vault-seeded) ────────────────────────────────────
#
# rule_args at the kind-binding site override these per-engagement.
# Profile values are the global default if a kind didn't customize.

DEFAULT_PARAMS: dict[str, Any] = {
    "_target":      "minimal compose — three magnets, three attempts",
    "target_count": 3,
    "max_attempts": 3,
    "max_pool_size": 8,
}


# ── Handler ───────────────────────────────────────────────────────────


class ComposeThreeHandler:
    """Compose-three engagement runner. One session at a time per handler."""

    INSTANCE_ID:       str = INSTANCE_ID
    ENTRY_POINT:       str = ENTRY_POINT
    DEFAULT_PROFILE:   str = DEFAULT_PROFILE
    STATE_EVENT_TYPES: tuple[str, ...] = STATE_EVENT_TYPES

    def __init__(self, vault):
        self.vault = vault
        self.active_profile = DEFAULT_PROFILE
        self._ensure_default_profile()
        # Session state — None when no engagement is active.
        self.session: dict | None = None
        # Active vault.runs row for the current engagement instance.
        # Opened on begin(), closed on end(). PR 3 swaps to vault.engagements.
        self._run_id: str | None = None
        self._state_events: list[dict] = []

    # -- profile bootstrapping --------------------------------------------

    def _ensure_default_profile(self) -> None:
        """Seed the default profile if absent. Idempotent across boots."""
        if self.vault.profile_load(INSTANCE_ID, DEFAULT_PROFILE) is None:
            self.vault.profile_save(
                INSTANCE_ID, DEFAULT_PROFILE,
                params=DEFAULT_PARAMS,
                notes="V1 PR 2 seed — minimal compose engagement",
            )

    # -- session lifecycle ------------------------------------------------

    def begin(
        self,
        agent_id: str,
        kind: str,
        rule_args: dict | None = None,
        rng: random.Random | None = None,
    ) -> bool:
        """Open a compose_three engagement against an agent.

        `rule_args` overrides profile defaults per the kind_config slot.
        Returns True on successful open, False if a session is already
        active (caller should `abort()` first).
        """
        if self.session is not None:
            return False
        if rng is None:
            rng = random.Random()

        params = self.vault.profile_resolve(INSTANCE_ID, self.active_profile)
        args = dict(rule_args or {})
        target_count  = int(args.get("target_count",  params.get("target_count", 3)))
        max_attempts  = int(args.get("max_attempts",  params.get("max_attempts", 3)))
        max_pool_size = int(args.get("max_pool_size", params.get("max_pool_size", 8)))
        pool_label    = str(args.get("pool", "default"))

        # V1: compose pool from reflective magnets module. V2 swaps in
        # per-pool dictionaries (rat_postures, scout_phrases, …).
        full_pool = magnets.compose_pool(rng)
        pool = full_pool[:max_pool_size] if max_pool_size > 0 else full_pool

        self.session = {
            "agent_id":      str(agent_id),
            "kind":          str(kind),
            "target_count":  target_count,
            "max_attempts":  max_attempts,
            "max_pool_size": max_pool_size,
            "pool_label":    pool_label,
            "pool":          list(pool),
            "composed":      [],
            "attempt_count": 0,
            "outcome":       None,
        }
        self._state_events.append({
            "type":     "engagement_open",
            "kind":     str(kind),
            "agent_id": str(agent_id),
            "rule":     INSTANCE_ID,
            "target":   target_count,
        })
        return True

    def place_magnet(self, magnet: str) -> bool:
        """Append a magnet to the composition. Returns True on placement."""
        if self.session is None:
            return False
        if magnet not in self.session["pool"]:
            return False
        self.session["composed"].append(magnet)
        return True

    def remove_magnet(self, index: int) -> bool:
        """Pop the magnet at the given index. Returns True on removal."""
        if self.session is None:
            return False
        composed = self.session["composed"]
        if index < 0 or index >= len(composed):
            return False
        composed.pop(index)
        return True

    def commit(self) -> str:
        """Evaluate AC predicate, increment attempt count, return outcome.

        Outcomes:
          - "win"       — composed length ≥ target_count, engagement passes
          - "retry"     — AC not satisfied, attempts remain, try again
          - "exhausted" — AC not satisfied, no attempts left, engagement fails
          - "inactive"  — no session open

        Does NOT close the session — caller decides whether to `end(outcome)`
        on win/exhausted, or leave open for another `place→commit` round.
        """
        if self.session is None:
            return "inactive"
        self.session["attempt_count"] += 1
        if len(self.session["composed"]) >= self.session["target_count"]:
            self.session["outcome"] = "win"
            return "win"
        if self.session["attempt_count"] >= self.session["max_attempts"]:
            self.session["outcome"] = "exhausted"
            return "exhausted"
        # AC failed, attempts remain — clear composition so the player
        # rebuilds rather than topping up a stale stack.
        self.session["composed"] = []
        return "retry"

    def abort(self) -> bool:
        """Player-initiated abort. Marks outcome and emits state event;
        caller still must `end()` to clear session state. Returns True
        if a session was active to abort."""
        if self.session is None:
            return False
        self.session["outcome"] = "aborted"
        self._state_events.append({
            "type":     "engagement_aborted",
            "kind":     self.session["kind"],
            "agent_id": self.session["agent_id"],
        })
        return True

    def end(self) -> dict | None:
        """Close the active session and emit the outcome state event.

        Returns the closed session dict (for telemetry / loot dispatch)
        or None if no session was active.
        """
        if self.session is None:
            return None
        outcome = self.session.get("outcome")
        kind = self.session["kind"]
        agent_id = self.session["agent_id"]
        if outcome == "win":
            ev_type = "engagement_won"
        elif outcome == "aborted":
            ev_type = "engagement_aborted"
        else:
            ev_type = "engagement_lost"
        # engagement_aborted was already pushed at abort() — don't double-emit.
        if ev_type != "engagement_aborted":
            self._state_events.append({
                "type":     ev_type,
                "kind":     kind,
                "agent_id": agent_id,
                "attempts": self.session["attempt_count"],
            })
        closed = self.session
        self.session = None
        return closed

    # -- state event drain (manifest builder reads from this) -------------

    def drain_state_events(self) -> list[dict]:
        """Pop and return all pending state events. Manifest builder
        calls this once per tick to fold engagement events into the
        outgoing manifest."""
        events = self._state_events
        self._state_events = []
        return events


# ── Registration ──────────────────────────────────────────────────────


def activate(vault) -> "make_brain_registry.MakeBrainSpec":
    """Register ComposeThreeHandler with make_brain_registry.

    Idempotent — repeated calls return the existing spec without
    re-registering.
    """
    try:
        return make_brain_registry.get(INSTANCE_ID)
    except LookupError:
        pass
    handler = ComposeThreeHandler(vault)
    return make_brain_registry.register(
        instance_id       = INSTANCE_ID,
        entry_point       = ENTRY_POINT,
        default_profile   = DEFAULT_PROFILE,
        state_event_types = STATE_EVENT_TYPES,
        handler           = handler,
    )
