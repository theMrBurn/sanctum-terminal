import sqlite3
import numpy as np
import sys
import os
from core.vault import Vault


def seed_object(obj_type="car", ox=0.0, oz=0.0):
    # Use the Vault class to handle pathing and table initialization
    vault = Vault()
    db_path = vault.db_path

    voxels = []

    if obj_type == "car":
        # CHASSIS (Deep Blue)
        for x in np.arange(ox - 1.5, ox + 1.5, 0.4):
            for z in np.arange(oz - 3.0, oz + 3.0, 0.4):
                voxels.append((float(x), 0.6, float(z), 0.0, 0.2, 0.8))
        # CABIN (Cyan)
        for x in np.arange(ox - 1.0, ox + 1.0, 0.4):
            for z in np.arange(oz - 1.0, oz + 2.0, 0.4):
                voxels.append((float(x), 1.2, float(z), 0.2, 0.8, 1.0))

    elif obj_type == "wall":
        # Straight lines: Best test for perspective/warping distortion
        for x in np.arange(ox - 15, ox + 15, 0.5):
            for y in np.arange(0, 10, 0.5):
                voxels.append((float(x), float(y), float(oz), 0.5, 0.5, 0.5))

    elif obj_type == "monolith":
        # High-density vertical marker to test height culling
        for y in range(0, 40):
            for dx in [-0.5, 0, 0.5]:
                for dz in [-0.5, 0, 0.5]:
                    voxels.append(
                        (float(ox + dx), float(y), float(oz + dz), 1.0, 0.2, 0.1)
                    )

    # Commit to the database using the Vault's resolved path
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO voxels (x, y, z, r, g, b) VALUES (?, ?, ?, ?, ?, ?)", voxels
        )
        conn.commit()

    print(f">>> [DEPLOY] Artifact Variable: {obj_type} at [{ox}, {oz}]")


if __name__ == "__main__":
    t = sys.argv[1] if len(sys.argv) > 1 else "car"
    seed_object(t)
