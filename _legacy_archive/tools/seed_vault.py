import sqlite3
import os
import numpy as np
from core.vault import Vault


def seed():
    # Use the Vault class to handle pathing logic automatically
    vault = Vault()
    db_path = vault.db_path

    print(f">>> [SEED] Target: {db_path}")

    # Ensure a fresh start for the foundation
    if os.path.exists(db_path):
        os.remove(db_path)

    # We re-init via the class to ensure schema exists
    vault._init_persistence()

    voxels = []
    # 600m area foundation (Deterministic Seed)
    for x in range(-300, 300, 4):
        for z in range(-300, 300, 4):
            # Baseline sin/cos floor for the 90k foundation
            y = np.sin(x * 0.1) * np.cos(z * 0.1) * 1.5
            voxels.append((float(x), float(y), float(z), 0.1, 0.6, 0.2))

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO voxels (x, y, z, r, g, b) VALUES (?, ?, ?, ?, ?, ?)", voxels
        )
        conn.commit()

    print(f">>> [SEED] Foundation set with {len(voxels)} voxels.")


if __name__ == "__main__":
    seed()
