import pytest
import math
import random


@pytest.fixture
def engine():
    from core.systems.placement_engine import PlacementEngine
    return PlacementEngine(seed=42)


class TestPlacementEngineInit:

    def test_boots_without_error(self, engine):
        assert engine is not None

    def test_has_golden_angle(self, engine):
        assert abs(engine.GOLDEN_ANGLE - 137.5077640500378) < 0.0001

    def test_seed_sets_rng(self, engine):
        assert engine.seed == 42


class TestGoldenSpiral:

    def test_spiral_returns_list(self, engine):
        points = engine.golden_spiral(count=10, radius=100.0)
        assert isinstance(points, list)
        assert len(points) == 10

    def test_spiral_points_are_tuples(self, engine):
        points = engine.golden_spiral(count=5, radius=100.0)
        for p in points:
            assert isinstance(p, tuple)
            assert len(p) == 2

    def test_spiral_points_within_radius(self, engine):
        radius = 100.0
        points = engine.golden_spiral(count=50, radius=radius)
        for x, y in points:
            dist = math.sqrt(x*x + y*y)
            assert dist <= radius * 1.05

    def test_spiral_no_duplicates(self, engine):
        points = engine.golden_spiral(count=20, radius=100.0)
        assert len(set(points)) == len(points)

    def test_spiral_phase_offset_changes_points(self, engine):
        p1 = engine.golden_spiral(count=10, radius=100.0, phase=0.0)
        p2 = engine.golden_spiral(count=10, radius=100.0, phase=1.0)
        assert p1 != p2

    def test_different_seeds_different_spirals(self):
        from core.systems.placement_engine import PlacementEngine
        e1 = PlacementEngine(seed=42)
        e2 = PlacementEngine(seed=99)
        p1 = e1.golden_spiral(count=10, radius=100.0)
        p2 = e2.golden_spiral(count=10, radius=100.0)
        assert p1 != p2


class TestPerlinField:

    def test_perlin_returns_float(self, engine):
        val = engine.perlin(x=10.0, y=20.0)
        assert isinstance(val, float)

    def test_perlin_normalized(self, engine):
        for x in range(0, 100, 10):
            for y in range(0, 100, 10):
                val = engine.perlin(float(x), float(y))
                assert 0.0 <= val <= 1.0

    def test_perlin_deterministic(self, engine):
        v1 = engine.perlin(42.0, 84.0)
        v2 = engine.perlin(42.0, 84.0)
        assert v1 == v2

    def test_perlin_varies_across_space(self, engine):
        vals = {engine.perlin(float(x), float(y))
                for x in range(0, 50, 5)
                for y in range(0, 50, 5)}
        assert len(vals) > 10


class TestCandidatePlacement:

    def test_candidates_returns_list(self, engine):
        candidates = engine.candidates(
            cx=0.0, cy=0.0, radius=200.0,
            count=20, category='flora'
        )
        assert isinstance(candidates, list)

    def test_candidates_respect_radius(self, engine):
        candidates = engine.candidates(
            cx=0.0, cy=0.0, radius=100.0,
            count=30, category='flora'
        )
        for x, y in candidates:
            dist = math.sqrt(x*x + y*y)
            assert dist <= 105.0

    def test_candidates_deterministic(self, engine):
        c1 = engine.candidates(0.0, 0.0, 100.0, 20, 'flora')
        c2 = engine.candidates(0.0, 0.0, 100.0, 20, 'flora')
        assert c1 == c2

    def test_different_categories_different_density(self, engine):
        flora   = engine.candidates(0.0, 0.0, 200.0, 50, 'flora')
        relics  = engine.candidates(0.0, 0.0, 200.0, 50, 'relic')
        assert len(flora) >= len(relics)

    def test_geology_candidates(self, engine):
        geo = engine.candidates(0.0, 0.0, 200.0, 30, 'geology')
        assert isinstance(geo, list)


class TestFullPipeline:

    def test_place_returns_list(self, engine):
        from core.systems.terrain_generator import TerrainGenerator
        terrain = TerrainGenerator(seed=42)
        results = engine.place(
            cx=0.0, cy=0.0, radius=200.0,
            category='flora', count=20,
            terrain=terrain
        )
        assert isinstance(results, list)

    def test_place_results_have_position(self, engine):
        from core.systems.terrain_generator import TerrainGenerator
        terrain = TerrainGenerator(seed=42)
        results = engine.place(
            cx=0.0, cy=0.0, radius=200.0,
            category='flora', count=20,
            terrain=terrain
        )
        for r in results:
            assert 'x' in r and 'y' in r and 'z' in r

    def test_place_results_have_weight(self, engine):
        from core.systems.terrain_generator import TerrainGenerator
        terrain = TerrainGenerator(seed=42)
        results = engine.place(
            cx=0.0, cy=0.0, radius=200.0,
            category='flora', count=20,
            terrain=terrain
        )
        for r in results:
            assert 'weight' in r
            assert 0.0 <= r['weight'] <= 1.0

    def test_place_seeds_differ(self):
        from core.systems.placement_engine import PlacementEngine
        from core.systems.terrain_generator import TerrainGenerator
        terrain = TerrainGenerator(seed=42)
        e1 = PlacementEngine(seed=42)
        e2 = PlacementEngine(seed=99)
        r1 = e1.place(0.0, 0.0, 200.0, 'flora', 20, terrain)
        r2 = e2.place(0.0, 0.0, 200.0, 'flora', 20, terrain)
        positions1 = [(r['x'], r['y']) for r in r1]
        positions2 = [(r['x'], r['y']) for r in r2]
        assert positions1 != positions2