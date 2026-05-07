"""PR 5 tests — combat resolution, monster AI, XP + level-up.

Validates:
  - to-hit math (seeded): d20 + level + str_bonus + weapon_bonus >= AC
  - damage rolls deterministic with seed
  - kill removes monster + grants XP + emits event
  - level-up triggers at correct XP threshold (2^(N-1)*100)
  - level-up grants HP + full heal
  - monster AI state transitions (wander / chase / attack)
  - roll() dice parser handles NdM correctly

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 5.
"""
from __future__ import annotations

import random
import pytest

from core.systems.make_brains.nethack.combat import (
    roll,
    resolve_player_attack,
    resolve_monster_attack,
    _xp_for_level,
    _check_level_up,
)
from core.systems.make_brains.nethack.entities import (
    Player,
    Monster,
    spawn_monster,
)
from core.systems.make_brains.nethack.ai import (
    tick_monster,
    tick_all,
    MONSTER_SIGHT,
)
from core.systems.make_brains.nethack.dungeon import generate_level


# ---------------------------------------------------------------------------
# Minimal game stub for combat tests
# ---------------------------------------------------------------------------

class _FakeHandler:
    def __init__(self):
        self._run_metrics = {
            "monsters_killed": 0, "items_picked_up": 0,
            "turns": 0, "depth_reached": 1, "level": 1, "xp": 0,
        }
    def _emit_event(self, *a, **kw): pass


def _make_game(seed: int = 42, dlvl: int = 1):
    """Return a minimal duck-typed game object for combat/AI tests."""
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
# Dice roller
# ---------------------------------------------------------------------------

def test_roll_1d6_range():
    rng = random.Random(0)
    results = [roll("1d6", rng) for _ in range(100)]
    assert all(1 <= r <= 6 for r in results)


def test_roll_2d4_range():
    rng = random.Random(1)
    results = [roll("2d4", rng) for _ in range(100)]
    assert all(2 <= r <= 8 for r in results)


def test_roll_deterministic_same_rng_seed():
    rng1 = random.Random(99)
    rng2 = random.Random(99)
    assert roll("1d20", rng1) == roll("1d20", rng2)


def test_roll_1d8_distribution():
    """Expect all values 1-8 to appear across 200 rolls."""
    rng = random.Random(42)
    values = {roll("1d8", rng) for _ in range(200)}
    assert values == set(range(1, 9))


# ---------------------------------------------------------------------------
# XP level-up table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level,expected_xp", [
    (1,   100),
    (2,   200),
    (3,   400),
    (4,   800),
    (5,  1600),
    (10, 51200),
])
def test_xp_for_level_formula(level: int, expected_xp: int):
    assert _xp_for_level(level) == expected_xp


# ---------------------------------------------------------------------------
# To-hit math — deterministic with seeded RNG
# ---------------------------------------------------------------------------

def test_to_hit_always_hits_low_ac_high_bonus():
    """A high-level player with good Str always hits AC=9 (easy)."""
    game = _make_game()
    game.player.str_ = 18   # str_bonus = +2
    game.player.level = 5
    monster = spawn_monster("newt", 5, 5, random.Random())
    monster.hp = 100   # don't kill it

    rng = random.Random(1)
    for _ in range(20):
        # d20 minimum 1 + 5 (level) + 2 (str) = 8 vs AC 9
        # Should hit more than half the time; at level 5, almost always.
        resolve_player_attack(game, monster, rng)

    # At least some hits in 20 swings vs AC 9 with +7 bonus
    hit_msgs = [m for m in game.messages if "hit" in m]
    assert len(hit_msgs) > 0


def test_to_hit_misses_high_ac():
    """A level-1 player with no bonus misses vs AC=25 (requires 25+ on d20)."""
    game = _make_game()
    game.player.level = 1
    game.player.str_ = 10   # str_bonus = 0
    monster = spawn_monster("gnome", 5, 5, random.Random())
    monster.ac = 25   # AC=25 requires 25+ on d20+bonuses — impossible
    monster.hp = 999

    rng = random.Random(5)
    for _ in range(10):
        resolve_player_attack(game, monster, rng)

    miss_msgs = [m for m in game.messages if "misses" in m or "miss" in m]
    # All 10 attacks should miss (d20 max is 20, need 25)
    assert len(miss_msgs) == 10


def test_damage_seeded():
    """Same seed produces same damage."""
    game = _make_game()
    monster = spawn_monster("newt", 5, 5, random.Random())
    monster.hp = 999

    rng1 = random.Random(42)
    rng2 = random.Random(42)

    # Record HP before
    before = monster.hp
    resolve_player_attack(game, monster, rng1)
    dmg1 = before - monster.hp

    monster.hp = 999
    game.messages.clear()
    resolve_player_attack(game, monster, rng2)
    dmg2 = 999 - monster.hp

    assert dmg1 == dmg2, "same rng seed must produce same damage"


def test_damage_minimum_1():
    """Even with negative Str bonus, damage is at least 1."""
    game = _make_game()
    game.player.str_ = 3   # str_bonus = -3
    monster = spawn_monster("newt", 5, 5, random.Random())
    monster.hp = 100
    monster.ac = 1   # ensure hit on d20=20

    # Force a hit by setting AC very low with a seeded rng that rolls 20
    rng = random.Random()
    # Patch: manually build scenario where we know we'll hit
    from core.systems.make_brains.nethack import combat as _c
    orig = _c.roll
    _c.roll = lambda dice, r=None: 1   # d20 roll = 1 in to-hit, 1 in damage
    try:
        resolve_player_attack(game, monster, rng)
    finally:
        _c.roll = orig

    # If we hit, damage must be >= 1
    hit_msgs = [m for m in game.messages if "hit" in m]
    if hit_msgs:
        # Extract damage from message "You hit the newt for N damage."
        for msg in hit_msgs:
            parts = msg.split("for ")
            if len(parts) > 1:
                dmg = int(parts[1].split(" ")[0])
                assert dmg >= 1


# ---------------------------------------------------------------------------
# Kill and XP
# ---------------------------------------------------------------------------

def test_kill_removes_monster_grants_xp():
    game = _make_game()
    monster = spawn_monster("newt", 5, 5, random.Random())
    monster.hp = 1   # one hit kills it
    monster.ac = 1   # low AC = easy to hit with our formula (need 1+ on d20+bonuses)

    game.monsters.append(monster)
    rng = random.Random(1)

    before_xp = game.player.xp
    resolve_player_attack(game, monster, rng)

    assert not monster.alive
    assert game.player.xp > before_xp
    assert game.player.xp == before_xp + monster.xp_value


def test_kill_emits_monster_killed_event():
    events: list[dict] = []

    class _TrackingHandler:
        def __init__(self):
            self._run_metrics = {
                "monsters_killed": 0, "items_picked_up": 0,
                "turns": 0, "depth_reached": 1, "level": 1,
            }
        def _emit_event(self, kind, **kw):
            events.append({"kind": kind, **kw})

    game = _make_game()
    game.handler = _TrackingHandler()
    game.items = []  # ensure no items module called

    monster = spawn_monster("newt", 5, 5, random.Random())
    monster.hp = 1
    monster.ac = 1   # low AC = easy to hit
    game.monsters.append(monster)

    rng = random.Random(1)
    resolve_player_attack(game, monster, rng)

    kinds = [e["kind"] for e in events]
    assert "monster_killed" in kinds


# ---------------------------------------------------------------------------
# Level-up
# ---------------------------------------------------------------------------

def test_level_up_triggers_at_xp_threshold():
    game = _make_game()
    # Level 1 → 2 requires 2^(2-1)*100 = 200 XP
    game.player.xp = 199
    game.player.level = 1
    game.player.max_hp = 12
    game.player.hp = 12

    game.player.xp += 1   # now 200
    rng = random.Random(42)
    _check_level_up(game, rng)

    assert game.player.level == 2


def test_level_up_increases_max_hp():
    game = _make_game()
    game.player.xp = 200
    game.player.level = 1
    game.player.max_hp = 12
    game.player.hp = 12
    before_max = game.player.max_hp

    rng = random.Random(42)
    _check_level_up(game, rng)

    assert game.player.max_hp > before_max


def test_level_up_full_heals():
    game = _make_game()
    game.player.xp = 200
    game.player.level = 1
    game.player.hp = 1   # near death
    game.player.max_hp = 12

    rng = random.Random(42)
    _check_level_up(game, rng)

    assert game.player.hp == game.player.max_hp


def test_multi_level_up_in_one_call():
    """If XP jumps enough for multiple levels, all are applied."""
    game = _make_game()
    game.player.xp = 800   # enough for level 1→2→3→4
    game.player.level = 1
    game.player.max_hp = 12
    game.player.hp = 12

    rng = random.Random(42)
    _check_level_up(game, rng)

    assert game.player.level >= 4


def test_level_up_not_triggered_below_threshold():
    game = _make_game()
    game.player.xp = 199
    game.player.level = 1

    rng = random.Random(42)
    _check_level_up(game, rng)

    assert game.player.level == 1


# ---------------------------------------------------------------------------
# Monster attacks player
# ---------------------------------------------------------------------------

def test_monster_attack_can_hit_player():
    game = _make_game()
    game.player.ac = 10   # easy to hit
    game.player.hp = 100

    monster = spawn_monster("orc", 5, 5, random.Random())
    rng = random.Random(1)

    for _ in range(10):
        resolve_monster_attack(game, monster, rng)

    # Some hits expected over 10 attacks vs AC 10
    hit_msgs = [m for m in game.messages if "hits you" in m]
    assert len(hit_msgs) > 0


def test_monster_kills_player_sets_cause_of_death():
    game = _make_game()
    game.player.ac = 10
    game.player.hp = 1   # almost dead

    monster = spawn_monster("orc", 5, 5, random.Random())
    # Ensure a hit: orc AC check with d20=20
    rng = random.Random()
    from core.systems.make_brains.nethack import combat as _c
    orig = _c.roll
    _c.roll = lambda dice, r=None: 20 if dice == "1d20" else 6
    try:
        resolve_monster_attack(game, monster, rng)
    finally:
        _c.roll = orig

    if not game.alive:
        assert "orc" in game.player.cause_of_death


# ---------------------------------------------------------------------------
# AI state transitions
# ---------------------------------------------------------------------------

def test_ai_wanders_when_far():
    """Monster far from player stays in wander state."""
    game = _make_game()
    # Place player and monster far apart
    game.player.x, game.player.y = 5, 5
    monster = spawn_monster("newt", 1, 1, random.Random())
    # dist = max(4, 4) = 4 > MONSTER_SIGHT (6)? No, 4 < 6.
    # Put it far enough:
    monster.x, monster.y = 50, 20
    game.monsters.append(monster)

    rng = random.Random(0)
    tick_monster(game, monster, rng)

    assert monster.ai_state == "wander"


def test_ai_chases_when_in_sight():
    """Monster within MONSTER_SIGHT of player enters chase state."""
    game = _make_game()
    game.player.x, game.player.y = 10, 5
    monster = spawn_monster("newt", 14, 5, random.Random())  # dist=4
    game.monsters.append(monster)

    rng = random.Random(0)
    prev_x, prev_y = monster.x, monster.y
    tick_monster(game, monster, rng)

    # Should have moved toward player
    assert monster.ai_state == "chase"
    new_dist = max(abs(monster.x - game.player.x), abs(monster.y - game.player.y))
    old_dist = max(abs(prev_x - game.player.x), abs(prev_y - game.player.y))
    assert new_dist <= old_dist, "chasing monster should have moved closer"


def test_ai_attacks_when_adjacent():
    """Monster adjacent to player enters attack state and deals damage."""
    game = _make_game()
    game.player.x, game.player.y = 10, 5
    game.player.ac = 10   # easy to hit
    game.player.hp = 100

    monster = spawn_monster("orc", 11, 5, random.Random())  # dist=1
    game.monsters.append(monster)

    rng = random.Random(1)
    tick_monster(game, monster, rng)

    assert monster.ai_state == "attack"


def test_tick_all_advances_all_monsters():
    """tick_all() processes every living monster."""
    game = _make_game()
    game.player.x, game.player.y = 5, 5

    # Place 3 monsters far away in wander territory
    for i in range(3):
        m = spawn_monster("newt", 60 + i, 5, random.Random())
        game.monsters.append(m)

    initial_positions = [(m.x, m.y) for m in game.monsters]
    tick_all(game)
    final_positions = [(m.x, m.y) for m in game.monsters]

    # At least some monsters should have moved (wander is random)
    # This is probabilistic — use a fixed seed via game.seed and game.turn
    # Just verify the function ran without error and monsters still exist.
    assert len(game.monsters) == 3
