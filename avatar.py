import numpy as np
from config_manager import ConfigManager


class Avatar:
    def __init__(self, color=None, height=None):
        config = ConfigManager()
        # Prioritize passed arguments for TDD, fallback to manifest
        self.color = color or config.get("avatar.color", [0.2, 0.8, 1.0])
        self.height = height or config.get("avatar.height", 1.8)
        self.bob_phase = 0.0

    def get_full_body(self):
        voxels = []
        rows = int(self.height * 10)
        for y in range(0, rows):
            voxels.append({"p": (0, y * 0.1, 0), "c": self.color})

        voxels.append({"p": (0, (rows * 0.1) + 0.1, 0), "c": [1, 1, 1]})
        return voxels

    def get_view_model(self, speed, dt, is_clicking=False):
        self.bob_phase += dt * (10.0 if speed > 0.1 else 2.0)
        bob_y = np.sin(self.bob_phase) * (0.02 if speed > 0.1 else 0.005)
        recoil_z = -0.15 if is_clicking else 0.0

        return [
            {"p": (0.5, -0.4 + bob_y, -0.6 + recoil_z), "c": self.color},
            {"p": (-0.5, -0.4 + bob_y, -0.6), "c": self.color},
        ]
