"""Per-frame quest evaluator.

Called once per brain main-loop iteration. Iterates `world.quest_state.active`,
runs each quest's predicate, fires the `on_complete` callback for any
quest whose predicate returns True, and migrates the completed quests
from active → completed.

The `on_complete` callback is brain-owned — it handles reward drops,
StateEvent emission, and any save-trigger side effects. Keeping side
effects in the brain (rather than this module) preserves the
`feedback_brain_owns_config` doctrine: the quest module is data-only.
"""
from __future__ import annotations

from typing import Callable

from core.systems.quests import Quest, get as get_quest
from core.systems.quests import predicates


OnCompleteFn = Callable[[Quest], None]


def tick(world, events: list[dict], on_complete: OnCompleteFn) -> None:
    """Evaluate all active quests once.

    `events` is the per-tick accumulator the brain populates from Godot
    commands (`kind_destroyed`, `cast_landed`, etc.). Cleared after this
    call by the brain so events fire on at most one tick.

    Predicates whose name doesn't resolve are skipped silently — better
    than crashing the loop on a typo'd quest definition. The startup
    validation (test_quest_predicate_references_resolve) catches shipped
    typos at test time.
    """
    state = world.quest_state
    completed_now: list[str] = []
    for qid in list(state.active):
        quest = get_quest(qid)
        if quest is None:
            continue
        fn = predicates.get(quest.predicate)
        if fn is None:
            continue
        progress = state.progress.setdefault(qid, {})
        # Pass a defensive copy of static args so the predicate cannot
        # mutate the registered quest's predicate_args dict.
        if fn(world, dict(quest.predicate_args), progress, events):
            completed_now.append(qid)
    for qid in completed_now:
        quest = get_quest(qid)
        if quest is None:
            continue
        state.complete(qid)
        on_complete(quest)
