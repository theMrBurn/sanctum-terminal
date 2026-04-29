"""Game loop state machine — DRG / Persona / SMT-style mission flow.

The spine of the gameplay loop. Player enters at HUB, chooses a mission
(MISSION_SELECT), launches into a procedural instance (IN_MISSION),
completes it and sees a summary (RESULTS), then returns to HUB. Each
transition is validated against an allowed-set so illegal jumps raise
loudly rather than silently corrupting state.

Brain-authoritative per `feedback_brain_owns_config`. Godot reads
manifest.game_state every update and renders accordingly. State
transitions are triggered either by:

  - Player intent (Godot sends a state_transition_request command)
  - Internal events (encounter or expedition handlers fire mission_complete)

State-specific fields (mission_id, mission_seed, results) carry the
context each state needs. Transition handlers update them atomically
with the state change.

Doctrine: pure data + rules. Immutability via NamedTuple — every
operation returns a new GameState. No I/O. Side effects (world regen,
manifest push) sit upstream in BrainWorld.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, NamedTuple, Optional


# --- States -----------------------------------------------------------------

class GameStateName(str, Enum):
    """The five canonical loop states. Stored as strings so manifest
    serialization is direct (json.dumps friendly)."""
    CHARACTER_CREATION = "CHARACTER_CREATION"  # at hub, doing the 7-pillar ritual
    HUB = "HUB"                     # at staging area, free exploration
    MISSION_SELECT = "MISSION_SELECT"  # picker open, choosing a mission
    IN_MISSION = "IN_MISSION"       # out in a procedural instance
    RESULTS = "RESULTS"             # post-mission summary screen


# Allowed transitions. Anything not in this set raises ValueError.
# Reading: (FROM, TO).
_ALLOWED_TRANSITIONS = frozenset({
    (GameStateName.CHARACTER_CREATION, GameStateName.HUB),     # all pillars sealed
    (GameStateName.HUB, GameStateName.MISSION_SELECT),         # open picker
    (GameStateName.MISSION_SELECT, GameStateName.HUB),         # cancel picker
    (GameStateName.MISSION_SELECT, GameStateName.IN_MISSION),  # launch mission
    (GameStateName.IN_MISSION, GameStateName.RESULTS),         # mission complete
    (GameStateName.IN_MISSION, GameStateName.HUB),             # abort/escape
    (GameStateName.RESULTS, GameStateName.HUB),                # acknowledge results
})


# --- State container --------------------------------------------------------

class GameState(NamedTuple):
    """Loop state + mission context. Immutable; transitions return new
    instances. Mission-specific fields are None when not relevant
    (clearer than sentinel values like "" or 0).
    """
    state: GameStateName
    mission_id: Optional[str]      # set when IN_MISSION or RESULTS
    mission_seed: Optional[int]    # procedural seed for the active instance
    results: Optional[dict]        # loot/xp/time payload when RESULTS

    @classmethod
    def initial(cls) -> "GameState":
        """Default starting state — player at hub, no mission active."""
        return cls(
            state=GameStateName.HUB,
            mission_id=None,
            mission_seed=None,
            results=None,
        )

    @classmethod
    def fresh_character(cls) -> "GameState":
        """Brand-new player — no save file, run the 7-pillar ritual at hub."""
        return cls(
            state=GameStateName.CHARACTER_CREATION,
            mission_id=None,
            mission_seed=None,
            results=None,
        )


# --- Transitions ------------------------------------------------------------

def transition(
    current: GameState,
    target: GameStateName,
    *,
    mission_id: Optional[str] = None,
    mission_seed: Optional[int] = None,
    results: Optional[dict] = None,
) -> GameState:
    """Validate + perform a state transition.

    Raises ValueError if (current.state, target) isn't in the allowed set,
    or if a target requires context (e.g., IN_MISSION needs mission_id)
    that wasn't supplied. Returns a new GameState; current is unchanged.
    """
    if (current.state, target) not in _ALLOWED_TRANSITIONS:
        raise ValueError(
            f"illegal transition: {current.state.value} -> {target.value}"
        )

    if target == GameStateName.HUB:
        # Returning to hub clears all mission context (and any character-creation
        # context — once you transition out of CHARACTER_CREATION, the draft
        # has been finalized). World regen that backs this transition lives
        # in BrainWorld; here we just mark the state as fresh.
        return current._replace(
            state=target,
            mission_id=None,
            mission_seed=None,
            results=None,
        )
    if target == GameStateName.MISSION_SELECT:
        return current._replace(state=target)
    if target == GameStateName.IN_MISSION:
        if mission_id is None:
            raise ValueError("IN_MISSION transition requires mission_id")
        return current._replace(
            state=target,
            mission_id=mission_id,
            mission_seed=mission_seed,
            results=None,
        )
    if target == GameStateName.RESULTS:
        # results may be {} for now — handlers can fill it in. Forcing
        # non-None makes downstream consumers' .get() calls safer.
        return current._replace(
            state=target,
            results=results if results is not None else {},
        )

    raise ValueError(f"unknown target state: {target!r}")


# --- Predicates -------------------------------------------------------------

def is_in_mission(gs: GameState) -> bool:
    return gs.state == GameStateName.IN_MISSION


def is_at_hub(gs: GameState) -> bool:
    return gs.state == GameStateName.HUB


# --- Serialization ----------------------------------------------------------

def to_manifest(gs: GameState) -> dict[str, Any]:
    """Serialize for streaming to Godot via manifest.game_state.

    All fields surface so Godot can render UI / gate input based on the
    current phase. results is passed through as-is — handlers that
    populate it own its shape.
    """
    return {
        "state": gs.state.value,
        "mission_id": gs.mission_id,
        "mission_seed": gs.mission_seed,
        "results": gs.results,
    }


def from_manifest(data: dict[str, Any]) -> GameState:
    """Inverse of to_manifest — reconstruct GameState from a manifest
    dict. Used at brain boot to load a save file's persisted state.
    """
    return GameState(
        state=GameStateName(data["state"]),
        mission_id=data.get("mission_id"),
        mission_seed=data.get("mission_seed"),
        results=data.get("results"),
    )
