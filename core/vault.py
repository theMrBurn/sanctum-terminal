"""
core/vault.py

Vault -- unified read/write interface for world state.
One object. Ask it anything.

Tables:
    archive   -- relics (real-world events, impact-rated)
    scenarios -- scenario ledger (provenance hash = primary key)
    objects   -- catalog cache (seeded from objects.json)

The vault is the ledger. Everything that passes through the world
leaves a mark. The Yellow Sign is on every record.
"""

import json
import sqlite3
from pathlib import Path


class vault:
    """
    Central data repository for Sanctum Terminal.
    Runtime registry (in-memory) backed by SQLite persistence.
    """

    DEFAULT_DB     = Path(__file__).parent.parent / "data" / "vault.db"
    OBJECTS_JSON   = Path(__file__).parent.parent / "config" / "blueprints" / "objects.json"

    def __init__(self, db_path=None):
        self._registry = {}
        self.db_path   = Path(db_path) if db_path else self.DEFAULT_DB
        self.initialized = True
        self._ensure_schema()
        print("Vault: Secured and Indexed.")

    # -- Schema ----------------------------------------------------------------

    def _ensure_schema(self):
        if not self.db_path.parent.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS archive (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        archetypal_name TEXT NOT NULL,
                        vibe            TEXT,
                        impact_rating   INTEGER DEFAULT 1
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS scenarios (
                        id               TEXT PRIMARY KEY,
                        type             TEXT NOT NULL,
                        state            TEXT NOT NULL,
                        objective        TEXT,
                        provenance_hash  TEXT UNIQUE NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS objects (
                        id        TEXT PRIMARY KEY,
                        category  TEXT,
                        role      TEXT,
                        primitive TEXT,
                        data      TEXT
                    )
                """)
                conn.commit()
        except sqlite3.Error as e:
            print(f"Vault: schema init failed -- {e}")

    # -- In-memory registry ----------------------------------------------------

    def store(self, key, value):
        self._registry[key] = value

    def retrieve(self, key):
        return self._registry.get(key)

    # -- Relic persistence (existing) ------------------------------------------

    def persist(self, archetypal_name, vibe="", impact_rating=1):
        impact_rating = max(1, min(10, int(impact_rating)))
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "INSERT INTO archive (archetypal_name, vibe, impact_rating) "
                    "VALUES (?, ?, ?)",
                    (archetypal_name, vibe, impact_rating),
                )
                conn.commit()
                row_id = cursor.lastrowid
            self._registry[f"relic:{row_id}"] = {
                "archetypal_name": archetypal_name,
                "vibe":            vibe,
                "impact_rating":   impact_rating,
            }
            print(f"Vault: Inked -- {archetypal_name}")
            return row_id
        except sqlite3.Error as e:
            print(f"Vault: persist failed -- {e}")
            return None

    def load_all(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT id, archetypal_name, vibe, impact_rating FROM archive"
                ).fetchall()
            for row in rows:
                self._registry[f"relic:{row['id']}"] = {
                    "archetypal_name": row["archetypal_name"],
                    "vibe":            row["vibe"],
                    "impact_rating":   row["impact_rating"],
                }
            print(f"Vault: Loaded {len(rows)} relics from ledger.")
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            print(f"Vault: load_all failed -- {e}")
            return []

    def all_relics(self):
        return {k: v for k, v in self._registry.items() if k.startswith("relic:")}

    # -- Scenario ledger -------------------------------------------------------

    def write_scenario(self, scenario: dict) -> str:
        """
        Write a scenario to the ledger.
        provenance_hash must be unique -- the Yellow Sign is made once.
        Raises on duplicate hash.
        Returns scenario id.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO scenarios (id, type, state, objective, provenance_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    scenario["id"],
                    scenario["type"],
                    scenario["state"],
                    scenario.get("objective", ""),
                    scenario["provenance_hash"],
                ),
            )
            conn.commit()
        return scenario["id"]

    def scenario_by_id(self, scenario_id: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM scenarios WHERE id = ?", (scenario_id,)
            ).fetchone()
        return dict(row) if row else None

    def scenario_by_hash(self, provenance_hash: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM scenarios WHERE provenance_hash = ?",
                (provenance_hash,)
            ).fetchone()
        return dict(row) if row else None

    def scenarios_by_state(self, state: str) -> list:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM scenarios WHERE state = ?", (state,)
            ).fetchall()
        return [dict(r) for r in rows]

    def update_scenario_state(self, scenario_id: str, state: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE scenarios SET state = ? WHERE id = ?",
                (state, scenario_id)
            )
            conn.commit()

    def all_scenarios(self) -> list:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM scenarios").fetchall()
        return [dict(r) for r in rows]

    def scenario_counts_by_type(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT type, COUNT(*) as n FROM scenarios GROUP BY type"
            ).fetchall()
        return {row[0]: row[1] for row in rows}

    def completion_rate(self) -> float:
        """Fraction of scenarios in COMPLETE state. 0.0 if none exist."""
        with sqlite3.connect(self.db_path) as conn:
            total    = conn.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0]
            complete = conn.execute(
                "SELECT COUNT(*) FROM scenarios WHERE state = 'COMPLETE'"
            ).fetchone()[0]
        if total == 0:
            return 0.0
        return complete / total

    # -- Object catalog --------------------------------------------------------

    def seed_objects(self, objects_path: Path = None) -> None:
        """
        Ingest objects.json into the objects table.
        Idempotent -- skips existing ids.
        Category is the top-level key in objects.json.
        """
        path = objects_path or self.OBJECTS_JSON
        raw  = json.load(open(path))

        with sqlite3.connect(self.db_path) as conn:
            for category, items in raw.items():
                for obj_id, obj_data in items.items():
                    existing = conn.execute(
                        "SELECT id FROM objects WHERE id = ?", (obj_id,)
                    ).fetchone()
                    if existing:
                        continue
                    conn.execute(
                        "INSERT INTO objects (id, category, role, primitive, data) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            obj_id,
                            category,
                            obj_data.get("role", ""),
                            obj_data.get("primitive", ""),
                            json.dumps(obj_data),
                        ),
                    )
            conn.commit()

    def all_objects(self) -> list:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM objects").fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d.update(json.loads(d.pop("data")))
            d["id"] = row["id"]
            result.append(d)
        return result

    def object_by_id(self, obj_id: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM objects WHERE id = ?", (obj_id,)
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d.update(json.loads(d.pop("data")))
        d["id"] = obj_id
        return d

    def objects_by_role(self, role: str) -> list:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM objects WHERE role = ?", (role,)
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d.update(json.loads(d.pop("data")))
            d["id"] = row["id"]
            result.append(d)
        return result

    def objects_by_category(self, category: str) -> list:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM objects WHERE category = ?", (category,)
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d.update(json.loads(d.pop("data")))
            d["id"] = row["id"]
            result.append(d)
        return result
