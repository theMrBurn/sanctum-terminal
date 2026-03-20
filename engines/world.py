# engines/world.py
import zlib
import math
from core.atlas import VOXEL_REGISTRY


class WorldEngine:
    def __init__(self, seed):
        self.seed = seed
        self.poi_coords = (100, 100)  # THE ALPHA NODE ANCHOR
        self.modifications = {}

    def get_elevation(self, x, z):
        """Calculates 3D Y-axis passively."""
        return round(abs(math.sin(x * 0.12) * math.cos(z * 0.12) * 3.8), 2)

    def get_node(self, x, z, session):
        # 1. Identity Hash
        h = zlib.adler32(f"{self.seed}-{x}-{z}".encode())

        # 2. Wave-Form Topography (Y-Axis)
        elev = self.get_elevation(x, z)

        # 3. Raster Jitter (Vertex Snapping Simulation)
        jitter = ((h % 3) - 1) * (session.tension / 250.0)

        # 4. Object Scatter
        char = self.modifications.get((x, z))
        if not char:
            v = h % 100
            if v < 1:
                char = "$"
            elif v < 7:
                char = "f"
            elif v > 96:
                char = "X"
            elif x < 12 + int(4 * math.sin(z * 0.4)):
                char = "~"
            else:
                char = "." if (h % 2 == 0) else "s"

        # 5. Relativity Math
        px, pz = session.pos[0], session.pos[2]
        dist = math.sqrt((x - px) ** 2 + (z - pz) ** 2)

        return {
            "char": char,
            "pos": (x, elev + jitter, z),
            "rel": {
                "intensity": max(0.05, 1.0 - (dist / 22.0)),
                "noise": (h % 10) / 10.0,
                "is_active": (char == "f" and dist < 2.5),
            },
            "meta": VOXEL_REGISTRY.get(char, {"material": 0}),
            "passable": char not in ["X", "~"],
        }
