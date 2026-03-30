"""
tests/test_encounter_engine.py

EncounterEngine -- resonance-gated encounter resolution.
Dragon Quest style, no battle screen.
Avatar acts from discipline automatically.
Only resonant encounters teach. Silence is load-bearing.

THINK / ACT / MOVE / DEFEND / TOOLS

XP stages at resolution, consolidates at rest/name day/milestone.
Level = age (declared, immutable). Depth = what that level means.
"""
import pytest


@pytest.fixture
def fingerprint():
    from core.systems.fingerprint_engine import FingerprintEngine
    fp = FingerprintEngine()
    # Philosopher Monk baseline -- precision dominant
    # Multiple records to build past resonance threshold (0.45)
    for _ in range(5):
        fp.record("precision_score",    0.9)
        fp.record("observation_time",   0.8)
    fp.record("crafting_time",      0.5)
    fp.record("negotiate_count",    0.4)
    fp.record("creature_interactions", 0.2)
    return fp


@pytest.fixture
def ghost_blend():
    """PRECISION_HAND dominant, SEEKER secondary."""
    return {
        "PRECISION_HAND": 0.217,
        "SEEKER":         0.181,
        "RHYTHM_KEEPER":  0.120,
    }


@pytest.fixture
def engine(fingerprint, ghost_blend):
    from core.systems.encounter_engine import EncounterEngine
    return EncounterEngine(
        fingerprint  = fingerprint,
        ghost_blend  = ghost_blend,
        age          = 45,
    )


# -- Import + boot -------------------------------------------------------------

class TestEncounterEngineInit:

    def test_importable(self):
        from core.systems.encounter_engine import EncounterEngine
        assert EncounterEngine is not None

    def test_verbs_defined(self):
        from core.systems.encounter_engine import VERBS
        assert set(VERBS) == {"THINK", "ACT", "MOVE", "DEFEND", "TOOLS"}

    def test_boots_with_fingerprint_and_ghost(self, engine):
        assert engine is not None

    def test_age_stored(self, engine):
        assert engine.age == 45

    def test_starts_with_no_staged_xp(self, engine):
        assert engine.staged_xp == 0.0

    def test_starts_with_no_active_encounter(self, engine):
        assert engine.active_encounter is None


# -- Resonance -----------------------------------------------------------------

class TestResonance:

    def test_resonance_returns_float(self, engine):
        r = engine.resonance(["precision_score", "observation_time"])
        assert isinstance(r, float)

    def test_resonance_zero_for_no_overlap(self, engine):
        r = engine.resonance(["combat_time", "overwhelm_count"])
        assert r == pytest.approx(0.0, abs=0.05)

    def test_resonance_high_for_dominant_dims(self, engine):
        r = engine.resonance(["precision_score", "observation_time"])
        assert r > 0.15  # sigmoid compression means single record() lands ~0.22

    def test_resonance_empty_tags_returns_zero(self, engine):
        assert engine.resonance([]) == 0.0

    def test_resonance_unknown_tags_ignored(self, engine):
        r = engine.resonance(["nonexistent_dim", "also_fake"])
        assert r == 0.0

    def test_resonance_pure_function_no_side_effects(self, engine):
        before = engine.staged_xp
        engine.resonance(["precision_score"])
        assert engine.staged_xp == before


# -- Begin encounter -----------------------------------------------------------

class TestBeginEncounter:

    def test_begin_returns_worth_knowing_bool(self, engine):
        result = engine.begin({
            "id":   "flint_shard_01",
            "tags": ["precision_score", "observation_time"],
            "type": "object",
        })
        assert isinstance(result, bool)

    def test_resonant_encounter_worth_knowing(self, engine):
        worth = engine.begin({
            "id":   "flint_shard_01",
            "tags": ["precision_score", "observation_time"],
            "type": "object",
        })
        assert worth is True

    def test_non_resonant_encounter_not_worth_knowing(self, engine):
        worth = engine.begin({
            "id":   "mud_01",
            "tags": ["combat_time", "overwhelm_count"],
            "type": "object",
        })
        assert worth is False

    def test_begin_sets_active_encounter(self, engine):
        engine.begin({
            "id": "flint_shard_01", "tags": ["precision_score"], "type": "object"
        })
        assert engine.active_encounter is not None

    def test_begin_stores_worth_knowing(self, engine):
        engine.begin({
            "id": "flint_shard_01", "tags": ["precision_score"], "type": "object"
        })
        assert engine.active_encounter["worth_knowing"] is True


# -- Verb selection ------------------------------------------------------------

class TestVerbSelection:

    def test_available_verbs_returns_list(self, engine):
        engine.begin({
            "id": "flint_shard_01", "tags": ["precision_score"], "type": "object"
        })
        verbs = engine.available_verbs()
        assert isinstance(verbs, list)
        assert len(verbs) > 0

    def test_think_always_available(self, engine):
        engine.begin({
            "id": "flint_shard_01", "tags": ["precision_score"], "type": "object"
        })
        assert "THINK" in engine.available_verbs()

    def test_dominant_verb_matches_ghost_profile(self, engine):
        """PRECISION_HAND dominant -> ACT and THINK weighted highest."""
        engine.begin({
            "id": "flint_shard_01", "tags": ["precision_score"], "type": "object"
        })
        dominant = engine.dominant_verb()
        assert dominant in {"ACT", "THINK"}

    def test_choose_valid_verb(self, engine):
        engine.begin({
            "id": "flint_shard_01", "tags": ["precision_score"], "type": "object"
        })
        result = engine.choose("ACT")
        assert result is not None

    def test_choose_invalid_verb_raises(self, engine):
        engine.begin({
            "id": "flint_shard_01", "tags": ["precision_score"], "type": "object"
        })
        with pytest.raises(ValueError):
            engine.choose("PUNCH")


# -- Resolve -------------------------------------------------------------------

class TestResolve:

    def test_resolve_returns_dict(self, engine):
        engine.begin({
            "id": "flint_shard_01", "tags": ["precision_score"], "type": "object"
        })
        result = engine.resolve()
        assert isinstance(result, dict)

    def test_resolve_has_required_keys(self, engine):
        engine.begin({
            "id": "flint_shard_01", "tags": ["precision_score"], "type": "object"
        })
        result = engine.resolve()
        assert "outcome" in result
        assert "xp_staged" in result
        assert "worth_knowing" in result
        assert "verb_used" in result

    def test_resonant_resolve_stages_xp(self, engine):
        engine.begin({
            "id": "flint_shard_01", "tags": ["precision_score"], "type": "object"
        })
        engine.resolve()
        assert engine.staged_xp > 0.0

    def test_non_resonant_resolve_stages_no_xp(self, engine):
        engine.begin({
            "id": "mud_01", "tags": ["combat_time", "overwhelm_count"], "type": "object"
        })
        before = engine.staged_xp
        engine.resolve()
        assert engine.staged_xp == before

    def test_resolve_clears_active_encounter(self, engine):
        engine.begin({
            "id": "flint_shard_01", "tags": ["precision_score"], "type": "object"
        })
        engine.resolve()
        assert engine.active_encounter is None

    def test_resolve_records_to_fingerprint(self, engine):
        before = engine.fingerprint.state["precision_score"]
        engine.begin({
            "id": "flint_shard_01", "tags": ["precision_score"], "type": "object"
        })
        engine.resolve()
        after = engine.fingerprint.state["precision_score"]
        assert after >= before


# -- XP + consolidation --------------------------------------------------------

class TestXPConsolidation:

    def test_stage_xp_accumulates(self, engine):
        engine.stage_xp(1.0)
        engine.stage_xp(0.5)
        assert engine.staged_xp == pytest.approx(1.5)

    def test_consolidate_returns_report(self, engine):
        engine.stage_xp(5.0)
        report = engine.consolidate()
        assert isinstance(report, dict)
        assert "xp_consumed" in report
        assert "depth_shift" in report
        assert "abilities_checked" in report

    def test_consolidate_clears_staged_xp(self, engine):
        engine.stage_xp(5.0)
        engine.consolidate()
        assert engine.staged_xp == 0.0

    def test_consolidate_zero_xp_returns_empty_report(self, engine):
        report = engine.consolidate()
        assert report["xp_consumed"] == 0.0
        assert report["depth_shift"] == pytest.approx(0.0)

    def test_depth_increases_after_consolidation(self, engine):
        before = engine.depth
        engine.stage_xp(10.0)
        engine.consolidate()
        assert engine.depth > before

    def test_level_unchanged_after_consolidation(self, engine):
        """Level is age. Immutable. Consolidation deepens it, never changes it."""
        engine.stage_xp(100.0)
        engine.consolidate()
        assert engine.age == 45

    def test_ability_slots_never_exceed_three(self, engine):
        """Frieren model -- 3 abilities max: CORE + EQUIPPED + FLOW."""
        for _ in range(20):
            engine.stage_xp(50.0)
            engine.consolidate()
        assert len(engine.abilities) <= 3


# -- Integration ---------------------------------------------------------------

class TestEncounterIntegration:

    def test_full_encounter_cycle(self, engine):
        """Begin -> choose -> resolve -> stage -> consolidate."""
        engine.begin({
            "id":   "flint_shard_01",
            "tags": ["precision_score", "observation_time"],
            "type": "object",
        })
        engine.choose("THINK")
        result = engine.resolve()

        assert result["worth_knowing"] is True
        assert engine.staged_xp > 0.0

        report = engine.consolidate()
        assert report["xp_consumed"] > 0.0
        assert engine.staged_xp == 0.0

    def test_non_resonant_encounter_leaves_no_trace(self, engine):
        """The world moves on. Nothing added. Silence."""
        engine.begin({
            "id":   "mud_patch_01",
            "tags": ["combat_time", "overwhelm_count"],
            "type": "environment",
        })
        result = engine.resolve()

        assert result["worth_knowing"] is False
        assert result["xp_staged"] == 0.0
        assert engine.staged_xp == 0.0

    def test_multiple_resonant_encounters_compound(self, engine):
        """Repeated resonant encounters deepen the same dimensions."""
        for i in range(3):
            engine.begin({
                "id":   f"flint_{i}",
                "tags": ["precision_score"],
                "type": "object",
            })
            engine.resolve()

        assert engine.staged_xp > 0.0
        report = engine.consolidate()
        assert report["depth_shift"] > 0.0

    def test_name_day_consolidation(self, engine):
        """Name day: full consolidation cycle, depth recorded."""
        engine.stage_xp(45.0)   # one per year of life, poetic
        report = engine.consolidate(reason="name_day")
        assert report["reason"] == "name_day"
        assert report["xp_consumed"] == pytest.approx(45.0)
