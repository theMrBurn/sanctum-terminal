# core/session.py
import random
import math


class GameSession:
    def __init__(self):
        self.lv, self.xp, self.hp = 1, 0, 100
        self.hp_max = 100
        self.floor = 1
        self.is_alive = True
        self.pos = [25.0, 0.0, 25.0]
        self.log = []
        self.journal = []

        # State & Input
        self.active_container = "CALIBRATION"
        self.input_buffer = ""
        self.modifiers = []

        # Recovery & Stealth Mechanics
        self.corpse_pos = None
        self.corpse_xp = 0
        self.recovery_grace = 0  # Stealth countdown

        # Combat Stats
        self.target_hp = 0
        self.target_max_hp = 1
        self.target_name = ""

    def calibrate(self, text):
        if not text:
            text = "Steady signal. No anomalies."
        self.journal.append(text)
        self.modifiers = []
        triggers = {
            "difficult": "SPIRE_GEN",
            "fight": "HOSTILE_BOOST",
            "walk": "ECO_BOOST",
            "money": "LOOT_BOOST",
        }
        for word, mod in triggers.items():
            if word in text.lower():
                self.modifiers.append(mod)
        self.active_container = None
        self.add_log("NEURAL CALIBRATION COMPLETE.")

    def handle_death(self):
        self.add_log("!!! CRITICAL SYSTEM FAILURE !!!")
        self.add_log("SIGNAL LOST. INITIATING RE-ENTRY.")
        self.corpse_pos = (int(self.pos[0]), int(self.pos[2]))
        self.corpse_xp = int(self.xp * 0.5)
        self.xp -= self.corpse_xp
        self.pos = [25.0, 0.0, 25.0]
        self.hp = self.hp_max
        self.recovery_grace = 0
        self.active_container = "RECOVERY_STUN"

    def recover_data(self):
        """Reclaim lost XP and activate Stealth Grace Period."""
        self.xp += self.corpse_xp
        gain = self.corpse_xp
        self.corpse_pos = None
        self.corpse_xp = 0
        self.recovery_grace = 50  # 50 steps of safety
        self.add_log(f">>> DATA RECLAIMED: +{gain} XP")
        self.add_log(">>> SIGNAL STABILIZED: STEALTH ACTIVE.")

    def process_step(self, symbol):
        if self.active_container:
            return "BLOCK"
        if symbol in ["#", "~"]:
            return "BLOCK"

        # Decrement Stealth Grace
        if self.recovery_grace > 0:
            self.recovery_grace -= 1
            return True  # No encounters allowed

        # Normal Encounter Logic
        if symbol == "&" or (symbol == "s" and random.random() < 0.05):
            self.trigger_combat()
            return "ENCOUNTER"
        return True

    def trigger_combat(self):
        self.active_container = "COMBAT"
        dist = math.sqrt((self.pos[0] - 25) ** 2 + (self.pos[2] - 25) ** 2)
        tier = int(dist / 50) + 1
        self.target_max_hp = 30 + (tier * 15)
        self.target_hp = self.target_max_hp
        self.target_name = f"VOID_LURKER [T{tier}]"
        self.add_log(f"(!) {self.target_name} LOCKED.")

    def combat_tick(self, action):
        if action == "ATTACK":
            dmg = random.randint(10, 20) + (self.lv * 2)
            self.target_hp -= dmg
            self.add_log(f"PURGING... {dmg} DAMAGE.")
        if self.target_hp <= 0:
            self.xp += 100
            self.active_container = None
            self.add_log("LINK RESTORED.")
            return
        tier = (
            int(math.sqrt((self.pos[0] - 25) ** 2 + (self.pos[2] - 25) ** 2) / 50) + 1
        )
        enemy_dmg = random.randint(4, 8) + (tier * 2)
        self.hp -= enemy_dmg
        if self.hp <= 0:
            self.handle_death()

    def decrypt_object(self, symbol):
        if symbol == "$":
            roll = random.random()
            if roll < 0.05:
                self.xp += 500
                self.add_log(">>> ULTRA DATA_NODE DECRYPTED! <<<")
            else:
                self.xp += 50
                self.add_log("DATA FRAGMENT SECURED.")
            return True
        return False

    def add_log(self, msg):
        self.log.append(msg)
        if len(self.log) > 6:
            self.log.pop(0)
