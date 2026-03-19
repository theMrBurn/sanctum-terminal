import numpy as np


class DungeonRoom:
    @staticmethod
    def generate(seed, flavor="STANDARD"):
        rng = random.Random(seed)
        # 32x32 Grid of Stone (#)
        grid = np.full((32, 32), "#")

        # Carve central chamber
        w, h = rng.randint(10, 20), rng.randint(10, 20)
        x, y = (32 - w) // 2, (32 - h) // 2
        grid[y : y + h, x : x + w] = "."

        # Apply Flavor Logic (Config as Code)
        if flavor == "WET":
            grid[y + 2, x + 2 : x + w - 2] = "~"  # Puddles
        elif flavor == "HOT":
            grid[y + h - 2, x + w // 2] = "s"  # Magma Vent
        elif flavor == "POISON":
            grid[y + 1 : y + 3, x + 1 : x + 3] = "&"  # Fungal Bloom

        return grid
