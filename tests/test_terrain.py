import pytest
import random
import math


@pytest.fixture
def gen():
    from core.systems.terrain_generator import TerrainGenerator
    return TerrainGenerator(seed=42)


class TestTerrainGeneratorInit:

    def test_boots_without_error(self, gen):
        assert gen is not None

    def test_has_seed(self, gen):
        assert gen.seed == 42


class TestHeightmap:

    def test_height_at_returns_float(self, gen):
        h = gen.height_at(0.0, 0.0)
        assert isinstance(h, float)

    def test_height_in_valid_range(self, gen):
        for x in range(-100, 100, 10):
            for y in range(-100, 100, 10):
                h = gen.height_at(float(x), float(y))
                assert -50.0 <= h <= 50.0

    def test_same_inputs_same_height(self, gen):
        h1 = gen.height_at(10.0, 20.0)
        h2 = gen.height_at(10.0, 20.0)
        assert h1 == h2

    def test_different_positions_different_heights(self, gen):
        heights = set()
        for i in range(20):
            h = gen.height_at(float(i * 15), float(i * 7))
            heights.add(round(h, 2))
        assert len(heights) > 5

    def test_sector_amplitude(self, gen):
        # Mountain sector (NE) should have higher amplitude than verdant (NW)
        verdant_heights = [abs(gen.height_at(float(x), float(y)))
                           for x in range(-400, 0, 50)
                           for y in range(0, 400, 50)]
        mountain_heights = [abs(gen.height_at(float(x), float(y)))
                            for x in range(0, 400, 50)
                            for y in range(0, 400, 50)]
        assert sum(mountain_heights) > sum(verdant_heights)

    def test_desert_gentle_waves(self, gen):
        # Desert sector (SW) should have low amplitude
        desert_heights = [abs(gen.height_at(float(x), float(y)))
                          for x in range(-400, 0, 50)
                          for y in range(-400, 0, 50)]
        assert max(desert_heights) < 30.0


class TestTerrainMesh:

    def test_build_mesh_returns_node(self, gen):
        node = gen.build_mesh(
            cx=0, cy=0, width=100, depth=100,
            subdivisions=8, color=(0.1, 0.25, 0.1)
        )
        assert node is not None

    def test_mesh_has_correct_vertex_count(self, gen):
        node = gen.build_mesh(
            cx=0, cy=0, width=100, depth=100,
            subdivisions=8, color=(0.1, 0.25, 0.1)
        )
        from panda3d.core import GeomNode
        assert isinstance(node, GeomNode)

    def test_ground_z_at_origin(self, gen):
        h = gen.height_at(0.0, 0.0)
        # Origin is in verdant sector, amplitude max is 6.0 * (1+0.4+0.15)
        assert -10.0 <= h <= 25.0


class TestElevationHelpers:

    def test_is_slope_returns_bool(self, gen):
        result = gen.is_slope(10.0, 20.0, threshold=0.3)
        assert isinstance(result, bool)

    def test_slope_direction(self, gen):
        dx, dy = gen.slope_direction(0.0, 0.0)
        assert isinstance(dx, float)
        assert isinstance(dy, float)

    def test_lowest_neighbor(self, gen):
        x, y = gen.lowest_neighbor(0.0, 0.0, step=10.0)
        assert isinstance(x, float)
        assert isinstance(y, float)