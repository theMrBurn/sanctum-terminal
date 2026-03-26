import zlib

import numpy as np


class Volume:
    def __init__(self, origin, size=64.0):
        # Origin is the anchor point for this grid cell
        self.origin = np.array(origin, dtype="f4")
        self.size = size

        # THE LOCATION KEY: Deterministic hash of the grid position
        self.loc_key = zlib.adler32(self.origin.tobytes())

        self.voxels = None
        self.is_hydrated = False

    def hydrate(self, current_time, biome_seed=0):
        if self.is_hydrated:
            return
        rng = np.random.default_rng(self.loc_key ^ biome_seed)

        # 1. THE GRID FLOOR (Deterministic reference plane)
        grid_res = 16
        x = np.linspace(0, self.size, grid_res)
        z = np.linspace(0, self.size, grid_res)
        xv, zv = np.meshgrid(x, z)
        # Flatten and place at y=0
        floor_pos = np.stack(
            [xv.flatten(), np.zeros(grid_res**2), zv.flatten()], axis=1
        )
        floor_pos += self.origin

        # Deep teal for the floor grid
        floor_colors = np.full((len(floor_pos), 3), [0.05, 0.15, 0.2])

        # 2. THE INFRASTRUCTURE (Random Data Pillars)
        count = 2000
        local_pos = rng.uniform(0, self.size, (count, 3))
        # Stretch them vertically to create "Data Spires"
        local_pos[:, 1] *= rng.uniform(0.5, 10.0, count)
        abs_pos = np.vstack([floor_pos, local_pos + self.origin])

        colors = np.vstack([floor_colors, rng.uniform(0.1, 0.4, (count, 3))])

        # 3. RARE LANDMARKS (The Gold Spires)
        if self.loc_key % 5 == 0:
            s_count = 1200
            s_base = rng.uniform(10, self.size - 10, (1, 3)) + self.origin
            s_pos = s_base + rng.uniform(-1.5, 1.5, (s_count, 3))
            s_pos[:, 1] = rng.uniform(0, 100, s_count)  # 100m tall
            abs_pos = np.vstack([abs_pos, s_pos])
            colors = np.vstack([colors, np.tile([0.8, 0.6, 0.1], (s_count, 1))])

        t_count = len(abs_pos)
        times = np.full((t_count, 1), current_time, dtype="f4")
        self.voxels = np.hstack([abs_pos, colors, times]).astype("f4")
        self.is_hydrated = True
        return self.voxels
