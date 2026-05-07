"""ai.py — Monster AI: wander, chase, attack states.

State machine per monster:
  wander: random walk when player is outside FOV radius.
  chase:  greedy step toward player when player is visible.
  attack: bump player when adjacent (calls combat resolver).

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 5.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.systems.make_brains.nethack.engine import GameState
    from core.systems.make_brains.nethack.entities import Monster


# Sight radius for monster: monsters "see" when the player is within this range.
MONSTER_SIGHT: int = 6


def _distance(x1: int, y1: int, x2: int, y2: int) -> int:
    """Chebyshev (chessboard) distance — for adjacency and sight checks."""
    return max(abs(x1 - x2), abs(y1 - y2))


def _step_toward(
    mx: int, my: int,
    px: int, py: int,
    game: "GameState",
    rng: random.Random,
) -> tuple[int, int]:
    """Return one greedy step from (mx, my) toward (px, py).

    Tries the direct cardinal step first; falls back to the other
    cardinal direction; finally tries a random passable step.
    This is intentionally simple (no A*) per spec §PR 5.
    """
    dx = 0 if px == mx else (1 if px > mx else -1)
    dy = 0 if py == my else (1 if py > my else -1)

    # Try the dominant direction first
    for candidate in [(dx, 0), (0, dy), (dx, dy)]:
        cdx, cdy = candidate
        if cdx == 0 and cdy == 0:
            continue
        nx, ny = mx + cdx, my + cdy
        if game.level.passable(nx, ny) and not _occupied_by_monster(game, nx, ny):
            return nx, ny

    # Fallback: random passable neighbor
    dirs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    rng.shuffle(dirs)
    for cdx, cdy in dirs:
        nx, ny = mx + cdx, my + cdy
        if game.level.passable(nx, ny) and not _occupied_by_monster(game, nx, ny):
            return nx, ny

    return mx, my   # stuck


def _occupied_by_monster(game: "GameState", x: int, y: int) -> bool:
    return any(m.x == x and m.y == y and m.alive for m in game.monsters)


def tick_monster(game: "GameState", monster: "Monster", rng: random.Random) -> None:
    """Advance one monster's AI by one step."""
    if not monster.alive:
        return

    from core.systems.make_brains.nethack import combat

    player = game.player
    dist = _distance(monster.x, monster.y, player.x, player.y)

    # Adjacent → attack
    if dist <= 1:
        monster.ai_state = "attack"
        combat.resolve_monster_attack(game, monster, rng)
        return

    # Within sight → chase
    if dist <= MONSTER_SIGHT:
        monster.ai_state = "chase"
        nx, ny = _step_toward(monster.x, monster.y, player.x, player.y, game, rng)
        monster.x, monster.y = nx, ny
        return

    # Otherwise → wander (random walk)
    monster.ai_state = "wander"
    dirs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    rng.shuffle(dirs)
    for dx, dy in dirs:
        nx, ny = monster.x + dx, monster.y + dy
        if game.level.passable(nx, ny) and not _occupied_by_monster(game, nx, ny):
            monster.x, monster.y = nx, ny
            break


def tick_all(game: "GameState") -> None:
    """Tick every living monster. Uses a per-turn RNG seeded by turn count."""
    rng = random.Random(game.turn + game.seed)
    for monster in list(game.monsters):
        if monster.alive:
            tick_monster(game, monster, rng)
