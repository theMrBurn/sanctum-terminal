import hashlib
import json
import sqlite3
import time
from pathlib import Path


class SeedEngine:
    """
    Manages the seed lifecycle for Sanctum Terminal.
    3 seeds max in pocket. 1 planted at a time.
    Archiving a seed ends it permanently — its story is complete.
    Consent version tracked on every seed. No PII ever stored.
    """

    MAX_POCKET = 3
    CONSENT_VERSION = "1.0"

    def __init__(self, db_path=None, config=None):
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "data" / "vault.db"

        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"SeedEngine: vault.db not found at {self.db_path}")

        self._ensure_schema()
        self.pocket = []
        self.planted = None
        self._load_state()

    # ── Schema ────────────────────────────────────────────────────────────────

    def _ensure_schema(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS seeds (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        label           TEXT,
                        seed_hash       TEXT UNIQUE NOT NULL,
                        status          TEXT DEFAULT 'exploring',
                        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        snapshot        TEXT,
                        consent_version TEXT DEFAULT '1.0'
                    )
                """)
                conn.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"SeedEngine: schema init failed — {e}") from e

    # ── State ─────────────────────────────────────────────────────────────────

    def _load_state(self):
        """Load exploring and planted seeds into memory on boot."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM seeds WHERE status != 'archived' "
                    "ORDER BY created_at ASC"
                ).fetchall()
            self.pocket = [dict(r) for r in rows]
            planted = [s for s in self.pocket if s["status"] == "planted"]
            self.planted = planted[0] if planted else None
        except sqlite3.Error as e:
            raise RuntimeError(f"SeedEngine: state load failed — {e}") from e

    # ── Seed hash ─────────────────────────────────────────────────────────────

    def _make_hash(self, label):
        """Deterministic but unique hash from label + timestamp."""
        raw = f"{label}:{time.time_ns()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def _make_snapshot(self):
        """
        Captures current world state as a JSON snapshot.
        No PII. Only game context.
        """
        return json.dumps(
            {
                "biome": "VOID",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "version": self.CONSENT_VERSION,
            }
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(self, label="Unnamed World"):
        """
        Generates a new seed and adds it to the pocket.
        Raises ValueError if pocket is full (max 3).
        """
        active = [s for s in self.pocket if s["status"] != "archived"]
        if len(active) >= self.MAX_POCKET:
            raise ValueError(
                f"SeedEngine: pocket is full ({self.MAX_POCKET} seeds max). "
                "Archive a seed to make room."
            )

        seed_hash = self._make_hash(label)
        snapshot = self._make_snapshot()

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "INSERT INTO seeds "
                    "(label, seed_hash, status, snapshot, consent_version) "
                    "VALUES (?, ?, 'exploring', ?, ?)",
                    (label, seed_hash, snapshot, self.CONSENT_VERSION),
                )
                conn.commit()
                row_id = cursor.lastrowid
        except sqlite3.Error as e:
            raise RuntimeError(f"SeedEngine.generate: DB write failed — {e}") from e

        seed = {
            "id": row_id,
            "label": label,
            "seed_hash": seed_hash,
            "status": "exploring",
            "snapshot": snapshot,
            "consent_version": self.CONSENT_VERSION,
        }
        self.pocket.append(seed)
        return seed

    def plant(self, seed_hash):
        """
        Plants a seed — sets it as the active world.
        Only one seed can be planted at a time.
        Raises ValueError if seed not found in pocket.
        """
        target = next((s for s in self.pocket if s["seed_hash"] == seed_hash), None)
        if target is None:
            raise ValueError(
                f"SeedEngine.plant: seed {seed_hash!r} not found in pocket."
            )

        # Unplant any currently planted seed
        for seed in self.pocket:
            if seed["status"] == "planted":
                seed["status"] = "exploring"
                try:
                    with sqlite3.connect(self.db_path) as conn:
                        conn.execute(
                            "UPDATE seeds SET status='exploring' WHERE seed_hash=?",
                            (seed["seed_hash"],),
                        )
                        conn.commit()
                except sqlite3.Error as e:
                    raise RuntimeError(
                        f"SeedEngine.plant: DB update failed — {e}"
                    ) from e

        # Plant the target
        target["status"] = "planted"
        self.planted = target
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE seeds SET status='planted' WHERE seed_hash=?", (seed_hash,)
                )
                conn.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"SeedEngine.plant: DB update failed — {e}") from e

        return target

    def archive(self, seed_hash):
        """
        Archives a seed — its story is complete.
        Removes from pocket. Frees a slot.
        This is permanent. The world is done.
        """
        target = next((s for s in self.pocket if s["seed_hash"] == seed_hash), None)
        if target is None:
            raise ValueError(
                f"SeedEngine.archive: seed {seed_hash!r} not found in pocket."
            )

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE seeds SET status='archived' WHERE seed_hash=?", (seed_hash,)
                )
                conn.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"SeedEngine.archive: DB update failed — {e}") from e

        self.pocket = [s for s in self.pocket if s["seed_hash"] != seed_hash]
        if self.planted and self.planted["seed_hash"] == seed_hash:
            self.planted = None

        return True

    def get_planted(self):
        """Returns the currently planted seed or None."""
        return self.planted

    def get_pocket(self):
        """Returns all seeds currently in pocket."""
        return self.pocket
