# Feature — feat/make-brain-nethack

**Status:** Spec drafted 2026-05-06.  Implementation in progress (PR 1).
**Branch:** `feat/make-brain-nethack` is the source of truth.
All commits + pushes land on this branch. **Do NOT merge to main**
until UAT signs off on the full V1 (Acceptance signature, §end).
**Base:** branched from `feat/make-brain-ping-pong` tip (5be40d2) so
the make-brain substrate (`vault.profiles`, `vault.runs`,
`make_brain_registry`) is inherited.  When ping_pong merges to main,
this branch will rebase.

## Premise

A faithful, classic NetHack-feel terminal roguelike — second instance
of the make-brain substrate established by ping_pong.  Built as a
**side-project comparator** so the user can play it standalone, observe
how a fully-developed RPG renders the same primitives sanctum is
trying to compose (procgen dungeon, role/stats, turn-based combat,
items, descent, permadeath telemetry), and decide what to absorb /
reject for sanctum proper.

V1 is a **classic NetHack vertical slice**:
- single-character Roguelike-class campaign (no role select V1 — fighter)
- one continuous dungeon, stairs descend `>`
- procedural rooms-and-corridors level gen
- bump-to-attack combat with classic d20-ish to-hit
- monsters with simple AI (wander / chase / attack)
- items: weapons, armor, potions, scrolls, gold
- HP / XP / level-up / depth tracking
- permadeath: HP=0 → YASD screen → vault.runs row closed
- curses ASCII renderer in the launching terminal

What is **explicitly out of V1** (deferred to V2+ if at all):
polymorph, BUC status, identification minigame, altars, pets,
shopkeepers, vaults, Sokoban, the Quest, Gnomish Mines, alignment,
roles beyond fighter, races, Elbereth, prayer, multiple weapon types
beyond a small starter set, magic spells, monster special abilities
beyond melee.

The classic-fidelity choice (vs inheriting cairn substrate) is
**deliberate per user 2026-05-06**: this is a comparator, not a
sanctum-proper feature.  Cairn rules and reflective-loop / death-only-
regen do **NOT** apply.  This brain implements YASD permadeath.

## Decisions locked

| # | Question | Locked answer |
|---|----------|---------------|
| 1 | Process model | **Standalone curses app**, not a brain_server.py TCP brain.  ASCII grid is the wrong output for the manifest-streaming protocol.  `nethack_terminal.py` at repo root is the entry point; `make brain-nethack` execs it directly.  Mirrors `sanctum_terminal.py` + `make terminal`. |
| 2 | Stat system | **Classic NetHack** — Str (3-25), Dex/Con/Int/Wis/Cha (3-18), HP, AC (lower=better), XP, level, depth.  Inherits NetHack's classic point-buy + d20-ish derivations.  Does **not** use cairn's level=age-immutable rule. |
| 3 | Death model | **YASD permadeath.**  HP→0 closes the vault.runs row with `terminal_state="died"`, persists final score + cause-of-death, shows tombstone screen.  No respawn, no reflective-loop integration.  New game = `make brain-nethack` again. |
| 4 | Renderer | **curses (Python stdlib)** — ASCII glyphs, status line, message log.  No vector_terminal integration.  Fallback to plain print/input only if curses unavailable (e.g. CI). |
| 5 | Substrate reuse | **vault.profiles** for difficulty/role configs (V1 ships only `vanilla`).  **vault.runs** for per-game telemetry (depth, kills, items, score, cause-of-death).  **make_brain_registry** for identity (`nethack` instance_id, `terminal:nethack` entry_point). |
| 6 | Map size | **80×24 standard NetHack grid** (compatibility + readability). |
| 7 | Dungeon gen | **Classic Rogue 3×3 super-grid** of room slots.  1-2 rooms per slot occupied randomly, L-shaped corridors connect adjacent occupied slots.  Stairs `>` placed in a random room (not the spawn room).  Single seed per run, stored in vault.runs metrics. |
| 8 | Combat math | **NetHack-style**: to-hit = d20 + level + Str_bonus + weapon_bonus, hit if ≥ target_AC.  Damage = weapon dice + Str_bonus.  Monster attacks symmetric.  See [3.4-era nethack code refs](§References). |
| 9 | XP / level-up | **Classic NetHack table**: level N → 2^(N-1) XP.  Level-up: max_HP += d8 + Con_bonus, full heal. |
| 10 | Monster spawn rate | Per-level: 3-6 monsters at gen, no respawn.  Spawn table weighted by depth: `dlvl 1-2` → newt/grid-bug/sewer-rat; `3-5` → kobold/jackal/giant-rat; `6+` → orc/gnome/giant-ant. |

## Make-brain identity

Registered at brain boot via `core/systems/make_brains/nethack/__init__.py:activate(vault)`:

```python
INSTANCE_ID       = "nethack"
ENTRY_POINT       = "terminal:nethack"      # not a biome — naming convention adopted
DEFAULT_PROFILE   = "vanilla"
STATE_EVENT_TYPES = (
    # universal lifecycle
    "make_brain_started", "make_brain_ended", "profile_loaded",
    "peak_recorded",
    # nethack-specific
    "level_descended", "monster_killed", "item_picked_up",
    "level_up", "player_died",
)
```

Vault profiles seeded on first activate:

- `vanilla` — classic NetHack defaults (Str 16, Dex 12, Con 14, Int 10, Wis 10, Cha 10, HP 12, AC 9 leather, dagger d4)

## Architecture (V1)

```
nethack_terminal.py                     # entry point — curses bootstrap, calls into engine
core/systems/make_brains/nethack/
├── __init__.py                          # activate() + identity constants
├── AGENTS.md                            # subsystem contract
├── handler.py                           # NetHackHandler — substrate (vault hooks, run lifecycle)
├── engine.py                            # GameState — turn loop, world tick (PR 4+)
├── dungeon.py                           # Level, Tile, generation algo (PR 2)
├── entities.py                          # Player + Monster + bestiary (PR 4+)
├── combat.py                            # to-hit, damage, kill resolution (PR 5)
├── items.py                             # item kinds, drops, inventory ops (PR 6)
├── ai.py                                # monster AI states (PR 5)
├── fov.py                               # recursive shadowcasting (PR 3)
├── render.py                            # curses screen layout (PR 3)
└── input_map.py                         # keystroke → command (PR 3)
tests/test_nethack_*.py                  # one test file per PR
```

## PR plan

| PR | Scope | Acceptance |
|----|-------|------------|
| **1** | Feature doc, AGENTS.md, package skeleton, registry registration, `nethack_terminal.py` splash, Makefile target, smoke tests. | TEST: `pytest tests/test_nethack_smoke.py`.  SCENARIO: `make brain-nethack` shows splash + exits on q. |
| 2 | Tile/Level types, classic rooms-and-corridors gen, stairs placement, deterministic with seed. | TEST: connectivity + golden seeded fixture. |
| 3 | curses renderer, hjkl + arrows, FOV (8-octant shadowcasting), memory of visited tiles. | TEST: shadowcasting unit tests.  SCENARIO: walk around generated level, FOV reveals/hides correctly. |
| 4 | Player + monster entities, bump-to-attack hook, walls/monsters block. | TEST: stat init, monster placement non-overlap, bump dispatches. |
| 5 | Combat resolution, monster AI (wander/chase/attack), XP + level-up. | TEST: to-hit math + damage rolls (seeded).  SCENARIO: kill 3 monsters, gain a level. |
| 6 | Items (weapons/armor/potions/scrolls/gold), pickup, inventory, wield/wear/quaff/read. | TEST: inventory ops.  SCENARIO: pick up dagger, wield it, fight stronger. |
| 7 | Stairs descent, depth-scaled monster + item tables. | TEST: descent state preservation, depth-N spawn picks. |
| 8 | YASD death screen, vault.runs `terminal_state="died"`, score formula, hi-score table query. | TEST: death triggers run_end, score deterministic.  SCENARIO: die, see tombstone, query hi-scores. |

## References

External material to study during implementation.  Same shape as the
ping_pong feature doc — pin sources up front so PR work has a known
reference baseline.

### Implementations to mine
- **NetHack 3.6 source** — `github.com/NetHackDeveloperTeam/NetHack`.  Specifically `src/mklev.c` (level gen), `src/mhitu.c` / `src/uhitm.c` (combat), `dat/monsters.h` (bestiary).  C, not Python — read for algorithm, don't port directly.
- **Brogue** — `github.com/tmewett/BrogueCE`.  Cleaner C codebase than NetHack, FOV implementation in `src/brogue/Light.c` is a good shadowcasting reference.
- **python-tcod tutorials** — `rogueliketutorials.com`.  Modern Python idioms for the patterns we'll re-implement (we are NOT using tcod; curses-only).

### Algorithm references
- **Recursive shadowcasting** — `roguebasin.com/index.php/FOV_using_recursive_shadowcasting`.  Canonical algorithm for PR 3 FOV.
- **Rogue dungeon generation** — `roguebasin.com/index.php/Articles#Map`.  Classic 3×3 grid algorithm for PR 2.
- **NetHack scoring** — `nethackwiki.com/wiki/Score`.  Score formula reference for PR 8.

### Locked numbers (V1)

| Thing | Value | Source |
|-------|-------|--------|
| Map size | 80 × 24 | NetHack standard |
| Super-grid | 3 × 3 room slots | Classic Rogue |
| Min room | 4 × 3 | Rogue tradition |
| Max room | 12 × 8 | fits 3×3 of 80×24 |
| FOV radius | 8 tiles | NetHack default torch radius |
| Player start HP | 12 | NetHack fighter |
| Player start AC | 9 (leather armor) | NetHack |
| To-hit dice | d20 | NetHack |
| XP curve | 2^(N-1) per level | NetHack |
| Monsters per level (V1) | 3–6, no respawn | V1 simplification |
| Auto-save | on every descent + on quit | YASD-safe |

## Air-gap

No LLM calls anywhere in this brain.  Death messages, cause-of-death
strings, monster names — all hardcoded tables.  Same air-gap rule as
sanctum proper.

## Acceptance signature

User signs off after PR 8 by:
- starting `make brain-nethack`
- playing one full run from spawn to death
- confirming score + hi-score table populate in vault.runs
- saying "ship it" or equivalent

Until then, **branch stays in `feat/make-brain-nethack`, do not merge.**
