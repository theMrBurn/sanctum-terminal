"""Vault profiles + runs — make-brain substrate tests.

T1 of `feat_make-brain-ping-pong` PR 1. Pins the contract for the two
universal tables shared by every make-brain instance:

- Schema lands idempotently on fresh + pre-existing vault.db
- profiles + runs CRUD round-trip
- Profile parent_profile inheritance resolves correctly (child overrides
  parent)
- Cycle detection in inheritance chain raises ValueError
- Missing parent in inheritance chain raises LookupError
- run_id generator is unique
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.vault import vault as Vault


@pytest.fixture
def fresh_vault(tmp_path: Path):
    db = tmp_path / "vault.db"
    return Vault(db_path=db)


# ── Schema migration ──────────────────────────────────────────────────


def test_profiles_runs_tables_created_on_fresh_db(fresh_vault):
    with sqlite3.connect(fresh_vault.db_path) as conn:
        names = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        idxs = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
    assert "profiles" in names
    assert "runs" in names
    assert "idx_profiles_instance" in idxs
    assert "idx_runs_instance" in idxs
    assert "idx_runs_profile" in idxs


def test_schema_idempotent_across_reinit(tmp_path: Path):
    """Re-opening an existing vault doesn't error or duplicate tables."""
    db = tmp_path / "vault.db"
    Vault(db_path=db)
    Vault(db_path=db)            # second init = idempotent ALTER TABLE path
    v = Vault(db_path=db)
    v.profile_save("ping_pong", "vanilla", {"a": 1})
    assert v.profile_load("ping_pong", "vanilla") is not None


# ── Profile CRUD ──────────────────────────────────────────────────────


def test_profile_save_then_load_round_trip(fresh_vault):
    rid = fresh_vault.profile_save(
        "ping_pong", "vanilla",
        params={"ball_mass": 1.0, "gravity_y": 0.0},
        notes="arcade defaults",
    )
    assert rid > 0
    row = fresh_vault.profile_load("ping_pong", "vanilla")
    assert row is not None
    assert row["instance_id"] == "ping_pong"
    assert row["profile_name"] == "vanilla"
    assert row["params"] == {"ball_mass": 1.0, "gravity_y": 0.0}
    assert row["notes"] == "arcade defaults"
    assert row["parent_profile"] is None


def test_profile_save_overwrites_on_unique_conflict(fresh_vault):
    rid1 = fresh_vault.profile_save("ping_pong", "vanilla", {"x": 1})
    rid2 = fresh_vault.profile_save(
        "ping_pong", "vanilla", {"x": 2}, notes="updated"
    )
    assert rid1 == rid2          # same row, ON CONFLICT path
    row = fresh_vault.profile_load("ping_pong", "vanilla")
    assert row["params"] == {"x": 2}
    assert row["notes"] == "updated"


def test_profile_load_missing_returns_none(fresh_vault):
    assert fresh_vault.profile_load("ping_pong", "nope") is None


def test_profile_save_rejects_non_dict_params(fresh_vault):
    with pytest.raises(ValueError):
        fresh_vault.profile_save("ping_pong", "vanilla", params="not a dict")


def test_profile_list_filters_by_instance(fresh_vault):
    fresh_vault.profile_save("ping_pong", "vanilla", {"a": 1})
    fresh_vault.profile_save("ping_pong", "heavy", {"a": 2})
    fresh_vault.profile_save("archery", "vanilla", {"a": 3})
    pings = fresh_vault.profile_list("ping_pong")
    assert {p["profile_name"] for p in pings} == {"vanilla", "heavy"}
    archery = fresh_vault.profile_list("archery")
    assert len(archery) == 1
    assert archery[0]["params"] == {"a": 3}


# ── Profile parent inheritance resolution ─────────────────────────────


def test_profile_resolve_with_no_parent_returns_own_params(fresh_vault):
    fresh_vault.profile_save("ping_pong", "vanilla",
                             {"ball_mass": 1.0, "gravity_y": 0.0})
    merged = fresh_vault.profile_resolve("ping_pong", "vanilla")
    assert merged == {"ball_mass": 1.0, "gravity_y": 0.0}


def test_profile_resolve_child_overrides_parent(fresh_vault):
    fresh_vault.profile_save(
        "ping_pong", "vanilla",
        {"ball_mass": 1.0, "ball_radius": 0.15, "gravity_y": 0.0},
    )
    fresh_vault.profile_save(
        "ping_pong", "tennis_sim",
        {"ball_mass": 0.058, "gravity_y": -9.81},
        parent_profile="vanilla",
    )
    merged = fresh_vault.profile_resolve("ping_pong", "tennis_sim")
    # parent contributes ball_radius; child overrides ball_mass + gravity_y
    assert merged == {
        "ball_mass":   0.058,
        "ball_radius": 0.15,
        "gravity_y":   -9.81,
    }


def test_profile_resolve_three_level_chain(fresh_vault):
    fresh_vault.profile_save("ping_pong", "vanilla",
                             {"a": 1, "b": 1, "c": 1})
    fresh_vault.profile_save("ping_pong", "mid",
                             {"b": 2, "c": 2}, parent_profile="vanilla")
    fresh_vault.profile_save("ping_pong", "child",
                             {"c": 3}, parent_profile="mid")
    merged = fresh_vault.profile_resolve("ping_pong", "child")
    assert merged == {"a": 1, "b": 2, "c": 3}


def test_profile_resolve_missing_root_raises_lookup(fresh_vault):
    with pytest.raises(LookupError):
        fresh_vault.profile_resolve("ping_pong", "nope")


def test_profile_resolve_missing_parent_raises_lookup(fresh_vault):
    fresh_vault.profile_save(
        "ping_pong", "child", {"c": 1}, parent_profile="ghost"
    )
    with pytest.raises(LookupError):
        fresh_vault.profile_resolve("ping_pong", "child")


def test_profile_resolve_cycle_raises_value_error(fresh_vault):
    # A → B → A
    fresh_vault.profile_save(
        "ping_pong", "a", {"a": 1}, parent_profile="b"
    )
    fresh_vault.profile_save(
        "ping_pong", "b", {"b": 1}, parent_profile="a"
    )
    with pytest.raises(ValueError):
        fresh_vault.profile_resolve("ping_pong", "a")


# ── Run CRUD ──────────────────────────────────────────────────────────


def test_run_start_and_end_round_trip(fresh_vault):
    fresh_vault.profile_save("ping_pong", "vanilla", {})
    run_id = fresh_vault.run_start("ping_pong", "vanilla")
    assert isinstance(run_id, str) and len(run_id) > 0
    row = fresh_vault.run_get("ping_pong", run_id)
    assert row is not None
    assert row["instance_id"] == "ping_pong"
    assert row["profile_name"] == "vanilla"
    assert row["started_at"] is not None
    assert row["ended_at"] is None
    assert row["terminal_state"] is None
    assert row["metrics"] == {}

    ok = fresh_vault.run_end(
        "ping_pong", run_id,
        terminal_state="aborted",
        metrics={"rallies": [{"length": 12, "max_v": 14.2}]},
    )
    assert ok
    closed = fresh_vault.run_get("ping_pong", run_id)
    assert closed["ended_at"] is not None
    assert closed["terminal_state"] == "aborted"
    assert closed["metrics"]["rallies"][0]["length"] == 12


def test_run_end_unknown_returns_false(fresh_vault):
    assert fresh_vault.run_end("ping_pong", "nope") is False


def test_runs_by_instance_filters_and_orders(fresh_vault):
    fresh_vault.profile_save("ping_pong", "vanilla", {})
    fresh_vault.profile_save("archery", "vanilla", {})
    r1 = fresh_vault.run_start("ping_pong", "vanilla")
    r2 = fresh_vault.run_start("archery", "vanilla")
    r3 = fresh_vault.run_start("ping_pong", "vanilla")
    pings = fresh_vault.runs_by_instance("ping_pong")
    archery = fresh_vault.runs_by_instance("archery")
    assert {r["run_id"] for r in pings} == {r1, r3}
    assert {r["run_id"] for r in archery} == {r2}
    # newest first
    assert pings[0]["started_at"] >= pings[1]["started_at"]


def test_run_id_uniqueness_under_burst(fresh_vault):
    fresh_vault.profile_save("ping_pong", "vanilla", {})
    ids = {
        fresh_vault.run_start("ping_pong", "vanilla")
        for _ in range(50)
    }
    assert len(ids) == 50         # no collisions in a 50-id burst
