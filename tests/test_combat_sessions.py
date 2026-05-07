"""vault.combat_sessions tests — feat/arpg-combat PR 7.

Schema migration + 3 helper APIs (open / close / by_weapon).
Mirrors test_activity_log.py shape.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.vault import vault as Vault


@pytest.fixture
def fresh_vault(tmp_path: Path):
    return Vault(db_path=tmp_path / "vault.db")


# ── schema ────────────────────────────────────────────────────────────


def test_combat_sessions_table_exists_after_init(fresh_vault):
    import sqlite3
    with sqlite3.connect(fresh_vault.db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='combat_sessions'"
        ).fetchall()
        assert len(rows) == 1


def test_schema_init_idempotent(tmp_path):
    db = tmp_path / "vault.db"
    Vault(db_path=db)
    Vault(db_path=db)
    Vault(db_path=db)


# ── combat_session_open ───────────────────────────────────────────────


def test_open_returns_row_id(fresh_vault):
    sid = fresh_vault.combat_session_open(
        source_actor="player",
        weapon_kind="iron_sword",
        weapon_class="melee_blade",
        mode="held",
    )
    assert isinstance(sid, int)
    assert sid > 0


def test_open_persists_with_started_at(fresh_vault):
    sid = fresh_vault.combat_session_open(
        source_actor="player",
        weapon_kind="throwing_axe",
        weapon_class="ranged_thrown",
        mode="shot",
    )
    rows = fresh_vault.combat_sessions_by_weapon("throwing_axe")
    assert len(rows) == 1
    assert rows[0]["id"] == sid
    assert rows[0]["mode"] == "shot"
    assert rows[0]["started_at"] is not None
    assert rows[0]["resolved_at"] is None       # not yet closed
    assert rows[0]["outcome"] is None


# ── combat_session_close ──────────────────────────────────────────────


def test_close_updates_outcome_and_resolved_at(fresh_vault):
    sid = fresh_vault.combat_session_open(
        source_actor="player",
        weapon_kind="chain_whip",
        weapon_class="melee_tether",
        mode="whip",
    )
    ok = fresh_vault.combat_session_close(
        session_id=sid,
        outcome="landed",
        target_kind="pot",
        target_id=42,
        kinetic_energy=15.5,
        metrics={"hit_count": 3},
    )
    assert ok is True
    rows = fresh_vault.combat_sessions_by_weapon("chain_whip")
    assert len(rows) == 1
    r = rows[0]
    assert r["outcome"] == "landed"
    assert r["target_kind"] == "pot"
    assert r["target_id"] == 42
    assert r["kinetic_energy"] == 15.5
    assert r["resolved_at"] is not None
    assert r["metrics"] == {"hit_count": 3}


def test_close_returns_false_on_unknown_id(fresh_vault):
    ok = fresh_vault.combat_session_close(
        session_id=99999,
        outcome="landed",
    )
    assert ok is False


def test_close_handles_missing_optional_fields(fresh_vault):
    """Faded strikes don't have target_kind / target_id / KE."""
    sid = fresh_vault.combat_session_open(
        source_actor="player",
        weapon_kind="throwing_axe",
        weapon_class="ranged_thrown",
        mode="shot",
    )
    ok = fresh_vault.combat_session_close(
        session_id=sid,
        outcome="missed",
    )
    assert ok is True
    rows = fresh_vault.combat_sessions_by_weapon("throwing_axe")
    assert rows[0]["outcome"] == "missed"
    assert rows[0]["target_kind"] is None
    assert rows[0]["kinetic_energy"] is None


# ── combat_sessions_by_weapon ─────────────────────────────────────────


def test_by_weapon_returns_newest_first(fresh_vault):
    fresh_vault.combat_session_open("player", "iron_sword", "melee_blade", "held")
    fresh_vault.combat_session_open("player", "iron_sword", "melee_blade", "held")
    fresh_vault.combat_session_open("player", "iron_sword", "melee_blade", "held")
    rows = fresh_vault.combat_sessions_by_weapon("iron_sword")
    assert len(rows) == 3
    # Started_at descends
    assert rows[0]["started_at"] >= rows[1]["started_at"] >= rows[2]["started_at"]


def test_by_weapon_filters_correctly(fresh_vault):
    fresh_vault.combat_session_open("player", "iron_sword", "melee_blade", "held")
    fresh_vault.combat_session_open("player", "throwing_axe", "ranged_thrown", "shot")
    fresh_vault.combat_session_open("player", "iron_sword", "melee_blade", "held")
    sword_rows = fresh_vault.combat_sessions_by_weapon("iron_sword")
    axe_rows = fresh_vault.combat_sessions_by_weapon("throwing_axe")
    assert len(sword_rows) == 2
    assert len(axe_rows) == 1


def test_by_weapon_empty_when_none_match(fresh_vault):
    rows = fresh_vault.combat_sessions_by_weapon("nonexistent_weapon")
    assert rows == []


# ── full lifecycle ────────────────────────────────────────────────────


def test_full_open_close_lifecycle(fresh_vault):
    """Open + close + read returns expected end-state."""
    sid = fresh_vault.combat_session_open(
        source_actor="player",
        weapon_kind="fire_staff",
        weapon_class="magic_staff",
        mode="shot",
    )
    fresh_vault.combat_session_close(
        session_id=sid,
        outcome="engagement_triggered",
        target_kind="rat",
        target_id=7,
        kinetic_energy=8.2,
    )
    rows = fresh_vault.combat_sessions_by_weapon("fire_staff")
    assert len(rows) == 1
    r = rows[0]
    assert r["weapon_class"] == "magic_staff"
    assert r["mode"] == "shot"
    assert r["outcome"] == "engagement_triggered"
    assert r["target_kind"] == "rat"
    assert r["resolved_at"] > r["started_at"]
