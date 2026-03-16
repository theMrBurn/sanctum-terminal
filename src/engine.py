import os
import sqlite3
from datetime import datetime
from typing import Any, List, Union

from rich.console import Console
from rich.panel import Panel

console = Console()


class SanctumTerminal:
    def __init__(self, db_path: str = None, debug: bool = False):
        self.debug = debug
        self.db_path = self._resolve_path(db_path)
        self._boot_sequence()

    def _resolve_path(self, db_path: str) -> str:
        """Determines if we use a mock DB or the production vault."""
        if db_path is not None:
            return db_path
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "data", "vault.db")

    def _boot_sequence(self):
        """Standard table initialization and state hardening."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # 1. Permanent Transaction History
        self._execute(
            """CREATE TABLE IF NOT EXISTS ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            amount REAL,
            event_type TEXT,
            note TEXT
        )""",
            commit=True,
        )

        # 2. Physical Asset Archive
        self._execute(
            """CREATE TABLE IF NOT EXISTS archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archetypal_name TEXT UNIQUE,
            vibe TEXT,
            impact_rating INTEGER,
            cost REAL DEFAULT 0.0
        )""",
            commit=True,
        )

        # 3. System State (Temporal Tracking & Metadata)
        self._execute(
            """CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )""",
            commit=True,
        )

        # Initialize the last_scout timestamp if it's a fresh vault
        self._execute(
            """
            INSERT OR IGNORE INTO system_state (key, value) 
            VALUES ('last_scout', '1970-01-01T00:00:00')
        """,
            commit=True,
        )

    def _execute(
        self, query: str, params: tuple = (), commit: bool = False
    ) -> List[Any]:
        """Telemetry-enabled SQL executor."""
        if self.debug:
            console.print(
                Panel(
                    f"[bold magenta]SQL REQUEST[/bold magenta]\n[white]{query}[/white]\n"
                    f"[cyan]PARAMS:[/cyan] {params}",
                    title="[bold]DATA WIRE[/bold]",
                    border_style="magenta",
                )
            )
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            result = cursor.fetchall()
            if commit:
                conn.commit()
            if self.debug:
                console.print(
                    f"[bold green]SQL RESPONSE:[/bold green] {len(result)} rows returned\n"
                )
            return result

    def log_event(self, amount: Union[float, int], event_type: str, note: str):
        """Records a movement of capital in the ledger."""
        query = "INSERT INTO ledger (timestamp, amount, event_type, note) VALUES (?, ?, ?, ?)"
        params = (datetime.now().isoformat(), float(amount), event_type, note)
        self._execute(query, params, commit=True)

    def update_vault(self, liquid_delta: float, note: str, is_mission: bool = False):
        """
        Unified write-back: Logs the transaction and updates system clocks.
        """
        # Record the financial change
        event_type = "MISSION" if is_mission else "ADJUST"
        self.log_event(amount=liquid_delta, event_type=event_type, note=note)

        # Update temporal lock if this was a mission
        if is_mission:
            now = datetime.now().isoformat()
            self._execute(
                "UPDATE system_state SET value = ? WHERE key = 'last_scout'",
                (now,),
                commit=True,
            )

    def get_last_scout_time(self) -> datetime:
        """Retrieves the last recorded scout timestamp for cooldown checks."""
        query = "SELECT value FROM system_state WHERE key = 'last_scout'"
        result = self._execute(query)
        return datetime.fromisoformat(result[0][0])

    def get_total_balance(self) -> float:
        """Calculates total liquid balance from the ledger."""
        query = "SELECT SUM(amount) FROM ledger"
        result = self._execute(query)
        return result[0][0] if result[0][0] is not None else 0.0

    def get_total_valuation(self) -> float:
        """Calculates the total value of the Physical Archive."""
        query = "SELECT SUM(cost) FROM archive"
        result = self._execute(query)
        return result[0][0] if result[0][0] is not None else 0.0

    def get_financial_snapshot(self) -> dict:
        """Aggregates the total financial state for the dashboard."""
        liquid = self.get_total_balance()
        assets = self.get_total_valuation()

        return {"liquid": liquid, "assets": assets, "aegis": liquid + assets}

    def acquire_relic(self, name: str, vibe: str, cost: float):
        """Atomic transaction for converting liquid capital to physical relics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                conn.execute("BEGIN TRANSACTION")
                cursor.execute(
                    "INSERT INTO ledger (timestamp, amount, event_type, note) VALUES (?, ?, ?, ?)",
                    (
                        datetime.now().isoformat(),
                        -float(cost),
                        "CONVERSION",
                        f"Acquired: {name}",
                    ),
                )
                cursor.execute(
                    "INSERT INTO archive (archetypal_name, vibe, cost) VALUES (?, ?, ?)",
                    (name, vibe, float(cost)),
                )
                conn.commit()
                return True
            except Exception as e:
                conn.rollback()
                raise e
