"""Game loop state machine — async-quest model.

The current model is:

  - CHARACTER_CREATION ↔ HUB   (7-pillar ritual, then return on re-do)
  - HUB ↔ REFLECTIVE           (fridge engagement / forced HP=0 path)

Free exploration + async quests stack on persistent world; world regen
only fires on HP=0 reflective commit (`design_death_only_regen`). Each
transition is validated against `_ALLOWED_TRANSITIONS` so illegal jumps
raise loudly.

Brain-authoritative per `feedback_brain_owns_config`. Vector terminal
reads `manifest.game_state` every update and renders accordingly.
Transitions are triggered by player intent (`state_transition_request`,
`engage_pillar`, `engage_fridge`) or internal events (HP=0 →
reflective).

History — PRs 5 and 6 (2026-05-02) collapsed the legacy DRG-style
5-state mission loop (HUB → MISSION_SELECT → IN_MISSION → RESULTS →
HUB) plus its mission_id / mission_seed / results context fields.
Async quests via `project_async_quest_refactor` are the new spine.

Doctrine: pure data + rules. Immutability via NamedTuple — every
operation returns a new GameState. No I/O. Side effects (world regen,
manifest push) sit upstream in BrainWorld.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, NamedTuple, Optional


# --- States -----------------------------------------------------------------

class GameStateName(str, Enum):
    """Canonical loop states. Stored as strings so manifest
    serialization is direct (json.dumps friendly).

    PR 5 (2026-05-02) dropped MISSION_SELECT / IN_MISSION / RESULTS —
    the 5-state DRG-style loop became a 2-state machine + REFLECTIVE.
    Free exploration replaces "in a mission instance"; async quests
    layer on top of persistent world (`project_async_quest_refactor`).
    """
    CHARACTER_CREATION = "CHARACTER_CREATION"  # at hub, doing the 7-pillar ritual
    HUB = "HUB"                     # at staging area, free exploration
    REFLECTIVE = "REFLECTIVE"       # at the fridge, composing under a rule


# Allowed transitions. Anything not in this set raises ValueError.
# Reading: (FROM, TO).
_ALLOWED_TRANSITIONS = frozenset({
    (GameStateName.CHARACTER_CREATION, GameStateName.HUB),     # all pillars sealed
    (GameStateName.HUB, GameStateName.CHARACTER_CREATION),     # re-do via Pillar of Reflection
    (GameStateName.HUB, GameStateName.REFLECTIVE),             # engage fridge (forced or voluntary)
    (GameStateName.REFLECTIVE, GameStateName.HUB),             # commit / abort back to hub
})


# --- State container --------------------------------------------------------

class GameState(NamedTuple):
    """Loop state container. Immutable; transitions return new instances.

    Post PR 6: just `state`. The legacy mission_id / mission_seed /
    results ghost fields were dropped — async quests carry per-quest
    context on `world.quest_state`, and reflective context lives on
    `world.reflective`. The state machine itself is just an enum tag.
    """
    state: GameStateName

    @classmethod
    def initial(cls) -> "GameState":
        """Default starting state — player at hub."""
        return cls(state=GameStateName.HUB)

    @classmethod
    def fresh_character(cls) -> "GameState":
        """Brand-new player — no save file, run the 7-pillar ritual at hub."""
        return cls(state=GameStateName.CHARACTER_CREATION)


# --- Transitions ------------------------------------------------------------

def transition(current: GameState, target: GameStateName) -> GameState:
    """Validate + perform a state transition.

    Raises ValueError if (current.state, target) isn't in the allowed
    set. Returns a new GameState; current is unchanged.
    """
    if (current.state, target) not in _ALLOWED_TRANSITIONS:
        raise ValueError(
            f"illegal transition: {current.state.value} -> {target.value}"
        )
    return GameState(state=target)


# --- Predicates -------------------------------------------------------------

def is_at_hub(gs: GameState) -> bool:
    return gs.state == GameStateName.HUB


# --- Serialization ----------------------------------------------------------

def to_manifest(gs: GameState) -> dict[str, Any]:
    """Serialize for streaming via manifest.game_state. Just the state
    tag now — per-quest / per-reflective context lives on its own
    manifest blocks (`quests`, `reflective`)."""
    return {"state": gs.state.value}


def from_manifest(data: dict[str, Any]) -> GameState:
    """Inverse of to_manifest. Tolerant of legacy V2 manifests that
    carried mission_id / mission_seed / results — they're silently
    dropped on read."""
    return GameState(state=GameStateName(data["state"]))
