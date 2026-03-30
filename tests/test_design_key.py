"""
tests/test_design_key.py

Design key -- computed vector that drives procedural generation.

Derived from ghost blend + fingerprint, not configured.
The engine watches behavior and projects it into generator-space.
"""
import pytest


@pytest.fixture
def pipeline():
    from core.systems.avatar_pipeline import AvatarPipeline
    return AvatarPipeline(
        answers={"q1": "home", "q5": "heavy", "q6": "deliberately", "q8": "seeker"},
        age=30, seed="TEST",
    )


# -- Design key exists ---------------------------------------------------------

class TestDesignKeyContract:

    def test_pipeline_has_design_key(self, pipeline):
        key = pipeline.design_key()
        assert isinstance(key, dict)

    def test_key_has_archetype_weights(self, pipeline):
        key = pipeline.design_key()
        assert "archetype_weights" in key
        for arch in ("survival", "mystic", "garden", "souls", "learning"):
            assert arch in key["archetype_weights"]

    def test_archetype_weights_sum_to_one(self, pipeline):
        key = pipeline.design_key()
        total = sum(key["archetype_weights"].values())
        assert total == pytest.approx(1.0, abs=0.01)

    def test_key_has_verb_emphasis(self, pipeline):
        key = pipeline.design_key()
        assert "verb_emphasis" in key
        for verb in ("THINK", "ACT", "MOVE", "DEFEND", "TOOLS", "CRAFT", "OBSERVE"):
            assert verb in key["verb_emphasis"]

    def test_verb_emphasis_sums_to_one(self, pipeline):
        key = pipeline.design_key()
        total = sum(key["verb_emphasis"].values())
        assert total == pytest.approx(1.0, abs=0.01)

    def test_key_has_resonance_bias(self, pipeline):
        pipeline.fingerprint.record("precision_score", 0.5)
        key = pipeline.design_key()
        assert "resonance_bias" in key
        assert isinstance(key["resonance_bias"], list)
        assert len(key["resonance_bias"]) > 0

    def test_key_has_pressure_curve(self, pipeline):
        key = pipeline.design_key()
        assert "pressure_curve" in key


# -- Design key shifts with behavior ------------------------------------------

class TestDesignKeyShifts:

    def test_exploration_shifts_archetype(self, pipeline):
        key_before = pipeline.design_key()
        # Simulate heavy exploration
        for _ in range(10):
            pipeline.fingerprint.record("exploration_time", 0.9)
            pipeline.fingerprint.record("objects_inspected", 0.7)
        pipeline.refresh_blend()
        key_after = pipeline.design_key()
        # Mystic weight should increase (exploration = discovery)
        assert key_after["archetype_weights"]["mystic"] >= key_before["archetype_weights"]["mystic"]

    def test_crafting_shifts_verb_emphasis(self, pipeline):
        for _ in range(10):
            pipeline.fingerprint.record("crafting_time", 0.9)
            pipeline.fingerprint.record("precision_score", 0.8)
        pipeline.refresh_blend()
        key = pipeline.design_key()
        # Crafting behavior should emphasize TOOLS/THINK
        assert key["verb_emphasis"]["TOOLS"] > 0.1 or key["verb_emphasis"]["THINK"] > 0.2

    def test_combat_shifts_pressure(self, pipeline):
        for _ in range(10):
            pipeline.fingerprint.record("combat_time", 0.9)
            pipeline.fingerprint.record("overwhelm_count", 0.5)
        pipeline.refresh_blend()
        key = pipeline.design_key()
        assert key["pressure_curve"] in ("adaptive", "spike", "steady")

    def test_resonance_bias_reflects_dominant_dims(self, pipeline):
        for _ in range(10):
            pipeline.fingerprint.record("observation_time", 0.9)
        pipeline.refresh_blend()
        key = pipeline.design_key()
        assert "observation_time" in key["resonance_bias"]
