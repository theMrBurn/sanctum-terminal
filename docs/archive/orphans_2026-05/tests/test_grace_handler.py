import pytest
import json
import sqlite3
from pathlib import Path


@pytest.fixture
def tmp_db(tmp_path):
    db = tmp_path / "vault.db"
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE archive (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            archetypal_name TEXT NOT NULL,
            vibe            TEXT,
            impact_rating   INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE seeds (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            label           TEXT,
            seed_hash       TEXT UNIQUE NOT NULL,
            status          TEXT DEFAULT 'exploring',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            snapshot        TEXT,
            consent_version TEXT DEFAULT '1.0'
        )
    """)
    conn.execute("""
        CREATE TABLE grace_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            payload    TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def handler(tmp_db, tmp_path):
    from core.systems.grace_handler import GraceHandler
    checkpoint = tmp_path / "checkpoint.json"
    return GraceHandler(db_path=tmp_db, checkpoint_path=checkpoint)


# ── Init ──────────────────────────────────────────────────────────────────────

class TestGraceHandlerInit:

    def test_boots_without_error(self, handler):
        assert handler is not None

    def test_db_path_missing_raises(self, tmp_path):
        from core.systems.grace_handler import GraceHandler
        with pytest.raises(FileNotFoundError):
            GraceHandler(db_path="/nonexistent/vault.db",
                        checkpoint_path=tmp_path / "checkpoint.json")

    def test_checkpoint_path_stored(self, handler, tmp_path):
        assert handler.checkpoint_path == tmp_path / "checkpoint.json"

    def test_event_log_starts_empty(self, handler):
        assert handler.event_log == []


# ── Fire event ────────────────────────────────────────────────────────────────

class TestFireEvent:

    def test_fire_returns_event_dict(self, handler):
        event = handler.fire("biome_transition", {"from": "VOID", "to": "VERDANT"})
        assert isinstance(event, dict)

    def test_fire_has_required_keys(self, handler):
        event = handler.fire("biome_transition", {"from": "VOID", "to": "VERDANT"})
        for key in ["event_type", "payload", "timestamp"]:
            assert key in event

    def test_fire_appends_to_log(self, handler):
        handler.fire("biome_transition", {"from": "VOID", "to": "VERDANT"})
        assert len(handler.event_log) == 1

    def test_fire_persists_to_db(self, handler, tmp_db):
        handler.fire("biome_transition", {"from": "VOID", "to": "VERDANT"})
        conn = sqlite3.connect(tmp_db)
        rows = conn.execute("SELECT * FROM grace_log").fetchall()
        conn.close()
        assert len(rows) == 1

    def test_fire_stores_correct_event_type(self, handler, tmp_db):
        handler.fire("seed_planted", {"seed_hash": "abc123"})
        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT event_type FROM grace_log").fetchone()
        conn.close()
        assert row[0] == "seed_planted"

    def test_fire_multiple_events(self, handler):
        handler.fire("biome_transition", {})
        handler.fire("seed_planted", {})
        handler.fire("relic_registered", {})
        assert len(handler.event_log) == 3


# ── Checkpoint ────────────────────────────────────────────────────────────────

class TestCheckpoint:

    def test_checkpoint_writes_file(self, handler, tmp_path):
        handler.fire("biome_transition", {"from": "VOID", "to": "CAVERNOUS"})
        handler.checkpoint({"biome_key": "CAVERNOUS", "karma": 0.3})
        assert (tmp_path / "checkpoint.json").exists()

    def test_checkpoint_is_valid_json(self, handler, tmp_path):
        handler.checkpoint({"biome_key": "CAVERNOUS", "karma": 0.3})
        data = json.load(open(tmp_path / "checkpoint.json"))
        assert isinstance(data, dict)

    def test_checkpoint_has_state(self, handler, tmp_path):
        handler.checkpoint({"biome_key": "CAVERNOUS", "karma": 0.3})
        data = json.load(open(tmp_path / "checkpoint.json"))
        assert data["state"]["biome_key"] == "CAVERNOUS"

    def test_checkpoint_has_timestamp(self, handler, tmp_path):
        handler.checkpoint({"biome_key": "CAVERNOUS", "karma": 0.3})
        data = json.load(open(tmp_path / "checkpoint.json"))
        assert "written_at" in data

    def test_checkpoint_has_last_event(self, handler, tmp_path):
        handler.fire("biome_transition", {"from": "VOID", "to": "CAVERNOUS"})
        handler.checkpoint({"biome_key": "CAVERNOUS", "karma": 0.3})
        data = json.load(open(tmp_path / "checkpoint.json"))
        assert data["last_event"]["event_type"] == "biome_transition"


# ── Recovery ──────────────────────────────────────────────────────────────────

class TestRecover:

    def test_recover_returns_none_if_no_checkpoint(self, handler):
        result = handler.recover()
        assert result is None

    def test_recover_returns_state_after_checkpoint(self, handler, tmp_path):
        handler.checkpoint({"biome_key": "CAVERNOUS", "karma": 0.3})
        result = handler.recover()
        assert result is not None
        assert result["biome_key"] == "CAVERNOUS"

    def test_recover_karma_value(self, handler):
        handler.checkpoint({"biome_key": "VERDANT", "karma": 0.6})
        result = handler.recover()
        assert result["karma"] == 0.6


# ── Grace events ──────────────────────────────────────────────────────────────

class TestGraceEvents:

    def test_known_event_types(self, handler):
        known = [
            "biome_transition", "seed_planted", "seed_archived",
            "relic_registered", "karma_threshold", "interview_complete",
            "system_panic"
        ]
        for event_type in known:
            event = handler.fire(event_type, {})
            assert event["event_type"] == event_type

    def test_system_panic_always_checkpoints(self, handler, tmp_path):
        handler.fire("system_panic", {"reason": "test"})
        assert (tmp_path / "checkpoint.json").exists()
