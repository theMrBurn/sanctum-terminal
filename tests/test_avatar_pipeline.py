"""
tests/test_avatar_pipeline.py

AvatarPipeline -- wires Interview → GhostProfile → Fingerprint → EncounterEngine.

The pipeline is the single construction point for a Monk's encounter identity.
Interview answers seed the ghost blend. Fingerprint updates it over time.
EncounterEngine consumes the blend for verb selection and resonance gating.
"""
import pytest


# -- Fixtures ------------------------------------------------------------------

@pytest.fixture
def interview_answers():
    """Philosopher Monk answers -- precision dominant, seeker secondary."""
    return {
        "q1": "home",       # GUARDIAN + MAKER + PRECISION_HAND
        "q5": "heavy",      # GUARDIAN + ENDURANCE_BODY + PRECISION_HAND
        "q6": "deliberately",  # PRECISION_HAND + GUARDIAN + NATURALIST
        "q8": "seeker",     # SEEKER + NATURALIST + PRECISION_HAND
    }


@pytest.fixture
def pipeline(interview_answers):
    from core.systems.avatar_pipeline import AvatarPipeline
    return AvatarPipeline(answers=interview_answers, age=45, seed="BURN")


# -- Import + boot -------------------------------------------------------------

class TestAvatarPipelineInit:

    def test_importable(self):
        from core.systems.avatar_pipeline import AvatarPipeline
        assert AvatarPipeline is not None

    def test_boots_with_answers_and_age(self, pipeline):
        assert pipeline is not None

    def test_has_fingerprint(self, pipeline):
        assert pipeline.fingerprint is not None

    def test_has_ghost_profile_engine(self, pipeline):
        assert pipeline.ghost is not None

    def test_has_encounter_engine(self, pipeline):
        assert pipeline.encounter is not None

    def test_age_flows_through(self, pipeline):
        assert pipeline.encounter.age == 45

    def test_ghost_blend_is_normalized(self, pipeline):
        blend = pipeline.ghost_blend
        total = sum(blend.values())
        assert total == pytest.approx(1.0, abs=0.01)


# -- Ghost blend from interview ------------------------------------------------

class TestGhostBlendFromInterview:

    def test_blend_has_profiles(self, pipeline):
        blend = pipeline.ghost_blend
        assert len(blend) > 0

    def test_precision_hand_weighted_for_philosopher(self, pipeline):
        """Philosopher Monk answers should weight PRECISION_HAND heavily."""
        blend = pipeline.ghost_blend
        assert "PRECISION_HAND" in blend
        assert blend["PRECISION_HAND"] > 0.1

    def test_blend_feeds_encounter_engine(self, pipeline):
        """EncounterEngine receives the ghost blend."""
        assert pipeline.encounter.ghost_blend is pipeline.ghost_blend

    def test_dominant_verb_reflects_profile(self, pipeline):
        """PRECISION_HAND dominant -> THINK or ACT weighted."""
        verb = pipeline.encounter.dominant_verb()
        assert verb in {"THINK", "ACT"}


# -- Fingerprint update flow ---------------------------------------------------

class TestFingerprintUpdate:

    def test_fingerprint_shared_with_encounter_engine(self, pipeline):
        """Same object reference -- encounter engine sees fingerprint changes."""
        assert pipeline.fingerprint is pipeline.encounter.fingerprint

    def test_record_updates_fingerprint(self, pipeline):
        before = pipeline.fingerprint.state["precision_score"]
        pipeline.fingerprint.record("precision_score", 0.5)
        assert pipeline.fingerprint.state["precision_score"] > before

    def test_refresh_blend_updates_ghost_blend(self, pipeline):
        """After behavioral data, refresh_blend merges interview + fingerprint."""
        pipeline.fingerprint.record("precision_score", 0.9)
        pipeline.fingerprint.record("observation_time", 0.8)
        old_blend = dict(pipeline.ghost_blend)
        pipeline.refresh_blend()
        new_blend = pipeline.ghost_blend
        # Blend should shift (fingerprint has 0.6 weight by default)
        assert new_blend != old_blend

    def test_refresh_blend_updates_encounter_engine(self, pipeline):
        """After refresh, encounter engine has the new blend."""
        pipeline.fingerprint.record("combat_time", 0.9)
        pipeline.refresh_blend()
        assert pipeline.encounter.ghost_blend is pipeline.ghost_blend


# -- Verb affinity coverage ----------------------------------------------------

class TestVerbAffinityCoverage:
    """All 10 ghost profiles must map to encounter verbs."""

    ALL_PROFILES = [
        "ENDURANCE_BODY", "PRECISION_HAND", "GUARDIAN",
        "FORCE_MULTIPLIER", "RHYTHM_KEEPER", "SYSTEMS_THINKER",
        "NATURALIST", "PERFORMER", "MAKER", "SEEKER",
    ]

    def test_all_ghost_profiles_have_verb_affinity(self):
        from core.systems.encounter_engine import _PROFILE_VERB_AFFINITY
        for profile in self.ALL_PROFILES:
            assert profile in _PROFILE_VERB_AFFINITY, (
                f"{profile} missing from _PROFILE_VERB_AFFINITY"
            )

    def test_each_affinity_sums_to_one(self):
        from core.systems.encounter_engine import _PROFILE_VERB_AFFINITY
        for profile, weights in _PROFILE_VERB_AFFINITY.items():
            total = sum(weights.values())
            assert total == pytest.approx(1.0, abs=0.01), (
                f"{profile} verb weights sum to {total}, not 1.0"
            )

    def test_each_affinity_covers_all_verbs(self):
        from core.systems.encounter_engine import _PROFILE_VERB_AFFINITY, VERBS
        for profile, weights in _PROFILE_VERB_AFFINITY.items():
            assert set(weights.keys()) == VERBS, (
                f"{profile} missing verbs: {VERBS - set(weights.keys())}"
            )

    def test_dominant_verb_with_single_profile_blend(self):
        """Each profile, when dominant, produces a sane verb."""
        from core.systems.encounter_engine import EncounterEngine, VERBS
        from core.systems.fingerprint_engine import FingerprintEngine
        fp = FingerprintEngine()
        for profile in self.ALL_PROFILES:
            blend = {profile: 1.0}
            eng = EncounterEngine(fingerprint=fp, ghost_blend=blend, age=30)
            verb = eng.dominant_verb()
            assert verb in VERBS, f"{profile} dominant_verb returned {verb}"


# -- Full pipeline integration -------------------------------------------------

class TestPipelineIntegration:

    def test_interview_to_encounter_resolution(self, pipeline):
        """Full cycle: pipeline boots -> encounter -> resolve."""
        worth = pipeline.encounter.begin({
            "id": "flint_shard_01",
            "tags": ["precision_score", "observation_time"],
            "type": "object",
        })
        # Philosopher Monk has precision_score + observation_time at 0
        # (pipeline starts fresh fingerprint), so this won't resonate yet
        # That's correct -- fingerprint needs behavioral data first
        result = pipeline.encounter.resolve()
        assert "outcome" in result

    def test_pipeline_with_primed_fingerprint(self, pipeline):
        """After behavioral data, encounters resonate."""
        # Prime the fingerprint with behavior
        pipeline.fingerprint.record("precision_score", 0.8)
        pipeline.fingerprint.record("observation_time", 0.7)
        pipeline.refresh_blend()

        worth = pipeline.encounter.begin({
            "id": "flint_shard_01",
            "tags": ["precision_score", "observation_time"],
            "type": "object",
        })
        assert worth is True

        pipeline.encounter.choose("THINK")
        result = pipeline.encounter.resolve()
        assert result["worth_knowing"] is True
        assert result["xp_staged"] > 0.0

    def test_consolidation_after_pipeline_encounters(self, pipeline):
        """Consolidation works through the pipeline."""
        pipeline.fingerprint.record("precision_score", 0.8)

        pipeline.encounter.begin({
            "id": "flint_01", "tags": ["precision_score"], "type": "object",
        })
        pipeline.encounter.resolve()

        report = pipeline.encounter.consolidate(reason="rest")
        assert report["reason"] == "rest"

    def test_boots_without_answers(self):
        """Pipeline can boot with empty answers (all defaults)."""
        from core.systems.avatar_pipeline import AvatarPipeline
        p = AvatarPipeline(answers={}, age=20)
        assert p.encounter is not None
        assert p.ghost_blend is not None
