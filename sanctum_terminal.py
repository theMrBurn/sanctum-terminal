"""sanctum_terminal — headless ASCII adventure with turn-based combat.

The game at its bedrock. No Godot, no manifest wire. Walks the brain's
stamp_world directly, renders a top-down glyph grid, drops into
DQ/PS-style combat on contact with a creature.

Controls (overworld):
    w/a/s/d       — step 1m (WASD caps = 5m sprint)
    t             — drop tag at current position
    q             — quit

Controls (combat):
    a             — attack (physical strike)
    d             — defend (halve incoming this round)
    m             — magic: then 1/2/3/4 for fire/ice/electric/light
    i             — item (TODO v2)
    f             — flee (DEX save)

Victory: creature removed from world. Defeat: respawn at hub, full HP.
"""
from __future__ import annotations

import argparse
import random
import sys
import termios
import time
import tty
from typing import Dict, Iterable, List, Set


def _get_key() -> str:
    """Single-keystroke read, roguelike style — no Enter required.
    Raw/cbreak mode via termios on a TTY; falls back to line-based
    stdin.read(1) otherwise (pipes in tests, etc.).

    Returns '' on EOF, '\\x03' on Ctrl+C (caller decides how to exit).
    """
    if not sys.stdin.isatty():
        return sys.stdin.read(1)
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)       # cbreak keeps signals (Ctrl+C raises) and
                                # preserves output flushing, unlike full raw
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


# ANSI control sequences. Alternate screen buffer eliminates the bounce
# you get from `clear + redraw` flashing the background between frames —
# the terminal swaps to a fresh back-buffer on entry and restores on
# exit, so scrollback stays clean.
_ALT_SCREEN_ON  = "\033[?1049h"
_ALT_SCREEN_OFF = "\033[?1049l"
_CURSOR_HIDE    = "\033[?25l"
_CURSOR_SHOW    = "\033[?25h"
_HOME           = "\033[H"              # cursor to top-left, no clear
_CLEAR_BELOW    = "\033[J"              # erase from cursor to end of screen


def _enter_screen() -> None:
    sys.stdout.write(_ALT_SCREEN_ON + _CURSOR_HIDE + _HOME)
    sys.stdout.flush()


def _exit_screen() -> None:
    sys.stdout.write(_CURSOR_SHOW + _ALT_SCREEN_OFF)
    sys.stdout.flush()


def _redraw(frame: str) -> None:
    """Repaint without flicker: cursor-home, write frame, erase trailing."""
    sys.stdout.write(_HOME + frame + _CLEAR_BELOW)
    sys.stdout.flush()

from core.systems import kind_config
from core.systems.ascii_render import render_view
from core.systems.player_state import PlayerState
from core.systems.stamp_world import get_visible


STEP_METERS = 1.0
VIEW_RADIUS_TILES = 14
CONTACT_RADIUS_M = 1.2           # how close = bump into a creature
DEFAULT_BIOME = "cavern"
DEFAULT_SEED = 42
HUB_SPAWN = (0.0, -14.0)

# Player stats for v1 — will derive from PlayerState.new() + extras later.
PLAYER_COMBAT = {
    "str_": 12, "dex": 10, "wil": 10, "speed": 12, "defense": 11,
    "element_mods": {},
}

MAGIC_ELEMENT_KEYS = {
    "1": ("fire_bolt",     "fire"),
    "2": ("ice_shard",     "ice"),
    "3": ("electric_arc",  "electric"),
    "4": ("light_beam",    "light"),
}


def _build_ascii_map() -> Dict[str, str]:
    cfg = kind_config.load()
    out: Dict[str, str] = {}
    for kind, entry in cfg.get("kinds", {}).items():
        glyph = entry.get("ascii")
        if isinstance(glyph, str) and len(glyph) == 1:
            out[kind] = glyph
    return out


def _creature_id(ent: dict) -> str:
    """Stable id matching encounter_builder._make_enemy so defeated_set can
    filter the creature out of future world frames."""
    return f"{ent['kind']}|{ent['x']:.2f}|{ent['y']:.2f}"


def _visible_filtered(px: float, py: float, biome: str, seed: int,
                      defeated: Set[str]) -> List[dict]:
    ents = get_visible(px, py, 49.0, seed, biome)
    if not defeated:
        return ents
    return [e for e in ents if _creature_id(e) not in defeated]


def _nearest_creature(px: float, py: float, ents: Iterable[dict],
                      kind_cfgs: Dict[str, dict]) -> dict | None:
    best = None
    best_d2 = CONTACT_RADIUS_M ** 2
    for e in ents:
        if "combat_profile" not in kind_cfgs.get(e.get("kind", ""), {}):
            continue
        dx = e["x"] - px
        dy = e["y"] - py
        d2 = dx * dx + dy * dy
        if d2 <= best_d2:
            best_d2 = d2
            best = e
    return best


# --- Overworld rendering -----------------------------------------------------

def _render_overworld(px: float, py: float, biome: str, seed: int,
                      ascii_map: Dict[str, str], player: PlayerState,
                      tag_count: int, defeated: Set[str]) -> str:
    ents = _visible_filtered(px, py, biome, seed, defeated)
    grid = render_view(ents, px, py, VIEW_RADIUS_TILES, ascii_map)
    header = (f"  sanctum · {biome} · ({px:5.1f}, {py:5.1f}) · "
              f"HP {player.hp}/{player.max_hp} · "
              f"ents {len(ents)} · tags {tag_count} · defeated {len(defeated)}")
    footer = "  [wasd] move · [t] tag · [q] quit"
    return "\n".join([header, ""] + ["  " + row for row in grid] + ["", footer])


# --- Main loop ---------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="sanctum_terminal")
    parser.add_argument("--biome", default=DEFAULT_BIOME)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--spawn", nargs=2, type=float, default=list(HUB_SPAWN),
                        metavar=("X", "Y"))
    args = parser.parse_args()

    ascii_map = _build_ascii_map()
    kind_cfgs = kind_config.load().get("kinds", {})
    player_state = PlayerState.new(name="Wanderer", seed=args.seed, max_hp=10)
    rng = random.Random(args.seed)
    roll_die = lambda size: rng.randint(1, size)

    px, py = args.spawn
    tags: list = []
    defeated: Set[str] = set()
    xp = 0

    print("\033[2J\033[H", end="")
    print(_render_overworld(px, py, args.biome, args.seed, ascii_map,
                            player_state, len(tags), defeated))

    while True:
        sys.stdout.write("\n  > ")
        sys.stdout.flush()
        try:
            ch = _get_key()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not ch or ch == "\x03":    # EOF or Ctrl+C
            print()
            return 0

        sys.stdout.write(ch + "\n")
        sys.stdout.flush()

        dx = dy = 0.0
        step = STEP_METERS if ch.islower() else STEP_METERS * 5.0
        lower = ch.lower()
        if lower == "w":
            dy = step
        elif lower == "s":
            dy = -step
        elif lower == "a":
            dx = -step
        elif lower == "d":
            dx = step
        elif lower == "t":
            tags.append({"x": px, "y": py, "t": time.time()})
            print(f"  [tagged #{len(tags)} @ ({px:.1f}, {py:.1f})]")
            continue
        elif lower == "q":
            print(f"  bye. {len(tags)} tags · XP {xp} · defeated {len(defeated)}")
            return 0
        else:
            print(f"  ? unknown key: {ch!r}")
            continue

        new_x = px + dx
        new_y = py + dy

        # Contact check — bump into a creature?
        ents = _visible_filtered(new_x, new_y, args.biome, args.seed, defeated)
        bumped = _nearest_creature(new_x, new_y, ents, kind_cfgs)
        if bumped is not None:
            name = bumped.get("kind", "creature")
            msg = f"bumped into {name} · (combat retired v1)"
            print("\033[2J\033[H", end="")
            print(_render_overworld(px, py, args.biome, args.seed, ascii_map,
                                    player_state, len(tags), defeated))
            print(f"\n  [{msg}]")
            continue

        # Normal step — no encounter
        px, py = new_x, new_y
        print("\033[2J\033[H", end="")
        print(_render_overworld(px, py, args.biome, args.seed, ascii_map,
                                player_state, len(tags), defeated))


if __name__ == "__main__":
    sys.exit(main())
