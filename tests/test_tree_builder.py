import pytest
import json
import random


@pytest.fixture
def blueprint():
    return json.load(open('config/blueprints/verdant.json'))


@pytest.fixture
def builder():
    from core.systems.tree_builder import TreeBuilder
    return TreeBuilder()


class TestBlueprintStructure:

    def test_has_seven_tree_types(self, blueprint):
        assert len(blueprint['trees']) == 7

    def test_all_expected_types_present(self, blueprint):
        for t in ['OAK','PINE','WILLOW','DEAD','YOUNG','ANCIENT','SHRUB']:
            assert t in blueprint['trees']

    def test_each_tree_has_trunk(self, blueprint):
        for name, tree in blueprint['trees'].items():
            assert 'trunk' in tree, f'{name} missing trunk'

    def test_each_tree_has_canopy(self, blueprint):
        for name, tree in blueprint['trees'].items():
            assert 'canopy' in tree, f'{name} missing canopy'

    def test_each_tree_has_frequency(self, blueprint):
        for name, tree in blueprint['trees'].items():
            assert 'frequency' in tree, f'{name} missing frequency'

    def test_frequencies_sum_to_one(self, blueprint):
        total = sum(t['frequency'] for t in blueprint['trees'].values())
        assert abs(total - 1.0) < 0.01, f'frequencies sum to {total}'

    def test_dead_tree_has_no_canopy(self, blueprint):
        assert blueprint['trees']['DEAD']['canopy'] == []

    def test_ancient_has_trunk_flare(self, blueprint):
        assert 'trunk_flare' in blueprint['trees']['ANCIENT']

    def test_shrub_has_ground_offset(self, blueprint):
        assert 'ground_offset' in blueprint['trees']['SHRUB']


class TestTreeBuilder:

    def test_boots_without_error(self, builder):
        assert builder is not None

    def test_build_returns_node_list(self, builder, blueprint):
        rng = random.Random(42)
        nodes = builder.build_tree('OAK', blueprint, rng, x=0, y=0)
        assert isinstance(nodes, list)
        assert len(nodes) > 0

    def test_all_tree_types_build(self, builder, blueprint):
        rng = random.Random(42)
        for tree_type in blueprint['trees']:
            nodes = builder.build_tree(tree_type, blueprint, rng, x=0, y=0)
            assert len(nodes) > 0, f'{tree_type} produced no nodes'

    def test_ancient_taller_than_young(self, builder, blueprint):
        rng = random.Random(42)
        ancient = builder.get_trunk_height('ANCIENT', blueprint, rng)
        young   = builder.get_trunk_height('YOUNG',   blueprint, rng)
        assert ancient > young

    def test_oak_wider_than_pine(self, builder, blueprint):
        rng = random.Random(42)
        oak_w  = builder.get_canopy_width('OAK',  blueprint, rng)
        pine_w = builder.get_canopy_width('PINE', blueprint, rng)
        assert oak_w > pine_w

    def test_dead_tree_has_no_canopy_nodes(self, builder, blueprint):
        rng = random.Random(42)
        nodes = builder.build_tree('DEAD', blueprint, rng, x=0, y=0)
        assert any(n['role'] == 'trunk' for n in nodes)
        assert not any(n['role'] == 'canopy' for n in nodes)

    def test_shrub_starts_at_ground(self, builder, blueprint):
        rng = random.Random(42)
        nodes = builder.build_tree('SHRUB', blueprint, rng, x=0, y=0)
        z_values = [n['z'] for n in nodes]
        assert min(z_values) < 2.0

    def test_weighted_random_picks_all_types(self, builder, blueprint):
        rng = random.Random(42)
        picked = set()
        for _ in range(200):
            t = builder.pick_tree_type(blueprint, rng)
            picked.add(t)
        assert len(picked) == 7

    def test_build_forest_returns_node_count(self, builder, blueprint):
        rng   = random.Random(42)
        nodes = builder.build_forest(
            blueprint, rng,
            x1=-50, x2=50, y1=-50, y2=50,
            count=20
        )
        # Returns all primitive nodes (trunk + canopy per tree) not just 20
        assert len(nodes) >= 20
        tree_types = set(n['tree_type'] for n in nodes)
        assert len(tree_types) > 0