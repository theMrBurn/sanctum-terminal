"""Tests for the expedition engine.

The engine is the runtime for the third stamp-like primitive in the
system — after kinds and stamps, expeditions. Tests are organized
roughly in commit order so each slice lands green independently:

  commit 2  — schema validation + symbol resolution + construction
  commit 3  — lifecycle + tag events
  commit 4  — milestones + satisfaction
  commit 5  — walk-through + log writer
  commit 6  — snapshot for manifest

See plan-before-code for the full spec. See expedition_data.py for
the first recipe (ANOMALY_HUNT) and the cavern binding used as the
happy-path fixture throughout.
"""

from __future__ import annotations

import copy

import pytest

from core.systems.expedition_engine import (
    ExpeditionEngine,
    ExpeditionState,
    ClassNotBiomeAgnostic,
    ClassNotInBiome,
    MissingAnchorBinding,
    UnknownExpeditionClass,
    UnknownBiome,
)
from core.systems.expedition_data import (
    EXPEDITION_CLASSES,
    BIOME_EXPEDITIONS,
    ANOMALY_HUNT,
    CAST_TRIAL,
    CAVERN_BINDING,
)


# -- fixtures -----------------------------------------------------------------


@pytest.fixture
def anomaly_hunt_class() -> dict:
    """Fresh deep copy of ANOMALY_HUNT — tests mutate safely."""
    return copy.deepcopy(ANOMALY_HUNT)


@pytest.fixture
def cavern_binding() -> dict:
    return copy.deepcopy(CAVERN_BINDING)


@pytest.fixture
def synthetic_binding() -> dict:
    """A minimal binding that registers anomaly_hunt with different
    anchors so tests can verify same-class-different-biome behavior
    without reaching for the real outdoor binding."""
    return {
        "anchors": {
            "axis_mundi": {"kind": "great_tree", "pos": [5.0, 5.0]},
            "exit_arch":  {"kind": "log_arch",   "pos": [5.0, -10.0]},
        },
        "active_classes": ["anomaly_hunt"],
        "message_overrides": {
            "anomaly_hunt": {
                "first_tag": "The canopy notices.",
            },
        },
    }


@pytest.fixture
def engine(anomaly_hunt_class, cavern_binding) -> ExpeditionEngine:
    return ExpeditionEngine(
        class_def=anomaly_hunt_class,
        biome="cavern",
        binding=cavern_binding,
    )


# -- commit 2 — schema, construction, resolution -----------------------------


class TestClassIsBiomeAgnostic:
    """Test 0a — ANOMALY_HUNT class declares no biome-specific state."""

    def test_anomaly_hunt_class_has_no_forbidden_keys(
        self, anomaly_hunt_class, cavern_binding,
    ):
        # Constructing the engine runs the full walk; no exception = pass.
        ExpeditionEngine(
            class_def=anomaly_hunt_class,
            biome="cavern",
            binding=cavern_binding,
        )

    def test_forbidden_pos_key_raises(self, cavern_binding):
        bad = copy.deepcopy(ANOMALY_HUNT)
        bad["deposit_points"][0]["pos"] = [0.0, 0.0]
        with pytest.raises(ClassNotBiomeAgnostic) as exc:
            ExpeditionEngine(
                class_def=bad, biome="cavern", binding=cavern_binding)
        assert "pos" in str(exc.value)

    def test_forbidden_kind_key_raises(self, cavern_binding):
        bad = copy.deepcopy(ANOMALY_HUNT)
        bad["deposit_points"][0]["kind"] = "mega_column"
        with pytest.raises(ClassNotBiomeAgnostic) as exc:
            ExpeditionEngine(
                class_def=bad, biome="cavern", binding=cavern_binding)
        assert "kind" in str(exc.value)

    def test_forbidden_select_at_key_raises(self, cavern_binding):
        bad = copy.deepcopy(ANOMALY_HUNT)
        bad["deposit_points"][0]["select_at"] = [0.0, 0.0]
        with pytest.raises(ClassNotBiomeAgnostic) as exc:
            ExpeditionEngine(
                class_def=bad, biome="cavern", binding=cavern_binding)
        assert "select_at" in str(exc.value)


class TestEngineResolvesAnchors:
    """Test 0b — after construction, deposit_points[0] has kind+pos."""

    def test_cavern_axis_mundi_resolves_to_mega_column(self, engine):
        assert len(engine.deposit_points) == 1
        dp = engine.deposit_points[0]
        assert dp.id == "axis_mundi"
        assert dp.kind == "mega_column"
        assert dp.pos == (0.0, 0.0, 0.0)

    def test_cavern_exit_arch_resolves_to_doorframe(self, engine):
        assert engine.exit_point is not None
        assert engine.exit_point.id == "exit_arch"
        assert engine.exit_point.kind == "doorframe"
        assert engine.exit_point.pos == (0.0, -14.0, 0.0)

    def test_resolved_deposit_carries_threshold_and_accepts(self, engine):
        dp = engine.deposit_points[0]
        assert dp.threshold == 3
        assert dp.accepts == ["any"]
        assert dp.visual.get("emission_boost") == 2.0
        assert dp.visual.get("pipe_lock") == "warm"


class TestMissingAnchorRaises:
    """Test 0c — binding without required anchor fails at construction."""

    def test_missing_axis_mundi_raises(self, anomaly_hunt_class):
        bad_binding = {
            "anchors": {
                # axis_mundi deliberately missing
                "exit_arch": {"kind": "doorframe", "pos": [0.0, -14.0]},
            },
            "active_classes": ["anomaly_hunt"],
            "message_overrides": {},
        }
        with pytest.raises(MissingAnchorBinding) as exc:
            ExpeditionEngine(
                class_def=anomaly_hunt_class,
                biome="cavern",
                binding=bad_binding)
        assert "axis_mundi" in str(exc.value)

    def test_missing_exit_arch_raises(self, anomaly_hunt_class):
        bad_binding = {
            "anchors": {
                "axis_mundi": {"kind": "mega_column", "pos": [0.0, 0.0]},
                # exit_arch deliberately missing
            },
            "active_classes": ["anomaly_hunt"],
            "message_overrides": {},
        }
        with pytest.raises(MissingAnchorBinding) as exc:
            ExpeditionEngine(
                class_def=anomaly_hunt_class,
                biome="cavern",
                binding=bad_binding)
        assert "exit_arch" in str(exc.value)

    def test_empty_outdoor_binding_cannot_host_anomaly_hunt(
        self, anomaly_hunt_class,
    ):
        # The real outdoor binding in expedition_data has no anchors
        # declared yet. Instantiating against it should fail loudly,
        # not silently produce a half-resolved engine.
        outdoor = BIOME_EXPEDITIONS["outdoor"]
        with pytest.raises(MissingAnchorBinding):
            ExpeditionEngine(
                class_def=anomaly_hunt_class,
                biome="outdoor",
                binding=outdoor)


class TestMessageMerge:
    """Tests 0d and 0e — class defaults + biome overrides flatten correctly."""

    def test_class_default_used_when_no_override(self, engine):
        # "halfway" is a class-level default; cavern binding does not
        # override it, so the class default should be in resolved_messages.
        assert engine.resolved_messages["halfway"] == "Halfway. Keep marking."

    def test_biome_override_replaces_class_default(self, engine):
        # "first_tag" is overridden by the cavern binding.
        assert engine.resolved_messages["first_tag"] == "The column listens."

    def test_all_class_keys_present_after_merge(self, engine):
        for key in ["spawn", "first_tag", "halfway", "satisfied", "complete"]:
            assert key in engine.resolved_messages


class TestSameClassDifferentBiome:
    """Test 0f — same recipe, different binding, different runtime state."""

    def test_different_biomes_produce_different_kinds_and_positions(
        self, anomaly_hunt_class, cavern_binding, synthetic_binding,
    ):
        cavern_engine = ExpeditionEngine(
            class_def=anomaly_hunt_class,
            biome="cavern",
            binding=cavern_binding)
        synthetic_engine = ExpeditionEngine(
            class_def=anomaly_hunt_class,
            biome="synthetic",
            binding=synthetic_binding)

        # Same class ID, different resolved kind + pos.
        assert cavern_engine.class_id == synthetic_engine.class_id
        assert cavern_engine.deposit_points[0].kind == "mega_column"
        assert synthetic_engine.deposit_points[0].kind == "great_tree"
        assert cavern_engine.deposit_points[0].pos == (0.0, 0.0, 0.0)
        assert synthetic_engine.deposit_points[0].pos == (5.0, 5.0, 0.0)

    def test_different_biomes_produce_different_messages(
        self, anomaly_hunt_class, cavern_binding, synthetic_binding,
    ):
        cavern_engine = ExpeditionEngine(
            class_def=anomaly_hunt_class,
            biome="cavern",
            binding=cavern_binding)
        synthetic_engine = ExpeditionEngine(
            class_def=anomaly_hunt_class,
            biome="synthetic",
            binding=synthetic_binding)

        assert cavern_engine.resolved_messages["first_tag"] == \
            "The column listens."
        assert synthetic_engine.resolved_messages["first_tag"] == \
            "The canopy notices."
        # Unoverridden messages still match across biomes
        assert cavern_engine.resolved_messages["halfway"] == \
            synthetic_engine.resolved_messages["halfway"]


class TestClassActiveInBiome:
    """A class not listed in a biome's active_classes must fail construction."""

    def test_inactive_class_raises(self, anomaly_hunt_class):
        bad_binding = {
            "anchors": {
                "axis_mundi": {"kind": "mega_column", "pos": [0.0, 0.0]},
                "exit_arch":  {"kind": "doorframe",   "pos": [0.0, -14.0]},
            },
            "active_classes": [],  # empty — nothing runs here
            "message_overrides": {},
        }
        with pytest.raises(ClassNotInBiome):
            ExpeditionEngine(
                class_def=anomaly_hunt_class,
                biome="cavern",
                binding=bad_binding)


# -- engine state + lookup ----------------------------------------------------


class TestEngineStartsDormant:
    """Test 1 — fresh engine is in DORMANT state."""

    def test_state_is_dormant_after_construction(self, engine):
        assert engine.state == ExpeditionState.DORMANT

    def test_no_messages_emitted_after_construction(self, engine):
        assert engine.pending_message_key is None
        assert engine.messages_emitted == []

    def test_tag_log_is_empty(self, engine):
        assert engine.tag_log == []

    def test_deposits_are_zero(self, engine):
        assert engine.deposit_points[0].current == 0
        assert engine.deposit_points[0].satisfied is False

    def test_exit_point_is_inactive(self, engine):
        assert engine.exit_point is not None
        assert engine.exit_point.active is False


class TestFromClassIdLookup:
    """Test 22 — from_class_id / unknown class / unknown biome."""

    def test_from_class_id_anomaly_hunt_cavern(self):
        engine = ExpeditionEngine.from_class_id("anomaly_hunt", "cavern")
        assert engine.class_id == "anomaly_hunt"
        assert engine.biome == "cavern"
        assert engine.deposit_points[0].kind == "mega_column"

    def test_unknown_class_id_raises(self):
        with pytest.raises(UnknownExpeditionClass):
            ExpeditionEngine.from_class_id("nope_not_a_class", "cavern")

    def test_unknown_biome_raises(self):
        with pytest.raises(UnknownBiome):
            ExpeditionEngine.from_class_id("anomaly_hunt", "nope_not_a_biome")


# -- commit 3 — lifecycle + tag events ---------------------------------------


def _make_tag(tag_id: int, reason: str = "neutral", **extra) -> dict:
    """Build a tag sidecar payload shaped like _save_tag produces."""
    tag = {
        "tag_id": tag_id,
        "tag_reason": reason,
        "camera": {"x": 1.0, "y": 2.0, "z": 2.5, "heading": 0.0, "pitch": 0.0},
        "crosshair": [{"kind": "buttress", "x": 12.5, "y": -3.0}],
    }
    tag.update(extra)
    return tag


class TestSessionStart:
    """Test 3 — on_session_start transitions DORMANT → ACTIVE."""

    def test_session_start_activates(self, engine):
        engine.on_session_start(t=100.0)
        assert engine.state == ExpeditionState.ACTIVE
        assert engine.started_at == 100.0

    def test_session_start_is_idempotent(self, engine):
        engine.on_session_start(t=100.0)
        engine.on_session_start(t=999.0)  # should be ignored
        assert engine.started_at == 100.0

    def test_spawn_message_queued_after_start(self, engine):
        engine.on_session_start(t=100.0)
        assert engine.pending_message_key == "spawn"
        assert "spawn" in engine.messages_emitted


class TestTagEventLogging:
    """Test 6 — on_tag_event appends to tag_log."""

    def test_tag_event_appended_to_log(self, engine):
        engine.on_session_start(t=0.0)
        tag = _make_tag(1, "weird")
        engine.on_tag_event(tag, t=1.0)
        assert len(engine.tag_log) == 1
        assert engine.tag_log[0]["tag_id"] == 1
        assert engine.tag_log[0]["tag_reason"] == "weird"

    def test_multiple_tags_preserve_order(self, engine):
        engine.on_session_start(t=0.0)
        for i in range(3):
            engine.on_tag_event(_make_tag(i + 1, "neutral"), t=float(i))
        assert [t["tag_id"] for t in engine.tag_log] == [1, 2, 3]

    def test_tag_event_before_start_is_dropped(self, engine):
        engine.on_tag_event(_make_tag(1), t=0.0)
        assert engine.tag_log == []

    def test_tag_log_stores_deep_copy(self, engine):
        engine.on_session_start(t=0.0)
        tag = _make_tag(1)
        engine.on_tag_event(tag, t=1.0)
        tag["tag_id"] = 999  # mutate caller's copy
        assert engine.tag_log[0]["tag_id"] == 1  # log unaffected


class TestDepositIntent:
    """Tests 7-9 — deposit_intent accept/reject paths."""

    def test_deposit_intent_increments_current(self, engine):
        engine.on_session_start(t=0.0)
        engine.on_tag_event(_make_tag(1, "weird"), t=1.0)
        result = engine.on_deposit_intent("axis_mundi", 1, t=2.0)
        assert result["accepted"] is True
        assert engine.deposit_points[0].current == 1

    def test_deposit_intent_idempotent_on_same_tag(self, engine):
        engine.on_session_start(t=0.0)
        engine.on_tag_event(_make_tag(1, "weird"), t=1.0)
        engine.on_deposit_intent("axis_mundi", 1, t=2.0)
        result = engine.on_deposit_intent("axis_mundi", 1, t=3.0)
        assert result["accepted"] is False
        assert result["reason"] == "already_deposited"
        assert engine.deposit_points[0].current == 1

    def test_deposit_intent_unknown_deposit_id(self, engine):
        engine.on_session_start(t=0.0)
        engine.on_tag_event(_make_tag(1), t=1.0)
        result = engine.on_deposit_intent("nonexistent", 1, t=2.0)
        assert result["accepted"] is False
        assert result["reason"] == "unknown_deposit"

    def test_deposit_intent_tag_not_in_log(self, engine):
        engine.on_session_start(t=0.0)
        # No tag_event fired; tag_id 42 has no log entry
        result = engine.on_deposit_intent("axis_mundi", 42, t=2.0)
        assert result["accepted"] is False
        assert result["reason"] == "tag_not_in_log"

    def test_deposit_intent_rejected_by_accepts_filter(
        self, anomaly_hunt_class, cavern_binding,
    ):
        # Set accepts to something specific to test rejection
        anomaly_hunt_class["deposit_points"][0]["accepts"] = ["weird"]
        engine = ExpeditionEngine(
            class_def=anomaly_hunt_class,
            biome="cavern",
            binding=cavern_binding)
        engine.on_session_start(t=0.0)
        engine.on_tag_event(_make_tag(1, "beautiful"), t=1.0)
        result = engine.on_deposit_intent("axis_mundi", 1, t=2.0)
        assert result["accepted"] is False
        assert result["reason"] == "rejected_by_accepts"
        assert engine.deposit_points[0].current == 0

    def test_deposit_intent_accepts_matching_reason(
        self, anomaly_hunt_class, cavern_binding,
    ):
        anomaly_hunt_class["deposit_points"][0]["accepts"] = ["weird"]
        engine = ExpeditionEngine(
            class_def=anomaly_hunt_class,
            biome="cavern",
            binding=cavern_binding)
        engine.on_session_start(t=0.0)
        engine.on_tag_event(_make_tag(1, "weird"), t=1.0)
        result = engine.on_deposit_intent("axis_mundi", 1, t=2.0)
        assert result["accepted"] is True

    def test_any_accepts_takes_all_reasons(self, engine):
        engine.on_session_start(t=0.0)
        for i, reason in enumerate(
            ["neutral", "weird", "dangerous", "beautiful", "interesting"],
            start=1,
        ):
            engine.on_tag_event(_make_tag(i, reason), t=float(i))
            # default threshold is 3; cap the first 3
            result = engine.on_deposit_intent("axis_mundi", i, t=float(i + 10))
            if i <= 3:
                assert result["accepted"] is True, \
                    f"tag {i} ({reason}) should have been accepted"


# -- commit 4 — milestones + satisfaction ------------------------------------


def _deposit_n_tags(engine, n: int) -> None:
    """Helper: run session start and deposit n tags at axis_mundi."""
    engine.on_session_start(t=0.0)
    # Clear the spawn message so milestone tests don't collide with it
    engine.messages_emitted.clear()
    engine.pending_message_key = None
    for i in range(1, n + 1):
        engine.on_tag_event(_make_tag(i, "neutral"), t=float(i))
        engine.on_deposit_intent("axis_mundi", i, t=float(i + 10))


class TestMilestones:
    """Tests 10-11 — first_tag and halfway emit at the right moments."""

    def test_first_tag_emits_on_first_accepted_deposit(self, engine):
        engine.on_session_start(t=0.0)
        # The spawn message was queued by session_start; clear it for
        # this assertion so we're only observing first_tag emission.
        engine.messages_emitted.clear()
        engine.pending_message_key = None
        engine.on_tag_event(_make_tag(1, "neutral"), t=1.0)
        engine.on_deposit_intent("axis_mundi", 1, t=2.0)
        assert "first_tag" in engine.messages_emitted

    def test_first_tag_only_emits_once(self, engine):
        _deposit_n_tags(engine, 2)
        # messages_emitted will contain first_tag + (halfway or satisfied)
        first_tag_count = engine.messages_emitted.count("first_tag")
        assert first_tag_count == 1

    def test_halfway_emits_at_fifty_percent(self, engine):
        # threshold=3, so halfway should emit after deposit 2 (66%)
        _deposit_n_tags(engine, 2)
        assert "halfway" in engine.messages_emitted

    def test_halfway_does_not_emit_before_fifty_percent(self, engine):
        _deposit_n_tags(engine, 1)
        # 1/3 = 33%, below halfway
        assert "halfway" not in engine.messages_emitted


class TestSatisfactionAndExitActivation:
    """Tests 12-14 — threshold satisfies, all-satisfied activates exit."""

    def test_threshold_satisfies_deposit(self, engine):
        _deposit_n_tags(engine, 3)
        dp = engine.deposit_points[0]
        assert dp.current == 3
        assert dp.satisfied is True

    def test_current_capped_at_threshold(self, engine):
        # Deposit more tags than threshold — current should cap
        engine.on_session_start(t=0.0)
        for i in range(1, 5):  # 4 tags; threshold is 3
            engine.on_tag_event(_make_tag(i, "neutral"), t=float(i))
            engine.on_deposit_intent("axis_mundi", i, t=float(i + 10))
        dp = engine.deposit_points[0]
        assert dp.current == 3, \
            f"current should cap at threshold; got {dp.current}"
        assert dp.satisfied is True

    def test_satisfied_message_emits(self, engine):
        _deposit_n_tags(engine, 3)
        assert "satisfied" in engine.messages_emitted

    def test_all_deposits_satisfied_activates_exit(self, engine):
        _deposit_n_tags(engine, 3)
        assert engine.exit_point is not None
        assert engine.exit_point.active is True

    def test_all_deposits_satisfied_transitions_to_resolution(self, engine):
        _deposit_n_tags(engine, 3)
        assert engine.state == ExpeditionState.RESOLUTION

    def test_partial_deposit_does_not_activate_exit(self, engine):
        _deposit_n_tags(engine, 2)
        assert engine.exit_point is not None
        assert engine.exit_point.active is False
        assert engine.state == ExpeditionState.ACTIVE

    def test_satisfied_does_not_reactivate_exit_on_further_deposits(
        self, engine,
    ):
        # Same tag can't deposit twice; but verify the state machine
        # doesn't double-fire satisfied message on subsequent calls.
        _deposit_n_tags(engine, 3)
        satisfied_count_before = engine.messages_emitted.count("satisfied")

        # Try another deposit (should be rejected — already satisfied)
        engine.on_tag_event(_make_tag(99, "weird"), t=100.0)
        result = engine.on_deposit_intent("axis_mundi", 99, t=101.0)
        assert result["accepted"] is False
        # No new satisfied message
        assert engine.messages_emitted.count("satisfied") == satisfied_count_before


# -- commit 5 — walk-through + log writer ------------------------------------


class TestWalkThrough:
    """Tests 15-16 — walk-through completes the expedition."""

    def test_walk_through_when_inactive_is_noop(self, engine, tmp_path):
        engine.on_session_start(t=0.0)
        # Exit hasn't activated yet
        result = engine.on_walk_through(t=1.0, sessions_dir=tmp_path)
        assert result["resolution"] == "exit_inactive"
        assert result["quit_godot"] is False
        assert engine.state == ExpeditionState.ACTIVE

    def test_walk_through_completes_expedition(self, engine, tmp_path):
        _deposit_n_tags(engine, 3)
        assert engine.state == ExpeditionState.RESOLUTION
        result = engine.on_walk_through(t=200.0, sessions_dir=tmp_path)
        assert result["resolution"] == "complete"
        assert result["quit_godot"] is True
        assert engine.state == ExpeditionState.COMPLETE

    def test_complete_message_emits_on_walk_through(self, engine, tmp_path):
        _deposit_n_tags(engine, 3)
        engine.on_walk_through(t=200.0, sessions_dir=tmp_path)
        assert "complete" in engine.messages_emitted

    def test_walk_through_sets_completed_at(self, engine, tmp_path):
        _deposit_n_tags(engine, 3)
        engine.on_walk_through(t=200.0, sessions_dir=tmp_path)
        assert engine.completed_at == 200.0


class TestSessionLog:
    """Tests 17-19 — session log shape and content."""

    def test_session_log_written_on_complete(self, engine, tmp_path):
        _deposit_n_tags(engine, 3)
        result = engine.on_walk_through(t=200.0, sessions_dir=tmp_path)
        log_path = result["log_path"]
        assert log_path is not None
        from pathlib import Path
        assert Path(log_path).exists()

    def test_session_log_contains_full_tag_history(self, engine, tmp_path):
        _deposit_n_tags(engine, 3)
        result = engine.on_walk_through(t=200.0, sessions_dir=tmp_path)
        from pathlib import Path
        import json as _json
        payload = _json.loads(Path(result["log_path"]).read_text())
        assert len(payload["tag_log"]) == 3
        assert [t["tag_id"] for t in payload["tag_log"]] == [1, 2, 3]

    def test_session_log_records_metadata(self, engine, tmp_path):
        _deposit_n_tags(engine, 3)
        result = engine.on_walk_through(t=200.0, sessions_dir=tmp_path)
        from pathlib import Path
        import json as _json
        payload = _json.loads(Path(result["log_path"]).read_text())
        assert payload["class_id"] == "anomaly_hunt"
        assert payload["biome"] == "cavern"
        assert payload["final_state"] == "complete"
        # 1 deposit point, satisfied
        assert len(payload["deposit_points"]) == 1
        dp = payload["deposit_points"][0]
        assert dp["id"] == "axis_mundi"
        assert dp["kind"] == "mega_column"
        assert dp["satisfied"] is True
        assert dp["deposited_tag_ids"] == [1, 2, 3]

    def test_session_log_captures_message_trail(self, engine, tmp_path):
        _deposit_n_tags(engine, 3)
        result = engine.on_walk_through(t=200.0, sessions_dir=tmp_path)
        from pathlib import Path
        import json as _json
        payload = _json.loads(Path(result["log_path"]).read_text())
        # messages_emitted was cleared by _deposit_n_tags to isolate
        # milestone testing, so we only see first_tag + satisfied +
        # complete (not spawn).
        assert "first_tag" in payload["messages_emitted"]
        assert "satisfied" in payload["messages_emitted"]
        assert "complete" in payload["messages_emitted"]

    def test_session_log_records_duration(self, engine, tmp_path):
        engine.on_session_start(t=100.0)
        engine.messages_emitted.clear()
        engine.pending_message_key = None
        for i in range(1, 4):
            engine.on_tag_event(_make_tag(i, "neutral"), t=float(i + 100))
            engine.on_deposit_intent("axis_mundi", i, t=float(i + 110))
        result = engine.on_walk_through(t=500.0, sessions_dir=tmp_path)
        from pathlib import Path
        import json as _json
        payload = _json.loads(Path(result["log_path"]).read_text())
        assert payload["started_at"] == 100.0
        assert payload["completed_at"] == 500.0
        assert payload["duration_s"] == 400.0


# -- commit 6 — snapshot for manifest ----------------------------------------


class TestSnapshotShape:
    """Test 20 — snapshot has all keys Godot needs to render generically."""

    REQUIRED_TOP_KEYS = frozenset([
        "id", "biome", "state", "objective_text",
        "deposit_points", "exit_point",
        "last_message", "last_message_text",
    ])

    REQUIRED_DEPOSIT_KEYS = frozenset([
        "id", "kind", "pos", "current", "threshold", "satisfied", "visual",
    ])

    REQUIRED_EXIT_KEYS = frozenset([
        "id", "kind", "pos", "active", "trigger_radius", "visual",
    ])

    def test_snapshot_top_level_keys(self, engine):
        snap = engine.snapshot()
        assert self.REQUIRED_TOP_KEYS.issubset(snap.keys())

    def test_snapshot_deposit_point_keys(self, engine):
        snap = engine.snapshot()
        assert len(snap["deposit_points"]) == 1
        dp = snap["deposit_points"][0]
        assert self.REQUIRED_DEPOSIT_KEYS.issubset(dp.keys())

    def test_snapshot_exit_point_keys(self, engine):
        snap = engine.snapshot()
        assert snap["exit_point"] is not None
        assert self.REQUIRED_EXIT_KEYS.issubset(snap["exit_point"].keys())

    def test_snapshot_identity_fields(self, engine):
        snap = engine.snapshot()
        assert snap["id"] == "anomaly_hunt"
        assert snap["biome"] == "cavern"
        assert snap["state"] == "dormant"

    def test_snapshot_carries_resolved_positions(self, engine):
        snap = engine.snapshot()
        assert snap["deposit_points"][0]["kind"] == "mega_column"
        assert snap["deposit_points"][0]["pos"] == [0.0, 0.0, 0.0]
        assert snap["exit_point"]["kind"] == "doorframe"
        assert snap["exit_point"]["pos"] == [0.0, -14.0, 0.0]

    def test_snapshot_reflects_state_transitions(self, engine, tmp_path):
        assert engine.snapshot()["state"] == "dormant"
        engine.on_session_start(t=0.0)
        assert engine.snapshot()["state"] == "active"
        for i in range(1, 4):
            engine.on_tag_event(_make_tag(i), t=float(i))
            engine.on_deposit_intent("axis_mundi", i, t=float(i + 10))
        assert engine.snapshot()["state"] == "resolution"
        assert engine.snapshot()["exit_point"]["active"] is True
        engine.on_walk_through(t=100.0, sessions_dir=tmp_path)
        assert engine.snapshot()["state"] == "complete"

    def test_snapshot_deposit_progress_visible(self, engine):
        engine.on_session_start(t=0.0)
        engine.on_tag_event(_make_tag(1, "neutral"), t=1.0)
        engine.on_deposit_intent("axis_mundi", 1, t=2.0)
        dp = engine.snapshot()["deposit_points"][0]
        assert dp["current"] == 1
        assert dp["threshold"] == 3
        assert dp["satisfied"] is False


class TestSnapshotMessages:
    """Test 21 — snapshot includes pending message; consume clears it."""

    def test_pending_message_in_snapshot_after_start(self, engine):
        engine.on_session_start(t=0.0)
        snap = engine.snapshot()
        assert snap["last_message"] == "spawn"
        assert snap["last_message_text"] == \
            "Something's off here. Mark what doesn't belong."

    def test_biome_override_text_in_snapshot(self, engine):
        engine.on_session_start(t=0.0)
        # Manually clear the spawn message to test first_tag
        engine.pending_message_key = None
        engine.on_tag_event(_make_tag(1, "neutral"), t=1.0)
        engine.on_deposit_intent("axis_mundi", 1, t=2.0)
        snap = engine.snapshot()
        assert snap["last_message"] == "first_tag"
        assert snap["last_message_text"] == "The column listens."

    def test_consume_message_clears_pending(self, engine):
        engine.on_session_start(t=0.0)
        assert engine.snapshot()["last_message"] == "spawn"
        engine.consume_message()
        snap = engine.snapshot()
        assert snap["last_message"] == ""
        assert snap["last_message_text"] == ""

    def test_snapshot_is_pure_read(self, engine):
        """Calling snapshot() multiple times should not mutate state."""
        engine.on_session_start(t=0.0)
        snap1 = engine.snapshot()
        snap2 = engine.snapshot()
        snap3 = engine.snapshot()
        assert snap1 == snap2 == snap3


# -- CAST_TRIAL — element-gated deposits ------------------------------------


def _make_cast(tag_id: int, element: str, **extra) -> dict:
    """Build a cast event payload."""
    cast = {
        "tag_id": tag_id,
        "element": element,
        "delivery": "straight",
        "camera": {"x": 1.0, "y": 2.0, "z": 2.5},
        "crosshair": [{"kind": "buttress", "x": 12.5, "y": -3.0}],
    }
    cast.update(extra)
    return cast


@pytest.fixture
def cast_engine(cavern_binding) -> ExpeditionEngine:
    return ExpeditionEngine(
        class_def=copy.deepcopy(CAST_TRIAL),
        biome="cavern",
        binding=cavern_binding,
    )


class TestCastTrialRecipe:
    """CAST_TRIAL loads and resolves against cavern binding."""

    def test_cast_trial_loads(self, cast_engine):
        assert cast_engine.class_id == "cast_trial"
        assert cast_engine.deposit_points[0].kind == "mega_column"

    def test_cast_trial_accepts_elements(self, cast_engine):
        assert cast_engine.deposit_points[0].accepts == [
            "fire", "ice", "electric", "light"]

    def test_from_class_id_cast_trial(self):
        engine = ExpeditionEngine.from_class_id("cast_trial", "cavern")
        assert engine.class_id == "cast_trial"

    def test_input_verb_field(self, cast_engine):
        assert cast_engine.class_def.get("input_verb") == "cast"


class TestCastElementMatching:
    """Cast events match deposits by element, not tag_reason."""

    def test_fire_cast_accepted_by_element_filter(self, cast_engine):
        cast_engine.on_session_start(t=0.0)
        cast_engine.on_tag_event(_make_cast(1, "fire"), t=1.0)
        result = cast_engine.on_deposit_intent("axis_mundi", 1, t=2.0)
        assert result["accepted"] is True

    def test_ice_cast_accepted(self, cast_engine):
        cast_engine.on_session_start(t=0.0)
        cast_engine.on_tag_event(_make_cast(1, "ice"), t=1.0)
        result = cast_engine.on_deposit_intent("axis_mundi", 1, t=2.0)
        assert result["accepted"] is True

    def test_wrong_element_rejected(self, cast_engine):
        cast_engine.on_session_start(t=0.0)
        cast_engine.on_tag_event(_make_cast(1, "water"), t=1.0)
        result = cast_engine.on_deposit_intent("axis_mundi", 1, t=2.0)
        assert result["accepted"] is False
        assert result["reason"] == "rejected_by_accepts"

    def test_tag_reason_fallback_rejected_by_element_filter(self, cast_engine):
        """A plain tag event with tag_reason but no element should be
        rejected by a deposit that accepts elements."""
        cast_engine.on_session_start(t=0.0)
        plain_tag = _make_tag(1, "neutral")  # has tag_reason, no element
        cast_engine.on_tag_event(plain_tag, t=1.0)
        result = cast_engine.on_deposit_intent("axis_mundi", 1, t=2.0)
        assert result["accepted"] is False

    def test_cast_deposits_satisfy_threshold(self, cast_engine, tmp_path):
        cast_engine.on_session_start(t=0.0)
        for i, elem in enumerate(["fire", "ice", "electric"], start=1):
            cast_engine.on_tag_event(_make_cast(i, elem), t=float(i))
            cast_engine.on_deposit_intent("axis_mundi", i, t=float(i + 10))
        assert cast_engine.deposit_points[0].satisfied is True
        assert cast_engine.exit_point.active is True
        assert cast_engine.state == ExpeditionState.RESOLUTION
