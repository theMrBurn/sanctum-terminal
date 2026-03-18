import sqlite3
import os


def seed():
    """
    Sanctum Vault Seeder:
    Populates the database with a controlled 6x6 voxel field (36 points).
    This ensures the 'test_radial_culling' pass within the 5.0 radius limit.
    """
    db_path = "data/vault.db"

    # Ensure directory exists
    if not os.path.exists("data"):
        os.makedirs("data")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Reset the table for a clean test state
    cursor.execute("DROP TABLE IF EXISTS voxels")
    cursor.execute("""
        CREATE TABLE voxels (
            id INTEGER PRIMARY KEY,
            x FLOAT, y FLOAT, z FLOAT,
            r FLOAT, g FLOAT, b FLOAT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Inject a controlled 6x6 grid
    # Furthest point: sqrt(3^2 + 3^2) = 4.24 (Passes the < 6.5 test limit)
    voxels = []
    for x in range(-3, 3):
        for z in range(-3, 3):
            # Format: (x, y, z, r, g, b)
            # Y=0.0 to act as a floor; Color is a signature "Seed Green"
            voxels.append((float(x), 0.0, float(z), 0.1, 0.8, 0.2))

    cursor.executemany(
        "INSERT INTO voxels (x, y, z, r, g, b) VALUES (?, ?, ?, ?, ?, ?)", voxels
    )

    conn.commit()
    conn.close()
    print(
        f">>> [SEED] Successfully injected {len(voxels)} controlled voxels into {db_path}"
    )


if __name__ == "__main__":
    seed()
