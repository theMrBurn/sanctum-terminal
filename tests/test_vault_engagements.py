"""vault.engagements table + helpers — creature engagement V1 PR 3.

Per `.claude/feature/feat_creature-engagement.md` PR 3 T3:
- schema migration idempotent on fresh + existing vault
- open/close round-trips a row
- terminal_state + metrics persist through close
- engagements_by_kind returns newest first
- engagements_by_kind handles unknown kind (empty list)
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from core.vault import vault as Vault


@pytest.fixture
def fresh_vault(tmp_path: Path):
    return Vault(db_path=tmp_path / "vault.db")


# ── Schema ────────────────────────────────────────────────────────────


def test_engagements_table_created(fresh_vault):
    with sqlite3.connect(fresh_vault.db_path) as conn:
        names = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "engagements" in names


def test_engagement_indexes_exist(fresh_vault):
    with sqlite3.connect(fresh_vault.db_path) as conn:
        idxs = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
    assert "idx_engagements_instance" in idxs
    assert "idx_engagements_kind" in idxs


def test_schema_init_idempotent(tmp_path: Path):
    """Two Vault inits on the same db must not duplicate the table."""
    db = tmp_path / "vault.db"
    Vault(db_path=db)
    Vault(db_path=db)   # second init — must not throw
    with sqlite3.connect(db) as conn:
        # Single table, no duplicates
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='engagements'"
        ).fetchall()
    assert len(rows) == 1


# ── Open ──────────────────────────────────────────────────────────────


def test_engagement_open_inserts_row(fresh_vault):
    rid = fresh_vault.engagement_open("compose_three", "rat_001", "rat")
    assert rid > 0
    with sqlite3.connect(fresh_vault.db_path) as conn:
        row = conn.execute(
            "SELECT instance_id, agent_id, kind, ended_at, terminal_state "
            "FROM engagements WHERE id = ?", (rid,)
        ).fetchone()
    assert row[0] == "compose_three"
    assert row[1] == "rat_001"
    assert row[2] == "rat"
    assert row[3] is None              # not closed yet
    assert row[4] is None              # no terminal state yet


def test_engagement_open_records_started_at(fresh_vault):
    before = time.time()
    rid = fresh_vault.engagement_open("compose_three", "rat_001", "rat")
    after = time.time()
    with sqlite3.connect(fresh_vault.db_path) as conn:
        started = conn.execute(
            "SELECT started_at FROM engagements WHERE id = ?", (rid,)
        ).fetchone()[0]
    assert before <= started <= after


# ── Close ─────────────────────────────────────────────────────────────


def test_engagement_close_marks_terminal_state(fresh_vault):
    rid = fresh_vault.engagement_open("compose_three", "rat_001", "rat")
    ok = fresh_vault.engagement_close(rid, "won", metrics={"attempts": 1})
    assert ok is True
    with sqlite3.connect(fresh_vault.db_path) as conn:
        row = conn.execute(
            "SELECT ended_at, terminal_state, metrics_json "
            "FROM engagements WHERE id = ?", (rid,)
        ).fetchone()
    assert row[0] is not None
    assert row[1] == "won"
    assert '"attempts": 1' in row[2]


def test_engagement_close_returns_false_on_unknown_id(fresh_vault):
    assert fresh_vault.engagement_close(9999, "won") is False


def test_engagement_close_empty_metrics_serializes_as_empty_object(fresh_vault):
    rid = fresh_vault.engagement_open("compose_three", "rat_001", "rat")
    fresh_vault.engagement_close(rid, "aborted")
    with sqlite3.connect(fresh_vault.db_path) as conn:
        mj = conn.execute(
            "SELECT metrics_json FROM engagements WHERE id = ?", (rid,)
        ).fetchone()[0]
    assert mj == "{}"


# ── Listing ───────────────────────────────────────────────────────────


def test_engagements_by_kind_returns_newest_first(fresh_vault):
    rid1 = fresh_vault.engagement_open("compose_three", "rat_001", "rat")
    time.sleep(0.005)                  # ensure distinct timestamps
    rid2 = fresh_vault.engagement_open("compose_three", "rat_002", "rat")
    rows = fresh_vault.engagements_by_kind("rat")
    assert [r["id"] for r in rows] == [rid2, rid1]


def test_engagements_by_kind_returns_empty_for_unknown(fresh_vault):
    assert fresh_vault.engagements_by_kind("phantom_thing") == []


def test_engagements_by_kind_round_trips_metrics(fresh_vault):
    rid = fresh_vault.engagement_open("compose_three", "rat_001", "rat")
    fresh_vault.engagement_close(
        rid, "won", metrics={"attempts": 2, "duration_ms": 4200},
    )
    rows = fresh_vault.engagements_by_kind("rat")
    assert len(rows) == 1
    assert rows[0]["metrics"]["attempts"] == 2
    assert rows[0]["metrics"]["duration_ms"] == 4200
    assert rows[0]["terminal_state"] == "won"


def test_engagements_by_kind_filters_by_kind(fresh_vault):
    fresh_vault.engagement_open("compose_three", "rat_001", "rat")
    fresh_vault.engagement_open("compose_three", "pixie_001", "boulder_pixie")
    rows = fresh_vault.engagements_by_kind("rat")
    assert len(rows) == 1
    assert rows[0]["kind"] == "rat"
