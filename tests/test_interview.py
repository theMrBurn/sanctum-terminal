import pytest
import json
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def config():
    return json.load(open("config/manifest.json"))


@pytest.fixture
def engine(config):
    from core.systems.interview import InterviewEngine
    return InterviewEngine(config=config)


# ── Init ──────────────────────────────────────────────────────────────────────

class TestInterviewEngineInit:

    def test_boots_without_error(self, engine):
        assert engine is not None

    def test_has_prompts(self, engine):
        assert len(engine.prompts) > 0

    def test_has_seven_prompts(self, engine):
        assert len(engine.prompts) == 7

    def test_answers_start_empty(self, engine):
        assert engine.answers == {}

    def test_complete_starts_false(self, engine):
        assert engine.complete is False


# ── Answer ────────────────────────────────────────────────────────────────────

class TestAnswer:

    def test_answer_stores_response(self, engine):
        engine.answer("q1", "city")
        assert engine.answers["q1"] == "city"

    def test_answer_invalid_prompt_raises(self, engine):
        with pytest.raises(ValueError):
            engine.answer("q99", "city")

    def test_answer_invalid_option_raises(self, engine):
        with pytest.raises(ValueError):
            engine.answer("q1", "underwater")

    def test_open_question_accepts_any_string(self, engine):
        engine.answer("q7", "scattered")
        assert engine.answers["q7"] == "scattered"

    def test_open_question_accepts_none(self, engine):
        engine.answer("q7", None)
        assert engine.answers["q7"] is None

    def test_multiple_answers_stored(self, engine):
        engine.answer("q1", "city")
        engine.answer("q2", "evening")
        assert len(engine.answers) == 2


# ── Resolve ───────────────────────────────────────────────────────────────────

class TestResolve:

    def test_resolve_returns_dict(self, engine):
        result = engine.resolve()
        assert isinstance(result, dict)

    def test_resolve_has_biome_key(self, engine):
        result = engine.resolve()
        assert "biome_key" in result

    def test_resolve_has_encounter_density(self, engine):
        result = engine.resolve()
        assert "encounter_density" in result

    def test_resolve_has_karma_baseline(self, engine):
        result = engine.resolve()
        assert "karma_baseline" in result

    def test_resolve_has_camera_speed(self, engine):
        result = engine.resolve()
        assert "camera_speed" in result

    def test_resolve_has_spawn_radius(self, engine):
        result = engine.resolve()
        assert "spawn_radius" in result

    def test_resolve_has_first_relic(self, engine):
        result = engine.resolve()
        assert "first_relic" in result

    def test_resolve_city_answer_gives_neon_city(self, engine):
        engine.answer("q1", "city")
        result = engine.resolve()
        assert result["biome_key"] == "NEON_CITY"

    def test_resolve_crushing_gives_high_density(self, engine):
        engine.answer("q5", "crushing")
        result = engine.resolve()
        assert result["encounter_density"] == 0.9

    def test_resolve_too_long_gives_high_karma(self, engine):
        engine.answer("q3", "too_long")
        result = engine.resolve()
        assert result["karma_baseline"] == 0.7

    def test_resolve_uses_defaults_for_missing(self, engine):
        result = engine.resolve()
        assert result["biome_key"] is not None

    def test_resolve_q7_sets_first_relic_name(self, engine):
        engine.answer("q7", "adrift")
        result = engine.resolve()
        assert result["first_relic"]["archetypal_name"] == "adrift"

    def test_resolve_q7_none_sets_default_relic(self, engine):
        engine.answer("q7", None)
        result = engine.resolve()
        assert result["first_relic"]["archetypal_name"] == "unnamed"


# ── Complete ──────────────────────────────────────────────────────────────────

class TestComplete:

    def test_complete_after_all_answers(self, engine):
        for qid, answer in [
            ("q1", "city"), ("q2", "evening"), ("q3", "too_long"),
            ("q4", "enclosed"), ("q5", "heavy"), ("q6", "quickly"),
            ("q7", "pressure")
        ]:
            engine.answer(qid, answer)
        assert engine.complete is True

    def test_not_complete_with_partial_answers(self, engine):
        engine.answer("q1", "city")
        engine.answer("q2", "evening")
        assert engine.complete is False

    def test_complete_fires_grace_event(self, engine):
        events = []
        engine.on_complete = lambda r: events.append(r)
        for qid, answer in [
            ("q1", "city"), ("q2", "evening"), ("q3", "too_long"),
            ("q4", "enclosed"), ("q5", "heavy"), ("q6", "quickly"),
            ("q7", "pressure")
        ]:
            engine.answer(qid, answer)
        assert len(events) == 1
