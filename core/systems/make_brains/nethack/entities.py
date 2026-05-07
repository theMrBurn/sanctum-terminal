"""entities.py — Player + Monster dataclasses and bestiary.

Player:   Classic NetHack stats (Str/Dex/Con/Int/Wis/Cha), HP, AC, XP,
          level, depth, inventory (letter-keyed, max 26 slots).
Monster:  dataclass with name, glyph, stats, AI state, spawn depth range.
Bestiary: 8 kinds spanning depths 1-8 per spec.

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 4.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.systems.make_brains.nethack.engine import GameState


# ---------------------------------------------------------------------------
# Stat-bonus helper (NetHack classic convention)
# ---------------------------------------------------------------------------

def _stat_bonus(stat: int) -> int:
    """Convert a stat value to its modifier using classic NetHack table.

    NetHack 3.6 convention: 3=-3, 4-5=-2, 6-7=-1, 8-14=0, 15-17=+1,
    18=+2, 19+=+3.
    """
    if stat <= 3:   return -3
    if stat <= 5:   return -2
    if stat <= 7:   return -1
    if stat <= 14:  return  0
    if stat <= 17:  return  1
    if stat <= 18:  return  2
    return 3   # stat 19+


# ---------------------------------------------------------------------------
# Inventory slot limit
# ---------------------------------------------------------------------------

INVENTORY_MAX: int = 26
INVENTORY_LETTERS: str = "abcdefghijklmnopqrstuvwxyz"


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------

@dataclass
class Player:
    """Full player state for one run."""
    # Position
    x: int = 0
    y: int = 0
    # Stats (NetHack classic range 3-25)
    str_: int = 16
    dex:  int = 12
    con:  int = 14
    int_: int = 10
    wis:  int = 10
    cha:  int = 10
    # Derived
    hp:      int = 12
    max_hp:  int = 12
    ac:      int = 9    # NetHack convention: lower = better
    xp:      int = 0
    level:   int = 1
    # FOV
    fov_radius: int = 8
    # Equipment slots
    equipped_weapon: Any | None = None
    equipped_armor:  Any | None = None
    # Inventory: letter → Item
    inventory: dict[str, Any] = field(default_factory=dict)
    # Cause of death (set on HP=0)
    cause_of_death: str = ""

    # -----------------------------------------------------------------------
    # Derived bonuses
    # -----------------------------------------------------------------------

    @property
    def str_bonus(self) -> int:
        return _stat_bonus(self.str_)

    @property
    def con_bonus(self) -> int:
        return _stat_bonus(self.con)

    @property
    def weapon_bonus(self) -> int:
        """Attack bonus from equipped weapon."""
        if self.equipped_weapon is None:
            return 0
        return getattr(self.equipped_weapon, "to_hit_bonus", 0)

    @property
    def weapon_damage(self) -> str:
        """Damage dice string from equipped weapon (or bare-hand default)."""
        if self.equipped_weapon is None:
            return "1d2"
        return getattr(self.equipped_weapon, "damage_dice", "1d2")

    # -----------------------------------------------------------------------
    # Inventory management
    # -----------------------------------------------------------------------

    def inventory_add(self, item: Any) -> str | None:
        """Add an item to inventory. Returns the assigned letter or None if full."""
        if len(self.inventory) >= INVENTORY_MAX:
            return None
        for letter in INVENTORY_LETTERS:
            if letter not in self.inventory:
                self.inventory[letter] = item
                return letter
        return None

    def inventory_remove(self, letter: str) -> Any | None:
        return self.inventory.pop(letter, None)

    def inventory_by_kind(self, kind: str) -> list[tuple[str, Any]]:
        """Return [(letter, item)] for items of the given kind."""
        return [
            (letter, item)
            for letter, item in self.inventory.items()
            if getattr(item, "kind", None) == kind
        ]


def make_player(profile_params: dict, x: int, y: int) -> Player:
    """Construct a Player from profile params at position (x, y)."""
    p = Player(
        x=x, y=y,
        str_=profile_params.get("start_str", 16),
        dex=profile_params.get("start_dex", 12),
        con=profile_params.get("start_con", 14),
        int_=profile_params.get("start_int", 10),
        wis=profile_params.get("start_wis", 10),
        cha=profile_params.get("start_cha", 10),
        hp=profile_params.get("start_hp", 12),
        max_hp=profile_params.get("start_hp", 12),
        ac=profile_params.get("start_ac", 9),
        fov_radius=profile_params.get("fov_radius", 8),
    )
    # Seed starting equipment (items module may not be loaded yet at PR 3)
    try:
        from core.systems.make_brains.nethack.items import make_starter_equipment
        weapon, armor = make_starter_equipment(profile_params)
        p.equipped_weapon = weapon
        p.equipped_armor = armor
    except (ImportError, TypeError):
        pass
    return p


# ---------------------------------------------------------------------------
# Monster dataclass
# ---------------------------------------------------------------------------

@dataclass
class Monster:
    """A single monster instance on the current level."""
    name:        str
    glyph:       str
    x:           int
    y:           int
    hp:          int
    max_hp:      int
    ac:          int   # lower = harder to hit
    attack_dice: str   # damage dice for its melee attack
    xp_value:    int   # XP granted on kill
    min_depth:   int   # minimum dlvl this kind spawns
    kind:        str   # bestiary key (matches BESTIARY dict)
    # AI state: "wander" | "chase" | "attack"
    ai_state:    str = "wander"
    alive:       bool = True

    @property
    def str_bonus(self) -> int:
        return 0   # monsters use flat attack_dice, no stat bonuses V1


# ---------------------------------------------------------------------------
# Bestiary — 8 kinds spanning depths 1-8
# ---------------------------------------------------------------------------

# Each entry: (name, glyph, hp_dice, ac, attack_dice, xp_value, min_depth)
# hp_dice not used directly here — HP is rolled at spawn time.

BESTIARY: list[dict] = [
    dict(kind="newt",       name="newt",       glyph=":",
         max_hp=3,  ac=9, attack_dice="1d2",  xp_value=1,  min_depth=1),
    dict(kind="grid_bug",   name="grid bug",   glyph="x",
         max_hp=4,  ac=9, attack_dice="1d2",  xp_value=2,  min_depth=1),
    dict(kind="sewer_rat",  name="sewer rat",  glyph="r",
         max_hp=6,  ac=7, attack_dice="1d3",  xp_value=3,  min_depth=1),
    dict(kind="kobold",     name="kobold",     glyph="k",
         max_hp=8,  ac=7, attack_dice="1d4",  xp_value=5,  min_depth=3),
    dict(kind="jackal",     name="jackal",     glyph="d",
         max_hp=7,  ac=7, attack_dice="1d3",  xp_value=4,  min_depth=3),
    dict(kind="giant_rat",  name="giant rat",  glyph="r",
         max_hp=10, ac=7, attack_dice="1d3",  xp_value=6,  min_depth=3),
    dict(kind="orc",        name="orc",        glyph="o",
         max_hp=14, ac=6, attack_dice="1d6",  xp_value=10, min_depth=6),
    dict(kind="gnome",      name="gnome",      glyph="G",
         max_hp=12, ac=5, attack_dice="1d6",  xp_value=10, min_depth=6),
    dict(kind="giant_ant",  name="giant ant",  glyph="a",
         max_hp=16, ac=3, attack_dice="1d4",  xp_value=14, min_depth=6),
]

# Depth buckets per spec §Locked numbers
DEPTH_POOL: list[tuple[range, list[str]]] = [
    (range(1, 3),  ["newt", "grid_bug", "sewer_rat"]),
    (range(3, 6),  ["kobold", "jackal", "giant_rat"]),
    (range(6, 99), ["orc", "gnome", "giant_ant"]),
]


def _bestiary_by_kind(kind: str) -> dict:
    for entry in BESTIARY:
        if entry["kind"] == kind:
            return entry
    raise KeyError(f"unknown monster kind: {kind}")


def spawn_monster(kind: str, x: int, y: int, rng: random.Random) -> Monster:
    """Create a Monster instance at (x, y) for the given bestiary kind."""
    proto = _bestiary_by_kind(kind)
    hp = max(1, proto["max_hp"] + rng.randint(-1, 1))   # tiny variance
    return Monster(
        name=proto["name"],
        glyph=proto["glyph"],
        x=x, y=y,
        hp=hp,
        max_hp=proto["max_hp"],
        ac=proto["ac"],
        attack_dice=proto["attack_dice"],
        xp_value=proto["xp_value"],
        min_depth=proto["min_depth"],
        kind=proto["kind"],
    )


def _monster_pool_for_depth(dlvl: int) -> list[str]:
    for depth_range, kinds in DEPTH_POOL:
        if dlvl in depth_range:
            return kinds
    return DEPTH_POOL[-1][1]   # deepest bucket for any level beyond range


def spawn_monsters(game: "GameState", rng: random.Random) -> None:
    """Place 3-6 monsters on game.level, avoiding spawn room and each other."""
    n = rng.randint(3, 6)
    pool = _monster_pool_for_depth(game.dlvl)
    spawn_room_center = game.level.spawn_pos
    occupied: set[tuple[int, int]] = {spawn_room_center}

    # Collect all passable positions NOT in the first room
    candidates = [
        (x, y)
        for x in range(len(game.level.grid))
        for y in range(len(game.level.grid[0]))
        if game.level.grid[x][y] in {
            __import__("core.systems.make_brains.nethack.dungeon", fromlist=["Tile"]).Tile.FLOOR
        }
        and (x, y) not in occupied
    ]

    # Exclude spawn room floor cells
    if game.level.rooms:
        spawn_room = game.level.rooms[0]
        spawn_cells = set(spawn_room.inner_cells())
        candidates = [(x, y) for x, y in candidates if (x, y) not in spawn_cells]

    rng.shuffle(candidates)
    placed = 0
    for pos in candidates:
        if placed >= n:
            break
        if pos not in occupied:
            kind = rng.choice(pool)
            m = spawn_monster(kind, pos[0], pos[1], rng)
            game.monsters.append(m)
            occupied.add(pos)
            placed += 1
