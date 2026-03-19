# systems/logic_walker.py
import numpy as np
import random
from systems.game_state import GameState
from systems.encounter_logic import EncounterEngine


class ASCIICrawler:
    def __init__(self):
        self.state = GameState()
        self.encounter_engine = EncounterEngine(self.state.lv, self.state.floor)
        self.grid = np.full((32, 32), ".")
        self._build_floor()
        self.active_combat = None
        self.active_challenge = None

    def _build_floor(self):
        self.grid = np.full((32, 32), ".")
        self.grid[0, :], self.grid[31, :], self.grid[:, 0], self.grid[:, 31] = (
            "#",
            "#",
            "#",
            "#",
        )
        rng = np.random.default_rng(seed=self.state.floor + 100)
        for _ in range(25 + self.state.floor):
            rx, ry = rng.integers(1, 31, 2)
            self.grid[ry, rx] = rng.choice(["#", "^", "$", "&"])
        self.grid[30, 30] = "X"
        self.state.pos = [1, 1]

    def handle_input(self, key):
        if self.active_combat:
            self._process_combat_input(key)
            return
        if self.active_challenge:
            self._process_challenge_input(key)
            return

        dx, dy = (
            (0, -1)
            if key == "w"
            else (
                (0, 1)
                if key == "s"
                else (-1, 0) if key == "a" else (1, 0) if key == "d" else (0, 0)
            )
        )
        nx, ny = self.state.pos[0] + dx, self.state.pos[1] + dy

        if 0 <= nx < 32 and 0 <= ny < 32:
            sym = self.grid[ny, nx]
            res = self.state.process_step(sym)
            if res == "CHALLENGE":
                self.active_challenge = self.encounter_engine.TrapChallenge(
                    self.state.lv
                )
                self.grid[ny, nx] = "."
            elif res:
                self.state.pos = [nx, ny]
                if sym == "$":
                    self.grid[ny, nx] = "."
                if sym == "X":
                    self._build_floor()
                cb = self.encounter_engine.check_step(self.state.hp)
                if cb:
                    self.active_combat = cb

    def _process_combat_input(self, key):
        c = self.active_combat
        if key == "f":
            _, msg = c.player_attack(self.state.lv)
            self.state.log.append(msg)
        elif key == "d":
            self.state.is_defending = True
            self.state.update_grit(15)
            self.state.log.append("ADOPTED DEFENSIVE STANCE.")
        elif key == "b" and self.state.grit_meter >= 100:
            self.state.grit_meter = 0
            for e in c.enemies:
                e["hp"] -= self.state.lv * 18
            self.state.log.append("BURST: VOXEL SHATTER!")
            c.enemies = [e for e in c.enemies if e["hp"] > 0]
        elif key == "r":
            if random.random() > 0.4:
                self.state.log.append("ESCAPE SUCCESSFUL.")
                self.active_combat = None
                return
            else:
                self.state.log.append("ESCAPE FAILED.")

        if c.enemies:
            dmg = self.state.apply_damage(c.enemy_turn())
            if dmg > 0:
                self.state.log.append(f"Took {dmg} DMG.")
            self.state.is_defending = False
        else:
            xp = 35 * self.state.floor
            self.state.xp += xp
            self.state.log.append(f"VICTORY. +{xp} XP.")
            self.active_combat = None

    def _process_challenge_input(self, key):
        if key == "a":
            if self.active_challenge.attempt(self.state.grit_meter):
                reward = int((self.state.xp_next - self.state.xp_prev) * 0.15)
                self.state.xp += reward
                self.state.log.append(f"BYPASS SUCCESS. +{reward} XP.")
            else:
                self.state.log.append("BYPASS FAILED!")
                self.state.apply_damage(self.state.get_scaling_stat(7))
            self.active_challenge = None
        elif key == "t":
            self.state.apply_damage(self.state.get_scaling_stat(4))
            self.active_challenge = None
