import pytest


@pytest.fixture
def inventory():
    from core.systems.inventory import Inventory
    return Inventory(max_slots=8, max_weight=20.0)


class TestInventoryInit:

    def test_boots_without_error(self, inventory):
        assert inventory is not None

    def test_starts_empty(self, inventory):
        assert inventory.count() == 0

    def test_has_max_slots(self, inventory):
        assert inventory.max_slots == 8

    def test_has_max_weight(self, inventory):
        assert inventory.max_weight == 20.0

    def test_current_weight_zero(self, inventory):
        assert inventory.current_weight() == 0.0


class TestInventoryPickup:

    def test_pickup_returns_true(self, inventory):
        obj = {'id': 'rock_01', 'name': 'River Stone',
               'weight': 1.0, 'category': 'geology'}
        assert inventory.pickup(obj) is True

    def test_pickup_adds_to_inventory(self, inventory):
        obj = {'id': 'rock_01', 'name': 'River Stone',
               'weight': 1.0, 'category': 'geology'}
        inventory.pickup(obj)
        assert inventory.count() == 1

    def test_pickup_updates_weight(self, inventory):
        obj = {'id': 'rock_01', 'name': 'River Stone',
               'weight': 1.0, 'category': 'geology'}
        inventory.pickup(obj)
        assert inventory.current_weight() == 1.0

    def test_pickup_respects_max_slots(self, inventory):
        for i in range(8):
            inventory.pickup({'id': f'rock_{i}', 'name': f'Stone {i}',
                              'weight': 0.5, 'category': 'geology'})
        result = inventory.pickup({'id': 'one_more', 'name': 'Extra',
                                   'weight': 0.5, 'category': 'geology'})
        assert result is False

    def test_pickup_respects_max_weight(self, inventory):
        inventory.pickup({'id': 'heavy', 'name': 'Boulder',
                          'weight': 19.0, 'category': 'geology'})
        result = inventory.pickup({'id': 'heavy2', 'name': 'Boulder2',
                                   'weight': 5.0, 'category': 'geology'})
        assert result is False

    def test_pickup_without_weight_defaults(self, inventory):
        obj = {'id': 'leaf', 'name': 'Leaf', 'category': 'flora'}
        assert inventory.pickup(obj) is True


class TestInventoryDrop:

    def test_drop_removes_item(self, inventory):
        obj = {'id': 'rock_01', 'name': 'River Stone',
               'weight': 1.0, 'category': 'geology'}
        inventory.pickup(obj)
        inventory.drop('rock_01')
        assert inventory.count() == 0

    def test_drop_updates_weight(self, inventory):
        obj = {'id': 'rock_01', 'name': 'River Stone',
               'weight': 1.0, 'category': 'geology'}
        inventory.pickup(obj)
        inventory.drop('rock_01')
        assert inventory.current_weight() == 0.0

    def test_drop_returns_object(self, inventory):
        obj = {'id': 'rock_01', 'name': 'River Stone',
               'weight': 1.0, 'category': 'geology'}
        inventory.pickup(obj)
        dropped = inventory.drop('rock_01')
        assert dropped['id'] == 'rock_01'

    def test_drop_unknown_id_returns_none(self, inventory):
        assert inventory.drop('nonexistent') is None


class TestInventoryInspect:

    def test_get_slot_returns_item(self, inventory):
        obj = {'id': 'rock_01', 'name': 'River Stone',
               'weight': 1.0, 'category': 'geology'}
        inventory.pickup(obj)
        assert inventory.get('rock_01') is not None

    def test_get_unknown_returns_none(self, inventory):
        assert inventory.get('nonexistent') is None

    def test_list_returns_all_items(self, inventory):
        for i in range(3):
            inventory.pickup({'id': f'rock_{i}', 'name': f'Stone {i}',
                              'weight': 1.0, 'category': 'geology'})
        assert len(inventory.list()) == 3

    def test_has_space_true_when_empty(self, inventory):
        assert inventory.has_space(weight=1.0) is True

    def test_has_space_false_when_full(self, inventory):
        for i in range(8):
            inventory.pickup({'id': f'rock_{i}', 'name': f'Stone {i}',
                              'weight': 0.5, 'category': 'geology'})
        assert inventory.has_space(weight=0.5) is False