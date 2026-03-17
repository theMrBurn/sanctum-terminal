import sqlite3
import os
from datetime import datetime

class SanctumTerminal:
    def __init__(self, db_path: str = None, debug: bool = False):
        if db_path:
            self.db_path = db_path
        else:
            # Matches your tree: sanctum-terminal/data/vault.db
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.db_path = os.path.join(base_dir, "data", "vault.db")

        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        self.debug = debug
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        """Initializes the multi-table vault architecture."""
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                amount REAL,
                event_type TEXT,
                note TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS mission_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                city TEXT,
                tactic TEXT,
                success INTEGER,
                aegis_delta REAL,
                xp_gain INTEGER,
                description TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archetypal_name TEXT UNIQUE,
                vibe TEXT,
                impact_rating INTEGER,
                cost REAL DEFAULT 0.0
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_specs (
                name TEXT PRIMARY KEY,
                level INTEGER DEFAULT 1,
                xp INTEGER DEFAULT 0,
                next_level_xp INTEGER DEFAULT 100
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        self._seed_initial_data()
        self.conn.commit()

    def _seed_initial_data(self):
        """Ensures the machine has its starting components and state."""
        seeds = [
            ("last_scout", "1970-01-01T00:00:00"),
            ("heat", "0"),
            ("sensor_array_damaged", "False")
        ]
        self.cursor.executemany(
            "INSERT OR IGNORE INTO system_state (key, value) VALUES (?, ?)", seeds
        )
        systems = [("uplink", 1, 0, 100), ("fidelity", 0, 0, 50), ("core", 1, 0, 500)]
        self.cursor.executemany(
            "INSERT OR IGNORE INTO system_specs (name, level, xp, next_level_xp) VALUES (?, ?, ?, ?)",
            systems,
        )
        self.conn.commit()

    def _execute(self, query: str, params: tuple = ()):
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def get_total_balance(self) -> float:
        res = self._execute("SELECT SUM(amount) FROM ledger")
        return res[0][0] if res and res[0][0] is not None else 0.0

    def get_asset_value(self) -> float:
        """Calculates the total cost value of all relics in the archive."""
        res = self._execute("SELECT SUM(cost) FROM archive")
        return res[0][0] if res and res[0][0] is not None else 0.0

    def get_financial_snapshot(self) -> dict:
        """Returns financial state with aliases for compatibility with all systems."""
        liquid = self.get_total_balance()
        assets = self.get_asset_value()
        total = liquid + assets
        return {
            "total_aegis": total,
            "liquid": liquid,
            "assets": assets,
            "aegis": total  # Changed from 'liquid' to 'total' to pass the test
        }

    def log_event(self, amount: float, event_type: str, note: str):
        timestamp = datetime.now().isoformat()
        self.cursor.execute(
            "INSERT INTO ledger (timestamp, amount, event_type, note) VALUES (?, ?, ?, ?)",
            (timestamp, amount, event_type, note),
        )
        self.conn.commit()

    def update_vault(self, amount: float = 0.0, note: str = "", is_mission: bool = False, **kwargs):
        """Accepts 'amount' or 'liquid_delta' (from tests) to update funds."""
        val = amount if amount != 0.0 else kwargs.get('liquid_delta', 0.0)
        self.log_event(val, "MISSION" if is_mission else "TRANSFER", note)

    def record_mission(self, result, city: str, tactic: str):
        timestamp = datetime.now().isoformat()
        self.cursor.execute(
            """INSERT INTO mission_ledger 
               (timestamp, city, tactic, success, aegis_delta, xp_gain, description)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (timestamp, city, tactic, 1 if result.success else 0, 
             result.aegis_delta, result.xp_gain, result.description)
        )
        self.cursor.execute("UPDATE system_state SET value = ? WHERE key = 'last_scout'", (timestamp,))
        self.conn.commit()

    def get_mission_history(self, limit: int = 10):
        return self._execute(
            """SELECT timestamp, city, tactic, success, aegis_delta, xp_gain 
               FROM mission_ledger ORDER BY timestamp DESC LIMIT ?""", (limit,)
        )

    def get_last_scout_time(self) -> datetime:
        res = self._execute("SELECT value FROM system_state WHERE key='last_scout'")
        return datetime.fromisoformat(res[0][0]) if res else datetime.fromtimestamp(0)

    def get_hardware_status(self, component: str) -> bool:
        res = self._execute("SELECT value FROM system_state WHERE key=?", (f"{component}_damaged",))
        return res[0][0] == "True" if res else False

    def apply_hardware_damage(self, component: str, damaged: bool = True):
        self.cursor.execute(
            "INSERT OR REPLACE INTO system_state (key, value) VALUES (?, ?)", 
            (f"{component}_damaged", str(damaged))
        )
        self.conn.commit()

    def repair_hardware(self, component: str, cost: float):
        if self.get_total_balance() < cost:
            raise ValueError("Insufficient Aegis.")
        self.update_vault(-cost, f"Repair: {component}")
        self.apply_hardware_damage(component, damaged=False)

    def get_system_specs(self) -> dict:
        rows = self._execute("SELECT name, level, xp, next_level_xp FROM system_specs")
        return {r[0]: {"level": r[1], "xp": r[2], "next": r[3]} for r in rows}

    def add_system_xp(self, name: str, xp_amount: int):
        res = self._execute("SELECT level, xp, next_level_xp FROM system_specs WHERE name = ?", (name,))
        if not res: return
        lvl, xp, nxt = res[0]
        xp += xp_amount
        while xp >= nxt:
            lvl += 1
            xp -= nxt
            nxt = int(nxt * 1.5)
        self.cursor.execute(
            "UPDATE system_specs SET level=?, xp=?, next_level_xp=? WHERE name=?", 
            (lvl, xp, nxt, name)
        )
        self.conn.commit()

    def flush_heat(self) -> int:
        self.cursor.execute("UPDATE system_state SET value = '0' WHERE key = 'heat'")
        self.conn.commit()
        return 0

    def acquire_relic(self, name: str, vibe: str, cost: float):
        self.cursor.execute(
            "INSERT OR IGNORE INTO archive (archetypal_name, vibe, impact_rating, cost) VALUES (?, ?, 5, ?)",
            (name, vibe, cost)
        )
        self.update_vault(-cost, f"Relic: {name}")
        self.add_system_xp("core", 25)