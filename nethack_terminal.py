"""nethack_terminal.py — entry point for the NetHack make-brain.

Standalone curses app.  Runs a full turn-based game loop in the terminal.
Fallback: plain text mode when curses is unavailable (e.g. CI / piped stdin).

Usage:
    PYTHONPATH=. python nethack_terminal.py
    PYTHONPATH=. python nethack_terminal.py --hi-scores
    make brain-nethack

Spec: `.claude/feature/feat_make-brain-nethack.md`.
"""
from __future__ import annotations

import sys
import time
import random
import argparse

from core.systems.make_brains import nethack
from core.vault import vault as Vault


# ---------------------------------------------------------------------------
# Tombstone template (PR 8 renders this on death)
# ---------------------------------------------------------------------------

TOMBSTONE_TEMPLATE = r"""
    ___________
   /           \
  /   R  I  P   \
 /               \
|   {name:^13}  |
|                 |
| Depth: {depth:<7}  |
| Kills: {kills:<7}  |
| Score: {score:<7}  |
|                 |
|  {killer:^15}  |
|                 |
 \_____________/
"""

HI_SCORE_HEADER = (
    "  # | Score  | Dlvl | Kills | Turns | Cause of death"
    "\n" + "-" * 60
)


# ---------------------------------------------------------------------------
# Substrate boot
# ---------------------------------------------------------------------------

def boot(vault_factory=None) -> dict:
    """Boot the substrate: vault, registry, handler, run row.

    vault_factory: optional callable → Vault instance (used by tests).
    Returns a snapshot dict the game loop and tests both inspect.
    """
    vault = (vault_factory or Vault)()
    spec = nethack.activate(vault)
    handler = spec.handler
    handler.start_run()
    snapshot = handler.manifest_keys()
    return {
        "instance_id":     spec.instance_id,
        "entry_point":     spec.entry_point,
        "default_profile": spec.default_profile,
        "active_profile":  handler.active_profile,
        "run_id":          handler._run_id,
        "manifest":        snapshot,
        "handler":         handler,
        "vault":           vault,
    }


# ---------------------------------------------------------------------------
# Hi-score display (PR 8 feature, wired here for --hi-scores flag)
# ---------------------------------------------------------------------------

def show_hi_scores(vault: Vault) -> None:
    runs = vault.runs_by_instance("nethack")
    died = [r for r in runs if r.get("terminal_state") == "died"]
    died.sort(key=lambda r: (r.get("metrics") or {}).get("score", 0), reverse=True)
    top = died[:10]
    print(HI_SCORE_HEADER)
    for i, r in enumerate(top, 1):
        m = r.get("metrics") or {}
        print(
            f"  {i:<2}| {m.get('score', 0):<6} | "
            f"{m.get('depth_reached', 1):<4} | "
            f"{m.get('monsters_killed', 0):<5} | "
            f"{m.get('turns', 0):<5} | "
            f"{m.get('cause_of_death', 'unknown')}"
        )
    if not top:
        print("  (no completed runs yet)")


# ---------------------------------------------------------------------------
# Tombstone render
# ---------------------------------------------------------------------------

def render_tombstone_text(game) -> str:
    """Return ASCII tombstone as a string for display on death."""
    m = game.handler._run_metrics
    score = _compute_score(game)
    killer = getattr(game.player, "cause_of_death", "unknown")
    return TOMBSTONE_TEMPLATE.format(
        name="anon",
        depth=m.get("depth_reached", 1),
        kills=m.get("monsters_killed", 0),
        score=score,
        killer=killer[:15],
    )


def _compute_score(game) -> int:
    """score = xp * 100 + gold + depth_reached * 50"""
    m = game.handler._run_metrics
    gold = getattr(game.player, "gold", 0)
    return (
        game.player.xp * 100
        + gold
        + m.get("depth_reached", 1) * 50
    )


# ---------------------------------------------------------------------------
# Death handling
# ---------------------------------------------------------------------------

def handle_death(game, win, use_curses: bool) -> None:
    """Emit player_died event, store score, show tombstone, end run."""
    score = _compute_score(game)
    game.handler._run_metrics["score"] = score
    game.handler._run_metrics["cause_of_death"] = getattr(
        game.player, "cause_of_death", "unknown"
    )
    game.handler._emit_event(
        "player_died",
        cause=game.player.cause_of_death,
        score=score,
        depth=game.dlvl,
    )

    tombstone = render_tombstone_text(game)

    if use_curses:
        import curses
        win.clear()
        for i, line in enumerate(tombstone.splitlines()):
            try:
                win.addstr(i, 0, line)
            except Exception:
                pass
        win.addstr(
            len(tombstone.splitlines()) + 1, 0,
            "Press any key to exit..."
        )
        win.refresh()
        win.nodelay(False)
        win.getch()
    else:
        print(tombstone)
        print("Press Enter to exit...")
        try:
            input()
        except EOFError:
            pass

    game.handler.end_run(
        terminal_state="died",
        score=score,
        cause_of_death=game.player.cause_of_death,
    )


# ---------------------------------------------------------------------------
# Curses game loop
# ---------------------------------------------------------------------------

def _run_curses_loop(stdscr, game, handler) -> None:
    """Full curses game loop. Runs until player dies or quits."""
    import curses
    from core.systems.make_brains.nethack.render import (
        init_colors, render_frame, MAP_H, MSG_LOG_LINES,
    )
    from core.systems.make_brains.nethack.input_map import build_keymap, CMD_QUIT

    init_colors()
    keymap = build_keymap()

    stdscr.keypad(True)
    curses.curs_set(0)

    game.log("Welcome to Sanctum NetHack!  hjkl or arrows to move.")
    game.log("Press Q to quit.  > to descend stairs.  , to pick up.")

    while game.alive and not game.quit:
        render_frame(
            stdscr, game.level,
            game.visible, game.visited,
            game.player, game.dlvl, game.turn,
            game.messages,
            monsters=game.monsters,
            items=game.items,
            use_curses=True,
        )

        key = stdscr.getch()
        cmd = keymap.get(key, "unknown")
        game.handle_command(cmd)

    if not game.alive:
        handle_death(game, stdscr, use_curses=True)
    else:
        handler.end_run(terminal_state="quit")


# ---------------------------------------------------------------------------
# Fallback text loop (CI / piped stdin)
# ---------------------------------------------------------------------------

def _run_text_loop(game, handler) -> None:
    """Minimal text-mode loop for environments where curses isn't available."""
    print("NetHack text mode (no curses). Type hjkl to move, Q to quit.")
    while game.alive and not game.quit:
        pos = f"({game.player.x},{game.player.y})"
        hp = f"HP:{game.player.hp}/{game.player.max_hp}"
        print(f"[T{game.turn} Dlvl:{game.dlvl} {hp} {pos}] cmd> ", end="", flush=True)
        try:
            line = input().strip()
        except EOFError:
            break
        if not line:
            continue
        for ch in line:
            game.handle_command({"h": "move_w", "j": "move_s",
                                  "k": "move_n", "l": "move_e",
                                  "Q": "quit", ">": "stairs",
                                  ",": "pickup"}.get(ch, "unknown"))
            if not game.alive or game.quit:
                break
        for msg in game.messages[-3:]:
            print(f"  {msg}")

    if not game.alive:
        print(render_tombstone_text(game))
        score = _compute_score(game)
        game.handler._run_metrics["score"] = score
        game.handler._run_metrics["cause_of_death"] = getattr(
            game.player, "cause_of_death", "unknown"
        )
        game.handler._emit_event("player_died",
                                  cause=game.player.cause_of_death,
                                  score=score)
        handler.end_run(
            terminal_state="died",
            score=score,
            cause_of_death=game.player.cause_of_death,
        )
    else:
        handler.end_run(terminal_state="quit")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sanctum NetHack terminal")
    parser.add_argument("--hi-scores", action="store_true",
                        help="show hi-score table and exit")
    parser.add_argument("--headless", action="store_true",
                        help="run in text mode (no curses)")
    args = parser.parse_args(argv)

    state = boot()
    handler = state["handler"]
    vault = state["vault"]

    if args.hi_scores:
        show_hi_scores(vault)
        # Don't leave an orphan run row
        handler.end_run(terminal_state="quit")
        return 0

    # Build game state
    from core.systems.make_brains.nethack.engine import GameState
    from core.systems.make_brains.nethack.entities import spawn_monsters
    import random as _rnd

    seed = int(time.time()) % (2 ** 31)
    game = GameState(handler, seed)

    # Spawn first-level entities
    rng = _rnd.Random(seed)
    spawn_monsters(game, rng)
    try:
        from core.systems.make_brains.nethack.items import spawn_items
        spawn_items(game, rng)
    except (ImportError, AttributeError):
        pass

    # Choose renderer
    use_curses = not args.headless and sys.stdin.isatty() and sys.stdout.isatty()

    if use_curses:
        try:
            import curses
            curses.wrapper(_run_curses_loop, game, handler)
        except Exception:
            # Fall back to text mode on any curses failure
            _run_text_loop(game, handler)
    else:
        _run_text_loop(game, handler)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
