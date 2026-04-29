"""Input dispatch helpers — inventory cycle + encounter action key map."""
from __future__ import annotations

from clients.vector_terminal.inputs import action_for_key_index, next_inventory_name


def test_empty_inventory_returns_none():
    assert next_inventory_name([], None) is None


def test_unequipped_returns_first_item():
    inv = [{"name": "torch"}, {"name": "potion"}]
    assert next_inventory_name(inv, None) == "torch"


def test_cycles_through_inventory():
    inv = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
    assert next_inventory_name(inv, "a") == "b"
    assert next_inventory_name(inv, "b") == "c"
    assert next_inventory_name(inv, "c") == "a"


def test_unknown_equipped_starts_from_first():
    inv = [{"name": "a"}, {"name": "b"}]
    assert next_inventory_name(inv, "ghost_item") == "a"


def test_action_key_index_with_strings():
    assert action_for_key_index(["parley", "flee", "attack"], 0) == "parley"
    assert action_for_key_index(["parley", "flee", "attack"], 2) == "attack"


def test_action_key_index_with_dicts():
    opts = [{"name": "parley"}, {"action": "flee"}, {"id": "attack"}]
    assert action_for_key_index(opts, 0) == "parley"
    assert action_for_key_index(opts, 1) == "flee"
    assert action_for_key_index(opts, 2) == "attack"


def test_action_key_index_out_of_range_returns_none():
    assert action_for_key_index(["only"], 5) is None
    assert action_for_key_index([], 0) is None


def test_action_key_index_negative_returns_none():
    assert action_for_key_index(["a", "b"], -1) is None
