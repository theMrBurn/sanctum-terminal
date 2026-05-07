import pytest
import time


@pytest.fixture
def engine():
    from core.systems.atmosphere_engine import AtmosphereEngine
    return AtmosphereEngine()


class TestAtmosphereEngineInit:

    def test_boots_without_error(self, engine):
        assert engine is not None

    def test_has_required_state_keys(self, engine):
        for key in [
            'clarity_radius', 'entropy_jitter', 'dither_depth',
            'specular_bleed', 'moisture', 'heat', 'friction',
            'time_of_day', 'encounter_density', 'karma',
        ]:
            assert key in engine.state, f'missing: {key}'

    def test_all_values_normalized(self, engine):
        for k, v in engine.state.items():
            assert 0.0 <= v <= 1.0, f'{k}={v} out of range'

    def test_clarity_radius_starts_high(self, engine):
        assert engine.state['clarity_radius'] >= 0.8


class TestAtmosphereSet:

    def test_set_updates_state(self, engine):
        engine.set('moisture', 0.9)
        assert engine.state['moisture'] == pytest.approx(0.9)

    def test_set_clamps_to_range(self, engine):
        engine.set('moisture', 5.0)
        assert engine.state['moisture'] <= 1.0
        engine.set('moisture', -5.0)
        assert engine.state['moisture'] >= 0.0

    def test_set_unknown_key_ignored(self, engine):
        engine.set('nonexistent', 0.5)
        assert 'nonexistent' not in engine.state

    def test_set_fires_subscribers(self, engine):
        fired = []
        engine.subscribe('moisture', lambda v: fired.append(v))
        engine.set('moisture', 0.7)
        assert len(fired) == 1
        assert fired[0] == pytest.approx(0.7)

    def test_set_lerp_creates_target(self, engine):
        engine.set('moisture', 0.9, duration=10.0)
        assert engine._targets.get('moisture') is not None

    def test_set_instant_no_target(self, engine):
        engine.set('moisture', 0.9, duration=0.0)
        assert engine._targets.get('moisture') is None


class TestAtmosphereTick:

    def test_tick_lerps_toward_target(self, engine):
        engine.set('moisture', 0.0)
        engine.set('moisture', 1.0, duration=10.0)
        initial = engine.state['moisture']
        engine.tick(dt=1.0)
        assert engine.state['moisture'] > initial

    def test_tick_reaches_target(self, engine):
        engine.set('moisture', 0.0)
        engine.set('moisture', 0.8, duration=1.0)
        for _ in range(20):
            engine.tick(dt=0.1)
        assert engine.state['moisture'] == pytest.approx(0.8, abs=0.01)

    def test_tick_clears_target_on_arrival(self, engine):
        engine.set('moisture', 0.0)
        engine.set('moisture', 0.5, duration=0.5)
        for _ in range(20):
            engine.tick(dt=0.1)
        assert engine._targets.get('moisture') is None


class TestAtmosphereSubscribers:

    def test_subscribe_fires_on_change(self, engine):
        events = []
        engine.subscribe('heat', lambda v: events.append(v))
        engine.set('heat', 0.8)
        assert len(events) == 1

    def test_multiple_subscribers_same_key(self, engine):
        events = []
        engine.subscribe('heat', lambda v: events.append('a'))
        engine.subscribe('heat', lambda v: events.append('b'))
        engine.set('heat', 0.8)
        assert len(events) == 2

    def test_unsubscribe_stops_firing(self, engine):
        events = []
        fn = lambda v: events.append(v)
        engine.subscribe('heat', fn)
        engine.unsubscribe('heat', fn)
        engine.set('heat', 0.8)
        assert len(events) == 0


class TestAtmosphereFromSeed:

    def test_from_seed_params_updates_state(self, engine):
        params = {
            'moisture': 0.8,
            'heat': 0.3,
            'encounter_density': 0.6,
            'karma_baseline': 0.4,
            'ambient_intensity': 0.7,
        }
        engine.from_seed_params(params)
        assert engine.state['moisture'] == pytest.approx(0.8)
        assert engine.state['heat'] == pytest.approx(0.3)

    def test_from_ghost_modifiers_updates_state(self, engine):
        mods = {
            'presence_regen_rate': 1.4,
            'timing_window_size': 1.3,
        }
        engine.from_ghost_modifiers(mods)
        assert engine.ghost_modifiers.get('presence_regen_rate') == 1.4

    def test_get_modifier_returns_float(self, engine):
        engine.from_ghost_modifiers({'timing_window_size': 1.5})
        val = engine.get_modifier('timing_window_size')
        assert isinstance(val, float)
        assert val == 1.5

    def test_get_modifier_default_one(self, engine):
        val = engine.get_modifier('nonexistent_modifier')
        assert val == 1.0