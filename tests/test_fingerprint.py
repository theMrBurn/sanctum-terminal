import pytest


@pytest.fixture
def engine():
    from core.systems.fingerprint_engine import FingerprintEngine
    return FingerprintEngine()


class TestFingerprintEngineInit:

    def test_boots_without_error(self, engine):
        assert engine is not None

    def test_all_dimensions_start_zero(self, engine):
        for k, v in engine.state.items():
            assert v == 0.0, f'{k} should start at 0.0'

    def test_has_required_dimensions(self, engine):
        required = [
            'exploration_time', 'crafting_time', 'observation_time',
            'combat_time', 'audio_interactions', 'workbench_interactions',
            'objects_inspected', 'distance_average', 'overwhelm_count',
            'negotiate_count', 'endure_count', 'retreat_count',
            'food_prepared', 'puzzle_attempts', 'timing_accuracy',
            'rhythm_pattern_score', 'precision_score', 'crafting_tier',
            'creature_interactions', 'unknown_combinations',
        ]
        for dim in required:
            assert dim in engine.state, f'missing dimension: {dim}'


class TestFingerprintRecord:

    def test_record_event_updates_state(self, engine):
        engine.record('overwhelm_count', 1.0)
        assert engine.state['overwhelm_count'] > 0

    def test_record_unknown_event_ignored(self, engine):
        engine.record('nonexistent_dimension', 1.0)
        assert 'nonexistent_dimension' not in engine.state

    def test_record_clamps_to_one(self, engine):
        engine.record('overwhelm_count', 999.0)
        assert engine.state['overwhelm_count'] <= 1.0

    def test_record_accumulates(self, engine):
        engine.record('overwhelm_count', 0.2)
        first = engine.state['overwhelm_count']
        engine.record('overwhelm_count', 0.2)
        # Second record adds to first -- value increases
        assert engine.state['overwhelm_count'] > first

    def test_tick_updates_exploration_time(self, engine):
        engine.tick(dt=10.0, activity='exploring')
        assert engine.state['exploration_time'] > 0

    def test_tick_updates_crafting_time(self, engine):
        engine.tick(dt=10.0, activity='crafting')
        assert engine.state['crafting_time'] > 0

    def test_tick_normalizes_time_dimensions(self, engine):
        for _ in range(100):
            engine.tick(dt=10.0, activity='exploring')
        assert engine.state['exploration_time'] <= 1.0


class TestFingerprintExport:

    def test_export_returns_dict(self, engine):
        assert isinstance(engine.export(), dict)

    def test_export_all_values_normalized(self, engine):
        engine.record('overwhelm_count', 0.5)
        engine.tick(dt=30.0, activity='exploring')
        for k, v in engine.export().items():
            assert 0.0 <= v <= 1.0, f'{k}={v} out of range'

    def test_dominant_activity_returns_string(self, engine):
        engine.tick(dt=100.0, activity='crafting')
        assert engine.dominant_activity() == 'crafting'

    def test_dominant_activity_reflects_most_time(self, engine):
        engine.tick(dt=50.0, activity='crafting')
        engine.tick(dt=10.0, activity='exploring')
        assert engine.dominant_activity() == 'crafting'


class TestFingerprintGhostIntegration:

    def test_heavy_crafting_biases_maker(self, engine):
        from core.systems.ghost_profile_engine import GhostProfileEngine
        gpe = GhostProfileEngine()
        for _ in range(50):
            engine.tick(dt=10.0, activity='crafting')
        engine.record('workbench_interactions', 0.9)
        engine.record('crafting_tier', 0.8)
        blend = gpe.update_from_fingerprint(engine.export())
        assert blend.get('MAKER', 0) > blend.get('FORCE_MULTIPLIER', 0)

    def test_heavy_exploration_biases_seeker(self, engine):
        from core.systems.ghost_profile_engine import GhostProfileEngine
        gpe = GhostProfileEngine()
        for _ in range(50):
            engine.tick(dt=10.0, activity='exploring')
        engine.record('objects_inspected', 0.85)
        engine.record('puzzle_attempts', 0.7)
        blend = gpe.update_from_fingerprint(engine.export())
        assert blend.get('SEEKER', 0) > blend.get('GUARDIAN', 0)