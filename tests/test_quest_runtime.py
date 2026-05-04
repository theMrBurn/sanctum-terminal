"""Quest runtime — state container, tick evaluator, reward roll.

PR 1.2 of `project_async_quest_refactor`. Brain wiring tests
(journal_toggle_quest cmd, manifest surface) live in
test_brain_quest_wire.py once the brain process tests get pulled in;
this suite covers the pure components.
"""
from __future__ import annotations

import random

import pytest

from core.systems import quests
from core.systems.quests import predicates, rewards
from core.systems.quests.state import QuestState
from core.systems.quests.tick import tick


# ── QuestState ──────────────────────────────────────────────────────


def test_state_starts_empty():
    s = QuestState()
    assert s.available == []
    assert s.active == []
    assert s.completed == []
    assert s.progress == {}


def test_toggle_available_to_active():
    s = QuestState(available=["q1"])
    assert s.toggle_active("q1") == "active"
    assert s.active == ["q1"]
    assert s.available == []
    assert s.progress.get("q1") == {}


def test_toggle_active_back_to_available_clears_progress():
    s = QuestState(available=["q1"])
    s.toggle_active("q1")
    s.progress["q1"]["count"] = 2
    assert s.toggle_active("q1") == "available"
    assert s.active == []
    assert s.available == ["q1"]
    assert "q1" not in s.progress


def test_toggle_completed_is_noop():
    s = QuestState(completed=["q1"])
    assert s.toggle_active("q1") == "completed"
    assert s.completed == ["q1"]
    assert s.active == []
    assert s.available == []


def test_toggle_unknown_returns_unknown():
    s = QuestState()
    assert s.toggle_active("nonexistent") == "unknown"


def test_complete_moves_active_to_completed():
    s = QuestState(active=["q1"], progress={"q1": {"count": 5}})
    s.complete("q1")
    assert s.active == []
    assert s.completed == ["q1"]
    assert "q1" not in s.progress


def test_complete_is_idempotent():
    """Completing a quest already in completed shouldn't duplicate it."""
    s = QuestState(completed=["q1"])
    s.complete("q1")
    assert s.completed == ["q1"]


# ── tick.tick() — evaluator ──────────────────────────────────────────


class _WorldStub:
    def __init__(self):
        self.quest_state = QuestState()
        self.player = None
        self.entities = []


def test_tick_with_no_active_quests_is_noop():
    completed = []
    world = _WorldStub()
    tick(world, [], lambda q: completed.append(q.id))
    assert completed == []


def test_tick_completes_quest_when_predicate_returns_true():
    world = _WorldStub()
    world.quest_state.active = ["anomaly_hunt_01"]
    world.quest_state.progress["anomaly_hunt_01"] = {}
    completed = []

    events = [{"type": "kind_destroyed", "kind": "clay_pot"}]
    tick(world, events, lambda q: completed.append(q.id))

    assert completed == ["anomaly_hunt_01"]
    assert world.quest_state.active == []
    assert "anomaly_hunt_01" in world.quest_state.completed


def test_tick_does_not_complete_when_predicate_false():
    world = _WorldStub()
    world.quest_state.active = ["anomaly_hunt_01"]
    completed = []

    tick(world, [], lambda q: completed.append(q.id))

    assert completed == []
    assert "anomaly_hunt_01" in world.quest_state.active


def test_tick_skips_unknown_quest_id_without_crashing():
    """A stale id from save migration shouldn't kill the loop."""
    world = _WorldStub()
    world.quest_state.active = ["nonexistent_quest_id"]
    tick(world, [], lambda q: None)


def test_tick_skips_quest_with_unknown_predicate():
    """Defensive — same protection at runtime as the test_quests check."""
    bad = quests.Quest(
        id="bad_quest_test_only",
        name="bad",
        description="",
        predicate="this_predicate_does_not_exist",
    )
    quests.register(bad)
    try:
        world = _WorldStub()
        world.quest_state.active = ["bad_quest_test_only"]
        # Should not raise
        tick(world, [], lambda q: None)
        assert "bad_quest_test_only" in world.quest_state.active  # still active
    finally:
        # Clean up — remove from registry so other tests don't see it
        quests._REGISTRY.pop("bad_quest_test_only", None)


def test_tick_does_not_mutate_static_predicate_args():
    """The predicate may write to `progress`, never to the quest's
    static config. Otherwise a kill on quest A would leak count to B."""
    world = _WorldStub()
    world.quest_state.active = ["anomaly_hunt_01"]
    quest = quests.get("anomaly_hunt_01")
    snapshot = dict(quest.predicate_args)

    events = [{"type": "kind_destroyed", "kind": "clay_pot"}]
    tick(world, events, lambda q: None)

    assert quest.predicate_args == snapshot, \
        "tick must defensively copy static args"


# ── rewards.roll() ───────────────────────────────────────────────────


def test_roll_guaranteed_drop():
    out = rewards.roll([{"name": "pot_shard", "weight": 1.0}])
    assert out == ["pot_shard"]


def test_roll_zero_weight_never_drops():
    """Weight 0 means random.random() > 0 is always True → always skipped."""
    out = rewards.roll([{"name": "never", "weight": 0.0}])
    assert out == []


def test_roll_skips_entries_without_name():
    out = rewards.roll([{"weight": 1.0}, {"name": "", "weight": 1.0}])
    assert out == []


def test_roll_skips_non_dict_entries():
    out = rewards.roll(["legacy_string_form", None, {"name": "real", "weight": 1.0}])
    assert out == ["real"]


def test_roll_preserves_table_order_and_drops_some():
    """Mock random to verify weight semantics deterministically."""
    random.seed(42)
    table = [
        {"name": "always", "weight": 1.0},
        {"name": "never", "weight": 0.0},
        {"name": "sometimes", "weight": 0.5},
    ]
    # Run many times — `always` always present; `never` never present.
    always_count = 0
    never_count = 0
    sometimes_count = 0
    for _ in range(100):
        out = rewards.roll(table)
        if "always" in out:
            always_count += 1
        if "never" in out:
            never_count += 1
        if "sometimes" in out:
            sometimes_count += 1
    assert always_count == 100
    assert never_count == 0
    # 30-70 is a generous band for 50/50 over 100 trials
    assert 30 <= sometimes_count <= 70


# ── End-to-end: tick + state + rewards (sans inventory) ──────────────


def test_kill_clay_pot_completes_anomaly_hunt():
    """The intended player flow: toggle quest active, kill the kind,
    quest completes and rewards roll."""
    world = _WorldStub()
    world.quest_state.available = ["anomaly_hunt_01"]
    assert world.quest_state.toggle_active("anomaly_hunt_01") == "active"

    completion_events = []

    def on_complete(quest):
        rolled = rewards.roll(quest.rewards)
        completion_events.append((quest.id, rolled))

    events = [{"type": "kind_destroyed", "kind": "clay_pot"}]
    tick(world, events, on_complete)

    assert len(completion_events) == 1
    qid, rolled = completion_events[0]
    assert qid == "anomaly_hunt_01"
    # pot_shard is guaranteed (weight 1.0)
    assert "pot_shard" in rolled
    # State migrated correctly
    assert world.quest_state.active == []
    assert world.quest_state.completed == ["anomaly_hunt_01"]
