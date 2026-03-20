# core/session.py
import random
import math
from core.atlas import query_atlas


class GameSession:
    def __init__(self):
        self.lv, self.xp, self.hp, self.hp_max = 1, 0, 100, 100
        self.pos = [25.0, 0.0, 25.0]
        self.log = ["NEURAL_LINK_STABLE"]
        self.is_alive = True
        self.seed = random.randint(1000, 9999)

        # State Management
        self.active_container = "BOOT_SEQUENCE"
        self.input_buffer = ""
        self.user_locale = "UNKNOWN"
        self.biome_tags = []

        # Kinetic & Survival Stats
        self.tension = 0.0
        self.is_scouting = False
        self.is_glitched = False
        self.stun_timer = 0
        self.last_material = 0

    def process_boot(self):
        return [
            "--- SANCTUM_OS v3.2.0 // NEURAL_LINK_STABLE ---",
            "SCANNING LOCAL ATMOSPHERICS...",
            "------------------------------------------------",
            "OPERATOR: Describe your current surroundings.",
            f"> {self.input_buffer}_",
            "",
            "Note: Accuracy improves neural stability.",
        ]

    def calibrate(self, text):
        res = query_atlas(text)
        self.user_locale, self.biome_tags = res["type"], res["tags"]
        self.active_container = "TRANSITION"
        self.input_buffer = ""

    def get_compass_heading(self, poi_coords):
        tx, tz = poi_coords
        dx, dz = tx - self.pos[0], tz - self.pos[2]
        angle = math.degrees(math.atan2(dz, dx))
        if -22.5 <= angle < 22.5:
            return "E"
        if 22.5 <= angle < 67.5:
            return "SE"
        if 67.5 <= angle < 112.5:
            return "S"
        if 112.5 <= angle < 157.5:
            return "SW"
        if angle >= 157.5 or angle < -157.5:
            return "W"
        if -157.5 <= angle < -112.5:
            return "NW"
        if -112.5 <= angle < -67.5:
            return "N"
        return "NE"

    def process_step(self, x, z, world):
        if self.is_glitched or self.active_container:
            return "BLOCK"
        node = world.get_node(x, z, self)
        if not node["passable"]:
            return "BLOCK"

        self.last_material = node["meta"]["material"]
        self.pos = [float(x), 0.0, float(z)]

        cost = 0.8 if self.is_scouting else 0.4
        self.tension = min(100.0, self.tension + cost + (node["pos"][1] * 0.2))

        if self.tension >= 100.0:
            self.hp -= 2
            if self.hp <= 0:
                self.is_alive = False
            self.is_glitched, self.stun_timer = True, 60
            self.add_log("CRITICAL_STRAIN: PHYSICAL_TRAUMA")
        return True

    def get_haptic_signal(self):
        if self.is_glitched:
            return (1.0, 1.0)
        strain_shake = (self.tension / 100.0) * 0.2
        material_kick = 0.4 if self.last_material in [2, 3] else 0.0
        return (round(strain_shake, 2), round(material_kick, 2))

    def get_rgb_handshake(self):
        from core.atlas import ARCHETYPES

        base_hex = ARCHETYPES.get(self.user_locale, {"rgb": "#505060"}).get(
            "rgb", "#505060"
        )
        if self.tension > 80:
            return "#FF0000" if (random.random() > 0.5) else base_hex
        return "#7F00FF" if self.is_glitched else base_hex

    def interact(self, x, z, world):
        node = world.get_node(x, z, self)
        meta = node["meta"]
        if meta.get("on_interact") == "lift":
            self.tension += 15.0
            world.modifications[(x, z)] = "."
            self.add_log("LIFTED_OBJECT")
        elif node["char"] == "$":
            self.xp += 100
            world.modifications[(x, z)] = "."
            self.add_log("DATA_SECURED")

    def update(self):
        if self.is_glitched:
            self.stun_timer -= 1
            if self.stun_timer <= 0:
                self.is_glitched, self.tension = False, 20.0
        elif not self.is_scouting:
            self.tension = max(0.0, self.tension - 0.5)
        if self.hp < self.hp_max and self.tension < 10:
            self.hp = min(self.hp_max, self.hp + 0.1)

    def add_log(self, msg):
        self.log.append(msg)
        if len(self.log) > 5:
            self.log.pop(0)
