"""
core/vault.py

Vault -- unified read/write interface for world state.
One object. Ask it anything.

Tables:
    archive          -- relics (real-world events, impact-rated)
    scenarios        -- scenario ledger (provenance hash = primary key)
    objects          -- catalog cache (seeded from objects.json)
    entries          -- Permanent Objects journal-planner entries (her voice, canon)
    lexicon          -- derived personal lexicon, grows monotonically
    lexicon_contexts -- per-appearance snippets preserving exact phrasing
    lexicon_state    -- singleton row tracking triple-trigger cadence + parser_version
    user_seeds       -- per-user category overrides; populated by planner bootstrap UI.
                        Categories are whatever string the user types -- no enum, no
                        cultural defaults. The system learns her vocabulary, not ours.

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
                        provenance_hash  TEXT UNIQUE NOT NULL,
                        params           TEXT NOT NULL DEFAULT '{}'
                    )
                """)
                # Idempotent migration for vault.dbs created before the
                # params column existed. ALTER TABLE ADD COLUMN raises if
                # the column already exists, which is the intended
                # signal — catch and skip.
                try:
                    conn.execute(
                        "ALTER TABLE scenarios "
                        "ADD COLUMN params TEXT NOT NULL DEFAULT '{}'"
                    )
                except sqlite3.OperationalError:
                    pass
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS objects (
                        id        TEXT PRIMARY KEY,
                        category  TEXT,
                        role      TEXT,
                        primitive TEXT,
                        data      TEXT
                    )
                """)
                # -- Permanent Objects journal ---------------------------------
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS entries (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        when_ts     TEXT    NOT NULL,
                        severity    INTEGER NOT NULL DEFAULT 1,
                        frequency   TEXT    NOT NULL DEFAULT 'once',
                        raw_note    TEXT,
                        created_at  TEXT    NOT NULL,
                        updated_at  TEXT    NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS lexicon (
                        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                        term                TEXT    NOT NULL,
                        lemma               TEXT,
                        ngram_size          INTEGER NOT NULL,
                        category            TEXT,
                        first_seen_entry_id INTEGER REFERENCES entries(id),
                        first_seen_at       TEXT    NOT NULL,
                        last_seen_at        TEXT    NOT NULL,
                        occurrences         INTEGER NOT NULL DEFAULT 1,
                        embedding           BLOB,
                        UNIQUE(term, ngram_size)
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS lexicon_contexts (
                        id           INTEGER PRIMARY KEY AUTOINCREMENT,
                        lexicon_id   INTEGER NOT NULL REFERENCES lexicon(id),
                        entry_id     INTEGER NOT NULL REFERENCES entries(id),
                        snippet      TEXT    NOT NULL,
                        slot         TEXT,
                        register     TEXT,
                        co_occurring TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS lexicon_state (
                        id                 INTEGER PRIMARY KEY CHECK (id = 1),
                        last_entry_at      TEXT,
                        last_inline_update TEXT,
                        last_full_retrain  TEXT,
                        last_planner_open  TEXT,
                        parser_version     INTEGER NOT NULL DEFAULT 1,
                        w2v_version        INTEGER NOT NULL DEFAULT 0
                    )
                """)
                # User-defined category overrides. Populated by the planner UI's
                # first-appearance bootstrap; the system never invents a category
                # without the user's input. Category is a free-form string.
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_seeds (
                        term      TEXT PRIMARY KEY,
                        category  TEXT NOT NULL,
                        source    TEXT NOT NULL DEFAULT 'bootstrap',
                        added_at  TEXT NOT NULL
                    )
                """)
                # Seed singleton row -- parser_version is the regen anchor
                conn.execute("""
                    INSERT OR IGNORE INTO lexicon_state (id, parser_version, w2v_version)
                    VALUES (1, 1, 0)
                """)
                # -- Workroom seeds (vector-workroom feature) --------------------
                # User-placed primitive instances with optional mesh-edit log.
                # Distinct from `user_seeds` above (which is lexicon category
                # overrides) — name disambiguates intent. See
                # .claude/feature/feat_vector-workroom.md for the full schema
                # contract and acceptance criteria.
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS world_seeds (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        biome       TEXT    NOT NULL,
                        kind        TEXT    NOT NULL,
                        base_mesh   TEXT    NOT NULL,
                        pos_x       REAL    NOT NULL,
                        pos_y       REAL    NOT NULL,
                        pos_z       REAL    NOT NULL,
                        yaw_deg     REAL    NOT NULL DEFAULT 0,
                        scale       REAL    NOT NULL DEFAULT 1.0,
                        color_r     REAL    NOT NULL DEFAULT 0.7,
                        color_g     REAL    NOT NULL DEFAULT 0.7,
                        color_b     REAL    NOT NULL DEFAULT 0.7,
                        mesh_edits  TEXT    NOT NULL DEFAULT '[]',
                        created_at  TEXT    NOT NULL,
                        updated_at  TEXT    NOT NULL
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_world_seeds_biome "
                    "ON world_seeds(biome)"
                )
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
        params_blob = json.dumps(scenario.get("params", {}) or {})
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO scenarios "
                "(id, type, state, objective, provenance_hash, params) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    scenario["id"],
                    scenario["type"],
                    scenario["state"],
                    scenario.get("objective", ""),
                    scenario["provenance_hash"],
                    params_blob,
                ),
            )
            conn.commit()
        return scenario["id"]

    def write_scenario_if_absent(self, scenario: dict) -> bool:
        """
        Idempotent variant of write_scenario for replay-safe paths.
        Uses INSERT OR IGNORE keyed on the UNIQUE provenance_hash, so
        the same deterministic hash silently no-ops on repeat. Returns
        True if a new row was inserted, False if a row with this hash
        already existed.

        Used by core/systems/scenario_ledger.create_pending: brain boot
        re-derives the same provenance_hash from each vault.entries row,
        and the journal-derived scenario quietly survives across restart
        without raising on the duplicate.
        """
        params_blob = json.dumps(scenario.get("params", {}) or {})
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO scenarios "
                "(id, type, state, objective, provenance_hash, params) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    scenario["id"],
                    scenario["type"],
                    scenario["state"],
                    scenario.get("objective", ""),
                    scenario["provenance_hash"],
                    params_blob,
                ),
            )
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _deserialize_scenario(row) -> dict:
        """SQLite Row → dict with params JSON deserialized. Defensive
        on missing/legacy params column (defaults to {})."""
        d = dict(row)
        raw = d.get("params") or "{}"
        try:
            d["params"] = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (TypeError, ValueError):
            d["params"] = {}
        return d

    def scenario_by_id(self, scenario_id: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM scenarios WHERE id = ?", (scenario_id,)
            ).fetchone()
        return self._deserialize_scenario(row) if row else None

    def scenario_by_hash(self, provenance_hash: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM scenarios WHERE provenance_hash = ?",
                (provenance_hash,)
            ).fetchone()
        return self._deserialize_scenario(row) if row else None

    def scenarios_by_state(self, state: str) -> list:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM scenarios WHERE state = ?", (state,)
            ).fetchall()
        return [self._deserialize_scenario(r) for r in rows]

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
        return [self._deserialize_scenario(r) for r in rows]

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

    # -- Permanent Objects journal: state singleton ---------------------------

    def lexicon_state(self) -> dict:
        """
        Return the lexicon_state singleton row.
        Always exists -- seeded on schema init with parser_version=1.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM lexicon_state WHERE id = 1"
            ).fetchone()
        return dict(row) if row else None

    # -- Permanent Objects journal: user-defined seed categories --------------

    def user_seed_category(self, term: str) -> str | None:
        """
        Return the user-defined category for `term`, or None.
        First lookup in the categorization pipeline -- user-defined seeds
        always win over system defaults.
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT category FROM user_seeds WHERE term = ?", (term,)
            ).fetchone()
        return row[0] if row else None

    def add_user_seed(self, term: str, category: str,
                      source: str = "bootstrap") -> None:
        """
        Record a user-defined category for `term`. Called by the planner
        UI's first-appearance bootstrap. `category` is whatever string
        the user typed -- no enum, no controlled vocabulary.
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO user_seeds (term, category, source, added_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(term) DO UPDATE SET
                  category = excluded.category,
                  source   = excluded.source,
                  added_at = excluded.added_at
            """, (term, category, source, now))
            conn.commit()

    # -- Object catalog (continued) -------------------------------------------

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

    # -- Workroom seeds: CRUD --------------------------------------------------
    #
    # Per `.claude/feature/feat_vector-workroom.md`. User-placed primitive
    # instances with an append-only mesh-edit log. CRUD is exposed as four
    # helpers; brain command handlers wrap them. mesh_edits is stored as a
    # JSON list and deserialized on read for caller convenience.

    _WORLD_SEED_FIELDS = (
        "biome", "kind", "base_mesh",
        "pos_x", "pos_y", "pos_z",
        "yaw_deg", "scale",
        "color_r", "color_g", "color_b",
        "mesh_edits",
    )
    # Subset that callers may patch via world_seed_update.
    _WORLD_SEED_UPDATABLE = (
        "biome", "kind", "base_mesh",
        "pos_x", "pos_y", "pos_z",
        "yaw_deg", "scale",
        "color_r", "color_g", "color_b",
        "mesh_edits",
    )

    @staticmethod
    def _deserialize_world_seed(row) -> dict:
        d = dict(row)
        raw = d.get("mesh_edits") or "[]"
        try:
            d["mesh_edits"] = (
                json.loads(raw) if isinstance(raw, str) else (raw or [])
            )
        except (TypeError, ValueError):
            d["mesh_edits"] = []
        return d

    def world_seed_create(self, seed: dict) -> int:
        """Insert a world_seed row. Returns the new row id.

        Required fields: biome, kind, base_mesh, pos_x, pos_y, pos_z.
        Defaults applied: yaw_deg=0, scale=1.0, color_r/g/b=0.7,
        mesh_edits=[]. Raises KeyError on missing required field.
        """
        from datetime import datetime, timezone
        for k in ("biome", "kind", "base_mesh", "pos_x", "pos_y", "pos_z"):
            if k not in seed:
                raise KeyError(f"world_seed_create: missing required field {k!r}")
        edits = seed.get("mesh_edits", [])
        if not isinstance(edits, (list, tuple)):
            raise ValueError("mesh_edits must be a list of edit ops")
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO world_seeds "
                "(biome, kind, base_mesh, pos_x, pos_y, pos_z, "
                "yaw_deg, scale, color_r, color_g, color_b, "
                "mesh_edits, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(seed["biome"]),
                    str(seed["kind"]),
                    str(seed["base_mesh"]),
                    float(seed["pos_x"]),
                    float(seed["pos_y"]),
                    float(seed["pos_z"]),
                    float(seed.get("yaw_deg", 0.0)),
                    float(seed.get("scale", 1.0)),
                    float(seed.get("color_r", 0.7)),
                    float(seed.get("color_g", 0.7)),
                    float(seed.get("color_b", 0.7)),
                    json.dumps(list(edits)),
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def world_seed_update(self, seed_id: int, fields: dict) -> bool:
        """Patch a subset of fields on an existing seed. Returns True if
        a row was updated, False if no seed with that id exists.

        Only fields in `_WORLD_SEED_UPDATABLE` are honored; unknown keys
        in the input are silently ignored. mesh_edits is JSON-encoded.
        """
        from datetime import datetime, timezone
        if not fields:
            return self._world_seed_exists(seed_id)
        sets: list[str] = []
        vals: list = []
        for k, v in fields.items():
            if k not in self._WORLD_SEED_UPDATABLE:
                continue
            if k == "mesh_edits":
                if not isinstance(v, (list, tuple)):
                    raise ValueError("mesh_edits must be a list of edit ops")
                vals.append(json.dumps(list(v)))
            elif k in ("biome", "kind", "base_mesh"):
                vals.append(str(v))
            else:
                vals.append(float(v))
            sets.append(f"{k} = ?")
        if not sets:
            return self._world_seed_exists(seed_id)
        sets.append("updated_at = ?")
        vals.append(datetime.now(timezone.utc).isoformat())
        vals.append(int(seed_id))
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                f"UPDATE world_seeds SET {', '.join(sets)} WHERE id = ?",
                tuple(vals),
            )
            conn.commit()
            return cur.rowcount > 0

    def world_seed_delete(self, seed_id: int) -> bool:
        """Remove a seed by id. Returns True if a row was deleted."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM world_seeds WHERE id = ?", (int(seed_id),)
            )
            conn.commit()
            return cur.rowcount > 0

    def world_seeds_by_biome(self, biome: str) -> list:
        """Return all seeds in a biome, ordered by id (placement order).
        mesh_edits is deserialized to a list per row."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM world_seeds WHERE biome = ? ORDER BY id ASC",
                (str(biome),),
            ).fetchall()
        return [self._deserialize_world_seed(r) for r in rows]

    def _world_seed_exists(self, seed_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM world_seeds WHERE id = ?", (int(seed_id),)
            ).fetchone()
        return row is not None
