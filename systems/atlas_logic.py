import numpy as np


class CartographerV1:
    def __init__(self):
        # The Ordered Biome Chain
        self.chain = [
            "BEACH",
            "BEACH",
            "COASTAL_FOREST",
            "COASTAL_FOREST",
            "GRASSLANDS",
            "GRASSLANDS",
            "VALLEY",
            "VALLEY",
            "RIVER",
            "RIVER",
            "MOUNTAIN",
            "MOUNTAIN",
            "CAVE",
            "CAVE",
            "DUNGEON",
            "DUNGEON",
        ]

    def get_path_x(self, global_z):
        # A gentle S-curve guiding the player from Beach to Cave
        return 16 + np.sin(global_z * 0.04) * 6

    def get_river_x(self, global_z):
        # The river only exists in the middle of the map
        return 20 + np.cos(global_z * 0.08) * 4


class AtlasLogic:
    def __init__(self, cart):
        self.cart = cart
        self.palette = {
            "BEACH": {"bg": ".", "extra": "~", "chance": 0.1},
            "COASTAL_FOREST": {"bg": "*", "extra": "#", "chance": 0.3},
            "GRASSLANDS": {"bg": ".", "extra": "v", "chance": 0.2},
            "VALLEY": {"bg": ",", "extra": "m", "chance": 0.15},
            "RIVER": {"bg": ",", "extra": "s", "chance": 0.8},  # River heavy
            "MOUNTAIN": {"bg": "_", "extra": "^", "chance": 0.4},
            "CAVE": {"bg": "^", "extra": "f", "chance": 0.2},
            "DUNGEON": {"bg": "_", "extra": "&", "chance": 0.5},
        }

    def generate_tile(self, tx, tz):
        biome_name = self.cart.chain[tz]
        cfg = self.palette[biome_name]
        grid = np.full((32, 32), cfg["bg"])

        for z in range(32):
            gz = (tz * 32) + z

            # 1. Base Biome Noise
            for x in range(32):
                if np.random.random() < cfg["chance"]:
                    grid[z, x] = cfg["extra"]

            # 2. Inject River (Only in VALLEY/RIVER zones)
            if "VALLEY" in biome_name or "RIVER" in biome_name:
                rx = int(self.cart.get_river_x(gz) - (tx * 32))
                if 0 <= rx < 32:
                    grid[z, rx] = "s"

            # 3. Inject S-Trail (Priority 1)
            px = int(self.cart.get_path_x(gz) - (tx * 32))
            if 0 <= px < 32:
                grid[z, px] = "P"

        return grid


# EXECUTION POC
cart = CartographerV1()
engine = AtlasLogic(cart)

for tz in range(16):
    print(f"\n[ ZONE {tz}: {cart.chain[tz]} ]")
    tile = engine.generate_tile(0, tz)  # Center Column
    for row in tile[:4]:  # Print first 4 rows of each tile to verify
        print("".join(row))
