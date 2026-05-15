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
                # Make-brain substrate -- universal config + run tables
                # shared by every make-brain instance (ping-pong, future
                # archery, future puzzle modules). See
                # .claude/feature/feat_make-brain-ping-pong.md PR 1.
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS profiles (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        instance_id     TEXT    NOT NULL,
                        profile_name    TEXT    NOT NULL,
                        parent_profile  TEXT,
                        params_json     TEXT    NOT NULL,
                        notes           TEXT    NOT NULL DEFAULT '',
                        created_at      TEXT    NOT NULL,
                        updated_at      TEXT    NOT NULL,
                        UNIQUE(instance_id, profile_name)
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_profiles_instance "
                    "ON profiles(instance_id)"
                )
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS runs (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        instance_id     TEXT    NOT NULL,
                        run_id          TEXT    NOT NULL,
                        profile_name    TEXT    NOT NULL,
                        started_at      TEXT    NOT NULL,
                        ended_at        TEXT,
                        metrics_json    TEXT    NOT NULL DEFAULT '{}',
                        terminal_state  TEXT,
                        UNIQUE(instance_id, run_id)
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_runs_instance "
                    "ON runs(instance_id)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_runs_profile "
                    "ON runs(instance_id, profile_name)"
                )
                # activity_log — telemetry-only stream of every ActivityClass
                # emit. NEVER read for gameplay; counters in
                # core/systems/activity_loop.py are the runtime currency.
                # See `.claude/audit_2026-05-06.md` A6.
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS activity_log (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp       REAL    NOT NULL,
                        class_index     INTEGER NOT NULL,
                        primitive       TEXT    NOT NULL,
                        intensity       INTEGER NOT NULL,
                        source_brain    TEXT    NOT NULL,
                        payload_json    TEXT    NOT NULL DEFAULT '{}'
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_activity_log_ts "
                    "ON activity_log(timestamp DESC)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_activity_log_class "
                    "ON activity_log(class_index, timestamp DESC)"
                )
                # combat_sessions — per-Strike telemetry record
                # (feat/arpg-combat PR 7). One row per spawned Strike;
                # opened on weapon_use cmd, closed on strike resolution.
                # Mirrors vault.runs but per-swing grain instead of
                # per-session.
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS combat_sessions (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_actor    TEXT    NOT NULL,
                        weapon_kind     TEXT    NOT NULL,
                        weapon_class    TEXT,
                        mode            TEXT    NOT NULL,
                        target_kind     TEXT,
                        target_id       INTEGER,
                        outcome         TEXT,
                        kinetic_energy  REAL,
                        started_at      REAL    NOT NULL,
                        resolved_at     REAL,
                        metrics_json    TEXT    NOT NULL DEFAULT '{}'
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_combat_sessions_weapon "
                    "ON combat_sessions(weapon_kind, started_at DESC)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_combat_sessions_mode "
                    "ON combat_sessions(mode, started_at DESC)"
                )

                # Creature engagement substrate per
                # `.claude/feature/feat_creature-engagement.md` PR 3.
                # One row per engagement *instance* (per agent contact).
                # Mirrors vault.runs but at instance grain — `runs` is
                # the make-brain *session*, `engagements` is the
                # per-agent run inside that session.
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS engagements (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        instance_id     TEXT    NOT NULL,
                        agent_id        TEXT    NOT NULL,
                        kind            TEXT    NOT NULL,
                        started_at      REAL    NOT NULL,
                        ended_at        REAL,
                        terminal_state  TEXT,
                        metrics_json    TEXT    NOT NULL DEFAULT '{}'
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_engagements_instance "
                    "ON engagements(instance_id, started_at DESC)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_engagements_kind "
                    "ON engagements(kind, started_at DESC)"
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

    def lexicon_terms(
        self,
        category: str | None = None,
        min_occurrences: int = 2,
        limit: int = 50,
        *,
        require_category: bool = True,
    ) -> list[dict]:
        """Read lexicon terms for synthesis-time substitution.

        Per `design_lexicon_architecture`: returns verbatim term + its
        category + occurrence count. Caller picks one to weave into
        a response.

        category=None returns all categorized terms.
        require_category=True (default) skips rows with NULL category
        — those are sub-token fragments that read as nonsense in
        substitution. Pass False to include them.
        """
        clauses = ["occurrences >= ?"]
        args: list = [int(min_occurrences)]
        if category is not None:
            clauses.append("category = ?")
            args.append(str(category))
        elif require_category:
            clauses.append("category IS NOT NULL")
        sql = (
            "SELECT term, category, occurrences FROM lexicon "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY occurrences DESC LIMIT ?"
        )
        args.append(int(limit))
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, args).fetchall()
        return [
            {
                "term":        r["term"],
                "category":    r["category"],
                "occurrences": r["occurrences"],
            }
            for r in rows
        ]

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

    # -- Make-brain substrate: profiles ----------------------------------------
    # Universal config snapshot table. Every make-brain instance
    # (ping_pong, future archery, future puzzle modules) shares this
    # table keyed by instance_id. params_json is per-instance free-form.
    # Profile inheritance is supported via parent_profile + profile_resolve().

    @staticmethod
    def _deserialize_profile(row) -> dict:
        d = dict(row)
        raw = d.get("params_json") or "{}"
        try:
            d["params"] = (
                json.loads(raw) if isinstance(raw, str) else (raw or {})
            )
        except (TypeError, ValueError):
            d["params"] = {}
        return d

    def profile_save(
        self,
        instance_id: str,
        profile_name: str,
        params: dict,
        parent_profile: str | None = None,
        notes: str = "",
    ) -> int:
        """Insert or update a make-brain profile. Returns row id.

        UNIQUE(instance_id, profile_name) — repeated saves overwrite.
        params is JSON-serialized.
        """
        from datetime import datetime, timezone
        if not isinstance(params, dict):
            raise ValueError("profile_save: params must be a dict")
        now = datetime.now(timezone.utc).isoformat()
        params_json = json.dumps(params)
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO profiles "
                "(instance_id, profile_name, parent_profile, params_json, "
                " notes, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(instance_id, profile_name) DO UPDATE SET "
                "  parent_profile = excluded.parent_profile, "
                "  params_json    = excluded.params_json, "
                "  notes          = excluded.notes, "
                "  updated_at     = excluded.updated_at",
                (
                    str(instance_id),
                    str(profile_name),
                    str(parent_profile) if parent_profile else None,
                    params_json,
                    str(notes or ""),
                    now,
                    now,
                ),
            )
            conn.commit()
            row_id = cur.lastrowid
            if row_id == 0:
                # ON CONFLICT path -- look up the existing row id
                row = conn.execute(
                    "SELECT id FROM profiles "
                    "WHERE instance_id = ? AND profile_name = ?",
                    (str(instance_id), str(profile_name)),
                ).fetchone()
                row_id = int(row[0]) if row else 0
            return int(row_id)

    def profile_load(self, instance_id: str, profile_name: str) -> dict | None:
        """Return raw profile row (no parent resolution) or None.

        For inheritance-resolved params, use profile_resolve().
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM profiles "
                "WHERE instance_id = ? AND profile_name = ?",
                (str(instance_id), str(profile_name)),
            ).fetchone()
        if row is None:
            return None
        return self._deserialize_profile(row)

    def profile_list(self, instance_id: str) -> list[dict]:
        """All profiles for an instance, ordered by name."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM profiles WHERE instance_id = ? "
                "ORDER BY profile_name ASC",
                (str(instance_id),),
            ).fetchall()
        return [self._deserialize_profile(r) for r in rows]

    def profile_resolve(self, instance_id: str, profile_name: str) -> dict:
        """Walk parent_profile chain and return merged params (child overrides
        parent). Raises:
          - LookupError if profile_name not found.
          - LookupError if a parent in the chain is missing.
          - ValueError if a cycle is detected.
        """
        seen: set[str] = set()
        chain: list[dict] = []
        current = profile_name
        while current is not None:
            if current in seen:
                raise ValueError(
                    f"profile_resolve: cycle detected at "
                    f"{instance_id}:{current}"
                )
            seen.add(current)
            row = self.profile_load(instance_id, current)
            if row is None:
                missing_kind = "profile" if not chain else "parent profile"
                raise LookupError(
                    f"profile_resolve: {missing_kind} not found: "
                    f"{instance_id}:{current}"
                )
            chain.append(row)
            current = row.get("parent_profile")
        # Merge from oldest ancestor down to the requested child so
        # child keys win.
        merged: dict = {}
        for row in reversed(chain):
            merged.update(row.get("params") or {})
        return merged

    # -- Make-brain substrate: runs --------------------------------------------
    # Per-engagement (session-grain) record. One row per make-brain
    # process lifetime; per-rally / per-event detail lives in
    # metrics_json.

    @staticmethod
    def _gen_run_id() -> str:
        """Timestamp-prefixed random id (ULID-style — sortable by start time)."""
        import secrets, time
        ts_ms = int(time.time() * 1000)
        return f"{ts_ms:013x}_{secrets.token_hex(4)}"

    @staticmethod
    def _deserialize_run(row) -> dict:
        d = dict(row)
        raw = d.get("metrics_json") or "{}"
        try:
            d["metrics"] = (
                json.loads(raw) if isinstance(raw, str) else (raw or {})
            )
        except (TypeError, ValueError):
            d["metrics"] = {}
        return d

    def run_start(self, instance_id: str, profile_name: str) -> str:
        """Open a new run row. Returns the generated run_id."""
        from datetime import datetime, timezone
        run_id = self._gen_run_id()
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO runs "
                "(instance_id, run_id, profile_name, started_at, "
                " ended_at, metrics_json, terminal_state) "
                "VALUES (?, ?, ?, ?, NULL, '{}', NULL)",
                (
                    str(instance_id),
                    run_id,
                    str(profile_name),
                    now,
                ),
            )
            conn.commit()
        return run_id

    def run_end(
        self,
        instance_id: str,
        run_id: str,
        terminal_state: str | None = None,
        metrics: dict | None = None,
    ) -> bool:
        """Close out a run. Returns True if a row was updated."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        metrics_json = json.dumps(metrics or {})
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE runs SET "
                "  ended_at       = ?, "
                "  terminal_state = ?, "
                "  metrics_json   = ? "
                "WHERE instance_id = ? AND run_id = ?",
                (
                    now,
                    str(terminal_state) if terminal_state else None,
                    metrics_json,
                    str(instance_id),
                    str(run_id),
                ),
            )
            conn.commit()
            return cur.rowcount > 0

    def run_get(self, instance_id: str, run_id: str) -> dict | None:
        """Return a single run row (or None)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM runs "
                "WHERE instance_id = ? AND run_id = ?",
                (str(instance_id), str(run_id)),
            ).fetchone()
        if row is None:
            return None
        return self._deserialize_run(row)

    def runs_by_instance(self, instance_id: str) -> list[dict]:
        """All runs for an instance, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM runs WHERE instance_id = ? "
                "ORDER BY started_at DESC",
                (str(instance_id),),
            ).fetchall()
        return [self._deserialize_run(r) for r in rows]

    def runs_peak_metric(
        self,
        instance_id: str,
        metric: str,
        profile_name: str | None = None,
    ) -> tuple[float, str | None]:
        """Aggregate query — return (peak_value, run_id) for a numeric
        metric across runs. profile_name optionally filters.

        Walks runs in Python rather than relying on SQLite JSON1
        (some Python builds ship without the json1 extension). This is
        fine at V1 scale; if vault.runs grows large, swap to a
        json_extract query.
        """
        rows = self.runs_by_instance(instance_id)
        peak = float("-inf")
        peak_run: str | None = None
        for r in rows:
            if profile_name is not None and r.get("profile_name") != profile_name:
                continue
            metrics = r.get("metrics") or {}
            v = metrics.get(metric)
            if v is None:
                continue
            try:
                vf = float(v)
            except (TypeError, ValueError):
                continue
            if vf > peak:
                peak = vf
                peak_run = r.get("run_id")
        if peak == float("-inf"):
            return 0.0, None
        return peak, peak_run

    # -- activity_log -----------------------------------------------------
    # Telemetry-only log of every ActivityClass emit. Per
    # `.claude/audit_2026-05-06.md` A6 — counters in
    # core/systems/activity_loop.py are the runtime currency; this log
    # is for UAT readout + post-hoc analysis. NEVER read for gameplay.

    def activity_log_append(
        self,
        class_index: int,
        primitive: str,
        intensity: int,
        source_brain: str,
        payload: dict | None = None,
    ) -> int:
        """Append a single activity event. Returns the row id."""
        import time as _time
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO activity_log "
                "(timestamp, class_index, primitive, intensity, source_brain, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _time.time(),
                    int(class_index),
                    str(primitive),
                    int(intensity),
                    str(source_brain),
                    json.dumps(payload or {}),
                ),
            )
            conn.commit()
            return cur.lastrowid

    def activity_log_recent(
        self,
        limit: int = 100,
        class_index: int | None = None,
    ) -> list[dict]:
        """Most-recent N events, optionally filtered by class. Newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if class_index is None:
                rows = conn.execute(
                    "SELECT * FROM activity_log "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM activity_log "
                    "WHERE class_index = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (int(class_index), int(limit)),
                ).fetchall()
            return [
                {
                    "id":           r["id"],
                    "timestamp":    r["timestamp"],
                    "class_index":  r["class_index"],
                    "primitive":    r["primitive"],
                    "intensity":    r["intensity"],
                    "source_brain": r["source_brain"],
                    "payload":      json.loads(r["payload_json"] or "{}"),
                }
                for r in rows
            ]

    # -- combat_sessions --------------------------------------------------
    # Per-Strike telemetry. Per `.claude/feature/feat_arpg-combat.md`
    # PR 7. Mirrors runs but per-swing grain.

    def combat_session_open(
        self,
        source_actor: str,
        weapon_kind:  str,
        weapon_class: str | None,
        mode:         str,
    ) -> int:
        """Open a new combat session row. Returns the row id."""
        import time as _time
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO combat_sessions "
                "(source_actor, weapon_kind, weapon_class, mode, started_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(source_actor),
                    str(weapon_kind),
                    str(weapon_class) if weapon_class else None,
                    str(mode),
                    _time.time(),
                ),
            )
            conn.commit()
            return cur.lastrowid

    def combat_session_close(
        self,
        session_id:    int,
        outcome:       str,
        target_kind:   str | None = None,
        target_id:     int | None = None,
        kinetic_energy: float | None = None,
        metrics:       dict | None = None,
    ) -> bool:
        """Close a combat session by id. Returns True if a row was
        updated."""
        import time as _time
        metrics_json = json.dumps(metrics or {})
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE combat_sessions SET "
                "  resolved_at    = ?, "
                "  outcome        = ?, "
                "  target_kind    = ?, "
                "  target_id      = ?, "
                "  kinetic_energy = ?, "
                "  metrics_json   = ? "
                "WHERE id = ?",
                (
                    _time.time(),
                    str(outcome),
                    str(target_kind) if target_kind else None,
                    int(target_id) if target_id is not None else None,
                    float(kinetic_energy) if kinetic_energy is not None else None,
                    metrics_json,
                    int(session_id),
                ),
            )
            conn.commit()
            return cur.rowcount > 0

    def combat_sessions_by_weapon(self, weapon_kind: str) -> list[dict]:
        """List all combat sessions for a weapon, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM combat_sessions "
                "WHERE weapon_kind = ? "
                "ORDER BY started_at DESC",
                (str(weapon_kind),),
            ).fetchall()
            return [
                {
                    "id":             r["id"],
                    "source_actor":   r["source_actor"],
                    "weapon_kind":    r["weapon_kind"],
                    "weapon_class":   r["weapon_class"],
                    "mode":           r["mode"],
                    "target_kind":    r["target_kind"],
                    "target_id":      r["target_id"],
                    "outcome":        r["outcome"],
                    "kinetic_energy": r["kinetic_energy"],
                    "started_at":     r["started_at"],
                    "resolved_at":    r["resolved_at"],
                    "metrics":        json.loads(r["metrics_json"] or "{}"),
                }
                for r in rows
            ]

    # -- Creature engagements (PR 3) --------------------------------------

    def engagement_open(
        self,
        instance_id: str,
        agent_id:    str,
        kind:        str,
    ) -> int:
        """Open a new engagement row. Returns the row id.

        One row per engagement instance — opened on contact, closed on
        resolution (win/lost/aborted/fled). `metrics_json` accumulates
        attempt counts, time-to-resolution, and engagement-type-specific
        signals on close.
        """
        import time as _time
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO engagements "
                "(instance_id, agent_id, kind, started_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    str(instance_id),
                    str(agent_id),
                    str(kind),
                    _time.time(),
                ),
            )
            conn.commit()
            return cur.lastrowid

    def engagement_close(
        self,
        engagement_id:  int,
        terminal_state: str,
        metrics:        dict | None = None,
    ) -> bool:
        """Close an engagement by id. Returns True if a row was updated.

        terminal_state ∈ {"won", "lost", "aborted", "fled"} per the
        StateEvent contract in design_creature_engagement_v1.
        """
        import time as _time
        metrics_json = json.dumps(metrics or {})
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "UPDATE engagements SET "
                "  ended_at       = ?, "
                "  terminal_state = ?, "
                "  metrics_json   = ? "
                "WHERE id = ?",
                (
                    _time.time(),
                    str(terminal_state),
                    metrics_json,
                    int(engagement_id),
                ),
            )
            conn.commit()
            return cur.rowcount > 0

    def engagements_by_kind(self, kind: str) -> list[dict]:
        """List all engagements for a creature kind, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM engagements "
                "WHERE kind = ? "
                "ORDER BY started_at DESC",
                (str(kind),),
            ).fetchall()
            return [
                {
                    "id":             r["id"],
                    "instance_id":    r["instance_id"],
                    "agent_id":       r["agent_id"],
                    "kind":           r["kind"],
                    "started_at":     r["started_at"],
                    "ended_at":       r["ended_at"],
                    "terminal_state": r["terminal_state"],
                    "metrics":        json.loads(r["metrics_json"] or "{}"),
                }
                for r in rows
            ]

    def activity_log_count_by_class(
        self,
        since_ts: float | None = None,
    ) -> dict[int, int]:
        """Sum of `intensity` per class_index, optionally since a timestamp.
        Returns {class_index: total_intensity}. Zero classes are omitted."""
        with sqlite3.connect(self.db_path) as conn:
            if since_ts is None:
                rows = conn.execute(
                    "SELECT class_index, SUM(intensity) "
                    "FROM activity_log GROUP BY class_index"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT class_index, SUM(intensity) "
                    "FROM activity_log WHERE timestamp >= ? "
                    "GROUP BY class_index",
                    (float(since_ts),),
                ).fetchall()
            return {int(r[0]): int(r[1] or 0) for r in rows}
