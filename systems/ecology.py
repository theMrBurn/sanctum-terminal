# systems/ecology.py
import copy
from systems.rosetta_stone import VOXEL_REGISTRY


class EcologyManager:
    def __init__(self, base_flavor="STANDARD"):
        self.base_registry = VOXEL_REGISTRY

    def get_config(self, flavor="STANDARD"):
        modified = copy.deepcopy(self.base_registry)

        if flavor == "HOT":
            modified["~"]["color"] = [1.0, 0.2, 0.0]  # Lava
            modified["~"]["fx"] = "heat_haze"
            modified["~"]["note"] = 30

        elif flavor == "WET":
            for sym in modified:
                modified[sym]["pts"] = int(modified[sym]["pts"] * 1.5)
                modified[sym]["color"][2] = min(1.0, modified[sym]["color"][2] + 0.3)

        elif flavor == "POISON":
            for sym in modified:
                modified[sym]["color"] = [0.1, 0.5, 0.1]  # Drab Green
                modified[sym]["fx"] = "pulse"
                modified[sym]["note"] = 82

        return modified
