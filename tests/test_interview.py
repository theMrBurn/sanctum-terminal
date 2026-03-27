import pytest
import json


@pytest.fixture
def config():
    return json.load(open("config/manifest.json"))


@pytest.fixture
def engine(config):
    from core.systems.interview import InterviewEngine
    return InterviewEngine(config=config)


class TestInterviewEngineInit:

    def test_boots_without_error(self, engine):
        assert engine is not None

    def test_has_ten_prompts(self, engine):
        assert len(engine.prompts) == 10

    def test_answers_start_empty(self, engine):
        assert engine.answers == {}

    def test_complete_starts_false(self, engine):
        assert engine.complete is False

    def test_torch_always_exists(self, engine):
        assert engine.torch is not None

    def test_depth_score_starts_zero(self, engine):
        assert engine.depth_score == 0

    def test_scales_start_empty(self, engine):
        assert engine.scales == {}


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

    def test_answer_stores_scale(self, engine):
        engine.answer("q1", "city")
        assert "q1" in engine.scales
        assert 0.0 <= engine.scales["q1"] <= 1.0

    def test_open_question_accepts_any_string(self, engine):
        engine.answer("q10", "scattered")
        assert engine.answers["q10"] == "scattered"

    def test_open_question_accepts_none(self, engine):
        engine.answer("q10", None)
        assert engine.answers["q10"] is None


class TestDepthDetection:

    def test_signal_word_is_depth_one(self):
        from core.systems.interview import _detect_commitment_depth
        assert _detect_commitment_depth("torch") == 1

    def test_medium_word_is_depth_two(self):
        from core.systems.interview import _detect_commitment_depth
        assert _detect_commitment_depth("adrift") == 2

    def test_long_word_is_depth_three(self):
        from core.systems.interview import _detect_commitment_depth
        assert _detect_commitment_depth("overwhelmed") == 3

    def test_q10_sets_depth_score(self, engine):
        engine.answer("q10", "overwhelmed")
        assert engine.depth_score == 3

    def test_q10_skip_sets_depth_zero(self, engine):
        engine.skip("q10")
        assert engine.depth_score == 0


class TestTorchEnhancement:

    def test_default_torch_always_generated(self, engine):
        assert engine.torch["id"] == "TORCH_DEFAULT"

    def test_low_depth_generates_dim_torch(self, engine):
        engine.answer("q10", "torch")
        assert "Dim" in engine.torch["name"]

    def test_medium_depth_names_torch(self, engine):
        engine.answer("q10", "adrift")
        assert "Adrift" in engine.torch["name"]

    def test_medium_depth_sets_ability(self, engine):
        engine.answer("q10", "adrift")
        assert engine.torch["ability"] == "Wayfinding"

    def test_high_depth_generates_rare_torch(self, engine):
        engine.answer("q10", "overwhelmed")
        assert engine.torch.get("rare") is True

    def test_high_depth_torch_is_transferable(self, engine):
        engine.answer("q10", "overwhelmed")
        assert engine.torch["transferable"] is True

    def test_high_depth_torch_impact_is_high(self, engine):
        engine.answer("q10", "overwhelmed")
        assert engine.torch["impact"] >= 6


class TestResolve:

    def test_resolve_returns_dict(self, engine):
        assert isinstance(engine.resolve(), dict)

    def test_resolve_has_biome_key(self, engine):
        assert "biome_key" in engine.resolve()

    def test_resolve_has_encounter_density(self, engine):
        assert "encounter_density" in engine.resolve()

    def test_resolve_has_karma_baseline(self, engine):
        assert "karma_baseline" in engine.resolve()

    def test_resolve_has_camera_speed(self, engine):
        assert "camera_speed" in engine.resolve()

    def test_resolve_has_spawn_radius(self, engine):
        assert "spawn_radius" in engine.resolve()

    def test_resolve_has_heat(self, engine):
        assert "heat" in engine.resolve()

    def test_resolve_has_moisture(self, engine):
        assert "moisture" in engine.resolve()

    def test_resolve_has_torch(self, engine):
        assert "torch" in engine.resolve()

    def test_resolve_has_depth_score(self, engine):
        assert "depth_score" in engine.resolve()

    def test_resolve_has_archetype(self, engine):
        assert "archetype" in engine.resolve()

    def test_resolve_has_label(self, engine):
        assert "label" in engine.resolve()

    def test_city_gives_neon_city(self, engine):
        engine.answer("q1", "city")
        assert engine.resolve()["biome_key"] == "NEON_CITY"

    def test_crushing_gives_high_density(self, engine):
        engine.answer("q5", "crushing")
        assert engine.resolve()["encounter_density"] > 0.7

    def test_too_long_gives_high_karma(self, engine):
        engine.answer("q3", "too_long")
        assert engine.resolve()["karma_baseline"] > 0.5

    def test_q10_sets_relic_name(self, engine):
        engine.answer("q10", "adrift")
        assert engine.resolve()["first_relic"]["archetypal_name"] == "adrift"

    def test_q9_sets_label(self, engine):
        engine.answer("q9", "The Long Winter")
        assert engine.resolve()["label"] == "The Long Winter"

    def test_seeker_archetype(self, engine):
        engine.answer("q8", "seeker")
        assert engine.resolve()["archetype"] == "SEEKER"

    def test_q10_none_sets_unnamed(self, engine):
        engine.answer("q10", None)
        assert engine.resolve()["first_relic"]["archetypal_name"] == "unnamed"


class TestComplete:

    def test_complete_after_all_answers(self, engine):
        for qid, ans in [
            ("q1","city"),("q2","evening"),("q3","too_long"),
            ("q4","enclosed"),("q5","heavy"),("q6","quickly"),
            ("q7","people"),("q8","seeker"),("q9","The Search"),
            ("q10","pressure")
        ]:
            engine.answer(qid, ans)
        assert engine.complete is True

    def test_complete_fires_callback(self, engine):
        events = []
        engine.on_complete = lambda r: events.append(r)
        for qid, ans in [
            ("q1","city"),("q2","evening"),("q3","too_long"),
            ("q4","enclosed"),("q5","heavy"),("q6","quickly"),
            ("q7","people"),("q8","seeker"),("q9","The Search"),
            ("q10","pressure")
        ]:
            engine.answer(qid, ans)
        assert len(events) == 1
        assert "torch" in events[0]
