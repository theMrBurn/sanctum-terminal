# systems/game_state.py
import math, random, time
from systems.rosetta_stone import VOXEL_REGISTRY

class GameState:
    def __init__(self):
        self.start_time = time.time()
        self.lv = 1
        self.xp = 0
        self.xp_prev = 0
        self.xp_next = 100
        self.hp = 35
        self.hp_max = 35
        self.floor = 1
        self.is_alive = True
        self.pos = [1, 1]
        self.log = ["SYSTEM INITIALIZED. WELCOME TO THE SANCTUM."]
        self.visited = set()
        self.total_tiles = 900
        self.regen_pool = 0.0
        self.grit_meter = 0
        self.is_defending = False
        self._death_defied = False

    def get_elapsed_time(self):
        s = int(time.time() - self.start_time)
        return f"{s // 60:02d}:{s % 60:02d}"

    def update_grit(self, amount):
        self.grit_meter = min(100, self.grit_meter + amount)
        if self.grit_meter == 100: self._add_log(">>> GRIT MAXIMIZED. BURST READY.")

    def apply_damage(self, raw_dmg):
        sync_ratio = len(self.visited) / self.total_tiles
        reduction = 1.0 - (sync_ratio * 0.3)
        if self.is_defending:
            reduction *= 0.5; self.update_grit(12)
        final_dmg = max(1, int(raw_dmg * reduction))
        if final_dmg >= self.hp and not self._death_defied:
            self.hp = 1; self._death_defied = True
            self._add_log("(!) GRIT ACTIVE: SYSTEM STABILIZED AT 1HP."); return 0
        self.hp -= final_dmg
        if not self.is_defending: self.update_grit(5)
        if self.hp <= 0: self.is_alive = False
        return final_dmg

    def process_step(self, symbol):
        self.visited.add(tuple(self.pos))
        self.is_defending = False
        tile_data = VOXEL_REGISTRY.get(symbol, {"type": "floor"})
        t_type = tile_data.get("type", "floor")
        if t_type == "wall": return False
        if t_type == "trap":
            self.apply_damage(self.get_scaling_stat(5))
            self._add_log("(!) SYSTEM SPIKE: HP REDUCED."); return True
        if symbol == "&": return "CHALLENGE"
        if t_type == "trigger":
            self.xp += 25 * self.floor; self._add_log("DATA FRAGMENT RECOVERED.")
        if t_type == "exit":
            self.floor += 1; self.visited.clear(); self._death_defied = False
            self.hp = min(self.hp + 15, self.hp_max)
            self._add_log(f"DESCENDING TO LEVEL {self.floor}...")
        self._apply_perception_regen()
        self._check_level_up()
        return True

    def _apply_perception_regen(self):
        ratio = len(self.visited) / self.total_tiles
        rate = 0.10 + (ratio * 1.2); self.regen_pool += rate
        if self.regen_pool >= 1.0:
            val = int(self.regen_pool)
            if self.hp < self.hp_max: self.hp = min(self.hp_max, self.hp + val)
            else: self.update_grit(val * 2)
            self.regen_pool -= val

    def get_scaling_stat(self, base): return int(base * (1.15**self.floor))

    def _check_level_up(self):
        if self.xp >= self.xp_next:
            old = self.hp_max; self.lv += 1
            new_target = self.xp_next + self.xp_prev
            self.xp_prev = self.xp_next; self.xp_next = new_target
            growth = 15 + (self.lv * 2); self.hp_max += growth; self.hp = self.hp_max
            self._add_log(f"--- [EVOLUTION: LV {self.lv}] ---")
            self._add_log(f" > HP: {old} -> {self.hp_max} (+{growth})")

    def _add_log(self, msg):
        self.log.append(msg)
        if len(self.log) > 4: self.log.pop(0)