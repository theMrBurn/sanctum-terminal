import pytest
from core.systems.primitive_factory import (
    PrimitiveFactory, Primitive, Recipe, PRIMITIVES
)


# -- Fixtures ------------------------------------------------------------

@pytest.fixture
def factory():
    return PrimitiveFactory()


@pytest.fixture
def seeker_profile():
    return {'archetype': 'SEEKER', 'karma': 0.3, 'depth_score': 3}


@pytest.fixture
def keeper_profile():
    return {'archetype': 'KEEPER', 'karma': 0.1, 'depth_score': 2}


@pytest.fixture
def repair_relic():
    return {
        'archetypal_name': 'repair',
        'vibe': 'necessity, stress, resolve',
        'impact_rating': 7,
    }


# -- Primitive contracts --------------------------------------------------

class TestPrimitives:

    def test_all_seven_primitives_exist(self):
        for name in ['PILLAR','SLAB','BLOCK','WEDGE','ARCH','SPIKE','PLANE']:
            assert name in PRIMITIVES

    def test_each_primitive_has_required_keys(self):
        for name, p in PRIMITIVES.items():
            for key in ['default_scale', 'role_hints', 'color_source']:
                assert key in p, f'{name} missing {key}'

    def test_primitive_default_scale_is_three_floats(self):
        for name, p in PRIMITIVES.items():
            s = p['default_scale']
            assert len(s) == 3
            assert all(isinstance(v, float) for v in s)


# -- PrimitiveFactory contracts -------------------------------------------

class TestPrimitiveFactory:

    def test_boots_without_error(self, factory):
        assert factory is not None

    def test_build_returns_primitive(self, factory):
        p = factory.build('PILLAR', scale=(1.0,8.0,1.0), color=(0.3,0.2,0.1))
        assert isinstance(p, Primitive)

    def test_primitive_has_geom_node(self, factory):
        p = factory.build('BLOCK', scale=(2.0,2.0,2.0), color=(0.5,0.5,0.5))
        assert p.geom_node is not None

    def test_primitive_has_role(self, factory):
        p = factory.build('PILLAR', scale=(1.0,8.0,1.0), color=(0.2,0.2,0.2), role='trunk')
        assert p.role == 'trunk'

    def test_primitive_has_scale(self, factory):
        p = factory.build('SLAB', scale=(4.0,0.5,4.0), color=(0.2,0.4,0.2))
        assert len(p.scale) == 3
        assert all(isinstance(v, float) for v in p.scale)

    def test_unknown_primitive_raises(self, factory):
        with pytest.raises(ValueError):
            factory.build('DRAGON', scale=(1.0,1.0,1.0), color=(1.0,0.0,0.0))


# -- Recipe contracts -----------------------------------------------------

class TestRecipe:

    def test_recipe_from_blueprint_returns_list(self, factory):
        blueprint = {
            'grammar': [
                {'primitive': 'PILLAR', 'role': 'trunk',
                 'scale': [0.8, 10.0, 0.8], 'color': 'floor'},
                {'primitive': 'SLAB', 'role': 'canopy',
                 'scale': [5.0, 0.5, 5.0], 'color': 'accent',
                 'parent': 'trunk'},
            ]
        }
        result = factory.from_blueprint(blueprint, palette={'floor':(0.1,0.2,0.1),'accent':(0.3,0.6,0.2)})
        assert isinstance(result, list)
        assert len(result) == 2

    def test_recipe_primitives_have_correct_roles(self, factory):
        blueprint = {
            'grammar': [
                {'primitive': 'PILLAR', 'role': 'trunk',
                 'scale': [0.8, 10.0, 0.8], 'color': 'floor'},
            ]
        }
        result = factory.from_blueprint(blueprint, palette={'floor':(0.1,0.2,0.1)})
        assert result[0].role == 'trunk'

    def test_canopy_inherits_parent_height(self, factory):
        blueprint = {
            'grammar': [
                {'primitive': 'PILLAR', 'role': 'trunk',
                 'scale': [0.8, 10.0, 0.8], 'color': 'floor'},
                {'primitive': 'SLAB', 'role': 'canopy',
                 'scale': [5.0, 0.5, 5.0], 'color': 'accent',
                 'parent': 'trunk'},
            ]
        }
        result = factory.from_blueprint(blueprint, palette={'floor':(0.1,0.2,0.1),'accent':(0.3,0.6,0.2)})
        trunk  = next(p for p in result if p.role == 'trunk')
        canopy = next(p for p in result if p.role == 'canopy')
        # Canopy z-offset should equal trunk height
        assert canopy.offset_z == pytest.approx(trunk.scale[1], rel=0.01)


# -- Relic influence contracts --------------------------------------------

class TestRelicInfluence:

    def test_high_impact_relic_increases_scale(self, factory, repair_relic):
        low  = factory.build('PILLAR', scale=(1.0,5.0,1.0), color=(0.3,0.2,0.1),
                             relic={'archetypal_name':'x','impact_rating':2})
        high = factory.build('PILLAR', scale=(1.0,5.0,1.0), color=(0.3,0.2,0.1),
                             relic=repair_relic)
        assert high.scale[1] >= low.scale[1]

    def test_relic_vibe_sets_primitive_vibe(self, factory, repair_relic):
        p = factory.build('BLOCK', scale=(2.0,2.0,2.0), color=(0.5,0.4,0.3),
                          relic=repair_relic)
        assert p.vibe == repair_relic['vibe']

    def test_no_relic_gives_default_scale(self, factory):
        p = factory.build('BLOCK', scale=(2.0,2.0,2.0), color=(0.5,0.5,0.5))
        assert p.scale == (2.0, 2.0, 2.0)


# -- Character profile influence ------------------------------------------

class TestCharacterInfluence:

    def test_seeker_elongates_pillars(self, factory, seeker_profile, repair_relic):
        seeker  = factory.build('PILLAR', scale=(1.0,5.0,1.0), color=(0.3,0.2,0.1),
                                relic=repair_relic, profile=seeker_profile)
        keeper  = factory.build('PILLAR', scale=(1.0,5.0,1.0), color=(0.3,0.2,0.1),
                                relic=repair_relic, profile={'archetype':'KEEPER','karma':0.1,'depth_score':2})
        # Seeker pillars reach higher
        assert seeker.scale[1] >= keeper.scale[1]

    def test_keeper_widens_slabs(self, factory, keeper_profile, repair_relic):
        keeper  = factory.build('SLAB', scale=(4.0,0.5,4.0), color=(0.2,0.4,0.2),
                                relic=repair_relic, profile=keeper_profile)
        seeker  = factory.build('SLAB', scale=(4.0,0.5,4.0), color=(0.2,0.4,0.2),
                                relic=repair_relic, profile={'archetype':'SEEKER','karma':0.3,'depth_score':3})
        # Keeper slabs are wider/more stable
        assert keeper.scale[0] >= seeker.scale[0]

    def test_wanderer_randomizes_rotation(self, factory, repair_relic):
        wanderer = factory.build('BLOCK', scale=(2.0,2.0,2.0), color=(0.4,0.3,0.2),
                                 relic=repair_relic,
                                 profile={'archetype':'WANDERER','karma':0.5,'depth_score':1})
        assert hasattr(wanderer, 'rotation')

    def test_builder_adds_detail_count(self, factory, repair_relic):
        builder = factory.build('BLOCK', scale=(2.0,2.0,2.0), color=(0.4,0.3,0.2),
                                relic=repair_relic,
                                profile={'archetype':'BUILDER','karma':0.2,'depth_score':2})
        assert builder.detail_level >= 1

    def test_profile_none_gives_neutral_primitive(self, factory, repair_relic):
        p = factory.build('BLOCK', scale=(2.0,2.0,2.0), color=(0.5,0.5,0.5),
                          relic=repair_relic, profile=None)
        assert p is not None


# -- Provenance hash ------------------------------------------------------

class TestProvenance:

    def test_primitive_has_provenance_hash(self, factory, repair_relic, seeker_profile):
        p = factory.build('SPIKE', scale=(0.5,3.0,0.5), color=(0.6,0.5,0.4),
                          relic=repair_relic, profile=seeker_profile)
        assert hasattr(p, 'provenance_hash')
        assert len(p.provenance_hash) > 0

    def test_same_inputs_same_hash(self, factory, repair_relic, seeker_profile):
        p1 = factory.build('SPIKE', scale=(0.5,3.0,0.5), color=(0.6,0.5,0.4),
                           relic=repair_relic, profile=seeker_profile)
        p2 = factory.build('SPIKE', scale=(0.5,3.0,0.5), color=(0.6,0.5,0.4),
                           relic=repair_relic, profile=seeker_profile)
        assert p1.provenance_hash == p2.provenance_hash

    def test_different_profile_different_hash(self, factory, repair_relic,
                                              seeker_profile, keeper_profile):
        p1 = factory.build('SPIKE', scale=(0.5,3.0,0.5), color=(0.6,0.5,0.4),
                           relic=repair_relic, profile=seeker_profile)
        p2 = factory.build('SPIKE', scale=(0.5,3.0,0.5), color=(0.6,0.5,0.4),
                           relic=repair_relic, profile=keeper_profile)
        assert p1.provenance_hash != p2.provenance_hash