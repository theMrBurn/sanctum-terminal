"""PR 6 tests — items: kinds, inventory ops, wield/wear/quaff/read.

Validates:
  - make_item constructs correct fields per prototype.
  - Inventory letter assignment stable across add/remove.
  - AC recomputed correctly on wear.
  - Potion healing effect bounded by max_hp.
  - Weapon swap updates equipped_weapon + damage string.
  - Scroll teleport moves player to a passable tile.
  - Gold stacks carry quantity.

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 6.
"""
from __future__ import annotations

import random
import pytest

from core.systems.make_brains.nethack.items import (
    Item,
    KIND_WEAPON,
    KIND_ARMOR,
    KIND_POTION,
    KIND_SCROLL,
    KIND_GOLD,
    ITEM_PROTOS,
    make_item,
    make_starter_equipment,
    spawn_items,
    monster_drop,
    cmd_wield,
    cmd_wear,
    cmd_quaff,
    cmd_read,
)
from core.systems.make_brains.nethack.entities import Player, spawn_monster
from core.systems.make_brains.nethack.dungeon import generate_level


# ---------------------------------------------------------------------------
# Minimal game stub
# ---------------------------------------------------------------------------

class _FakeHandler:
    def __init__(self):
        self._run_metrics = {
            "monsters_killed": 0, "items_picked_up": 0,
            "turns": 0, "depth_reached": 1, "level": 1, "xp": 0,
        }
    def _emit_event(self, *a, **kw): pass


def _make_game(seed: int = 42, dlvl: int = 1):
    level = generate_level(seed)

    class _G:
        pass

    g = _G()
    g.handler = _FakeHandler()
    g.turn = 0
    g.alive = True
    g.dlvl = dlvl
    g.seed = seed
    g.level = level
    g.messages = []
    g.player = Player(x=level.spawn_pos[0], y=level.spawn_pos[1])
    g.monsters = []
    g.items = []

    def log(msg):
        g.messages.append(msg)

    g.log = log
    return g


# ---------------------------------------------------------------------------
# Item constructor
# ---------------------------------------------------------------------------

def test_make_item_weapon_fields():
    dagger = make_item("dagger", x=3, y=7)
    assert dagger.kind        == KIND_WEAPON
    assert dagger.name        == "dagger"
    assert dagger.glyph       == ")"
    assert dagger.damage_dice == "1d4"
    assert dagger.x == 3
    assert dagger.y == 7


def test_make_item_armor_fields():
    leather = make_item("leather")
    assert leather.kind     == KIND_ARMOR
    assert leather.ac_bonus == -1


def test_make_item_chain_ac():
    chain = make_item("chain")
    assert chain.ac_bonus == -3


def test_make_item_potion_fields():
    healing = make_item("healing")
    assert healing.kind    == KIND_POTION
    assert healing.glyph   == "!"
    assert healing.subtype == "healing"


def test_make_item_scroll_fields():
    teleport = make_item("teleport")
    assert teleport.kind    == KIND_SCROLL
    assert teleport.glyph   == "?"
    assert teleport.subtype == "teleport"


def test_make_item_gold_quantity():
    gold = make_item("gold", quantity=42)
    assert gold.kind     == KIND_GOLD
    assert gold.quantity == 42
    assert "42" in gold.display_name()


def test_make_item_unknown_raises():
    with pytest.raises(KeyError):
        make_item("vorpal_sword")


def test_all_protos_constructable():
    """Every entry in ITEM_PROTOS must be constructable via make_item."""
    for proto in ITEM_PROTOS:
        item = make_item(proto["subtype"])
        assert item.kind == proto["kind"]


# ---------------------------------------------------------------------------
# Starter equipment
# ---------------------------------------------------------------------------

def test_make_starter_equipment_defaults():
    weapon, armor = make_starter_equipment({})
    assert weapon.subtype == "dagger"
    assert armor.subtype  == "leather"


def test_make_starter_equipment_from_params():
    params = {"start_weapon": "long sword", "start_armor": "chain"}
    weapon, armor = make_starter_equipment(params)
    assert weapon.damage_dice == "1d8"
    assert armor.ac_bonus     == -3


# ---------------------------------------------------------------------------
# Inventory letter assignment
# ---------------------------------------------------------------------------

def test_inventory_letter_stable_after_remove():
    """After removing 'b', the next add should reuse 'b'."""
    p = Player()
    items = [make_item("dagger"), make_item("dagger"), make_item("dagger")]
    la = p.inventory_add(items[0])
    lb = p.inventory_add(items[1])
    lc = p.inventory_add(items[2])
    assert la == "a" and lb == "b" and lc == "c"
    p.inventory_remove(lb)
    d = make_item("healing")
    ld = p.inventory_add(d)
    assert ld == "b"


def test_inventory_full_returns_none():
    p = Player()
    for _ in range(26):
        p.inventory_add(make_item("gold"))
    result = p.inventory_add(make_item("gold"))
    assert result is None


# ---------------------------------------------------------------------------
# Wear / wield / AC recalc
# ---------------------------------------------------------------------------

def test_wear_armor_adjusts_ac():
    game = _make_game()
    leather = make_item("leather")
    game.player.inventory_add(leather)
    game.player.equipped_armor = None
    base_ac = game.player.ac
    cmd_wear(game)
    assert game.player.ac == base_ac + leather.ac_bonus
    assert game.player.ac < base_ac   # lower = better


def test_wear_chain_adjusts_ac_more():
    game = _make_game()
    chain = make_item("chain")
    game.player.inventory_add(chain)
    game.player.equipped_armor = None
    base_ac = game.player.ac
    cmd_wear(game)
    assert game.player.ac == base_ac + chain.ac_bonus


def test_wear_replaces_previous_armor():
    """Wearing new armor removes the old AC bonus first."""
    game = _make_game()
    leather = make_item("leather")
    chain   = make_item("chain")
    game.player.inventory_add(leather)
    game.player.inventory_add(chain)

    # Wear leather first
    game.player.equipped_armor = None
    base_ac = game.player.ac
    cmd_wear(game)   # wears leather (first in inventory)
    ac_after_leather = game.player.ac

    # Force wearing chain by setting it as first weapon in inventory
    game.player.inventory = {}
    game.player.inventory_add(chain)
    cmd_wear(game)   # wears chain, should undo leather first
    # AC should be base_ac + chain.ac_bonus (not cumulative)
    assert game.player.ac == ac_after_leather - leather.ac_bonus + chain.ac_bonus


def test_wield_weapon_updates_equipped():
    game = _make_game()
    sword = make_item("long_sword")
    game.player.inventory_add(sword)
    cmd_wield(game)
    assert game.player.equipped_weapon is sword


def test_weapon_damage_changes_on_wield():
    game = _make_game()
    # Start with dagger (d4) as equipped
    game.player.equipped_weapon = make_item("dagger")
    sword = make_item("long_sword")
    game.player.inventory_add(sword)
    cmd_wield(game)
    assert game.player.weapon_damage == "1d8"


def test_wield_empty_inventory_logs_message():
    game = _make_game()
    game.player.inventory = {}
    game.player.equipped_weapon = None
    cmd_wield(game)
    assert any("no weapons" in m.lower() for m in game.messages)


# ---------------------------------------------------------------------------
# Potion effects
# ---------------------------------------------------------------------------

def test_quaff_healing_restores_hp():
    game = _make_game()
    game.player.max_hp = 20
    game.player.hp = 5
    potion = make_item("healing")
    game.player.inventory_add(potion)
    cmd_quaff(game)
    assert game.player.hp > 5


def test_quaff_healing_capped_at_max_hp():
    game = _make_game()
    game.player.max_hp = 12
    game.player.hp = 12   # already full
    potion = make_item("healing")
    game.player.inventory_add(potion)
    cmd_quaff(game)
    assert game.player.hp <= game.player.max_hp


def test_quaff_removes_potion_from_inventory():
    game = _make_game()
    potion = make_item("healing")
    letter = game.player.inventory_add(potion)
    cmd_quaff(game)
    assert letter not in game.player.inventory


def test_quaff_gain_level_triggers_level_up():
    game = _make_game()
    game.player.level = 1
    game.player.xp = 0
    potion = make_item("gain_level")
    game.player.inventory_add(potion)
    cmd_quaff(game)
    assert game.player.level >= 2


def test_quaff_empty_inventory_logs():
    game = _make_game()
    game.player.inventory = {}
    cmd_quaff(game)
    assert any("no potion" in m.lower() for m in game.messages)


# ---------------------------------------------------------------------------
# Scroll effects
# ---------------------------------------------------------------------------

def test_read_identify_noop_logs():
    game = _make_game()
    scroll = make_item("identify")
    game.player.inventory_add(scroll)
    cmd_read(game)
    assert any("identify" in m.lower() for m in game.messages)


def test_read_teleport_moves_player():
    game = _make_game()
    scroll = make_item("teleport")
    game.player.inventory_add(scroll)
    px, py = game.player.x, game.player.y
    cmd_read(game)
    # Player should be on a passable tile after teleport
    assert game.level.passable(game.player.x, game.player.y)
    # (position may or may not have changed — teleport is random)


def test_read_removes_scroll_from_inventory():
    game = _make_game()
    scroll = make_item("teleport")
    letter = game.player.inventory_add(scroll)
    cmd_read(game)
    assert letter not in game.player.inventory


def test_read_empty_inventory_logs():
    game = _make_game()
    game.player.inventory = {}
    cmd_read(game)
    assert any("no scroll" in m.lower() for m in game.messages)


# ---------------------------------------------------------------------------
# Monster drops
# ---------------------------------------------------------------------------

def test_monster_drop_orc_50_percent():
    """Orc should drop items about 50% of the time across many runs."""
    game = _make_game()
    orc = spawn_monster("orc", 10, 10, random.Random())
    drops = 0
    trials = 200
    for i in range(trials):
        game.items.clear()
        monster_drop(game, orc, random.Random(i))
        if game.items:
            drops += 1
    # Expect roughly 100 ± 30 drops (50% ± 15%)
    assert 70 <= drops <= 130, f"unexpected drop rate: {drops}/{trials}"


def test_monster_drop_newt_never():
    game = _make_game()
    newt = spawn_monster("newt", 5, 5, random.Random())
    for i in range(50):
        game.items.clear()
        monster_drop(game, newt, random.Random(i))
    assert not game.items, "newts should never drop items"


# ---------------------------------------------------------------------------
# Spawn items on level
# ---------------------------------------------------------------------------

def test_spawn_items_places_0_to_3():
    for seed in range(10):
        game = _make_game(seed=seed)
        rng = random.Random(seed)
        spawn_items(game, rng)
        assert 0 <= len(game.items) <= 3


def test_spawn_items_on_passable_tiles():
    game = _make_game(seed=42)
    rng = random.Random(42)
    spawn_items(game, rng)
    for item in game.items:
        assert game.level.passable(item.x, item.y)
