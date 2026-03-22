import random
from core.registry import MANIFEST


class ScenarioLoader:
    def __init__(self, seed=42):
        self.seed = seed
        self.rng = random.Random(self.seed)

    def load_scenario(self, scenario_id: str):
        """
        Accept a scenario_id (e.g., ZEN_GARDEN, NEON_STATION)
        and return coordinates based on the Registry constraints.
        """
        objects_to_spawn = []

        # Determine the base cluster of items needed for the scenario
        if scenario_id == "NEON_STATION":
            # Needs slabs, gas pumps, lanterns
            objects_to_spawn.extend(["401_slab"] * 4)  # Base foundation
            objects_to_spawn.extend(["403"] * 2)  # 2 Gas Pumps
            objects_to_spawn.extend(["201"] * 3)  # 3 Lanterns
            objects_to_spawn.extend(["101"] * 1)  # 1 Data Vault
        elif scenario_id == "ZEN_GARDEN":
            objects_to_spawn.extend(["401_slab"] * 2)
            objects_to_spawn.extend(["201"] * 5)
            objects_to_spawn.extend(["301"] * 2)
        else:
            # Default fallback
            objects_to_spawn.extend(["101", "301"])

        return self._resolve_constraints(objects_to_spawn)

    def _resolve_constraints(self, objects):
        """
        Process constraints (like must_anchor_to) and return
        a list of dicts with calculated (x, y, z) coords.
        """
        placed_objects = []
        anchors = {}  # Map obj_id to list of placement coords

        # 1. Place all foundations/anchors first
        for obj_id in list(objects):
            constraints = MANIFEST.get(obj_id, {}).get("constraints", {})
            if "must_anchor_to" not in constraints:
                # Place randomly within a bounded area (-10 to 10)
                x = self.rng.randint(-10, 10)
                z = self.rng.randint(-10, 10)

                coords = (x, 0.0, z)
                placed_objects.append({"id": obj_id, "pos": coords})

                if obj_id not in anchors:
                    anchors[obj_id] = []
                anchors[obj_id].append(coords)

                objects.remove(obj_id)

        # 2. Place constrained objects
        for obj_id in objects:
            constraints = MANIFEST.get(obj_id, {}).get("constraints", {})
            anchor_target = constraints.get("must_anchor_to")

            if anchor_target and anchor_target in anchors and anchors[anchor_target]:
                # Pick a random placed anchor to attach to
                base_coords = self.rng.choice(anchors[anchor_target])

                # Offset slightly from the anchor
                ox = base_coords[0] + self.rng.uniform(-0.5, 0.5)
                oz = base_coords[2] + self.rng.uniform(-0.5, 0.5)
                oy = base_coords[1] + 0.1  # slightly above the anchor

                placed_objects.append({"id": obj_id, "pos": (ox, oy, oz)})
            else:
                # If constraint can't be met, skip or place safely
                pass

        return placed_objects


if __name__ == "__main__":
    loader = ScenarioLoader()
    print("NEON_STATION:", loader.load_scenario("NEON_STATION"))
