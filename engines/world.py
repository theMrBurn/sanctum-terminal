# engines/world.py
import zlib
import math


class WorldEngine:
    def __init__(self, seed, modifiers):
        self.seed = seed
        self.mods = modifiers
        self.poi_coords = (100, 100)
        self.modifications = {}

    def get_tile(self, x, z, session=None):
        if (x, z) in self.modifications:
            return self.modifications[(x, z)]

        # 1. Recovery Point
        if session and session.corpse_pos == (x, z):
            return "R"

        # 2. Spire Logic
        if "SPIRE_GEN" in self.mods:
            if 39 <= x <= 41 and 39 <= z <= 41:
                return "X" if (x == 40 and z == 40) else "#"

        # 3. Settlement
        dist = math.sqrt((x - self.poi_coords[0]) ** 2 + (z - self.poi_coords[1]) ** 2)
        if dist < 12:
            if 98 <= x <= 102 and 98 <= z <= 102:
                return "O" if (x == 100 and z == 100) else "#"
            return "."

        # 4. Procedural
        h = zlib.adler32(f"{self.seed}-{x}-{z}".encode())
        shore = 15 + int(7 * math.sin(z * 0.2))
        if x < shore:
            return "~"

        val = h % 100
        if val < 1:
            return "b"
        if val < 3:
            return "i"
        if val < 5:
            return "&"
        if val < 8:
            return "$"
        return "s"

    def set_tile(self, x, z, char):
        self.modifications[(x, z)] = char
