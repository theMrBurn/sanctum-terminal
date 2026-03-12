import sqlite3
from datetime import datetime
from typing import Union


class SanctumTerminal:
    def __init__(self, db_path: str = "vault.db"):
        self.db_path = db_path
        self._boot_sequence()

    def _boot_sequence(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Ledger: Tracking the Gold
            cursor.execute("""CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                amount REAL,
                event_type TEXT,
                note TEXT
            )""")
            # Archive: Tracking the Relics
            cursor.execute("""CREATE TABLE IF NOT EXISTS archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archetypal_name TEXT UNIQUE,
                vibe TEXT,
                impact_rating INTEGER
            )""")
            conn.commit()

    def log_event(self, amount: Union[float, int], event_type: str, note: str):
        """Logs a financial event with strict type validation."""
        # Risk Validation: Ensure amount is numeric
        if not isinstance(amount, (int, float)):
            raise ValueError(
                f"CRITICAL: Amount must be numeric. Received: {type(amount).__name__}"
            )

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO ledger (timestamp, amount, event_type, note) VALUES (?, ?, ?, ?)",
                (datetime.now().isoformat(), float(amount), event_type, note),
            )
            conn.commit()


def acquire_relic(self, name, vibe, cost):
    """
    Executes an Atomic Transaction:
    1. Debits the Liquid Ledger
    2. Credits the Physical Archive
    """
    with sqlite3.connect(self.db_path) as conn:
        cursor = conn.cursor()
        try:
            conn.execute("BEGIN TRANSACTION")

            # 1. Debit the Ledger
            cursor.execute(
                "INSERT INTO ledger (timestamp, amount, event_type, note) VALUES (?, ?, ?, ?)",
                (
                    datetime.now().isoformat(),
                    -float(cost),
                    "CONVERSION",
                    f"Acquired: {name}",
                ),
            )

            # 2. Ink the Archive
            cursor.execute(
                "INSERT INTO archive (archetypal_name, vibe, cost) VALUES (?, ?, ?)",
                (name, vibe, float(cost)),
            )

            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise e
