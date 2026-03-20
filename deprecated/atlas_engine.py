import numpy as np


class Cartographer:
    """The Global Logic: Defines the 16x16 Macro World."""

    def __init__(self, seed=42):
        self.seed = seed
        self.grid_dim = 16  # 16x16 Tiles
        self.tile_res = 32  # 32x32 ASCII chars per tile

        # Biome LUT: 0: Deep Water, 1: Shallow/Beach, 2: Coastal Forest, 3: Meadow
        self.biomes = ["~", ".", "*", "v"]

    def get_biome_at(self, gx, gz):
        """Returns biome based on X-axis gradient (Water to Meadow)."""
        x_percent = gx / self.grid_dim
        if x_percent < 0.25:
            return 0  # Water
        if x_percent < 0.35:
            return 1  # Beach
        if x_percent < 0.75:
            return 2  # Forest
        return 3  # Meadow

    def get_path_x(self, gz):
        """The 'S-Trail' Spline: Guarantees continuity across ALL tiles."""
        # Math: Midpoint (8) + Sine Wave.
        # Period and Amplitude are fixed to ensure edges ALWAYS match.
        return 16 + np.sin(gz * 0.15) * 10

    def get_stream_x(self, gz):
        """The Stream Spline: Flows from Forest to Water."""
        return 10 + np.cos(gz * 0.1) * 5


class AtlasEngine:
    """The Local Logic: Generates the 32x32 'CAPTCHA' maps."""

    def __init__(self, cart):
        self.cart = cart

    def generate_tile(self, tx, tz):
        """Generates a seamless 32x32 ASCII tile."""
        grid = np.full((self.cart.tile_res, self.cart.tile_res), " ")

        for z in range(self.cart.tile_res):
            # Global Z-coordinate for the spline math
            global_z = (tz * self.cart.tile_res) + z

            # 1. Determine Biome (Horizontal Gradient)
            for x in range(self.cart.tile_res):
                (tx * self.cart.tile_res) + x
                b_idx = self.cart.get_biome_at(tx, tz)  # Simplified to tile-level
                grid[z, x] = self.cart.biomes[b_idx]

            # 2. Inject S-Trail (Priority Overlap)
            # Find the path's X-position relative to THIS tile
            target_x = self.cart.get_path_x(global_z)
            local_x = int(target_x - (tx * self.cart.tile_res))

            if 0 <= local_x < self.cart.tile_res:
                grid[z, local_x] = "P"  # 'P' for Path

            # 3. Inject Stream (Priority Overlap)
            stream_x = self.cart.get_stream_x(global_z)
            local_sx = int(stream_x - (tx * self.cart.tile_res))

            if 0 <= local_sx < self.cart.tile_res:
                grid[z, local_sx] = "S"  # 'S' for Stream

        return grid


def debug_render():
    """Stand-alone CLI to verify the puzzle pieces fit."""
    cart = Cartographer()
    engine = AtlasEngine(cart)

    # Let's look at a 2x2 block of tiles (64x64 characters)
    for tz in [0, 1]:  # Two tiles North/South
        tile_rows = []
        for tx in [4, 5]:  # Two tiles East/West (The Beach/Forest transition)
            tile_rows.append(engine.generate_tile(tx, tz))

        # Merge tile rows for printing
        for r in range(32):
            combined_row = "".join(["".join(tile[r]) for tile in tile_rows])
            print(combined_row)


if __name__ == "__main__":
    debug_render()
