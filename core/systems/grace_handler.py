import json
import sqlite3
import time
from pathlib import Path


CHECKPOINT_EVENTS = {"system_panic", "biome_transition", "seed_planted", "seed_archived"}


class GraceHandler:
    """
    Universal state preservation layer.
    Any system fires events here. Grace handler logs, checkpoints, recovers.
    system_panic always writes checkpoint immediately.
    """

    def __init__(self, db_path=None, checkpoint_path=None):
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "data" / "vault.db"

        self.db_path         = Path(db_path)
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path else                                Path(__file__).parent.parent.parent / "data" / "checkpoint.json"

        if not self.db_path.exists():
            raise FileNotFoundError(
                f"GraceHandler: vault.db not found at {self.db_path}"
            )

        self.event_log = []
        self._ensure_schema()

    def _ensure_schema(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS grace_log (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT NOT NULL,
                        payload    TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"GraceHandler: schema init failed — {e}") from e

    def fire(self, event_type, payload=None):
        """
        Fire a grace event. Logs to memory + DB.
        system_panic always writes checkpoint immediately.
        """
        payload   = payload or {}
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")

        event = {
            "event_type": event_type,
            "payload":    payload,
            "timestamp":  timestamp,
        }

        self.event_log.append(event)

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO grace_log (event_type, payload) VALUES (?, ?)",
                    (event_type, json.dumps(payload))
                )
                conn.commit()
        except sqlite3.Error as e:
            raise RuntimeError(f"GraceHandler.fire: DB write failed — {e}") from e

        if event_type == "system_panic":
            self.checkpoint(payload)

        return event

    def checkpoint(self, state):
        """
        Write current state to checkpoint.json.
        Called on significant transitions and system_panic.
        """
        last_event = self.event_log[-1] if self.event_log else None
        data = {
            "written_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "state":      state,
            "last_event": last_event,
        }
        try:
            with open(self.checkpoint_path, "w") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            raise RuntimeError(f"GraceHandler.checkpoint: write failed — {e}") from e

    def recover(self):
        """
        Attempt to recover state from checkpoint.json.
        Returns state dict or None if no checkpoint exists.
        """
        if not self.checkpoint_path.exists():
            return None
        try:
            data = json.load(open(self.checkpoint_path))
            return data.get("state")
        except (OSError, json.JSONDecodeError):
            return None
