import pytest
import json


@pytest.fixture
def catalog():
    return json.load(open('config/blueprints/objects.json'))


@pytest.fixture
def recipes():
    return json.load(open('config/blueprints/crafting.json'))


class TestObjectCatalog:

    def test_catalog_has_categories(self, catalog):
        for cat in ['flora', 'geology', 'fauna', 'remnant']:
            assert cat in catalog

    def test_each_object_has_required_keys(self, catalog):
        for cat, objects in catalog.items():
            for name, obj in objects.items():
                for key in ['primitive', 'role', 'color', 'scale', 'description']:
                    assert key in obj, f'{name} missing {key}'

    def test_each_object_has_valid_primitive(self, catalog):
        valid = ['PILLAR','SLAB','BLOCK','WEDGE','ARCH','SPIKE','PLANE']
        for cat, objects in catalog.items():
            for name, obj in objects.items():
                assert obj['primitive'] in valid, f'{name} has invalid primitive'

    def test_survival_objects_have_craft_uses(self, catalog):
        for cat, objects in catalog.items():
            for name, obj in objects.items():
                assert 'uses' in obj, f'{name} missing uses'
                assert len(obj['uses']) > 0

    def test_relic_objects_have_ability(self, catalog):
        relics = catalog.get('relic', {})
        for name, obj in relics.items():
            assert 'ability' in obj, f'{name} missing ability'


class TestCraftingRecipes:

    def test_recipes_is_dict(self, recipes):
        assert isinstance(recipes, dict)

    def test_each_recipe_has_inputs_and_output(self, recipes):
        for name, recipe in recipes.items():
            assert 'inputs' in recipe, f'{name} missing inputs'
            assert 'output' in recipe, f'{name} missing output'
            assert len(recipe['inputs']) >= 2

    def test_output_has_required_keys(self, recipes):
        for name, recipe in recipes.items():
            out = recipe['output']
            for key in ['name', 'primitive', 'description']:
                assert key in out, f'{name} output missing {key}'

    def test_unknown_combo_produces_unnamed(self, recipes):
        assert 'UNKNOWN' in recipes
        assert recipes['UNKNOWN']['output']['name'] == 'Unnamed Object'


class TestCraftingEngine:

    def test_boots_without_error(self):
        from core.systems.crafting_engine import CraftingEngine
        ce = CraftingEngine()
        assert ce is not None

    def test_craft_known_recipe(self):
        from core.systems.crafting_engine import CraftingEngine
        ce = CraftingEngine()
        result = ce.craft('stripped_branch', 'sap_vessel')
        assert result is not None
        assert 'name' in result

    def test_craft_unknown_combo_returns_unnamed(self):
        from core.systems.crafting_engine import CraftingEngine
        ce = CraftingEngine()
        result = ce.craft('river_stone', 'creature_hide')
        assert result['name'] == 'Unnamed Object'

    def test_craft_result_has_provenance_hash(self):
        from core.systems.crafting_engine import CraftingEngine
        ce = CraftingEngine()
        result = ce.craft('flint_shard', 'fuel_canister')
        assert 'provenance_hash' in result
        assert len(result['provenance_hash']) == 16

    def test_same_inputs_same_hash(self):
        from core.systems.crafting_engine import CraftingEngine
        ce = CraftingEngine()
        r1 = ce.craft('flint_shard', 'fuel_canister')
        r2 = ce.craft('flint_shard', 'fuel_canister')
        assert r1['provenance_hash'] == r2['provenance_hash']

    def test_craft_order_independent(self):
        from core.systems.crafting_engine import CraftingEngine
        ce = CraftingEngine()
        r1 = ce.craft('stripped_branch', 'sap_vessel')
        r2 = ce.craft('sap_vessel', 'stripped_branch')
        assert r1['provenance_hash'] == r2['provenance_hash']

    def test_craft_registers_in_vault(self):
        from core.systems.crafting_engine import CraftingEngine
        ce = CraftingEngine()
        result = ce.craft('river_stone', 'flint_shard')
        history = ce.get_history()
        assert any(r['provenance_hash'] == result['provenance_hash']
                   for r in history)