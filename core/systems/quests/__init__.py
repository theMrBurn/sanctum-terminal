"""Quest registry — the async ambient quest substrate.

Per `project_async_quest_refactor` and `feedback_no_modal_state_changes`:
quests are stackable objectives the player toggles active in the journal.
They progress in-place on the persistent world; completion fires a
StateEvent toast + drops rewards passively. No modal state changes, no
world regen on launch (only on death — see `design_death_only_regen`).

Each quest carries:

  - id            stable identifier (`anomaly_hunt_01`)
  - name          short title shown in HUD + journal
  - description   one-line journal text
  - predicate     named predicate id (see `core.systems.quests.predicates`)
  - predicate_args static config the predicate consumes
  - rewards       loot table — same shape as the legacy `mission_loot`:
                   list of {name, weight} entries; weight ≤1.0 = roll-chance
  - register      StateEvent register for the completion toast (default LOOP)

Definitions live in `core.systems.quests.definitions` (Python module —
JSON migration deferred until predicate references stabilize per
`design_crud_substrate`). Each module's import calls `register(...)`.

This module is data-only. Predicate evaluation, manifest surfacing, and
brain-loop wiring live next door once PR 1 lands.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Quest:
    id: str
    name: str
    description: str
    predicate: str
    predicate_args: dict = field(default_factory=dict)
    rewards: list[dict] = field(default_factory=list)
    register: str = "loop"


_REGISTRY: dict[str, Quest] = {}


def register(quest: Quest) -> None:
    if quest.id in _REGISTRY:
        raise ValueError(f"quest already registered: {quest.id!r}")
    _REGISTRY[quest.id] = quest


def register_dynamic(quest: Quest) -> None:
    """Runtime registration — idempotent overwrite by id. Used by the
    journal→quest bridge: the same entry id always maps to the same
    quest id, so re-running the bridge replaces the existing row instead
    of raising. Build-time `register()` keeps strict-once semantics."""
    _REGISTRY[quest.id] = quest


def get(quest_id: str) -> Quest | None:
    return _REGISTRY.get(quest_id)


def all_quests() -> dict[str, Quest]:
    """Snapshot of the registry. Tests + brain manifest both consume this."""
    return dict(_REGISTRY)


def clear() -> None:
    """Test-only — reset the registry. Production code should never call this."""
    _REGISTRY.clear()


# Import quest definition modules to trigger registration. Same pattern as
# `core.systems.pillars.__init__`.
from core.systems.quests import definitions as _definitions  # noqa: E402, F401
