import numpy as np


class BiomeEngine:
    def __init__(self, seed=42):
        self.seed = seed

    def get_local_biome(self, x, z):
        # Very basic mock of noise-based biome detection
        # In a real setup, we'd use a noise library here
        temp = np.sin(x * 0.01) * np.cos(z * 0.01)
        moisture = np.cos(x * 0.005 + z * 0.005)

        if temp > 0.5:
            return "DESERT" if moisture < 0 else "JUNGLE"
        elif temp < -0.5:
            return "TUNDRA"
        return "PLAINS"

    def generate_voxels(self, offset, radius):
        # Logic to send specific generation commands to the Vault
        # based on the current biome type
        pass
