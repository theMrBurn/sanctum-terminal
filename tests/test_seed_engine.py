import json
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """Clean vault.db with both archive and seeds tables."""
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
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            label       TEXT,
            seed_hash   TEXT UNIQUE NOT NULL,
            status      TEXT DEFAULT 'exploring',
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            snapshot    TEXT,
            consent_version TEXT DEFAULT '1.0'
        )
    """)
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def engine(tmp_db):
    from core.systems.seed_engine import SeedEngine

    return SeedEngine(db_path=tmp_db)


# ── Instantiation ─────────────────────────────────────────────────────────────


class TestSeedEngineInit:

    def test_boots_without_error(self, engine):
        assert engine is not None

    def test_db_path_missing_raises(self):
        from core.systems.seed_engine import SeedEngine

        with pytest.raises(FileNotFoundError):
            SeedEngine(db_path="/nonexistent/vault.db")

    def test_pocket_starts_empty(self, engine):
        assert engine.pocket == []

    def test_planted_starts_none(self, engine):
        assert engine.planted is None


# ── Seed Generation ───────────────────────────────────────────────────────────


class TestGenerateSeed:

    def test_generate_returns_seed_dict(self, engine):
        seed = engine.generate(label="Test World")
        assert isinstance(seed, dict)

    def test_generate_has_required_keys(self, engine):
        seed = engine.generate(label="Test World")
        for key in ["id", "label", "seed_hash", "status", "snapshot"]:
            assert key in seed

    def test_generate_status_is_exploring(self, engine):
        seed = engine.generate(label="Test World")
        assert seed["status"] == "exploring"

    def test_generate_seed_hash_is_unique(self, engine):
        s1 = engine.generate(label="World One")
        s2 = engine.generate(label="World Two")
        assert s1["seed_hash"] != s2["seed_hash"]

    def test_generate_persists_to_db(self, engine, tmp_db):
        engine.generate(label="Test World")
        conn = sqlite3.connect(tmp_db)
        rows = conn.execute("SELECT * FROM seeds").fetchall()
        conn.close()
        assert len(rows) == 1

    def test_generate_adds_to_pocket(self, engine):
        engine.generate(label="Test World")
        assert len(engine.pocket) == 1

    def test_pocket_max_three(self, engine):
        for i in range(3):
            engine.generate(label=f"World {i}")
        assert len(engine.pocket) == 3

    def test_generate_fourth_raises_when_pocket_full(self, engine):
        for i in range(3):
            engine.generate(label=f"World {i}")
        with pytest.raises(ValueError):
            engine.generate(label="World 4")


# ── Planting ──────────────────────────────────────────────────────────────────


class TestPlantSeed:

    def test_plant_sets_status_planted(self, engine):
        seed = engine.generate(label="My World")
        engine.plant(seed["seed_hash"])
        assert engine.planted["seed_hash"] == seed["seed_hash"]

    def test_plant_persists_status(self, engine, tmp_db):
        seed = engine.generate(label="My World")
        engine.plant(seed["seed_hash"])
        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT status FROM seeds WHERE seed_hash=?", (seed["seed_hash"],)
        ).fetchone()
        conn.close()
        assert row[0] == "planted"

    def test_only_one_planted_at_a_time(self, engine):
        s1 = engine.generate(label="World One")
        s2 = engine.generate(label="World Two")
        engine.plant(s1["seed_hash"])
        engine.plant(s2["seed_hash"])
        planted = [s for s in engine.pocket if s["status"] == "planted"]
        assert len(planted) == 1

    def test_plant_nonexistent_raises(self, engine):
        with pytest.raises(ValueError):
            engine.plant("nonexistent-hash")


# ── Archiving ─────────────────────────────────────────────────────────────────


class TestArchiveSeed:

    def test_archive_sets_status_archived(self, engine, tmp_db):
        seed = engine.generate(label="Ending World")
        engine.plant(seed["seed_hash"])
        engine.archive(seed["seed_hash"])
        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT status FROM seeds WHERE seed_hash=?", (seed["seed_hash"],)
        ).fetchone()
        conn.close()
        assert row[0] == "archived"

    def test_archive_removes_from_pocket(self, engine):
        seed = engine.generate(label="Ending World")
        engine.plant(seed["seed_hash"])
        engine.archive(seed["seed_hash"])
        hashes = [s["seed_hash"] for s in engine.pocket]
        assert seed["seed_hash"] not in hashes

    def test_archive_clears_planted_if_was_planted(self, engine):
        seed = engine.generate(label="Ending World")
        engine.plant(seed["seed_hash"])
        engine.archive(seed["seed_hash"])
        assert engine.planted is None

    def test_archive_nonexistent_raises(self, engine):
        with pytest.raises(ValueError):
            engine.archive("nonexistent-hash")

    def test_archived_seeds_persist_in_db(self, engine, tmp_db):
        seed = engine.generate(label="Ending World")
        engine.plant(seed["seed_hash"])
        engine.archive(seed["seed_hash"])
        conn = sqlite3.connect(tmp_db)
        rows = conn.execute(
            "SELECT * FROM seeds WHERE status=?", ("archived",)
        ).fetchall()
        conn.close()
        assert len(rows) == 1

    def test_pocket_frees_after_archive(self, engine):
        """Archiving a seed frees a pocket slot."""
        for i in range(3):
            engine.generate(label=f"World {i}")
        seed = engine.pocket[0]
        engine.archive(seed["seed_hash"])
        assert len(engine.pocket) == 2
        engine.generate(label="New World")
        assert len(engine.pocket) == 3


# ── Snapshot ──────────────────────────────────────────────────────────────────


class TestSeedSnapshot:

    def test_snapshot_is_valid_json(self, engine):
        seed = engine.generate(label="Snapshot World")
        snapshot = json.loads(seed["snapshot"])
        assert isinstance(snapshot, dict)

    def test_snapshot_has_biome_key(self, engine):
        seed = engine.generate(label="Snapshot World")
        snapshot = json.loads(seed["snapshot"])
        assert "biome" in snapshot

    def test_snapshot_has_timestamp(self, engine):
        seed = engine.generate(label="Snapshot World")
        snapshot = json.loads(seed["snapshot"])
        assert "created_at" in snapshot

    def test_consent_version_recorded(self, engine, tmp_db):
        engine.generate(label="Consent World")
        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT consent_version FROM seeds").fetchone()
        conn.close()
        assert row[0] == "1.0"
