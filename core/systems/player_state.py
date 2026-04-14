"""Cairn-flavored player state primitive.

A player is: HP + max_hp, three saves (STR/DEX/WIL, each rolled once on
creation, 1..20 range), and a fixed-size slot inventory. Items occupy
slot_cost slots. Saves are rolled d20-vs-stat (roll ≤ stat = success).

Pure data + rules. Immutability via NamedTuple — every operation returns
a new PlayerState. RNG is injected so tests stay deterministic. Combat,
leveling, loot tables all sit upstream and consume this primitive.
"""
from __future__ import annotations

import random
from typing import Callable, NamedTuple, Tuple


# --- Data --------------------------------------------------------------------

class Item(NamedTuple):
    name: str
    slot_cost: int = 1    # 1 = regular, 2 = bulky, 3+ = siege weapons et al.


class PlayerState(NamedTuple):
    name: str
    hp: int
    max_hp: int
    str_save: int     # rolled 1..20, higher = tougher; d20 ≤ stat = pass
    dex_save: int
    wil_save: int
    slots: int
    inventory: Tuple[Item, ...]

    @classmethod
    def new(cls, name: str = "Wanderer",
            seed: int | None = None,
            max_hp: int = 6,
            slots: int = 10) -> "PlayerState":
        rng = random.Random(seed)
        return cls(
            name=name,
            hp=max_hp,
            max_hp=max_hp,
            str_save=rng.randint(1, 20),
            dex_save=rng.randint(1, 20),
            wil_save=rng.randint(1, 20),
            slots=slots,
            inventory=(),
        )

    def is_dead(self) -> bool:
        return self.hp <= 0


class SaveResult(NamedTuple):
    success: bool
    roll: int
    stat: int


# --- Pure operations ---------------------------------------------------------

def take_damage(p: PlayerState, amount: int) -> PlayerState:
    if amount <= 0:
        return p
    return p._replace(hp=max(0, p.hp - amount))


def heal(p: PlayerState, amount: int) -> PlayerState:
    if amount <= 0:
        return p
    return p._replace(hp=min(p.max_hp, p.hp + amount))


def inventory_used(p: PlayerState) -> int:
    return sum(i.slot_cost for i in p.inventory)


def inventory_free(p: PlayerState) -> int:
    return p.slots - inventory_used(p)


def add_item(p: PlayerState, item: Item) -> PlayerState:
    if item.slot_cost > inventory_free(p):
        raise ValueError(
            f"inventory full: item {item.name!r} needs "
            f"{item.slot_cost} slots, {inventory_free(p)} free")
    return p._replace(inventory=p.inventory + (item,))


def remove_item(p: PlayerState, item: Item) -> PlayerState:
    for i, existing in enumerate(p.inventory):
        if existing == item:
            new_inv = p.inventory[:i] + p.inventory[i + 1:]
            return p._replace(inventory=new_inv)
    raise ValueError(f"item {item.name!r} not in inventory")


_SAVE_FIELDS = {"str": "str_save", "dex": "dex_save", "wil": "wil_save"}


def save_roll(p: PlayerState, stat: str,
              rng: Callable[[], int] | None = None) -> SaveResult:
    """Roll a d20 save. Lowercase stat name. `rng` returns an int 1..20;
    default uses the system RNG. Success = roll ≤ stat (Cairn convention)."""
    field = _SAVE_FIELDS.get(stat.lower())
    if field is None:
        raise ValueError(f"unknown stat {stat!r}; expected one of {list(_SAVE_FIELDS)}")
    stat_val = getattr(p, field)
    roll = rng() if rng is not None else random.randint(1, 20)
    return SaveResult(success=roll <= stat_val, roll=roll, stat=stat_val)
