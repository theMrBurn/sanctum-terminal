"""vault.greenhouse_requests — substrate for biome-things demand log."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.vault import vault as Vault


@pytest.fixture
def fresh_vault(tmp_path: Path):
    return Vault(db_path=tmp_path / "v.db")


# ── Hash determinism ────────────────────────────────────────────


def test_tag_profile_hash_is_deterministic():
    h1 = Vault._tag_profile_hash(["a", "b", "c"])
    h2 = Vault._tag_profile_hash(["c", "b", "a"])           # sort-invariant
    h3 = Vault._tag_profile_hash(["a", "b", "c", "a"])      # dedup-invariant
    assert h1 == h2 == h3


def test_tag_profile_hash_differs_on_content():
    h1 = Vault._tag_profile_hash(["a", "b"])
    h2 = Vault._tag_profile_hash(["a", "c"])
    assert h1 != h2


def test_empty_tags_hash_is_stable():
    assert Vault._tag_profile_hash([]) == Vault._tag_profile_hash([])
    assert Vault._tag_profile_hash([]) == Vault._tag_profile_hash([""])


# ── record_demand ───────────────────────────────────────────────


def test_record_demand_inserts(fresh_vault):
    rid = fresh_vault.greenhouse_record_demand(
        biome="cavern", tile_x=1, tile_y=2, slot=0,
        tag_profile=["carcosa", "decorative"],
    )
    assert rid > 0


def test_record_demand_idempotent_increments_count(fresh_vault):
    fresh_vault.greenhouse_record_demand(
        biome="cavern", tile_x=1, tile_y=2, slot=0,
        tag_profile=["carcosa", "decorative"],
    )
    fresh_vault.greenhouse_record_demand(
        biome="cavern", tile_x=1, tile_y=2, slot=0,
        tag_profile=["carcosa", "decorative"],
    )
    unfilled = fresh_vault.greenhouse_list_unfilled(biome="cavern")
    assert len(unfilled) == 1
    assert unfilled[0]["encounter_count"] == 2


def test_different_slots_are_separate_rows(fresh_vault):
    fresh_vault.greenhouse_record_demand(
        biome="cavern", tile_x=1, tile_y=2, slot=0, tag_profile=["a"])
    fresh_vault.greenhouse_record_demand(
        biome="cavern", tile_x=1, tile_y=2, slot=1, tag_profile=["a"])
    assert len(fresh_vault.greenhouse_list_unfilled()) == 2


def test_different_tiles_are_separate_rows(fresh_vault):
    fresh_vault.greenhouse_record_demand(
        biome="cavern", tile_x=1, tile_y=2, slot=0, tag_profile=["a"])
    fresh_vault.greenhouse_record_demand(
        biome="cavern", tile_x=5, tile_y=5, slot=0, tag_profile=["a"])
    assert len(fresh_vault.greenhouse_list_unfilled()) == 2


def test_different_biomes_are_separate_rows(fresh_vault):
    fresh_vault.greenhouse_record_demand(
        biome="cavern",  tile_x=1, tile_y=2, slot=0, tag_profile=["a"])
    fresh_vault.greenhouse_record_demand(
        biome="outdoor", tile_x=1, tile_y=2, slot=0, tag_profile=["a"])
    assert len(fresh_vault.greenhouse_list_unfilled()) == 2


# ── mark_filled ─────────────────────────────────────────────────


def test_mark_filled_idempotent(fresh_vault):
    fresh_vault.greenhouse_record_demand(
        biome="cavern", tile_x=1, tile_y=2, slot=0, tag_profile=["a"])
    assert fresh_vault.greenhouse_mark_filled(
        "cavern", 1, 2, 0, ["a"], "test_thing") is True
    # No longer in unfilled list
    assert fresh_vault.greenhouse_list_unfilled() == []
    # Re-filling is a no-op (still True since it found the row)
    assert fresh_vault.greenhouse_mark_filled(
        "cavern", 1, 2, 0, ["a"], "test_thing") is True


def test_mark_filled_unknown_returns_false(fresh_vault):
    assert fresh_vault.greenhouse_mark_filled(
        "phantom", 0, 0, 0, [], "x") is False


def test_record_after_mark_resets_filled(fresh_vault):
    """If a request gets re-encountered after being filled, it's
    unfilled again (the library lost the thing, was edited, etc.)."""
    fresh_vault.greenhouse_record_demand(
        biome="cavern", tile_x=1, tile_y=2, slot=0, tag_profile=["a"])
    fresh_vault.greenhouse_mark_filled("cavern", 1, 2, 0, ["a"], "thing")
    assert fresh_vault.greenhouse_list_unfilled() == []
    fresh_vault.greenhouse_record_demand(
        biome="cavern", tile_x=1, tile_y=2, slot=0, tag_profile=["a"])
    unfilled = fresh_vault.greenhouse_list_unfilled()
    assert len(unfilled) == 1
    assert unfilled[0]["encounter_count"] == 2  # count carried over


# ── demand_by_profile ───────────────────────────────────────────


def test_demand_by_profile_aggregates_across_tiles(fresh_vault):
    for tx in range(5):
        fresh_vault.greenhouse_record_demand(
            biome="cavern", tile_x=tx, tile_y=0, slot=0,
            tag_profile=["moebius", "decorative"],
        )
    for tx in range(2):
        fresh_vault.greenhouse_record_demand(
            biome="outdoor", tile_x=tx, tile_y=0, slot=0,
            tag_profile=["tolkien"],
        )
    by_profile = fresh_vault.greenhouse_demand_by_profile()
    assert len(by_profile) == 2
    # Sorted by total_encounters desc
    assert by_profile[0]["unfilled_count"] == 5
    assert sorted(by_profile[0]["tag_profile"]) == ["decorative", "moebius"]
    assert by_profile[1]["unfilled_count"] == 2


def test_demand_by_profile_skips_filled(fresh_vault):
    fresh_vault.greenhouse_record_demand(
        biome="cavern", tile_x=0, tile_y=0, slot=0, tag_profile=["a"])
    fresh_vault.greenhouse_record_demand(
        biome="cavern", tile_x=1, tile_y=0, slot=0, tag_profile=["a"])
    fresh_vault.greenhouse_mark_filled("cavern", 0, 0, 0, ["a"], "x")
    by_profile = fresh_vault.greenhouse_demand_by_profile()
    assert len(by_profile) == 1
    assert by_profile[0]["unfilled_count"] == 1


# ── stats ────────────────────────────────────────────────────────


def test_stats_counts(fresh_vault):
    fresh_vault.greenhouse_record_demand(
        biome="cavern", tile_x=0, tile_y=0, slot=0, tag_profile=["a"])
    fresh_vault.greenhouse_record_demand(
        biome="cavern", tile_x=1, tile_y=0, slot=0, tag_profile=["a"])
    fresh_vault.greenhouse_mark_filled("cavern", 0, 0, 0, ["a"], "x")
    s = fresh_vault.greenhouse_stats()
    assert s["unfilled"] == 1
    assert s["filled"] == 1


# ── list_unfilled biome filter ──────────────────────────────────


def test_list_unfilled_biome_filter(fresh_vault):
    fresh_vault.greenhouse_record_demand(
        biome="cavern",  tile_x=0, tile_y=0, slot=0, tag_profile=["a"])
    fresh_vault.greenhouse_record_demand(
        biome="outdoor", tile_x=0, tile_y=0, slot=0, tag_profile=["a"])
    cav = fresh_vault.greenhouse_list_unfilled(biome="cavern")
    out = fresh_vault.greenhouse_list_unfilled(biome="outdoor")
    assert len(cav) == 1
    assert len(out) == 1
    assert cav[0]["biome"] == "cavern"
    assert out[0]["biome"] == "outdoor"


# ── Schema idempotency ──────────────────────────────────────────


def test_schema_init_idempotent(tmp_path: Path):
    db = tmp_path / "v.db"
    Vault(db_path=db)
    Vault(db_path=db)
    import sqlite3
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='greenhouse_requests'"
        ).fetchall()
        assert len(rows) == 1
