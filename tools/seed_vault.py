import sqlite3
import os
import numpy as np
from vault_engine import DataNode  # Consistency Fix


def seed():
    db_path = "data/vault.db"
    if not os.path.exists("data"):
        os.makedirs("data")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS voxels")
    cursor.execute("""
        CREATE TABLE voxels (
            id INTEGER PRIMARY KEY,
            x FLOAT, y FLOAT, z FLOAT,
            r FLOAT, g FLOAT, b FLOAT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    voxels = []
    # Stepping by 2 to cover a 1200x1200m area without crashing VRAM
    for x in range(-600, 600, 2):
        for z in range(-600, 600, 2):
            # Procedural floor wave
            y = np.sin(x * 0.1) * np.cos(z * 0.1) * 2.0
            voxels.append((float(x), float(y), float(z), 0.1, 0.8, 0.2))

    cursor.executemany(
        "INSERT INTO voxels (x, y, z, r, g, b) VALUES (?, ?, ?, ?, ?, ?)", voxels
    )
    conn.commit()
    conn.close()
    print(f">>> [SEED] Successfully expanded vault to {len(voxels)} voxels.")


if __name__ == "__main__":
    seed()
