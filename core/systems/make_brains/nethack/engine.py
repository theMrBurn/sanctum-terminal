"""engine.py — GameState: the turn loop and world tick.

Owns the complete mutable game state for one run:
  - current Level + dungeon seed
  - Player entity
  - Monster list
  - Item list (on map)
  - FOV + visited tile sets
  - Message log
  - Turn counter + depth

GameState is constructed once per run and updated in-place each turn.
The curses entry point (nethack_terminal.py) drives the loop;
GameState only knows about game rules, not curses.

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 3+.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.systems.make_brains.nethack.dungeon import generate_level, PASSABLE, Tile
from core.systems.make_brains.nethack.fov import compute_fov_from_level
from core.systems.make_brains.nethack.input_map import (
    MOVE_DELTAS,
    CMD_MOVE_N, CMD_MOVE_S, CMD_MOVE_E, CMD_MOVE_W,
    CMD_PICKUP, CMD_STAIRS, CMD_QUIT,
    CMD_WIELD, CMD_WEAR, CMD_QUAFF, CMD_READ,
)

if TYPE_CHECKING:
    from core.systems.make_brains.nethack.handler import NetHackHandler


# Message log capacity
MSG_LOG_MAX: int = 200
FOV_RADIUS: int = 8


class GameState:
    """Full mutable state for one NetHack run.

    Entities (monsters, items) and combat are wired in by later PRs.
    PR 3 establishes the frame loop, movement, FOV, and message log.
    """

    def __init__(self, handler: "NetHackHandler", seed: int):
        self.handler = handler
        self.seed = seed
        self.dlvl: int = 1
        self.turn: int = 0
        self.alive: bool = True
        self.quit: bool = False

        # Message log — most recent at end
        self.messages: list[str] = []

        # Will be populated after entity module lands (PR 4)
        self.player: Any = None
        self.monsters: list[Any] = []
        self.items: list[Any] = []

        # FOV state
        self.visible: set[tuple[int, int]] = set()
        self.visited: set[tuple[int, int]] = set()

        # Generate the first level
        self.level = generate_level(seed)
        self._place_player_at_spawn()
        # Spawn dlvl 1 monsters + items. PR 7's _spawn_level_entities
        # was wired only into try_descend, so dlvl 1 booted empty. Without
        # this call the player explores the first floor with nothing on it.
        self._spawn_level_entities()
        self._update_fov()

    # -----------------------------------------------------------------------
    # Player placement — entities.Player created in PR 4; PR 3 uses a stub.
    # -----------------------------------------------------------------------

    def _place_player_at_spawn(self) -> None:
        """Place player at spawn. Full entity wiring happens in PR 4."""
        sx, sy = self.level.spawn_pos
        if self.player is None:
            # PR 3 stub: minimal player object so render doesn't crash.
            from core.systems.make_brains.nethack.entities import make_player
            params = self.handler.vault.profile_load(
                self.handler.INSTANCE_ID,
                self.handler.active_profile,
            )
            profile_params = params["params"] if params else {}
            self.player = make_player(profile_params, sx, sy)
        else:
            self.player.x = sx
            self.player.y = sy

    # -----------------------------------------------------------------------
    # FOV update
    # -----------------------------------------------------------------------

    def _update_fov(self) -> None:
        fov_radius = getattr(self.player, "fov_radius", FOV_RADIUS)
        self.visible = compute_fov_from_level(
            self.level, self.player.x, self.player.y, fov_radius
        )
        # Lit-room effect (classic NetHack): standing inside a room reveals
        # the entire room interior, not just the FOV disk. Walls of the
        # containing room are also revealed so the player sees the boundary.
        px, py = self.player.x, self.player.y
        for room in self.level.rooms:
            if room.x < px < room.x2 and room.y < py < room.y2:
                for cell in room.inner_cells():
                    self.visible.add(cell)
                for rx in range(room.x, room.x2 + 1):
                    self.visible.add((rx, room.y))
                    self.visible.add((rx, room.y2))
                for ry in range(room.y, room.y2 + 1):
                    self.visible.add((room.x,  ry))
                    self.visible.add((room.x2, ry))
                break
        self.visited |= self.visible

    # -----------------------------------------------------------------------
    # Message log
    # -----------------------------------------------------------------------

    def log(self, msg: str) -> None:
        self.messages.append(msg)
        if len(self.messages) > MSG_LOG_MAX:
            self.messages = self.messages[-MSG_LOG_MAX:]

    # -----------------------------------------------------------------------
    # Movement
    # -----------------------------------------------------------------------

    def try_move(self, dx: int, dy: int) -> bool:
        """Attempt to move the player by (dx, dy).

        Returns True if the player moved or attacked (turn consumed).
        Returns False if the move was blocked (no turn consumed).
        """
        nx = self.player.x + dx
        ny = self.player.y + dy

        # Bounds check
        if not (0 <= nx < len(self.level.grid) and 0 <= ny < len(self.level.grid[0])):
            return False

        # Wall check
        if not self.level.passable(nx, ny):
            return False

        # Monster check (bump-to-attack; real combat in PR 5)
        monster = self._monster_at(nx, ny)
        if monster is not None:
            self._bump_attack(monster)
            return True

        # Move
        self.player.x = nx
        self.player.y = ny
        return True

    def _monster_at(self, x: int, y: int) -> Any | None:
        for m in self.monsters:
            if m.x == x and m.y == y and m.alive:
                return m
        return None

    def _bump_attack(self, monster: Any) -> None:
        """Bump-to-attack: real combat resolver wired in PR 5."""
        from core.systems.make_brains.nethack import combat
        combat.resolve_player_attack(self, monster)

    # -----------------------------------------------------------------------
    # Item pickup
    # -----------------------------------------------------------------------

    def try_pickup(self) -> None:
        """Pick up items at the player's current position."""
        pos = (self.player.x, self.player.y)
        picked = [it for it in self.items if (it.x, it.y) == pos]
        if not picked:
            self.log("There is nothing here to pick up.")
            return
        for it in picked:
            letter = self.player.inventory_add(it)
            if letter:
                self.items.remove(it)
                self.handler._run_metrics["items_picked_up"] += 1
                self.handler._emit_event(
                    "item_picked_up",
                    item_kind=it.kind,
                    depth=self.dlvl,
                )
                self.log(f"{letter} - {it.display_name()} (picked up)")
            else:
                self.log("Your pack is full.")
                break

    # -----------------------------------------------------------------------
    # Stairs
    # -----------------------------------------------------------------------

    def try_descend(self) -> None:
        """Use stairs: generate new level, preserve player, update depth."""
        pos = (self.player.x, self.player.y)
        if self.level.at(*pos) != Tile.STAIRS_DOWN:
            self.log("There are no stairs here.")
            return
        self.dlvl += 1
        new_seed = self.seed + self.dlvl
        self.level = generate_level(new_seed)
        self.monsters = []
        self.items = []
        # Spawn monsters + items on the new level (wired in PR 4+)
        self._spawn_level_entities()
        # Move player to new spawn
        sx, sy = self.level.spawn_pos
        self.player.x = sx
        self.player.y = sy
        self.visible = set()
        self._update_fov()
        self.handler._run_metrics["depth_reached"] = max(
            self.handler._run_metrics["depth_reached"], self.dlvl
        )
        self.handler._emit_event("level_descended", depth=self.dlvl)
        self.log(f"You descend to dungeon level {self.dlvl}.")

    def _spawn_level_entities(self) -> None:
        """Spawn monsters + items for the current level. Wired in PR 4."""
        try:
            from core.systems.make_brains.nethack import entities as _ent
            import random as _rnd
            rng = _rnd.Random(self.seed + self.dlvl * 1000)
            _ent.spawn_monsters(self, rng)
            try:
                from core.systems.make_brains.nethack import items as _itm
                _itm.spawn_items(self, rng)
            except (ImportError, AttributeError):
                pass
        except (ImportError, AttributeError):
            pass

    # -----------------------------------------------------------------------
    # Item management commands (wired in PR 6)
    # -----------------------------------------------------------------------

    def try_wield(self) -> None:
        """Wield a weapon from inventory."""
        try:
            from core.systems.make_brains.nethack import items as _itm
            _itm.cmd_wield(self)
        except (ImportError, AttributeError):
            self.log("Nothing to wield.")

    def try_wear(self) -> None:
        """Wear armor from inventory."""
        try:
            from core.systems.make_brains.nethack import items as _itm
            _itm.cmd_wear(self)
        except (ImportError, AttributeError):
            self.log("Nothing to wear.")

    def try_quaff(self) -> None:
        """Quaff a potion from inventory."""
        try:
            from core.systems.make_brains.nethack import items as _itm
            _itm.cmd_quaff(self)
        except (ImportError, AttributeError):
            self.log("Nothing to quaff.")

    def try_read(self) -> None:
        """Read a scroll from inventory."""
        try:
            from core.systems.make_brains.nethack import items as _itm
            _itm.cmd_read(self)
        except (ImportError, AttributeError):
            self.log("Nothing to read.")

    # -----------------------------------------------------------------------
    # Turn dispatch
    # -----------------------------------------------------------------------

    def handle_command(self, cmd: str) -> bool:
        """Process one command string. Returns True if a turn was consumed."""
        if cmd in MOVE_DELTAS:
            dx, dy = MOVE_DELTAS[cmd]
            moved = self.try_move(dx, dy)
            if moved:
                self._update_fov()
                self._tick_monsters()
                self.turn += 1
                self.handler._run_metrics["turns"] = self.turn
                # Check player death
                if self.player.hp <= 0:
                    self.alive = False
            return moved

        if cmd == CMD_PICKUP:
            self.try_pickup()
            self._update_fov()
            self._tick_monsters()
            self.turn += 1
            self.handler._run_metrics["turns"] = self.turn
            return True

        if cmd == CMD_STAIRS:
            self.try_descend()
            return True

        if cmd == CMD_WIELD:
            self.try_wield()
            return False

        if cmd == CMD_WEAR:
            self.try_wear()
            return False

        if cmd == CMD_QUAFF:
            self.try_quaff()
            self._update_fov()
            self._tick_monsters()
            self.turn += 1
            self.handler._run_metrics["turns"] = self.turn
            return True

        if cmd == CMD_READ:
            self.try_read()
            self._update_fov()
            self._tick_monsters()
            self.turn += 1
            self.handler._run_metrics["turns"] = self.turn
            return True

        if cmd == CMD_QUIT:
            self.quit = True
            return False

        return False

    # -----------------------------------------------------------------------
    # Monster AI tick (real AI in PR 5)
    # -----------------------------------------------------------------------

    def _tick_monsters(self) -> None:
        """Advance monster AI one step. Full AI in PR 5."""
        try:
            from core.systems.make_brains.nethack import ai as _ai
            _ai.tick_all(self)
        except (ImportError, AttributeError):
            pass
        # Remove dead monsters
        self.monsters = [m for m in self.monsters if m.alive]
