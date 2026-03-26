import sqlite3
from pathlib import Path


class vault:
    """
    The central data repository for the Sanctum Terminal.
    Runtime registry (in-memory) backed by SQLite persistence.
    Syncs with vault.db on reads and writes.
    """

    DEFAULT_DB = Path(__file__).parent.parent / "data" / "vault.db"

    def __init__(self, db_path=None):
        self._registry = {}
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB
        self.initialized = True
        self._ensure_schema()
        print("Vault: Secured and Indexed.")

    # ── Schema ────────────────────────────────────────────────────────────────

    def _ensure_schema(self):
        """Creates archive table if it doesn't exist yet."""
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
                conn.commit()
        except sqlite3.Error as e:
            print(f"Vault: schema init failed — {e}")

    # ── In-memory registry ────────────────────────────────────────────────────

    def store(self, key, value):
        """Stores a value in the runtime registry."""
        self._registry[key] = value

    def retrieve(self, key):
        """Retrieves a value from the runtime registry."""
        return self._registry.get(key)

    # ── SQLite persistence ────────────────────────────────────────────────────

    def persist(self, archetypal_name, vibe="", impact_rating=1):
        """
        Writes a relic to vault.db and mirrors it in the runtime registry.
        """
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
                "vibe": vibe,
                "impact_rating": impact_rating,
            }
            print(f"Vault: Inked — {archetypal_name}")
            return row_id
        except sqlite3.Error as e:
            print(f"Vault: persist failed — {e}")
            return None

    def load_all(self):
        """
        Pulls all relics from vault.db into the runtime registry.
        Called on boot to restore session state.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT id, archetypal_name, vibe, impact_rating FROM archive"
                ).fetchall()
            for row in rows:
                self._registry[f"relic:{row['id']}"] = {
                    "archetypal_name": row["archetypal_name"],
                    "vibe": row["vibe"],
                    "impact_rating": row["impact_rating"],
                }
            print(f"Vault: Loaded {len(rows)} relics from ledger.")
            return [dict(r) for r in rows]
        except sqlite3.Error as e:
            print(f"Vault: load_all failed — {e}")
            return []

    def all_relics(self):
        """Returns all relic entries currently in the runtime registry."""
        return {k: v for k, v in self._registry.items() if k.startswith("relic:")}
