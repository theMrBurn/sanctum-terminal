import sqlite3
import numpy as np
import os
from pathlib import Path


class VoxelRecord:
    DTYPE = [("p", "f4", (3,)), ("c", "f4", (3,))]


class Vault:
    def __init__(self, db_relative_path="data/vault.db"):
        # Absolute pathing to prevent TDD / Runtime drift
        root_dir = Path(__file__).parent.parent.absolute()
        self.db_path = root_dir / db_relative_path
        self._init_persistence()

    def _init_persistence(self):
        os.makedirs(self.db_path.parent, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS voxels (id INTEGER PRIMARY KEY, x FLOAT, y FLOAT, z FLOAT, r FLOAT, g FLOAT, b FLOAT)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pos ON voxels(x, z)")
            conn.commit()

    def _bloom_entropy(self, cx, cz):
        """Procedural Bloom: Deterministic generation for new sectors."""
        voxels = []
        for x in range(int(cx), int(cx + 40), 4):
            for z in range(int(cz), int(cz + 40), 4):
                # Deterministic Seeded Entropy
                seed = np.sin(x * 0.05) * np.cos(z * 0.05)
                y = seed * 2.5
                # Color shift: Deeper greens for low ground, cyan for peaks
                r, g, b = 0.05, 0.2 + (seed * 0.1), 0.15 + (seed * 0.2)
                voxels.append((float(x), float(y), float(z), r, g, b))

        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO voxels (x, y, z, r, g, b) VALUES (?, ?, ?, ?, ?, ?)",
                voxels,
            )
            conn.commit()

    def get_visible_frame(self, observer_pos, observer_front, radius):
        """
        THE UNIFIED PIPELINE:
        1. Coordinate Unpacking
        2. Procedural Check (Bloom)
        3. Database Query (AABB)
        4. Spatial Filtering (Culling)
        """
        try:
            px, pz = float(observer_pos[0]), float(observer_pos[2])
        except (TypeError, AttributeError, IndexError):
            px, pz = float(observer_pos.x), float(observer_pos.z)

        # A. BLOOM CHECK: Auto-generate if sector is empty
        cx, cz = (px // 40) * 40, (pz // 40) * 40
        with sqlite3.connect(self.db_path) as conn:
            if not conn.execute(
                "SELECT 1 FROM voxels WHERE x=? AND z=? LIMIT 1", (cx, cz)
            ).fetchone():
                self._bloom_entropy(cx, cz)

        # B. DB FETCH (Broad Phase)
        query = "SELECT x, y, z, r, g, b FROM voxels WHERE x BETWEEN ? AND ? AND z BETWEEN ? AND ?"
        bounds = (px - radius, px + radius, pz - radius, pz + radius)
        with sqlite3.connect(self.db_path) as conn:
            res = conn.execute(query, bounds).fetchall()

        if not res:
            return np.array([], dtype=VoxelRecord.DTYPE)

        # C. RELATIVITY FILTER (Narrow Phase)
        raw_data = np.array(res, dtype="f4")
        abs_p = raw_data[:, :3]
        delta = abs_p - np.array([px, float(observer_pos[1]), pz])
        dists_sq = np.sum(delta**2, axis=1)

        # Frustum + Radial Mask
        mask = dists_sq <= (radius**2)
        if observer_front is not None:
            norm_delta = delta / (np.sqrt(dists_sq)[:, np.newaxis] + 1e-6)
            mask &= np.dot(norm_delta, np.array(observer_front)) > -0.5

        # D. PACKING
        records = np.empty(np.sum(mask), dtype=VoxelRecord.DTYPE)
        records["p"] = abs_p[mask]
        records["c"] = raw_data[mask, 3:]
        return records

    def check_collision(self, pos, radius=1.0):
        try:
            px, pz = float(pos[0]), float(pos[2])
        except (TypeError, AttributeError):
            px, pz = float(pos.x), float(pos.z)
        with sqlite3.connect(self.db_path) as conn:
            return (
                conn.execute(
                    "SELECT COUNT(*) FROM voxels WHERE x BETWEEN ? AND ? AND z BETWEEN ? AND ? AND y > 0.5",
                    (px - radius, px + radius, pz - radius, pz + radius),
                ).fetchone()[0]
                > 0
            )
