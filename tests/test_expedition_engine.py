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
