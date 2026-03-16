import sqlite3
import os
from datetime import datetime


class SanctumTerminal:
    def __init__(self, db_path: str = None, debug: bool = False):
        if db_path:
            self.db_path = db_path
        else:
            # Resolve absolute path to project root /data/vault.db
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.db_path = os.path.join(base_dir, "data", "vault.db")

        self.debug = debug
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        """Initializes the multi-table vault architecture."""
        # Financial Tables
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
            CREATE TABLE IF NOT EXISTS archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                archetypal_name TEXT UNIQUE,
                vibe TEXT,
                impact_rating INTEGER,
                cost REAL DEFAULT 0.0
            )
        """)

        # Progression Table: The Genome
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_specs (
                name TEXT PRIMARY KEY,
                level INTEGER DEFAULT 1,
                xp INTEGER DEFAULT 0,
                next_level_xp INTEGER DEFAULT 100
            )
        """)

        # System State (Cooldowns, Heat, Hardware Flags)
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
        self.cursor.execute(
            "INSERT OR IGNORE INTO system_state (key, value) VALUES (?, ?)",
            ("last_scout", "1970-01-01T00:00:00"),
        )
        self.cursor.execute(
            "INSERT OR IGNORE INTO system_state (key, value) VALUES (?, ?)",
            ("heat", "0"),
        )
        # Initial Hardware State: Nominal
        self.cursor.execute(
            "INSERT OR IGNORE INTO system_state (key, value) VALUES (?, ?)",
            ("sensor_array_damaged", "False"),
        )

        # Initial Systems: Start at Level 0 for Fidelity to trigger 'BIOS' mode
        systems = [("uplink", 1, 0, 100), ("fidelity", 0, 0, 50), ("core", 1, 0, 500)]
        self.cursor.executemany(
            "INSERT OR IGNORE INTO system_specs (name, level, xp, next_level_xp) VALUES (?, ?, ?, ?)",
            systems,
        )

    # --- HARDWARE INTEGRITY API ---

    def get_hardware_status(self, component_name: str) -> bool:
        """
        GREEN: Retrieves the damage status of a specific hardware component.
        Returns True if damaged, False if nominal.
        """
        key = f"{component_name}_damaged"
        res = self._execute("SELECT value FROM system_state WHERE key=?", (key,))

        # SQLite stores everything as strings; we check for "True"
        if res and res[0][0] == "True":
            return True
        return False

    def apply_hardware_damage(self, component_name: str, damaged: bool = True):
        """
        GREEN: Persists hardware damage state to the database.
        Used when high heat causes system degradation.
        """
        key = f"{component_name}_damaged"
        val = str(damaged)
        self.cursor.execute(
            "INSERT OR REPLACE INTO system_state (key, value) VALUES (?, ?)", (key, val)
        )
        self.conn.commit()

    def repair_hardware(self, component_name: str, cost: float):
        """
        GREEN: Repairs a component, deducts cost, and resets the damage flag.
        Raises ValueError if funds are insufficient.
        """
        current_balance = self.get_total_balance()

        if current_balance < cost:
            raise ValueError(
                f"Insufficient Aegis for repair. Required: {cost}, Available: {current_balance}"
            )

        # 1. Deduct the cost from the ledger
        self.update_vault(-cost, f"Hardware Repair: {component_name}")

        # 2. Reset the damage flag to False
        self.apply_hardware_damage(component_name, damaged=False)

        if self.debug:
            print(f"[REPAIR] {component_name.upper()} restored to nominal state.")

    # --- PROGRESSION API ---

    def get_system_specs(self) -> dict:
        """Returns a dictionary of all system levels and progress."""
        self.cursor.execute("SELECT name, level, xp, next_level_xp FROM system_specs")
        rows = self.cursor.fetchall()
        return {r[0]: {"level": r[1], "xp": r[2], "next": r[3]} for r in rows}

    def add_system_xp(self, name: str, xp_amount: int):
        """Adds XP to a specific system and handles leveling."""
        self.cursor.execute(
            "SELECT level, xp, next_level_xp FROM system_specs WHERE name = ?", (name,)
        )
        res = self.cursor.fetchone()
        if not res:
            return

        level, current_xp, next_xp = res
        new_xp = current_xp + xp_amount

        while new_xp >= next_xp:
            level += 1
            new_xp = new_xp - next_xp
            next_xp = int(next_xp * 1.5)
            if self.debug:
                print(f"[EVOLUTION] {name.upper()} reached Level {level}")

        self.cursor.execute(
            "UPDATE system_specs SET level = ?, xp = ?, next_level_xp = ? WHERE name = ?",
            (level, new_xp, next_xp, name),
        )
        self.conn.commit()

    # --- RECONCILED FINANCE LOGIC ---

    def log_event(self, amount: float, event_type: str, note: str):
        """Direct ledger logging (supports existing tests)."""
        timestamp = datetime.now().isoformat()
        self.cursor.execute(
            "INSERT INTO ledger (timestamp, amount, event_type, note) VALUES (?, ?, ?, ?)",
            (timestamp, amount, event_type, note),
        )
        self.conn.commit()

    def acquire_relic(self, name: str, vibe: str, cost: float):
        """Converts liquid capital into an asset and grants Core XP."""
        self.log_event(-cost, "CONVERSION", f"Acquired: {name}")
        self.cursor.execute(
            "INSERT OR IGNORE INTO archive (archetypal_name, vibe, cost) VALUES (?, ?, ?)",
            (name, vibe, cost),
        )
        # RPG Hook: System growth tied to asset acquisition
        self.add_system_xp("core", int(cost / 2))
        self.conn.commit()

    def update_vault(self, liquid_delta: float, note: str, is_mission: bool = False):
        """Standard method for adding/subtracting Aegis."""
        timestamp = datetime.now().isoformat()
        self.cursor.execute(
            "INSERT INTO ledger (timestamp, amount, event_type, note) VALUES (?, ?, ?, ?)",
            (timestamp, liquid_delta, "MISSION" if is_mission else "PASSIVE", note),
        )
        if is_mission:
            self.cursor.execute(
                "INSERT OR REPLACE INTO system_state (key, value) VALUES (?, ?)",
                ("last_scout", timestamp),
            )
        self.conn.commit()

    def get_total_balance(self):
        self.cursor.execute("SELECT SUM(amount) FROM ledger")
        res = self.cursor.fetchone()[0]
        return res if res else 0.0

    def get_financial_snapshot(self):
        liquid = self.get_total_balance()
        self.cursor.execute("SELECT SUM(cost) FROM archive")
        assets = self.cursor.fetchone()[0] or 0.0
        return {"liquid": liquid, "assets": assets, "aegis": liquid + assets}

    def get_last_scout_time(self):
        self.cursor.execute("SELECT value FROM system_state WHERE key = 'last_scout'")
        res = self.cursor.fetchone()
        return datetime.fromisoformat(res[0]) if res else datetime(1970, 1, 1)

    def _execute(self, query, params=()):
        """Internal helper for testing snippets."""
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def get_total_valuation(self):
        """Returns total cost of all archived relics."""
        self.cursor.execute("SELECT SUM(cost) FROM archive")
        res = self.cursor.fetchone()[0]
        return res if res else 0.0

    def flush_heat(self, amount: int = 25, cost: float = 100.0):
        """Vents thermal load in exchange for liquid Aegis."""
        heat_data = self._execute("SELECT value FROM system_state WHERE key='heat'")
        current_heat = int(heat_data[0][0]) if heat_data else 0
        new_heat = max(0, current_heat - amount)

        # 1. Deduct Cost
        self.update_vault(-cost, f"Thermal Flush: -{amount}% Heat")

        # 2. Update Heat
        self.cursor.execute(
            "UPDATE system_state SET value = ? WHERE key = 'heat'", (str(new_heat),)
        )
        self.conn.commit()
        return new_heat