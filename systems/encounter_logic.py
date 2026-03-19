# systems/encounter_logic.py
import random


class EncounterEngine:
    def __init__(self, player_lv, floor):
        self.lv = player_lv
        self.floor = floor
        self.step_counter = 0
        self.next_threshold = random.randint(15, 45)

    def check_step(self, player_hp):
        self.step_counter += 1
        if self.step_counter >= self.next_threshold:
            self.step_counter = 0
            self.next_threshold = random.randint(15, 45)
            return self.Combat(self.lv, self.floor, player_hp)
        return None

    class Combat:
        def __init__(self, lv, floor, player_hp):
            self.lv = lv
            self.floor = floor
            self.player_hp = player_hp
            self.is_active = True
            self.enemies = self._generate_fair_group()

        def _generate_fair_group(self):
            pool = [
                {"name": "Fragment-Stalker", "hp": 10, "atk": 3, "sym": "s"},
                {"name": "Voxel-Reaper", "hp": 18, "atk": 5, "sym": "r"},
                {"name": "Grid-Watcher", "hp": 35, "atk": 8, "sym": "G"},
            ]
            group = []

            # 1. Select raw templates
            if self.floor == 1:
                group.append(pool[0].copy())
            else:
                max_atk_allowance = max(3, self.player_hp / 3.8)
                num_enemies = random.randint(1, 2 if self.floor < 4 else 3)
                for _ in range(num_enemies):
                    m = random.choice(pool).copy()
                    m["hp"] = int(m["hp"] * (1.10**self.floor))
                    m["atk"] = int(m["atk"] * (1.08**self.floor))

                    current_atk = sum(e["atk"] for e in group)
                    if current_atk + m["atk"] > max_atk_allowance and len(group) > 0:
                        continue
                    group.append(m)

            # 2. MANDATORY DATA STAMP: Viewport requires max_hp to render health bars
            for e in group:
                e["max_hp"] = e["hp"]

            return group

        def player_attack(self, player_lv):
            if not self.enemies:
                return 0, "NO TARGETS."
            target = self.enemies[0]
            dmg = random.randint(player_lv + 6, player_lv + 14)
            target["hp"] -= dmg
            msg = f"Dealt {dmg} DMG to {target['name']}."
            if target["hp"] <= 0:
                self.enemies.pop(0)
                msg += f" {target['name']} DELETED."
            return dmg, msg

        def enemy_turn(self):
            return sum(random.randint(1, e["atk"]) for e in self.enemies)

    class TrapChallenge:
        def __init__(self, lv):
            self.name = random.choice(
                ["LOGIC BOMB", "DATA SYNC LOCK", "VOXEL COLLAPSE"]
            )
            self.is_active = True

        def attempt(self, grit_meter):
            chance = 0.45 + (grit_meter / 200)
            success = random.random() < chance
            self.is_active = False
            return success
