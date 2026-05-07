"""vault.activity_log telemetry tests — A6 from .claude/audit_2026-05-06.md.

Schema migration + 3 helper APIs + integration with activity_loop emit
path. Per the audit doctrine: log is for UAT/post-hoc, NEVER read for
gameplay. These tests verify schema + helpers + non-load-bearing
fail-safety.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.systems import activity_loop
from core.systems.activity_loop import ActivityClass
from core.systems.state_events import StateEventBuffer
from core.vault import vault as Vault


@pytest.fixture(autouse=True)
def _reset_singletons():
    activity_loop._reset_for_tests()
    yield
    activity_loop._reset_for_tests()


@pytest.fixture
def fresh_vault(tmp_path: Path):
    return Vault(db_path=tmp_path / "vault.db")


# ── schema ────────────────────────────────────────────────────────────


def test_activity_log_table_exists_after_init(fresh_vault):
    """Schema migration is idempotent + creates the activity_log table."""
    import sqlite3
    with sqlite3.connect(fresh_vault.db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='activity_log'"
        ).fetchall()
        assert len(rows) == 1


def test_schema_init_is_idempotent(tmp_path):
    """Re-instantiating the vault on the same DB doesn't error or duplicate."""
    db = tmp_path / "vault.db"
    Vault(db_path=db)
    Vault(db_path=db)        # second init should not raise
    Vault(db_path=db)        # third for good measure


# ── activity_log_append ───────────────────────────────────────────────


def test_append_returns_row_id(fresh_vault):
    rid = fresh_vault.activity_log_append(
        class_index=int(ActivityClass.HUNT),
        primitive="brick_destroyed",
        intensity=1,
        source_brain="ping_pong",
        payload={"score": 100},
    )
    assert isinstance(rid, int) and rid > 0


def test_append_default_payload_is_empty(fresh_vault):
    fresh_vault.activity_log_append(
        class_index=int(ActivityClass.UNWIND),
        primitive="dwell_slice",
        intensity=1,
        source_brain="brain_world",
    )
    rows = fresh_vault.activity_log_recent(limit=1)
    assert rows[0]["payload"] == {}


# ── activity_log_recent ───────────────────────────────────────────────


def test_recent_returns_newest_first(fresh_vault):
    fresh_vault.activity_log_append(0, "p1", 1, "src")
    fresh_vault.activity_log_append(1, "p2", 1, "src")
    fresh_vault.activity_log_append(2, "p3", 1, "src")
    rows = fresh_vault.activity_log_recent(limit=10)
    primitives = [r["primitive"] for r in rows]
    assert primitives == ["p3", "p2", "p1"]


def test_recent_respects_limit(fresh_vault):
    for i in range(20):
        fresh_vault.activity_log_append(0, f"p{i}", 1, "src")
    rows = fresh_vault.activity_log_recent(limit=5)
    assert len(rows) == 5


def test_recent_filters_by_class(fresh_vault):
    fresh_vault.activity_log_append(int(ActivityClass.HUNT),   "h1", 1, "src")
    fresh_vault.activity_log_append(int(ActivityClass.UNWIND), "u1", 1, "src")
    fresh_vault.activity_log_append(int(ActivityClass.HUNT),   "h2", 1, "src")
    rows = fresh_vault.activity_log_recent(
        limit=10, class_index=int(ActivityClass.HUNT),
    )
    assert [r["primitive"] for r in rows] == ["h2", "h1"]


def test_recent_payload_round_trips(fresh_vault):
    fresh_vault.activity_log_append(
        0, "p", 5, "src", payload={"score": 300, "max_hp": 3, "nested": {"a": 1}},
    )
    rows = fresh_vault.activity_log_recent(limit=1)
    assert rows[0]["payload"] == {"score": 300, "max_hp": 3, "nested": {"a": 1}}
    assert rows[0]["intensity"] == 5


# ── activity_log_count_by_class ───────────────────────────────────────


def test_count_by_class_sums_intensity(fresh_vault):
    fresh_vault.activity_log_append(int(ActivityClass.HUNT),   "h1", 1, "src")
    fresh_vault.activity_log_append(int(ActivityClass.HUNT),   "h2", 3, "src")  # boss
    fresh_vault.activity_log_append(int(ActivityClass.UNWIND), "u1", 1, "src")
    counts = fresh_vault.activity_log_count_by_class()
    assert counts[int(ActivityClass.HUNT)]   == 4
    assert counts[int(ActivityClass.UNWIND)] == 1
    assert int(ActivityClass.MAKE) not in counts        # zero-class omitted


def test_count_by_class_since_filter(fresh_vault):
    import time as _time
    fresh_vault.activity_log_append(0, "early", 1, "src")
    cutoff = _time.time() + 0.001     # slightly future, captures next inserts only
    _time.sleep(0.01)
    fresh_vault.activity_log_append(0, "late", 5, "src")
    counts = fresh_vault.activity_log_count_by_class(since_ts=cutoff)
    assert counts[0] == 5             # only "late" counted


# ── integration: emit_activity → vault append ─────────────────────────


def test_emit_activity_appends_to_vault_when_installed(fresh_vault):
    se = StateEventBuffer()
    activity_loop.install(se, vault=fresh_vault)
    activity_loop.emit_activity(
        ActivityClass.HUNT, 1,
        primitive="brick_destroyed", source_brain="ping_pong",
        payload={"score": 100},
    )
    rows = fresh_vault.activity_log_recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["primitive"]    == "brick_destroyed"
    assert rows[0]["source_brain"] == "ping_pong"
    assert rows[0]["intensity"]    == 1
    assert rows[0]["payload"]      == {"score": 100}


def test_emit_activity_no_vault_does_not_append(fresh_vault):
    """When install() is called WITHOUT vault, emits still work but
    nothing lands in activity_log."""
    se = StateEventBuffer()
    activity_loop.install(se)            # no vault arg
    activity_loop.emit_activity(ActivityClass.HUNT, 1)
    rows = fresh_vault.activity_log_recent(limit=10)
    assert rows == []


def test_emit_activity_failsafe_when_vault_raises(fresh_vault, monkeypatch):
    """If activity_log_append raises, the emit should still bump the
    counter (counter is gameplay-load-bearing; log is not)."""
    def _explode(*_a, **_kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(fresh_vault, "activity_log_append", _explode)
    se = StateEventBuffer()
    prefs, _ = activity_loop.install(se, vault=fresh_vault)
    activity_loop.emit_activity(ActivityClass.HUNT, 1)
    # Counter still bumped despite vault failure
    assert prefs.counts[int(ActivityClass.HUNT)] == 1


def test_emit_activity_default_metadata_lands(fresh_vault):
    """Producers without explicit primitive/source pass defaults."""
    se = StateEventBuffer()
    activity_loop.install(se, vault=fresh_vault)
    activity_loop.emit_activity(ActivityClass.MAKE, 2)
    rows = fresh_vault.activity_log_recent(limit=10)
    assert rows[0]["primitive"]    == "emit"
    assert rows[0]["source_brain"] == "brain"
    assert rows[0]["intensity"]    == 2
