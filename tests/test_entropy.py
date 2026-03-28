import pytest
import math


@pytest.fixture
def engine():
    from core.systems.entropy_engine import EntropyEngine
    return EntropyEngine()


class TestEntropyEngineInit:

    def test_boots_without_error(self, engine):
        assert engine is not None

    def test_has_tree_ideals(self, engine):
        assert hasattr(engine, 'IDEALS')
        assert len(engine.IDEALS) == 7

    def test_all_tree_types_have_ideals(self, engine):
        for t in ['OAK','PINE','WILLOW','DEAD','YOUNG','ANCIENT','SHRUB']:
            assert t in engine.IDEALS, f'{t} missing from IDEALS'

    def test_each_ideal_has_required_keys(self, engine):
        for name, ideal in engine.IDEALS.items():
            for key in ['elevation', 'moisture', 'slope']:
                assert key in ideal, f'{name} missing {key}'
            for key in ['elevation', 'moisture', 'slope']:
                assert 'mu' in ideal[key], f'{name}.{key} missing mu'
                assert 'sigma' in ideal[key], f'{name}.{key} missing sigma'


class TestGaussian:

    def test_gaussian_at_ideal_returns_one(self, engine):
        score = engine.gaussian(value=5.0, mu=5.0, sigma=2.0)
        assert abs(score - 1.0) < 0.001

    def test_gaussian_far_from_ideal_near_zero(self, engine):
        score = engine.gaussian(value=100.0, mu=0.0, sigma=1.0)
        assert score < 0.01

    def test_gaussian_returns_float(self, engine):
        assert isinstance(engine.gaussian(1.0, 0.0, 1.0), float)

    def test_gaussian_always_between_zero_and_one(self, engine):
        for v in [-50, -10, 0, 5, 10, 50, 100]:
            s = engine.gaussian(float(v), mu=5.0, sigma=3.0)
            assert 0.0 <= s <= 1.0


class TestPlacementWeight:

    def test_placement_weight_returns_float(self, engine):
        w = engine.placement_weight('OAK', elevation=2.0, moisture=0.5, slope=0.1)
        assert isinstance(w, float)

    def test_weight_between_zero_and_one(self, engine):
        w = engine.placement_weight('PINE', elevation=12.0, moisture=0.3, slope=0.4)
        assert 0.0 <= w <= 1.0

    def test_willow_prefers_low_wet(self, engine):
        wet_low  = engine.placement_weight('WILLOW', elevation=1.0, moisture=0.9, slope=0.05)
        dry_high = engine.placement_weight('WILLOW', elevation=15.0, moisture=0.1, slope=0.5)
        assert wet_low > dry_high

    def test_pine_prefers_high_slope(self, engine):
        high_slope = engine.placement_weight('PINE', elevation=12.0, moisture=0.3, slope=0.5)
        low_flat   = engine.placement_weight('PINE', elevation=1.0,  moisture=0.3, slope=0.05)
        assert high_slope > low_flat

    def test_ancient_prefers_valley_floor(self, engine):
        valley = engine.placement_weight('ANCIENT', elevation=0.0, moisture=0.7, slope=0.05)
        peak   = engine.placement_weight('ANCIENT', elevation=20.0, moisture=0.2, slope=0.6)
        assert valley > peak

    def test_dead_prefers_dry_exposed(self, engine):
        dry  = engine.placement_weight('DEAD', elevation=8.0, moisture=0.1, slope=0.3)
        wet  = engine.placement_weight('DEAD', elevation=1.0, moisture=0.9, slope=0.0)
        assert dry > wet

    def test_shrub_prefers_flat_ground(self, engine):
        flat  = engine.placement_weight('SHRUB', elevation=2.0, moisture=0.5, slope=0.02)
        steep = engine.placement_weight('SHRUB', elevation=2.0, moisture=0.5, slope=0.8)
        assert flat > steep

    def test_unknown_tree_type_raises(self, engine):
        with pytest.raises(ValueError):
            engine.placement_weight('DRAGON', elevation=5.0, moisture=0.5, slope=0.1)


class TestPickTreeType:

    def test_pick_returns_string(self, engine):
        import random
        rng = random.Random(42)
        result = engine.pick_tree_type(elevation=2.0, moisture=0.6, slope=0.1, rng=rng)
        assert isinstance(result, str)

    def test_pick_returns_valid_type(self, engine):
        import random
        rng = random.Random(42)
        valid = {'OAK','PINE','WILLOW','DEAD','YOUNG','ANCIENT','SHRUB'}
        for _ in range(50):
            t = engine.pick_tree_type(elevation=2.0, moisture=0.5, slope=0.1, rng=rng)
            assert t in valid

    def test_wet_low_ground_favors_willow(self, engine):
        import random
        rng = random.Random(42)
        picks = [engine.pick_tree_type(elevation=0.5, moisture=0.95, slope=0.02, rng=rng)
                 for _ in range(100)]
        assert picks.count('WILLOW') > 10

    def test_high_slope_favors_pine(self, engine):
        import random
        rng = random.Random(42)
        picks = [engine.pick_tree_type(elevation=14.0, moisture=0.2, slope=0.6, rng=rng)
                 for _ in range(100)]
        assert picks.count('PINE') > 10


class TestWideCurve:

    def test_lod_tier_returns_string(self, engine):
        tier = engine.lod_tier(distance=5.0)
        assert tier in ['FOCUS', 'MIDFIELD', 'HORIZON']

    def test_close_is_focus(self, engine):
        assert engine.lod_tier(5.0) == 'FOCUS'

    def test_mid_is_midfield(self, engine):
        assert engine.lod_tier(20.0) == 'MIDFIELD'

    def test_far_is_horizon(self, engine):
        assert engine.lod_tier(50.0) == 'HORIZON'

    def test_sigmoid_weight_returns_float(self, engine):
        w = engine.sigmoid_weight(distance=15.0)
        assert isinstance(w, float)
        assert 0.0 <= w <= 1.0

    def test_close_objects_full_weight(self, engine):
        assert engine.sigmoid_weight(0.0) > 0.95

    def test_far_objects_near_zero(self, engine):
        assert engine.sigmoid_weight(100.0) < 0.05