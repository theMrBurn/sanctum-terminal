"""Brain `_quest_bearings` helper + manifest surface (PR 4 step 4c).

Validates the bearing computation for active quests reaches the
manifest's quests block as a `{qid: "NE"}` map.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.systems.quests import Quest, register, register_dynamic
from core.systems.quests import predicates as _quest_predicates
from core.systems.quests.state import QuestState


@dataclass
class _FakeWorld:
    entities: list = field(default_factory=list)
    quest_state: QuestState = field(default_factory=QuestState)


def _import_helper():
    """Import the brain helper. Requires venv with spacy."""
    import importlib
    bs = importlib.import_module("brain_server")
    return bs._quest_bearings


# ── Helper output ─────────────────────────────────────────────────


def test_no_active_quests_yields_empty_map():
    fn = _import_helper()
    world = _FakeWorld()
    out = fn(world, 0.0, 0.0)
    assert out == {}


def test_active_quest_with_resolver_and_target_emits_bearing():
    """destroy_kind active quest + matching entity in world →
    bearing string in the map."""
    fn = _import_helper()

    # Use the production quests anomaly_hunt_01 (destroy_kind/clay_pot).
    qid = "anomaly_hunt_01"
    world = _FakeWorld(entities=[
        {"kind": "clay_pot", "x": 10.0, "y": 0.0},  # due east
    ])
    world.quest_state = QuestState(active=[qid])

    out = fn(world, 0.0, 0.0)
    assert out == {qid: "E"}


def test_active_quest_without_resolver_absent_from_map():
    """journal_followup quests have no target resolver. They're active
    but don't appear in the bearings map; vector terminal renders the
    name without a `[XX]` prefix."""
    fn = _import_helper()

    journal_quest = Quest(
        id="test_journal_followup",
        name="Test followup",
        description="…",
        predicate="journal_followup",
        predicate_args={"term": "test"},
    )
    register_dynamic(journal_quest)

    world = _FakeWorld()
    world.quest_state = QuestState(active=["test_journal_followup"])

    out = fn(world, 0.0, 0.0)
    assert "test_journal_followup" not in out


def test_no_target_in_world_absent_from_map():
    """destroy_kind quest active but no clay_pots in world →
    quest absent from bearings map (resolver returned None)."""
    fn = _import_helper()
    world = _FakeWorld(entities=[])  # no clay_pots
    world.quest_state = QuestState(active=["anomaly_hunt_01"])

    out = fn(world, 0.0, 0.0)
    assert "anomaly_hunt_01" not in out


def test_unknown_quest_id_skipped():
    fn = _import_helper()
    world = _FakeWorld()
    world.quest_state = QuestState(active=["does_not_exist"])

    out = fn(world, 0.0, 0.0)
    assert out == {}


def test_player_position_drives_bearing():
    """Same world entity, different player positions → different
    bearings."""
    fn = _import_helper()
    qid = "anomaly_hunt_01"

    world = _FakeWorld(entities=[
        {"kind": "clay_pot", "x": 0.0, "y": 10.0},  # at (0, 10)
    ])
    world.quest_state = QuestState(active=[qid])

    # Player south of target → N
    out = fn(world, 0.0, 0.0)
    assert out == {qid: "N"}

    # Player east of target → W
    out = fn(world, 10.0, 10.0)
    assert out == {qid: "W"}


# ── Manifest surface integration ──────────────────────────────────


def test_manifest_quests_block_has_bearings_key():
    """Static check: brain_server.py's manifest builder includes
    `"bearings": bearings_map` in the quests dict literal."""
    src = (Path(__file__).resolve().parents[1] / "brain_server.py").read_text()
    assert '"bearings": bearings_map' in src
    # And the bearings_map variable comes from the helper.
    assert "bearings_map = _quest_bearings(" in src


def test_brain_imports_bearing_module():
    """Helper imports core.systems.bearing — confirms wiring is real,
    not just a stub."""
    src = (Path(__file__).resolve().parents[1] / "brain_server.py").read_text()
    assert "from core.systems.bearing import bearing" in src
