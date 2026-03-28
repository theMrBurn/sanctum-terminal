import pytest
import json


@pytest.fixture
def profiles():
    return json.load(open('config/ghost_profiles.json'))


@pytest.fixture
def engine():
    from core.systems.ghost_profile_engine import GhostProfileEngine
    return GhostProfileEngine()


class TestGhostProfileConfig:

    def test_has_ten_profiles(self, profiles):
        assert len(profiles) == 10

    def test_each_profile_has_required_keys(self, profiles):
        for name, p in profiles.items():
            for key in ['discipline','rhythm','threshold',
                        'resolution_bias','world_modifiers',
                        'combat_style','fingerprint_weights']:
                assert key in p, f'{name} missing {key}'

    def test_resolution_bias_values_normalized(self, profiles):
        for name, p in profiles.items():
            for path, val in p['resolution_bias'].items():
                assert 0.0 <= val <= 1.0, f'{name}.{path} out of range'

    def test_threshold_is_float(self, profiles):
        for name, p in profiles.items():
            assert isinstance(p['threshold'], float)

    def test_all_have_combat_style(self, profiles):
        for name, p in profiles.items():
            assert p['combat_style'], f'{name} missing combat_style'


class TestGhostProfileEngine:

    def test_boots_without_error(self, engine):
        assert engine is not None

    def test_has_profiles(self, engine):
        assert len(engine.profiles) == 10

    def test_map_interview_returns_blend(self, engine):
        answers = {
            'q1': 'nature', 'q2': 'morning', 'q3': 'few_hours',
            'q4': 'open', 'q5': 'light', 'q6': 'carefully',
            'q7': 'nature', 'q8': 'wanderer', 'q9': 'The Walk',
            'q10': 'open'
        }
        blend = engine.map_interview(answers)
        assert isinstance(blend, dict)
        assert len(blend) > 0
        assert abs(sum(blend.values()) - 1.0) < 0.01

    def test_blend_values_between_zero_and_one(self, engine):
        answers = {'q8': 'seeker'}
        blend = engine.map_interview(answers)
        for k, v in blend.items():
            assert 0.0 <= v <= 1.0

    def test_seeker_archetype_biases_seeker_profile(self, engine):
        blend = engine.map_interview({'q8': 'seeker'})
        assert blend.get('SEEKER', 0) > 0.1

    def test_keeper_archetype_biases_guardian(self, engine):
        blend = engine.map_interview({'q8': 'keeper'})
        assert blend.get('GUARDIAN', 0) > 0.1

    def test_update_from_fingerprint(self, engine):
        fingerprint = {
            'crafting_time': 0.8,
            'observation_time': 0.2,
            'distance_average': 0.1,
            'overwhelm_count': 0.1
        }
        blend = engine.update_from_fingerprint(fingerprint)
        assert isinstance(blend, dict)
        assert abs(sum(blend.values()) - 1.0) < 0.01

    def test_maker_fingerprint_biases_maker(self, engine):
        fingerprint = {
            'crafting_time': 0.95,
            'workbench_interactions': 0.9,
            'crafting_tier': 0.8
        }
        blend = engine.update_from_fingerprint(fingerprint)
        assert blend.get('MAKER', 0) > blend.get('FORCE_MULTIPLIER', 0)

    def test_get_world_modifiers_returns_dict(self, engine):
        blend = {'NATURALIST': 0.7, 'SEEKER': 0.3}
        mods = engine.get_world_modifiers(blend)
        assert isinstance(mods, dict)
        assert len(mods) > 0

    def test_dominant_profile_returns_string(self, engine):
        blend = {'NATURALIST': 0.6, 'SEEKER': 0.3, 'MAKER': 0.1}
        dominant = engine.dominant_profile(blend)
        assert dominant == 'NATURALIST'

    def test_get_combat_style_from_blend(self, engine):
        blend = {'RHYTHM_KEEPER': 0.8, 'SEEKER': 0.2}
        style = engine.get_combat_style(blend)
        assert style == 'PULSE'

    def test_blend_merges_interview_and_fingerprint(self, engine):
        interview_blend = engine.map_interview({'q8': 'builder'})
        fingerprint = {'crafting_time': 0.9, 'workbench_interactions': 0.8}
        fp_blend = engine.update_from_fingerprint(fingerprint)
        merged = engine.merge_blends(interview_blend, fp_blend)
        assert isinstance(merged, dict)
        assert abs(sum(merged.values()) - 1.0) < 0.01