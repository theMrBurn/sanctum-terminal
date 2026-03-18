import sqlite3
import numpy as np
import os


class DataNode:
    def __init__(self, db_path="data/vault.db"):
        self.db_path = db_path
        self.voxel_dtype = [("p", "f4", (3,)), ("c", "f4", (3,))]
        self._ensure_vault_exists()

    def _ensure_vault_exists(self):
        if not os.path.exists("data"):
            os.makedirs("data")
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS voxels (id INTEGER PRIMARY KEY, x FLOAT, y FLOAT, z FLOAT, r FLOAT, g FLOAT, b FLOAT)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pos ON voxels(x, z)")
        conn.close()

    def fetch_sector(self, pos, radius):
        """Pure Persistence: Just fetches absolute world data."""
        self.sync_world_state(pos)  # Keep the procedural gen running
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT x, y, z, r, g, b FROM voxels WHERE x BETWEEN ? AND ? AND z BETWEEN ? AND ?",
            (pos.x - radius, pos.x + radius, pos.z - radius, pos.z + radius),
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return np.array([], dtype=self.voxel_dtype)
        data = np.zeros(len(rows), dtype=self.voxel_dtype)
        for i, r in enumerate(rows):
            data[i]["p"], data[i]["c"] = r[0:3], r[3:6]
        return data

    def sync_world_state(self, pos):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cx, cz = int(np.floor(pos.x / 40)) * 40, int(np.floor(pos.z / 40)) * 40
        cursor.execute(
            "SELECT id FROM voxels WHERE x = ? AND z = ? AND y < 0.5 LIMIT 1", (cx, cz)
        )
        if not cursor.fetchone():
            voxels = []
            for x in range(cx, cx + 44, 4):
                for z in range(cz, cz + 44, 4):
                    y = np.sin(x * 0.1) * np.cos(z * 0.1) * 0.2
                    voxels.append((float(x), float(y), float(z), 0.1, 0.3, 0.2))
            conn.executemany(
                "INSERT INTO voxels (x, y, z, r, g, b) VALUES (?, ?, ?, ?, ?, ?)",
                voxels,
            )
            conn.commit()
        conn.close()

    def check_collision(self, pos, radius=1.0):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM voxels WHERE x BETWEEN ? AND ? AND z BETWEEN ? AND ? AND y > 0.4 LIMIT 1",
            (pos.x - radius, pos.x + radius, pos.z - radius, pos.z + radius),
        )
        hit = cursor.fetchone()[0] > 0
        conn.close()
        return hit
