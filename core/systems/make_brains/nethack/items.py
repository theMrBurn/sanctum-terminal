"""items.py — Item dataclass, item kinds, inventory ops, drop tables.

Item kinds per spec:
  Weapons: dagger (d4), short sword (d6), mace (d6), long sword (d8)
  Armor:   leather (AC -1), chain (AC -3)
  Potions: healing (+1d8 HP), gain_level
  Scrolls: identify (no-op V1), teleport (random map position)
  Gold:    stack — contributes to score

Pickup: `,` adds item to player inventory and removes from map.
Wield `w`, Wear `W`, Quaff `q`, Read `r` dispatched from engine.

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 6.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.systems.make_brains.nethack.engine import GameState
    from core.systems.make_brains.nethack.entities import Monster


# ---------------------------------------------------------------------------
# Item kinds — keyed identifiers
# ---------------------------------------------------------------------------

KIND_WEAPON:  str = "weapon"
KIND_ARMOR:   str = "armor"
KIND_POTION:  str = "potion"
KIND_SCROLL:  str = "scroll"
KIND_GOLD:    str = "gold"


# ---------------------------------------------------------------------------
# Item prototype registry
# ---------------------------------------------------------------------------

# Each entry: (kind, name, glyph, subtype, damage_dice, ac_bonus,
#              to_hit_bonus, stack, effect)
ITEM_PROTOS: list[dict] = [
    # Weapons
    dict(kind=KIND_WEAPON, name="dagger",      glyph=")",
         damage_dice="1d4", to_hit_bonus=0, ac_bonus=0, stack=False,
         subtype="dagger"),
    dict(kind=KIND_WEAPON, name="short sword", glyph=")",
         damage_dice="1d6", to_hit_bonus=0, ac_bonus=0, stack=False,
         subtype="short_sword"),
    dict(kind=KIND_WEAPON, name="mace",        glyph=")",
         damage_dice="1d6", to_hit_bonus=0, ac_bonus=0, stack=False,
         subtype="mace"),
    dict(kind=KIND_WEAPON, name="long sword",  glyph=")",
         damage_dice="1d8", to_hit_bonus=1, ac_bonus=0, stack=False,
         subtype="long_sword"),
    # Armor
    dict(kind=KIND_ARMOR,  name="leather armor", glyph="[",
         damage_dice="",  to_hit_bonus=0, ac_bonus=-1, stack=False,
         subtype="leather"),
    dict(kind=KIND_ARMOR,  name="chain mail",    glyph="[",
         damage_dice="",  to_hit_bonus=0, ac_bonus=-3, stack=False,
         subtype="chain"),
    # Potions
    dict(kind=KIND_POTION, name="potion of healing",    glyph="!",
         damage_dice="1d8", to_hit_bonus=0, ac_bonus=0, stack=False,
         subtype="healing"),
    dict(kind=KIND_POTION, name="potion of gain level", glyph="!",
         damage_dice="",  to_hit_bonus=0, ac_bonus=0, stack=False,
         subtype="gain_level"),
    # Scrolls
    dict(kind=KIND_SCROLL, name="scroll of identify",  glyph="?",
         damage_dice="",  to_hit_bonus=0, ac_bonus=0, stack=False,
         subtype="identify"),
    dict(kind=KIND_SCROLL, name="scroll of teleport",  glyph="?",
         damage_dice="",  to_hit_bonus=0, ac_bonus=0, stack=False,
         subtype="teleport"),
    # Gold
    dict(kind=KIND_GOLD,   name="gold",                glyph="$",
         damage_dice="",  to_hit_bonus=0, ac_bonus=0, stack=True,
         subtype="gold"),
]

_PROTO_BY_SUBTYPE: dict[str, dict] = {p["subtype"]: p for p in ITEM_PROTOS}


# ---------------------------------------------------------------------------
# Item dataclass
# ---------------------------------------------------------------------------

@dataclass
class Item:
    """A single item on the map or in inventory."""
    kind:        str
    name:        str
    glyph:       str
    subtype:     str
    x:           int = 0
    y:           int = 0
    damage_dice: str = ""
    to_hit_bonus: int = 0
    ac_bonus:    int = 0
    stack:       bool = False
    quantity:    int = 1       # for gold stacks

    def display_name(self) -> str:
        if self.kind == KIND_GOLD:
            return f"{self.quantity} gold pieces"
        return self.name


def make_item(subtype: str, x: int = 0, y: int = 0,
              quantity: int = 1) -> Item:
    """Construct an Item from a prototype subtype key."""
    proto = _PROTO_BY_SUBTYPE.get(subtype)
    if proto is None:
        raise KeyError(f"unknown item subtype: {subtype}")
    return Item(
        kind=proto["kind"],
        name=proto["name"],
        glyph=proto["glyph"],
        subtype=subtype,
        x=x, y=y,
        damage_dice=proto["damage_dice"],
        to_hit_bonus=proto["to_hit_bonus"],
        ac_bonus=proto["ac_bonus"],
        stack=proto["stack"],
        quantity=quantity,
    )


def make_starter_equipment(
    profile_params: dict,
) -> tuple["Item", "Item"]:
    """Return (weapon, armor) from profile start_weapon / start_armor keys."""
    weapon_key  = profile_params.get("start_weapon", "dagger")
    armor_key   = profile_params.get("start_armor",  "leather")
    # Map human-readable names to subtype keys
    name_to_subtype = {
        "dagger":       "dagger",
        "short sword":  "short_sword",
        "mace":         "mace",
        "long sword":   "long_sword",
        "leather":      "leather",
        "chain":        "chain",
    }
    weapon = make_item(name_to_subtype.get(weapon_key, "dagger"))
    armor  = make_item(name_to_subtype.get(armor_key,  "leather"))
    return weapon, armor


# ---------------------------------------------------------------------------
# Map placement
# ---------------------------------------------------------------------------

def spawn_items(game: "GameState", rng: random.Random) -> None:
    """Place 0-3 items per level in random room floor cells."""
    from core.systems.make_brains.nethack.dungeon import Tile

    n = rng.randint(0, 3)
    candidates = [
        (x, y)
        for x in range(len(game.level.grid))
        for y in range(len(game.level.grid[0]))
        if game.level.grid[x][y] == Tile.FLOOR
        and (x, y) != game.level.spawn_pos
        and (x, y) != game.level.stairs_pos
    ]
    rng.shuffle(candidates)

    # Weighted pool: favor weapons and potions
    pool = (
        ["dagger"] * 2 + ["short_sword"] + ["mace"] + ["long_sword"]
        + ["leather"] + ["chain"]
        + ["healing"] * 3 + ["gain_level"]
        + ["identify"] + ["teleport"]
        + ["gold"] * 3
    )

    for i in range(min(n, len(candidates))):
        pos = candidates[i]
        subtype = rng.choice(pool)
        quantity = rng.randint(5, 50) if subtype == "gold" else 1
        item = make_item(subtype, pos[0], pos[1], quantity)
        game.items.append(item)


# ---------------------------------------------------------------------------
# Monster drops
# ---------------------------------------------------------------------------

# Kinds that drop items 50% of the time
DROP_KINDS: frozenset[str] = frozenset({"orc", "gnome"})

DROP_POOL: list[str] = [
    "dagger", "short_sword", "healing", "gold", "gold", "identify",
]


def monster_drop(
    game: "GameState",
    monster: "Monster",
    rng: random.Random,
) -> None:
    """Maybe drop an item at the monster's position."""
    if monster.kind not in DROP_KINDS:
        return
    if rng.random() >= 0.5:
        return
    subtype = rng.choice(DROP_POOL)
    quantity = rng.randint(5, 30) if subtype == "gold" else 1
    item = make_item(subtype, monster.x, monster.y, quantity)
    game.items.append(item)


# ---------------------------------------------------------------------------
# Inventory commands (called from engine.py)
# ---------------------------------------------------------------------------

def cmd_wield(game: "GameState") -> None:
    """Select a weapon from inventory and equip it."""
    weapons = game.player.inventory_by_kind(KIND_WEAPON)
    if not weapons:
        game.log("You have no weapons to wield.")
        return
    # Auto-pick first available weapon for V1 (no interactive menu)
    letter, weapon = weapons[0]
    game.player.equipped_weapon = weapon
    game.log(f"You wield the {weapon.name} ({letter}).")


def cmd_wear(game: "GameState") -> None:
    """Select armor from inventory and wear it, recomputing AC."""
    armors = game.player.inventory_by_kind(KIND_ARMOR)
    if not armors:
        game.log("You have no armor to wear.")
        return
    letter, armor = armors[0]
    # Remove previous armor's AC bonus before applying new one
    if game.player.equipped_armor is not None:
        game.player.ac -= game.player.equipped_armor.ac_bonus
    game.player.equipped_armor = armor
    game.player.ac += armor.ac_bonus
    game.log(f"You wear the {armor.name} ({letter}). AC is now {game.player.ac}.")


def cmd_quaff(game: "GameState") -> None:
    """Quaff a potion from inventory."""
    potions = game.player.inventory_by_kind(KIND_POTION)
    if not potions:
        game.log("You have no potions to quaff.")
        return
    letter, potion = potions[0]
    game.player.inventory_remove(letter)
    _apply_potion(game, potion)


def _apply_potion(game: "GameState", potion: Item) -> None:
    from core.systems.make_brains.nethack.combat import roll
    if potion.subtype == "healing":
        heal = roll("1d8")
        game.player.hp = min(game.player.max_hp, game.player.hp + heal)
        game.log(f"You feel better! (+{heal} HP)")
    elif potion.subtype == "gain_level":
        from core.systems.make_brains.nethack.combat import _check_level_up, _xp_for_level
        # Jump XP to the threshold for the next level
        next_level_xp = _xp_for_level(game.player.level + 1)
        game.player.xp = max(game.player.xp, next_level_xp)
        _check_level_up(game)
        game.log("You feel more experienced!")
    else:
        game.log(f"You quaff the {potion.name}.")


def cmd_read(game: "GameState") -> None:
    """Read a scroll from inventory."""
    scrolls = game.player.inventory_by_kind(KIND_SCROLL)
    if not scrolls:
        game.log("You have no scrolls to read.")
        return
    letter, scroll = scrolls[0]
    game.player.inventory_remove(letter)
    _apply_scroll(game, scroll)


def _apply_scroll(game: "GameState", scroll: Item) -> None:
    if scroll.subtype == "identify":
        # No-op in V1 (no unidentified items)
        game.log("This is a scroll of identify. (No effect in V1)")
    elif scroll.subtype == "teleport":
        import random as _rnd
        passable = game.level.all_passable_positions()
        if passable:
            rng = _rnd.Random()
            pos = rng.choice(passable)
            game.player.x, game.player.y = pos
            game.log("You feel a wrenching sensation — you teleport!")
        else:
            game.log("Nothing happens.")
    else:
        game.log(f"You read the {scroll.name}.")
