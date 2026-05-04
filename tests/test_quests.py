"""Quest scaffolding — registry, predicates, definitions.

Per `project_async_quest_refactor` PR 1. Brain wiring (tick, manifest,
journal cmd) lands in PR 1.5; this suite validates the data substrate
in isolation.
"""
from __future__ import annotations

import pytest

from core.systems import quests
from core.systems.quests import Quest
from core.systems.quests import predicates


# ── Registry ──────────────────────────────────────────────────────


def test_anomaly_hunt_registered():
    """The legacy clay_pot mission migrates to anomaly_hunt_01."""
    q = quests.get("anomaly_hunt_01")
    assert q is not None
    assert q.predicate == "destroy_kind"
    assert q.predicate_args["kind"] == "clay_pot"


def test_cast_trial_registered():
    q = quests.get("cast_trial_01")
    assert q is not None
    assert q.predicate == "cast_at_kind"
    assert set(q.predicate_args["elements"]) == {"fire", "ice", "electric", "light"}


def test_all_quests_returns_snapshot():
    snapshot = quests.all_quests()
    assert "anomaly_hunt_01" in snapshot
    assert "cast_trial_01" in snapshot
    # Mutating the snapshot doesn't affect the registry.
    snapshot.clear()
    assert quests.get("anomaly_hunt_01") is not None


def test_quest_is_immutable():
    """Quest is a frozen dataclass — no accidental mutation of catalog entries."""
    q = quests.get("anomaly_hunt_01")
    with pytest.raises(Exception):  # FrozenInstanceError
        q.name = "Changed"


def test_register_rejects_duplicate_id():
    """Registering the same id twice is a doctrine violation — fail loudly."""
    duplicate = Quest(
        id="anomaly_hunt_01",
        name="dupe",
        description="dupe",
        predicate="destroy_kind",
        predicate_args={"kind": "x"},
    )
    with pytest.raises(ValueError, match="already registered"):
        quests.register(duplicate)


def test_quest_predicate_references_resolve():
    """Every registered quest references a real predicate."""
    for qid, q in quests.all_quests().items():
        assert predicates.get(q.predicate) is not None, \
            f"quest {qid!r} references unknown predicate {q.predicate!r}"


# ── Predicate: destroy_kind ────────────────────────────────────────


def _world_stub():
    """Predicates only need attribute access on `world`; tests can stub it."""
    class _W:
        player = None
        entities = []
    return _W()


def test_destroy_kind_returns_false_with_no_events():
    fn = predicates.get("destroy_kind")
    progress: dict = {}
    assert fn(_world_stub(), {"kind": "clay_pot", "count": 1}, progress, []) is False
    assert progress["count"] == 0


def test_destroy_kind_completes_on_matching_event():
    fn = predicates.get("destroy_kind")
    progress: dict = {}
    events = [{"type": "kind_destroyed", "kind": "clay_pot"}]
    assert fn(_world_stub(), {"kind": "clay_pot", "count": 1}, progress, events) is True
    assert progress["count"] == 1


def test_destroy_kind_ignores_other_kinds():
    fn = predicates.get("destroy_kind")
    progress: dict = {}
    events = [{"type": "kind_destroyed", "kind": "rat"}]
    assert fn(_world_stub(), {"kind": "clay_pot", "count": 1}, progress, events) is False
    assert progress["count"] == 0


def test_destroy_kind_accumulates_progress_across_ticks():
    """Progress carries between predicate calls — kill 3 over 3 ticks completes."""
    fn = predicates.get("destroy_kind")
    progress: dict = {}
    args = {"kind": "clay_pot", "count": 3}
    # Tick 1 — one kill
    assert fn(_world_stub(), args, progress, [{"type": "kind_destroyed", "kind": "clay_pot"}]) is False
    # Tick 2 — one more, total 2
    assert fn(_world_stub(), args, progress, [{"type": "kind_destroyed", "kind": "clay_pot"}]) is False
    assert progress["count"] == 2
    # Tick 3 — third kill completes
    assert fn(_world_stub(), args, progress, [{"type": "kind_destroyed", "kind": "clay_pot"}]) is True
    assert progress["count"] == 3


def test_destroy_kind_handles_multiple_events_in_one_tick():
    fn = predicates.get("destroy_kind")
    progress: dict = {}
    events = [
        {"type": "kind_destroyed", "kind": "clay_pot"},
        {"type": "kind_destroyed", "kind": "clay_pot"},
        {"type": "kind_destroyed", "kind": "clay_pot"},
    ]
    assert fn(_world_stub(), {"kind": "clay_pot", "count": 3}, progress, events) is True
    assert progress["count"] == 3


def test_destroy_kind_rejects_empty_kind():
    """Defensive — a malformed quest config shouldn't accidentally complete."""
    fn = predicates.get("destroy_kind")
    progress: dict = {}
    assert fn(_world_stub(), {"kind": "", "count": 1}, progress, []) is False


# ── Predicate: cast_at_kind ────────────────────────────────────────


def test_cast_at_kind_returns_false_until_all_elements_seen():
    fn = predicates.get("cast_at_kind")
    progress: dict = {}
    args = {"kind": "mega_column", "elements": ["fire", "ice"]}
    # Just fire so far
    e1 = [{"type": "cast_landed", "kind": "mega_column", "element": "fire"}]
    assert fn(_world_stub(), args, progress, e1) is False
    # Adding ice completes
    e2 = [{"type": "cast_landed", "kind": "mega_column", "element": "ice"}]
    assert fn(_world_stub(), args, progress, e2) is True


def test_cast_at_kind_set_semantics():
    """Casting the same element twice doesn't double-count or block completion."""
    fn = predicates.get("cast_at_kind")
    progress: dict = {}
    args = {"kind": "mega_column", "elements": ["fire", "ice"]}
    events = [
        {"type": "cast_landed", "kind": "mega_column", "element": "fire"},
        {"type": "cast_landed", "kind": "mega_column", "element": "fire"},
        {"type": "cast_landed", "kind": "mega_column", "element": "ice"},
    ]
    assert fn(_world_stub(), args, progress, events) is True


def test_cast_at_kind_ignores_wrong_kind():
    fn = predicates.get("cast_at_kind")
    progress: dict = {}
    args = {"kind": "mega_column", "elements": ["fire"]}
    events = [{"type": "cast_landed", "kind": "rat", "element": "fire"}]
    assert fn(_world_stub(), args, progress, events) is False


def test_cast_at_kind_rejects_empty_required_set():
    fn = predicates.get("cast_at_kind")
    progress: dict = {}
    args = {"kind": "mega_column", "elements": []}
    assert fn(_world_stub(), args, progress, []) is False


# ── Predicate registry ─────────────────────────────────────────────


def test_predicate_registry_includes_built_ins():
    registered = predicates.all_predicates()
    assert "destroy_kind" in registered
    assert "cast_at_kind" in registered


def test_predicate_register_rejects_duplicate():
    @predicates.register("test_unique_predicate_42")
    def _fn(world, args, progress, events):
        return False

    with pytest.raises(ValueError, match="already registered"):
        @predicates.register("test_unique_predicate_42")
        def _fn2(world, args, progress, events):
            return False
