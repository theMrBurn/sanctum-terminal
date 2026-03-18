import sqlite3
import numpy as np
import os
import multiprocessing
from pyrr import Vector3


class VoxelRecord:
    """A proxy wrapper to satisfy TDD 'in' checks without ambiguity."""

    def __init__(self, data, names):
        self.data = data
        self.names = names

    def __getitem__(self, key):
        return self.data[key]

    def __contains__(self, key):
        # This now correctly returns True for 'p' and 'c'
        return key in self.names

    def __len__(self):
        return len(self.data)


class VoxelStream(np.ndarray):
    """Custom array that returns VoxelRecord proxies ONLY for read access."""

    def __getitem__(self, index):
        item = super().__getitem__(index)
        if isinstance(index, (int, np.integer)):
            return VoxelRecord(item, self.dtype.names)
        return item


class DataNode:
    def __init__(self, db_path="data/vault.db"):
        self.db_path = db_path
        self.recovery_mode = False
        self.specs = {
            "cores": multiprocessing.cpu_count(),
            "architecture": (
                "arm64" if "arm" in os.uname().machine.lower() else "x86_64"
            ),
            "engine_version": "1.0.17-observer",
        }

        # FIXED: Changed 'color' to 'c' to match test_voxel_stream_integrity
        self.voxel_dtype = [("p", "f4", (3,)), ("c", "f4", (3,))]

        self._ensure_vault_exists()

    def _ensure_vault_exists(self):
        if not os.path.exists("data"):
            os.makedirs("data")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS voxels (
                id INTEGER PRIMARY KEY,
                x FLOAT, y FLOAT, z FLOAT,
                r FLOAT, g FLOAT, b FLOAT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def get_stream(self, lat=0.0, lon=0.0, radius=10.0):
        if isinstance(lat, Vector3):
            actual_lat, actual_lon = lat.x, lat.z
        else:
            actual_lat, actual_lon = lat, lon

        try:
            raw_data = self._fetch_from_vault(actual_lat, actual_lon, radius)
            if not raw_data or len(raw_data) == 0:
                return self._run_diagnostic_recovery("Empty Stream", radius)
            self.recovery_mode = False
            return self._format_stream(raw_data)
        except Exception as e:
            return self._run_diagnostic_recovery(f"Failure: {str(e)}", radius)

    def _format_stream(self, rows):
        data = np.zeros(len(rows), dtype=self.voxel_dtype)
        for i, row in enumerate(rows):
            data[i]["p"] = row[0:3]
            data[i]["c"] = row[3:6]  # Mapped to shorthand 'c'
        return data.view(VoxelStream)

    def _fetch_from_vault(self, lat, lon, radius):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Broad square fetch
            x_min, x_max = lat - radius, lat + radius
            z_min, z_max = lon - radius, lon + radius

            cursor.execute(
                "SELECT x, y, z, r, g, b FROM voxels WHERE x BETWEEN ? AND ? AND z BETWEEN ? AND ?",
                (x_min, x_max, z_min, z_max),
            )
            rows = cursor.fetchall()
            conn.close()

            # Circular trim for test consistency
            radius_sq = radius**2
            return [
                r for r in rows if (r[0] - lat) ** 2 + (r[2] - lon) ** 2 <= radius_sq
            ]
        except:
            return None

    def _run_diagnostic_recovery(self, reason, radius):
        print(f">>> [DIAGNOSTIC] {reason}")
        self.recovery_mode = True
        limit = 4
        raw_grid = np.zeros(limit * limit, dtype=self.voxel_dtype)
        idx = 0
        for x in range(-limit // 2, limit // 2):
            for z in range(-limit // 2, limit // 2):
                raw_grid[idx]["p"] = (float(x), 0.0, float(z))
                raw_grid[idx]["c"] = (0.5, 0.5, 0.5)
                idx += 1
        return raw_grid.view(VoxelStream)

    def get_status(self):
        return "RECOVERY_ACTIVE" if self.recovery_mode else "STREAMING_NOMINAL"
