"""
core/systems/session_boundary.py

The breath between sessions.
Every session is one inhale and one exhale.
The world exists in between.

On begin: the world remembers what it was.
On end:   the world records what happened.
In between: 1:1 real time passes.
The world ages whether you are watching or not.
"""
import json
import math
import sqlite3
import time
from pathlib import Path


# Drift rate — how much the world shifts per real second of absence
# At this rate: 1 hour = 0.004 drift, 24 hours = 0.086 drift
DRIFT_RATE      = 0.000001  # per second
DRIFT_MAX       = 1.0
SCHEMA_VERSION  = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    seed        TEXT    NOT NULL,
    began_at    REAL    NOT NULL,
    ended_at    REAL,
    position_x  REAL,
    position_y  REAL,
    position_z  REAL,
    atmosphere  TEXT,
    fingerprint TEXT,
    world_age   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);
"""


class SessionBoundary:
    """
    The threshold between sessions.
    Knows what was. Records what is. Calculates what changed.
    The Philosopher Monk exists here between worlds.
    """

    def __init__(self, db_path=None):
        self.db_path      = db_path or str(Path("data/vault.db"))
        self._current_seed= None
        self._began_at    = None
        self._session_id  = None
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._conn() as cx:
            cx.executescript(SCHEMA)
            cx.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION))
            )

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def is_first_session(self, seed=None):
        """True if no completed sessions exist for this seed."""
        with self._conn() as cx:
            if seed:
                row = cx.execute(
                    "SELECT COUNT(*) FROM sessions WHERE seed=? AND ended_at IS NOT NULL",
                    (seed,)
                ).fetchone()
            else:
                row = cx.execute(
                    "SELECT COUNT(*) FROM sessions WHERE ended_at IS NOT NULL"
                ).fetchone()
            return row[0] == 0

    def world_age(self, seed=None):
        """Number of completed sessions for this seed."""
        with self._conn() as cx:
            if seed:
                row = cx.execute(
                    "SELECT COUNT(*) FROM sessions WHERE seed=? AND ended_at IS NOT NULL",
                    (seed,)
                ).fetchone()
            else:
                row = cx.execute(
                    "SELECT COUNT(*) FROM sessions WHERE ended_at IS NOT NULL"
                ).fetchone()
            return row[0]

    def elapsed_real_seconds(self, seed=None):
        """
        Real seconds since the last session ended.
        Zero if no prior session exists.
        """
        seed = seed or self._current_seed
        with self._conn() as cx:
            row = cx.execute(
                "SELECT ended_at FROM sessions WHERE seed=? AND ended_at IS NOT NULL ORDER BY ended_at DESC LIMIT 1",
                (seed or "",)
            ).fetchone()
        if not row:
            return 0
        return max(0, time.time() - row[0])

    def begin(self, seed):
        """
        Begin a session.
        Returns state dict: position, world_age, elapsed, atmosphere,
        fingerprint, is_first.
        The world remembers.
        """
        self._current_seed = seed
        self._began_at     = time.time()
        elapsed    = self.elapsed_real_seconds(seed)
        age        = self.world_age(seed)
        first      = age == 0
        last       = self._last_session(seed)
        position   = None
        atmosphere = {}
        fingerprint= {}
        if last:
            if last["position_x"] is not None:
                position = (
                    last["position_x"],
                    last["position_y"],
                    last["position_z"],
                )
            if last["atmosphere"]:
                atmosphere = json.loads(last["atmosphere"])
            if last["fingerprint"]:
                fingerprint = json.loads(last["fingerprint"])
        with self._conn() as cx:
            cur = cx.execute(
                "INSERT INTO sessions (seed, began_at, world_age) VALUES (?, ?, ?)",
                (seed, self._began_at, age)
            )
            self._session_id = cur.lastrowid
        return {
            "position":        position,
            "world_age":       age,
            "elapsed_seconds": elapsed,
            "atmosphere":      atmosphere,
            "fingerprint":     fingerprint,
            "is_first":        first,
            "drift":           self.calculate_drift(elapsed),
        }

    def end(self, position=(0,0,0), atmosphere=None, fingerprint=None):
        """
        End a session.
        Records position, atmosphere, fingerprint, timestamp.
        The world exhales.
        """
        if not self._session_id:
            return
        x, y, z = position
        with self._conn() as cx:
            cx.execute(
                """UPDATE sessions SET
                   ended_at=?, position_x=?, position_y=?, position_z=?,
                   atmosphere=?, fingerprint=?
                   WHERE id=?""",
                (
                    time.time(), x, y, z,
                    json.dumps(atmosphere or {}),
                    json.dumps(fingerprint or {}),
                    self._session_id
                )
            )
        self._session_id = None

    def calculate_drift(self, elapsed_seconds):
        """
        How much has the world shifted during this absence?
        Proportional to real time. Capped at DRIFT_MAX.
        The world ages whether you are watching or not.
        """
        return min(DRIFT_MAX, elapsed_seconds * DRIFT_RATE)

    def get_history(self, seed=None):
        """
        Return completed session records.
        The world remembers every breath.
        """
        seed = seed or self._current_seed
        with self._conn() as cx:
            if seed:
                rows = cx.execute(
                    "SELECT * FROM sessions WHERE seed=? AND ended_at IS NOT NULL ORDER BY began_at",
                    (seed,)
                ).fetchall()
            else:
                rows = cx.execute(
                    "SELECT * FROM sessions WHERE ended_at IS NOT NULL ORDER BY began_at"
                ).fetchall()
            cols = [d[0] for d in cx.execute("SELECT * FROM sessions LIMIT 0").description]
        records = []
        for row in rows:
            r = dict(zip(cols, row))
            r["timestamp"] = r["began_at"]
            records.append(r)
        return records

    def _last_session(self, seed):
        """Most recent completed session for this seed."""
        with self._conn() as cx:
            row = cx.execute(
                "SELECT * FROM sessions WHERE seed=? AND ended_at IS NOT NULL ORDER BY ended_at DESC LIMIT 1",
                (seed,)
            ).fetchone()
            if not row:
                return None
            cols = [d[0] for d in cx.execute("SELECT * FROM sessions LIMIT 0").description]
            return dict(zip(cols, row))