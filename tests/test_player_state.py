"""Tests for core.systems.player_state — Cairn-flavored player primitive.

Contract (fits on a business card):
    Player has HP + max_hp, three saves (STR/DEX/WIL), and a fixed-size
    slot inventory. Items occupy 1, 2, or 'bulky' (N) slots. Saves are
    rolled d20-vs-stat (low roll = success). Wounds come from combat.
    No classes yet — everything is a save + stat + inventory entry.

    Pure data + rules. No I/O. RNG injected.
"""
from __future__ import annotations

import pytest

from core.systems.player_state import (
    PlayerState, Item,
    take_damage, heal, add_item, remove_item,
    inventory_used, inventory_free, save_roll,
    equip, unequip,
)


# --- Construction ------------------------------------------------------------

def test_default_new_player():
    p = PlayerState.new(name="Wanderer")
    assert p.name == "Wanderer"
    assert p.hp == p.max_hp
    assert p.max_hp > 0
    assert p.slots > 0
    # Cairn-style: three saves rolled on creation, each 1..20.
    assert 1 <= p.str_save <= 20
    assert 1 <= p.dex_save <= 20
    assert 1 <= p.wil_save <= 20
    assert p.inventory == ()


def test_new_player_with_seed_deterministic():
    a = PlayerState.new(name="A", seed=42)
    b = PlayerState.new(name="A", seed=42)
    assert a == b


# --- Damage + healing --------------------------------------------------------

def test_take_damage_reduces_hp():
    p = PlayerState.new(seed=1)
    hp0 = p.hp
    p2 = take_damage(p, 3)
    assert p2.hp == hp0 - 3
    # Original unmutated (dataclass-style immutability).
    assert p.hp == hp0


def test_damage_clamps_at_zero():
    p = PlayerState.new(seed=1)
    p2 = take_damage(p, p.hp + 99)
    assert p2.hp == 0


def test_zero_hp_is_dead():
    p = PlayerState.new(seed=1)
    p2 = take_damage(p, p.hp)
    assert p2.hp == 0
    assert p2.is_dead()
    assert not p.is_dead()


def test_heal_raises_hp():
    p = PlayerState.new(seed=1)
    wounded = take_damage(p, 5)
    healed = heal(wounded, 3)
    assert healed.hp == wounded.hp + 3


def test_heal_clamps_at_max():
    p = PlayerState.new(seed=1)
    wounded = take_damage(p, 3)
    overhealed = heal(wounded, 999)
    assert overhealed.hp == p.max_hp


def test_negative_damage_ignored():
    p = PlayerState.new(seed=1)
    assert take_damage(p, -5).hp == p.hp


# --- Inventory ---------------------------------------------------------------

def test_add_item_uses_slots():
    p = PlayerState.new(seed=1, slots=6)
    sword = Item(name="sword", slot_cost=1)
    p2 = add_item(p, sword)
    assert p2.inventory == (sword,)
    assert inventory_used(p2) == 1
    assert inventory_free(p2) == 5


def test_add_bulky_item_consumes_two_slots():
    p = PlayerState.new(seed=1, slots=6)
    polearm = Item(name="polearm", slot_cost=2)
    p2 = add_item(p, polearm)
    assert inventory_used(p2) == 2
    assert inventory_free(p2) == 4


def test_inventory_overflow_rejected():
    p = PlayerState.new(seed=1, slots=3)
    p = add_item(p, Item(name="a", slot_cost=1))
    p = add_item(p, Item(name="b", slot_cost=2))
    # No room left for slot_cost=1.
    with pytest.raises(ValueError):
        add_item(p, Item(name="c", slot_cost=1))


def test_remove_item():
    p = PlayerState.new(seed=1, slots=6)
    rope = Item(name="rope", slot_cost=1)
    p2 = add_item(p, rope)
    p3 = remove_item(p2, rope)
    assert p3.inventory == ()
    assert inventory_free(p3) == 6


def test_remove_item_missing_raises():
    p = PlayerState.new(seed=1)
    with pytest.raises(ValueError):
        remove_item(p, Item(name="ghost", slot_cost=1))


def test_removes_first_matching_instance_only():
    """Two rope entries → remove one leaves the other."""
    p = PlayerState.new(seed=1, slots=6)
    rope = Item(name="rope", slot_cost=1)
    p = add_item(p, rope)
    p = add_item(p, rope)
    p = remove_item(p, rope)
    assert p.inventory == (rope,)


# --- Saves -------------------------------------------------------------------

def test_save_roll_below_stat_succeeds():
    """d20 roll ≤ stat = success (Cairn convention)."""
    p = PlayerState.new(seed=1)
    p = p._replace(str_save=15)
    # Inject deterministic rng: always rolls 10 → ≤ 15 → success.
    result = save_roll(p, "str", rng=lambda: 10)
    assert result.success is True
    assert result.roll == 10


def test_save_roll_above_stat_fails():
    p = PlayerState.new(seed=1)
    p = p._replace(dex_save=8)
    result = save_roll(p, "dex", rng=lambda: 17)
    assert result.success is False
    assert result.roll == 17


def test_save_roll_exactly_at_stat_succeeds():
    """Cairn: roll ≤ stat (inclusive)."""
    p = PlayerState.new(seed=1)
    p = p._replace(wil_save=12)
    result = save_roll(p, "wil", rng=lambda: 12)
    assert result.success is True


def test_save_roll_unknown_stat_raises():
    p = PlayerState.new(seed=1)
    with pytest.raises(ValueError):
        save_roll(p, "charm", rng=lambda: 10)


# --- Determinism -------------------------------------------------------------

def test_pure_operations_preserve_original():
    p = PlayerState.new(seed=1, slots=6)
    p2 = add_item(p, Item(name="x", slot_cost=1))
    p3 = take_damage(p2, 2)
    # Original `p` is untouched.
    assert p.inventory == ()
    assert p.hp == p.max_hp


# --- Equipped item -----------------------------------------------------------

def test_default_player_has_nothing_equipped():
    p = PlayerState.new(seed=1)
    assert p.equipped is None


def test_equip_sets_equipped_field():
    p = PlayerState.new(seed=1, slots=4)
    p = add_item(p, Item(name="torch_handcrafted"))
    p = equip(p, "torch_handcrafted")
    assert p.equipped == "torch_handcrafted"


def test_equip_rejects_item_not_in_inventory():
    p = PlayerState.new(seed=1, slots=4)
    with pytest.raises(ValueError, match="not in inventory"):
        equip(p, "torch_handcrafted")


def test_unequip_clears_equipped():
    p = PlayerState.new(seed=1, slots=4)
    p = add_item(p, Item(name="torch_handcrafted"))
    p = equip(p, "torch_handcrafted")
    p = unequip(p)
    assert p.equipped is None


def test_remove_equipped_item_clears_equipped():
    """Can't wield what you don't carry — removing the equipped item
    must clear the equipped field, not leave a dangling reference."""
    p = PlayerState.new(seed=1, slots=4)
    item = Item(name="torch_handcrafted")
    p = add_item(p, item)
    p = equip(p, "torch_handcrafted")
    p = remove_item(p, item)
    assert p.equipped is None
    assert not p.inventory


def test_remove_non_equipped_item_preserves_equipped():
    p = PlayerState.new(seed=1, slots=4)
    torch = Item(name="torch_handcrafted")
    candle = Item(name="candle")
    p = add_item(p, torch)
    p = add_item(p, candle)
    p = equip(p, "torch_handcrafted")
    p = remove_item(p, candle)
    assert p.equipped == "torch_handcrafted"
