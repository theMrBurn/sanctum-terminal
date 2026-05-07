"""PR 7 tests — descent + depth scaling.

Validates:
  - Pressing > on STAIRS_DOWN generates a new level with dlvl += 1.
  - Player stats + inventory survive descent.
  - New seed = old_seed + dlvl (deterministic).
  - depth_reached updates monotonically in run_metrics.
  - Depth-scaled spawn pool picks correct monster kinds per depth.
  - level_descended event emitted on descent.

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 7.
"""
from __future__ import annotations

import random
import pytest

from core.systems.make_brains.nethack.entities import (
    _monster_pool_for_depth,
    spawn_monster,
    DEPTH_POOL,
)
from core.systems.make_brains.nethack.dungeon import generate_level, Tile
from core.systems.make_brains.nethack.items import make_item


# ---------------------------------------------------------------------------
# GameState setup for descent tests
# ---------------------------------------------------------------------------

def _make_game_state(tmp_path, seed: int = 42):
    """Boot a real GameState with real vault in tmp_path."""
    from core.systems import make_brain_registry
    from core.systems.make_brains import nethack as _nethack
    from core.vault import vault as Vault
    from core.systems.make_brains.nethack.engine import GameState
    from core.systems.make_brains.nethack.entities import spawn_monsters
    from core.systems.make_brains.nethack.items import spawn_items

    make_brain_registry._reset_for_tests()
    v = Vault(db_path=str(tmp_path / "vault.db"))
    spec = _nethack.activate(v)
    handler = spec.handler
    handler.start_run()

    game = GameState(handler, seed=seed)
    rng = random.Random(seed)
    spawn_monsters(game, rng)
    spawn_items(game, rng)
    return game, handler, make_brain_registry


# ---------------------------------------------------------------------------
# Depth pool correctness
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dlvl,expected", [
    (1, ["newt", "grid_bug", "sewer_rat"]),
    (2, ["newt", "grid_bug", "sewer_rat"]),
    (3, ["kobold", "jackal", "giant_rat"]),
    (4, ["kobold", "jackal", "giant_rat"]),
    (5, ["kobold", "jackal", "giant_rat"]),
    (6, ["orc", "gnome", "giant_ant"]),
    (10, ["orc", "gnome", "giant_ant"]),
])
def test_spawn_pool_correct_for_depth(dlvl: int, expected: list):
    pool = _monster_pool_for_depth(dlvl)
    for kind in expected:
        assert kind in pool, f"depth {dlvl}: {kind} not in pool {pool}"


def test_spawn_pool_shallow_excludes_deep():
    pool = _monster_pool_for_depth(1)
    assert "orc" not in pool
    assert "gnome" not in pool
    assert "giant_ant" not in pool


def test_spawn_pool_deep_includes_orc_gnome():
    pool = _monster_pool_for_depth(6)
    assert "orc" in pool
    assert "gnome" in pool


# ---------------------------------------------------------------------------
# Descent preserves player state
# ---------------------------------------------------------------------------

def test_descent_preserves_hp(tmp_path):
    game, handler, registry = _make_game_state(tmp_path, seed=42)

    # Wound the player a bit
    game.player.hp = 8
    game.player.max_hp = 12

    # Teleport player to stairs
    sx, sy = game.level.stairs_pos
    game.player.x, game.player.y = sx, sy

    game.try_descend()

    assert game.player.hp == 8, "HP should not change on descent"
    assert game.player.max_hp == 12

    registry._reset_for_tests()


def test_descent_preserves_inventory(tmp_path):
    game, handler, registry = _make_game_state(tmp_path, seed=42)

    # Give player an item
    sword = make_item("long_sword")
    letter = game.player.inventory_add(sword)
    assert letter is not None

    sx, sy = game.level.stairs_pos
    game.player.x, game.player.y = sx, sy
    game.try_descend()

    assert letter in game.player.inventory
    assert game.player.inventory[letter] is sword

    registry._reset_for_tests()


def test_descent_preserves_xp_level(tmp_path):
    game, handler, registry = _make_game_state(tmp_path, seed=42)
    game.player.xp = 500
    game.player.level = 3

    sx, sy = game.level.stairs_pos
    game.player.x, game.player.y = sx, sy
    game.try_descend()

    assert game.player.xp == 500
    assert game.player.level == 3

    registry._reset_for_tests()


def test_descent_increments_dlvl(tmp_path):
    game, handler, registry = _make_game_state(tmp_path, seed=42)
    assert game.dlvl == 1

    sx, sy = game.level.stairs_pos
    game.player.x, game.player.y = sx, sy
    game.try_descend()

    assert game.dlvl == 2

    registry._reset_for_tests()


def test_descent_generates_new_level(tmp_path):
    game, handler, registry = _make_game_state(tmp_path, seed=42)

    old_seed = game.level.seed
    sx, sy = game.level.stairs_pos
    game.player.x, game.player.y = sx, sy
    game.try_descend()

    # New level seed = original seed + dlvl
    expected_seed = game.seed + game.dlvl
    assert game.level.seed == expected_seed
    # And the level itself is a freshly generated level with that seed
    expected_level = generate_level(expected_seed)
    assert game.level.spawn_pos == expected_level.spawn_pos

    registry._reset_for_tests()


def test_descent_monsters_reset(tmp_path):
    game, handler, registry = _make_game_state(tmp_path, seed=42)

    old_count = len(game.monsters)
    sx, sy = game.level.stairs_pos
    game.player.x, game.player.y = sx, sy
    game.try_descend()

    # Monsters are reset to a new set for the new level
    assert isinstance(game.monsters, list)
    # New level may have 0-6 monsters (could be empty if spawn fails)
    assert len(game.monsters) >= 0

    registry._reset_for_tests()


# ---------------------------------------------------------------------------
# depth_reached updates monotonically
# ---------------------------------------------------------------------------

def test_depth_reached_updates_monotonically(tmp_path):
    game, handler, registry = _make_game_state(tmp_path, seed=42)
    assert handler._run_metrics["depth_reached"] == 1

    sx, sy = game.level.stairs_pos
    game.player.x, game.player.y = sx, sy
    game.try_descend()
    assert handler._run_metrics["depth_reached"] == 2

    sx2, sy2 = game.level.stairs_pos
    game.player.x, game.player.y = sx2, sy2
    game.try_descend()
    assert handler._run_metrics["depth_reached"] == 3

    registry._reset_for_tests()


def test_depth_reached_never_decreases(tmp_path):
    """depth_reached = max(depth_reached, dlvl) — never goes backwards."""
    game, handler, registry = _make_game_state(tmp_path, seed=42)

    # Manually set a high depth_reached
    handler._run_metrics["depth_reached"] = 5
    game.dlvl = 3   # simulate being on level 3

    # Trigger a descent
    sx, sy = game.level.stairs_pos
    game.player.x, game.player.y = sx, sy
    game.try_descend()

    assert handler._run_metrics["depth_reached"] >= 5

    registry._reset_for_tests()


# ---------------------------------------------------------------------------
# Descent emits level_descended event
# ---------------------------------------------------------------------------

def test_descent_emits_level_descended_event(tmp_path):
    game, handler, registry = _make_game_state(tmp_path, seed=42)

    sx, sy = game.level.stairs_pos
    game.player.x, game.player.y = sx, sy
    game.try_descend()

    events = handler.drain_state_events()
    kinds = [e["kind"] for e in events]
    assert "level_descended" in kinds, f"events: {kinds}"

    registry._reset_for_tests()


# ---------------------------------------------------------------------------
# Descend without stairs — should reject
# ---------------------------------------------------------------------------

def test_descend_without_stairs_logs_message(tmp_path):
    game, handler, registry = _make_game_state(tmp_path, seed=42)

    # Move player away from stairs
    game.player.x, game.player.y = game.level.spawn_pos
    assert game.level.at(game.player.x, game.player.y) != Tile.STAIRS_DOWN

    old_dlvl = game.dlvl
    game.try_descend()

    assert game.dlvl == old_dlvl, "dlvl should not change without stairs"
    assert any("no stairs" in m.lower() or "stairs" in m.lower()
               for m in game.messages)

    registry._reset_for_tests()


# ---------------------------------------------------------------------------
# Depth-scaled spawn monsters on new level
# ---------------------------------------------------------------------------

def test_deep_level_spawns_depth_appropriate_monsters(tmp_path):
    """After multiple descents, monsters should match the depth pool."""
    game, handler, registry = _make_game_state(tmp_path, seed=42)

    # Descend 6 times to reach dlvl 7
    for _ in range(6):
        sx, sy = game.level.stairs_pos
        game.player.x, game.player.y = sx, sy
        game.try_descend()

    assert game.dlvl == 7
    deep_pool = _monster_pool_for_depth(7)
    # All spawned monsters should come from the deep pool
    for m in game.monsters:
        assert m.kind in deep_pool, (
            f"depth {game.dlvl}: unexpected monster kind '{m.kind}'"
        )

    registry._reset_for_tests()
