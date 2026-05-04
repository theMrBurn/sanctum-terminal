"""Vault world_seeds — schema migration + CRUD round-trip tests.

T1 of `feat_vector-workroom` PR 1. Pins the contract for the
workroom-seed table: schema lands idempotently on a fresh and on a
pre-existing vault.db, every CRUD helper round-trips fields, mesh_edits
deserializes correctly, biome filtering is honored, and unknown ids on
update/delete return False without raising.
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


def test_world_seeds_table_created_on_fresh_db(fresh_vault):
    """A new vault must have the world_seeds table + the biome index."""
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
    assert "world_seeds" in names
    assert "idx_world_seeds_biome" in idxs


def test_world_seeds_schema_has_expected_columns(fresh_vault):
    with sqlite3.connect(fresh_vault.db_path) as conn:
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(world_seeds)").fetchall()}
    expected = {
        "id", "biome", "kind", "base_mesh",
        "pos_x", "pos_y", "pos_z", "yaw_deg", "scale",
        "color_r", "color_g", "color_b", "mesh_edits",
        "created_at", "updated_at",
    }
    assert expected <= cols


def test_migration_idempotent_on_existing_vault(tmp_path: Path):
    """Boot vault twice on the same db_path. First call creates schema,
    second call should be a no-op — no exceptions, no duplicate tables."""
    db = tmp_path / "vault.db"
    Vault(db_path=db)
    # Drop a row so we can confirm the second boot doesn't wipe it.
    Vault(db_path=db).world_seed_create({
        "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "cube",
        "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0,
    })
    # Second boot — must not crash, must not blow away the row.
    v3 = Vault(db_path=db)
    seeds = v3.world_seeds_by_biome("workroom")
    assert len(seeds) == 1
    assert seeds[0]["base_mesh"] == "cube"


def test_migration_on_db_with_only_legacy_tables(tmp_path: Path):
    """M1 acceptance: a vault.db that predates this feature opens cleanly
    and gains the world_seeds table without touching legacy rows."""
    db = tmp_path / "vault.db"
    # Synthesize a pre-feature vault: only the archive table.
    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE archive (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                archetypal_name TEXT NOT NULL,
                vibe            TEXT,
                impact_rating   INTEGER DEFAULT 1
            )
        """)
        conn.execute(
            "INSERT INTO archive (archetypal_name) VALUES ('legacy_relic')"
        )
        conn.commit()
    # Boot the modern vault on top of the legacy db.
    v = Vault(db_path=db)
    # Legacy row preserved.
    legacy = v.load_all()
    assert any(r["archetypal_name"] == "legacy_relic" for r in legacy)
    # New table available.
    assert v.world_seeds_by_biome("workroom") == []


# ── CRUD round-trip ──────────────────────────────────────────────────


def test_create_then_list_returns_inserted_seed(fresh_vault):
    sid = fresh_vault.world_seed_create({
        "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "spire",
        "pos_x": 1.0, "pos_y": 2.0, "pos_z": 3.0,
        "yaw_deg": 90.0, "scale": 1.5,
        "color_r": 0.4, "color_g": 0.5, "color_b": 0.6,
    })
    assert isinstance(sid, int)
    seeds = fresh_vault.world_seeds_by_biome("workroom")
    assert len(seeds) == 1
    s = seeds[0]
    assert s["id"] == sid
    assert s["base_mesh"] == "spire"
    assert s["pos_x"] == 1.0 and s["pos_y"] == 2.0 and s["pos_z"] == 3.0
    assert s["yaw_deg"] == 90.0
    assert s["scale"] == 1.5
    assert s["color_r"] == 0.4
    assert s["mesh_edits"] == []


def test_create_applies_defaults_when_optional_fields_missing(fresh_vault):
    fresh_vault.world_seed_create({
        "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "cube",
        "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0,
    })
    s = fresh_vault.world_seeds_by_biome("workroom")[0]
    assert s["yaw_deg"] == 0.0
    assert s["scale"] == 1.0
    assert s["color_r"] == 0.7
    assert s["color_g"] == 0.7
    assert s["color_b"] == 0.7
    assert s["mesh_edits"] == []


def test_create_raises_on_missing_required_field(fresh_vault):
    with pytest.raises(KeyError):
        fresh_vault.world_seed_create({
            "biome": "workroom", "kind": "wireframe_mesh",
            # missing base_mesh + pos_*
        })


def test_create_with_mesh_edits_round_trips(fresh_vault):
    edits = [
        {"op": "move_vertex", "i": 3, "to": [-0.5, 1.0, -0.5]},
        {"op": "add_edge", "a": 0, "b": 6},
    ]
    sid = fresh_vault.world_seed_create({
        "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "spire",
        "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0,
        "mesh_edits": edits,
    })
    s = fresh_vault.world_seeds_by_biome("workroom")[0]
    assert s["id"] == sid
    assert s["mesh_edits"] == edits


def test_create_rejects_non_list_mesh_edits(fresh_vault):
    with pytest.raises(ValueError):
        fresh_vault.world_seed_create({
            "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "cube",
            "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0,
            "mesh_edits": "not-a-list",
        })


def test_update_patches_subset_of_fields(fresh_vault):
    sid = fresh_vault.world_seed_create({
        "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "spire",
        "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0,
    })
    ok = fresh_vault.world_seed_update(sid, {"scale": 2.0, "color_r": 0.9})
    assert ok is True
    s = fresh_vault.world_seeds_by_biome("workroom")[0]
    assert s["scale"] == 2.0
    assert s["color_r"] == 0.9
    # Untouched fields preserved.
    assert s["base_mesh"] == "spire"
    assert s["color_g"] == 0.7


def test_update_replaces_mesh_edits_log(fresh_vault):
    sid = fresh_vault.world_seed_create({
        "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "spire",
        "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0,
    })
    fresh_vault.world_seed_update(sid, {"mesh_edits": [
        {"op": "move_vertex", "i": 0, "to": [9.0, 9.0, 9.0]},
    ]})
    s = fresh_vault.world_seeds_by_biome("workroom")[0]
    assert s["mesh_edits"] == [{"op": "move_vertex", "i": 0, "to": [9.0, 9.0, 9.0]}]


def test_update_unknown_id_returns_false(fresh_vault):
    assert fresh_vault.world_seed_update(9999, {"scale": 2.0}) is False


def test_update_ignores_unknown_fields(fresh_vault):
    sid = fresh_vault.world_seed_create({
        "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "cube",
        "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0,
    })
    # Should be a no-op update returning whether the seed exists, not raise.
    ok = fresh_vault.world_seed_update(sid, {"bogus_field": "ignored"})
    assert ok is True


def test_delete_existing_returns_true(fresh_vault):
    sid = fresh_vault.world_seed_create({
        "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "cube",
        "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0,
    })
    assert fresh_vault.world_seed_delete(sid) is True
    assert fresh_vault.world_seeds_by_biome("workroom") == []


def test_delete_unknown_returns_false(fresh_vault):
    assert fresh_vault.world_seed_delete(9999) is False


def test_list_filters_by_biome(fresh_vault):
    fresh_vault.world_seed_create({
        "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "cube",
        "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0,
    })
    fresh_vault.world_seed_create({
        "biome": "outdoor", "kind": "wireframe_mesh", "base_mesh": "spire",
        "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0,
    })
    assert len(fresh_vault.world_seeds_by_biome("workroom")) == 1
    assert len(fresh_vault.world_seeds_by_biome("outdoor")) == 1
    assert fresh_vault.world_seeds_by_biome("nowhere") == []


def test_list_orders_by_insertion(fresh_vault):
    """Placement order matters for the user — seeds list should reflect
    when they were dropped."""
    ids = []
    for mesh in ("cube", "spire", "octahedron", "tetrahedron"):
        ids.append(fresh_vault.world_seed_create({
            "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": mesh,
            "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0,
        }))
    seeds = fresh_vault.world_seeds_by_biome("workroom")
    assert [s["id"] for s in seeds] == ids


def test_full_crud_lifecycle(fresh_vault):
    """End-to-end: create, list, update, list, delete, list — counts and
    field values match across each step."""
    sid = fresh_vault.world_seed_create({
        "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "spire",
        "pos_x": 1.0, "pos_y": 0.0, "pos_z": 1.0,
    })
    assert len(fresh_vault.world_seeds_by_biome("workroom")) == 1

    fresh_vault.world_seed_update(sid, {"scale": 1.5, "yaw_deg": 45.0})
    s = fresh_vault.world_seeds_by_biome("workroom")[0]
    assert s["scale"] == 1.5
    assert s["yaw_deg"] == 45.0

    assert fresh_vault.world_seed_delete(sid) is True
    assert fresh_vault.world_seeds_by_biome("workroom") == []
