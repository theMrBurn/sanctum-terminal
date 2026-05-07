"""PR 4 tests — Player + Monster entities.

Validates:
  - Player stat initialization from profile params.
  - Stat bonus derivation (NetHack classic table).
  - Inventory: letter assignment stable, max 26 slots.
  - Monster placement: no overlap, not in spawn room.
  - Bestiary covers depths 1-8 (at least one kind per bucket).
  - Bump-to-attack dispatches the attack resolver.

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 4.
"""
from __future__ import annotations

import random
import pytest

from core.systems.make_brains.nethack.entities import (
    BESTIARY,
    DEPTH_POOL,
    INVENTORY_MAX,
    Player,
    Monster,
    _stat_bonus,
    _monster_pool_for_depth,
    make_player,
    spawn_monster,
    spawn_monsters,
)
from core.systems.make_brains.nethack.dungeon import generate_level


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_player(**overrides) -> Player:
    defaults = dict(x=5, y=5)
    defaults.update(overrides)
    return Player(**defaults)


def _fake_game(seed: int = 42):
    """Minimal game-state duck-type for spawn_monsters tests."""
    class _FakeHandler:
        _run_metrics: dict = {}
        def _emit_event(self, *a, **kw): pass

    level = generate_level(seed)

    class _FakeGame:
        pass

    g = _FakeGame()
    g.handler = _FakeHandler()
    g.dlvl = 1
    g.seed = seed
    g.turn = 0
    g.level = level
    g.monsters = []
    g.items = []
    g.player = Player(x=level.spawn_pos[0], y=level.spawn_pos[1])
    return g


# ---------------------------------------------------------------------------
# Stat bonus
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stat,expected", [
    (3,  -3), (4, -2), (5, -2), (6, -1), (7, -1), (8, 0), (9, 0), (14, 0),
    (15, 1), (17, 1), (18, 2), (19, 3), (25, 3),
])
def test_stat_bonus_table(stat: int, expected: int):
    assert _stat_bonus(stat) == expected


# ---------------------------------------------------------------------------
# Player initialization
# ---------------------------------------------------------------------------

def test_player_default_stats():
    p = Player()
    assert p.str_    == 16
    assert p.dex     == 12
    assert p.con     == 14
    assert p.hp      == 12
    assert p.max_hp  == 12
    assert p.ac      == 9
    assert p.level   == 1
    assert p.xp      == 0


def test_make_player_from_profile_params():
    params = {
        "start_str": 18, "start_dex": 14, "start_con": 16,
        "start_int": 10, "start_wis": 10, "start_cha": 10,
        "start_hp": 15, "start_ac": 8, "fov_radius": 8,
    }
    p = make_player(params, x=3, y=7)
    assert p.str_ == 18
    assert p.con  == 16
    assert p.hp   == 15
    assert p.max_hp == 15
    assert p.ac   == 8
    assert p.x    == 3
    assert p.y    == 7


def test_player_str_bonus_propagates():
    p = Player(str_=18)
    assert p.str_bonus == 2


def test_player_con_bonus_propagates():
    p = Player(con=16)
    assert p.con_bonus == 1


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

def test_inventory_add_assigns_letters():
    p = Player()

    class _FakeItem:
        kind = "weapon"

    items = [_FakeItem() for _ in range(3)]
    letters = [p.inventory_add(it) for it in items]
    assert letters == list("abc")
    assert len(p.inventory) == 3


def test_inventory_letters_stable_after_remove():
    p = Player()

    class _FakeItem:
        kind = "weapon"

    a = _FakeItem()
    b = _FakeItem()
    c = _FakeItem()
    la = p.inventory_add(a)
    lb = p.inventory_add(b)
    lc = p.inventory_add(c)
    assert la == "a"
    p.inventory_remove(lb)   # remove 'b'
    d = _FakeItem()
    ld = p.inventory_add(d)
    # 'b' slot should be reused
    assert ld == "b"


def test_inventory_max_26_slots():
    p = Player()

    class _FakeItem:
        kind = "junk"

    for _ in range(INVENTORY_MAX):
        p.inventory_add(_FakeItem())
    overflow = p.inventory_add(_FakeItem())
    assert overflow is None
    assert len(p.inventory) == INVENTORY_MAX


def test_inventory_by_kind():
    p = Player()

    class _FakeWeapon:
        kind = "weapon"

    class _FakePotion:
        kind = "potion"

    p.inventory_add(_FakeWeapon())
    p.inventory_add(_FakePotion())
    p.inventory_add(_FakeWeapon())

    weapons = p.inventory_by_kind("weapon")
    potions = p.inventory_by_kind("potion")
    assert len(weapons) == 2
    assert len(potions) == 1


# ---------------------------------------------------------------------------
# Bestiary
# ---------------------------------------------------------------------------

def test_bestiary_covers_required_kinds():
    kinds = {b["kind"] for b in BESTIARY}
    required = {"newt", "grid_bug", "sewer_rat", "kobold", "jackal",
                "giant_rat", "orc", "gnome"}
    assert required <= kinds


def test_depth_pool_covers_shallow_mid_deep():
    shallow = _monster_pool_for_depth(1)
    mid     = _monster_pool_for_depth(4)
    deep    = _monster_pool_for_depth(7)
    assert "newt"      in shallow or "sewer_rat" in shallow
    assert "kobold"    in mid     or "giant_rat"  in mid
    assert "orc"       in deep    or "gnome"      in deep


@pytest.mark.parametrize("dlvl,expected_kind", [
    (1, "newt"), (2, "sewer_rat"), (4, "kobold"), (6, "orc"),
])
def test_spawn_pool_correct_for_depth(dlvl: int, expected_kind: str):
    pool = _monster_pool_for_depth(dlvl)
    assert expected_kind in pool


# ---------------------------------------------------------------------------
# Monster instance
# ---------------------------------------------------------------------------

def test_spawn_monster_fields():
    rng = random.Random(42)
    m = spawn_monster("newt", 5, 3, rng)
    assert m.name  == "newt"
    assert m.glyph == ":"
    assert m.x     == 5
    assert m.y     == 3
    assert m.hp    > 0
    assert m.alive is True
    assert m.ai_state == "wander"


def test_spawn_monster_unknown_kind_raises():
    with pytest.raises(KeyError):
        spawn_monster("dragon", 0, 0, random.Random())


# ---------------------------------------------------------------------------
# Monster placement (spawn_monsters)
# ---------------------------------------------------------------------------

def test_spawn_monsters_no_overlap(tmp_path, monkeypatch):
    """No two monsters should occupy the same cell."""
    game = _fake_game(seed=42)
    rng = random.Random(42)
    spawn_monsters(game, rng)

    positions = [(m.x, m.y) for m in game.monsters]
    assert len(positions) == len(set(positions)), "monster overlap detected"


def test_spawn_monsters_count_in_range(tmp_path):
    for seed in range(5):
        game = _fake_game(seed=seed)
        rng = random.Random(seed)
        spawn_monsters(game, rng)
        assert 3 <= len(game.monsters) <= 6, (
            f"seed={seed}: spawned {len(game.monsters)} monsters"
        )


def test_spawn_monsters_not_in_spawn_room():
    """Monsters should not be placed in the spawn room (room 0)."""
    game = _fake_game(seed=99)
    rng = random.Random(99)
    spawn_monsters(game, rng)

    spawn_room = game.level.rooms[0]
    spawn_cells = set(spawn_room.inner_cells())
    for m in game.monsters:
        assert (m.x, m.y) not in spawn_cells, (
            f"monster at {(m.x, m.y)} is inside spawn room"
        )


def test_spawn_monsters_on_passable_tiles():
    game = _fake_game(seed=77)
    rng = random.Random(77)
    spawn_monsters(game, rng)

    for m in game.monsters:
        assert game.level.passable(m.x, m.y), (
            f"monster at ({m.x},{m.y}) is on a non-passable tile"
        )


# ---------------------------------------------------------------------------
# Bump-to-attack dispatches the resolver
# ---------------------------------------------------------------------------

def test_bump_dispatches_attack(tmp_path, monkeypatch):
    """Moving into a monster's cell should trigger an attack, not a move."""
    from core.systems.make_brains.nethack.engine import GameState
    from core.systems import make_brain_registry
    from core.systems.make_brains import nethack as _nethack
    from core.vault import vault as Vault

    make_brain_registry._reset_for_tests()
    v = Vault(db_path=str(tmp_path / "vault.db"))
    spec = _nethack.activate(v)
    handler = spec.handler
    handler.start_run()

    game = GameState(handler, seed=42)
    # Force a monster adjacent to the player
    game.monsters = []
    px, py = game.player.x, game.player.y
    monster = spawn_monster("newt", px + 1, py, random.Random(0))
    game.monsters.append(monster)

    attacked: list[bool] = []

    # Patch the combat resolver to track the call
    import core.systems.make_brains.nethack.combat as _combat

    original = _combat.resolve_player_attack

    def _spy(g, m, rng=None):
        attacked.append(True)
        original(g, m, rng)

    monkeypatch.setattr(_combat, "resolve_player_attack", _spy)

    # Move east (into the monster's cell)
    game.handle_command("move_e")

    assert len(attacked) >= 1, "bump did not call resolve_player_attack"
    # Player position must NOT have changed (we attacked, not moved)
    assert game.player.x == px
    assert game.player.y == py

    make_brain_registry._reset_for_tests()
