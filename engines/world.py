import math


class WorldEngine:
    def __init__(self, seed=42):
        self.seed = seed

    def get_object_at(self, x, y):
        """
        001: Substrate (Ground)
        101: Data Vault (Entity)
        301: Void Wall (Barrier)
        """
        # Deterministic seed for spatial consistency
        h = (int(x) * 73856093 ^ int(y) * 19349663 ^ self.seed) % 100

        # Buffer around spawn
        if abs(x) < 3 and abs(y) < 3:
            return None

        if h > 92:
            return "101"  # Data Vault
        if h > 75:
            return "301"  # Void Wall

        return None
