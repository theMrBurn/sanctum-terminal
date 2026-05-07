"""combat.py — Combat resolution: to-hit, damage, kill, XP, level-up.

NetHack-style combat math:
  to-hit: d20 + level + Str_bonus + weapon_bonus >= target_AC
  damage: weapon_dice + Str_bonus, minimum 1

Monster AI calls resolve_monster_attack(game, monster).
Player bump calls resolve_player_attack(game, monster).

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 5.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.systems.make_brains.nethack.engine import GameState
    from core.systems.make_brains.nethack.entities import Monster, Player


# ---------------------------------------------------------------------------
# Dice roller
# ---------------------------------------------------------------------------

def roll(dice_str: str, rng: random.Random | None = None) -> int:
    """Roll dice expressed as NdM (e.g. '1d8', '2d6').

    Returns the sum of N rolls of an M-sided die.
    """
    rng = rng or random.Random()
    count, sides = dice_str.split("d")
    n, m = int(count), int(sides)
    return sum(rng.randint(1, m) for _ in range(n))


# ---------------------------------------------------------------------------
# XP level-up table — classic NetHack: level N requires 2^(N-1) * 100 XP
# ---------------------------------------------------------------------------

def _xp_for_level(level: int) -> int:
    return (2 ** (level - 1)) * 100


def _check_level_up(game: "GameState", rng: random.Random | None = None) -> None:
    """Grant a level-up if the player has enough XP."""
    rng = rng or random.Random()
    player = game.player
    while player.xp >= _xp_for_level(player.level + 1):
        player.level += 1
        hp_gain = roll("1d8", rng) + player.con_bonus
        hp_gain = max(1, hp_gain)
        player.max_hp += hp_gain
        player.hp = player.max_hp   # full heal on level-up
        game.handler._run_metrics["level"] = player.level
        game.handler._emit_event(
            "level_up",
            new_level=player.level,
            hp_gain=hp_gain,
        )
        game.log(
            f"You advance to experience level {player.level}! "
            f"(+{hp_gain} HP)"
        )


# ---------------------------------------------------------------------------
# Player attacks monster
# ---------------------------------------------------------------------------

def resolve_player_attack(
    game: "GameState",
    monster: "Monster",
    rng: random.Random | None = None,
) -> None:
    """Resolve one player melee attack against monster."""
    rng = rng or random.Random()
    player = game.player

    to_hit = rng.randint(1, 20) + player.level + player.str_bonus + player.weapon_bonus
    if to_hit >= monster.ac:
        dmg = max(1, roll(player.weapon_damage, rng) + player.str_bonus)
        monster.hp -= dmg
        game.log(f"You hit the {monster.name} for {dmg} damage.")
        if monster.hp <= 0:
            _kill_monster(game, monster, rng)
    else:
        game.log(f"You miss the {monster.name}.")


def _kill_monster(
    game: "GameState",
    monster: "Monster",
    rng: random.Random,
) -> None:
    monster.alive = False
    xp_gain = monster.xp_value
    game.player.xp += xp_gain
    game.handler._run_metrics["monsters_killed"] += 1
    game.handler._emit_event(
        "monster_killed",
        monster_kind=monster.kind,
        depth=game.dlvl,
        xp_gain=xp_gain,
    )
    game.log(f"The {monster.name} dies! (+{xp_gain} XP)")

    # Item drops (wired in PR 6)
    try:
        from core.systems.make_brains.nethack.items import monster_drop
        monster_drop(game, monster, rng)
    except (ImportError, AttributeError):
        pass

    _check_level_up(game, rng)


# ---------------------------------------------------------------------------
# Monster attacks player
# ---------------------------------------------------------------------------

def resolve_monster_attack(
    game: "GameState",
    monster: "Monster",
    rng: random.Random | None = None,
) -> None:
    """Resolve one monster melee attack against the player."""
    rng = rng or random.Random()
    player = game.player

    to_hit = rng.randint(1, 20) + 1   # monsters use level=1 equivalent
    if to_hit >= player.ac:
        dmg = max(1, roll(monster.attack_dice, rng))
        player.hp -= dmg
        game.log(f"The {monster.name} hits you for {dmg} damage.")
        if player.hp <= 0:
            player.cause_of_death = f"killed by a {monster.name}"
            game.alive = False
            game.log(f"You die... killed by a {monster.name}.")
    else:
        game.log(f"The {monster.name} misses you.")
