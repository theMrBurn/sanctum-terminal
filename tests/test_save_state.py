"""Tests for core.systems.save_state — JSON disk persistence.

V2 schema: PlayerState + optional CharacterSheet. V1 saves migrate inline
(character_sheet=None), so legacy players don't lose progress on the
schema bump — they just enter CHARACTER_CREATION on next launch to seal
a sheet.

Covers:
  - to_dict / from_dict round-trip preserves every field (V2 shape)
  - save / load round-trip preserves PlayerState + CharacterSheet
  - load() returns None on missing file / malformed JSON / future versions
  - V1 → V2 migration: V1 saves load with character_sheet=None
  - SANCTUM_SAVE_PATH env var redirects the default location
  - Atomic save: no .tmp residue after clean write
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.systems import save_state
from core.systems.character_sheet import (
    ClassEntry,
    generate_character_sheet,
)
from core.systems.player_state import Item, PlayerState


# --- Fixtures ---------------------------------------------------------------

@pytest.fixture
def isolated_save(tmp_path, monkeypatch):
    """Redirect saves into tmp_path via the SANCTUM_SAVE_PATH env var."""
    target = tmp_path / "player.json"
    monkeypatch.setenv("SANCTUM_SAVE_PATH", str(target))
    return target


def _make_player() -> PlayerState:
    p = PlayerState.new(name="Test", seed=42)
    p = p._replace(
        inventory=(
            Item(name="torch_handcrafted", slot_cost=1),
            Item(name="healing_potion", slot_cost=1),
            Item(name="pot_shard", slot_cost=2),
        ),
        equipped="torch_handcrafted",
        completed_missions=("anomaly_hunt_01", "deeper_anomaly"),
        hp=4,
    )
    return p


def _make_sheet():
    return generate_character_sheet(
        name="themrburn",
        birthday=(3, 25),
        age=45,
    )


# --- to_dict / from_dict ----------------------------------------------------

def test_to_dict_v2_includes_player_and_null_sheet_by_default():
    p = _make_player()
    d = save_state.to_dict(p)
    assert d["version"] == 3
    assert d["character_sheet"] is None
    pd = d["player"]
    assert pd["name"] == "Test"
    assert pd["hp"] == 4
    assert pd["equipped"] == "torch_handcrafted"
    assert pd["completed_missions"] == ["anomaly_hunt_01", "deeper_anomaly"]


def test_to_dict_with_sheet_includes_identity_fields():
    p = _make_player()
    sheet = _make_sheet()
    d = save_state.to_dict(p, sheet)
    assert d["version"] == 3
    sd = d["character_sheet"]
    assert sd["name"] == "themrburn"
    assert sd["birthday"] == [3, 25]
    assert sd["age"] == 45
    assert len(sd["class_history"]) == 2  # rogue → monk template
    assert sd["stats"]["WIS"] == 16  # monk preset
    assert "OBSERVE" in sd["verbs_known"]


def test_from_dict_returns_saved_with_player_only():
    p = _make_player()
    saved = save_state.from_dict(save_state.to_dict(p))
    assert saved.player == p
    assert saved.character_sheet is None


def test_from_dict_returns_saved_with_sheet():
    p = _make_player()
    sheet = _make_sheet()
    saved = save_state.from_dict(save_state.to_dict(p, sheet))
    assert saved.player == p
    assert saved.character_sheet is not None
    assert saved.character_sheet.name == "themrburn"
    assert saved.character_sheet.age == 45
    # earned_abilities recomputed from class_history (not stored)
    assert len(saved.character_sheet.earned_abilities) == 8  # rogue + monk = 8


def test_from_dict_handles_v1_minimal_save():
    """A V1 save (no character_sheet field, no version=2) still loads.
    V1 → V2 migration injects character_sheet=None."""
    minimal_v1 = {
        "version": 1,
        "player": {
            "name": "Legacy",
            "hp": 6, "max_hp": 6,
            "str_save": 10, "dex_save": 10, "wil_save": 10,
            "slots": 10,
            "inventory": [],
        },
    }
    # from_dict expects already-migrated data; load() does the migration.
    # Test the migration via save_load_round_trip below.
    # Direct call with V1-shaped dict:
    minimal_v1["character_sheet"] = None  # what migration would inject
    saved = save_state.from_dict(minimal_v1)
    assert saved.player.name == "Legacy"
    assert saved.character_sheet is None


# --- Disk round-trip --------------------------------------------------------

def test_save_load_round_trip_player_only(isolated_save):
    p = _make_player()
    written = save_state.save(p)
    assert written == isolated_save
    saved = save_state.load()
    assert saved is not None
    assert saved.player == p
    assert saved.character_sheet is None


def test_save_load_round_trip_with_sheet(isolated_save):
    p = _make_player()
    sheet = _make_sheet()
    save_state.save(p, sheet)
    saved = save_state.load()
    assert saved is not None
    assert saved.player == p
    assert saved.character_sheet is not None
    assert saved.character_sheet.name == sheet.name
    assert saved.character_sheet.age == sheet.age
    assert saved.character_sheet.dex == sheet.dex


def test_save_writes_v2_human_readable_json(isolated_save):
    p = _make_player()
    save_state.save(p)
    text = isolated_save.read_text()
    assert "  " in text  # pretty-printed
    assert "\n" in text
    parsed = json.loads(text)
    assert parsed["version"] == 3
    assert "character_sheet" in parsed  # field exists, even if null
    assert parsed["player"]["active_quests"] == []
    assert parsed["player"]["completed_quests"] == []


# --- V1 → V2 migration ------------------------------------------------------

def test_load_v1_save_migrates_inline(isolated_save):
    """A V1 save on disk should load successfully with character_sheet=None.
    Brain treats this as 'legacy player; run pillar 1 to get a sheet.'
    V1 → V2 → V3 migration also lands empty quest fields."""
    isolated_save.parent.mkdir(parents=True, exist_ok=True)
    v1_save = {
        "version": 1,
        "player": {
            "name": "Legacy",
            "hp": 6, "max_hp": 6,
            "str_save": 10, "dex_save": 10, "wil_save": 10,
            "slots": 10,
            "inventory": [],
            "equipped": None,
            "completed_missions": [],
        },
    }
    isolated_save.write_text(json.dumps(v1_save))
    saved = save_state.load()
    assert saved is not None
    assert saved.player.name == "Legacy"
    assert saved.character_sheet is None  # migrated to None
    assert saved.player.active_quests == ()  # V3 fields default empty
    assert saved.player.completed_quests == ()


# --- V2 → V3 migration ------------------------------------------------------


def test_load_v2_save_migrates_to_v3(isolated_save):
    """V2 saves had no quest fields. Loader injects empty tuples so the
    legacy save keeps all character + inventory progress and just gains
    the new async-quest substrate blank."""
    isolated_save.parent.mkdir(parents=True, exist_ok=True)
    v2_save = {
        "version": 2,
        "player": {
            "name": "Returning",
            "hp": 4, "max_hp": 6,
            "str_save": 12, "dex_save": 14, "wil_save": 8,
            "slots": 10,
            "inventory": [{"name": "torch", "slot_cost": 1}],
            "equipped": "torch",
            "completed_missions": ["anomaly_hunt_01"],
        },
        "character_sheet": None,
    }
    isolated_save.write_text(json.dumps(v2_save))
    saved = save_state.load()
    assert saved is not None
    assert saved.player.name == "Returning"
    assert saved.player.completed_missions == ("anomaly_hunt_01",)  # preserved
    assert saved.player.active_quests == ()
    assert saved.player.completed_quests == ()


def test_v3_round_trip_persists_quest_fields(isolated_save):
    """V3 active_quests + completed_quests survive save → load."""
    p = PlayerState(
        name="Tester",
        hp=6, max_hp=6,
        str_save=10, dex_save=10, wil_save=10,
        slots=10,
        inventory=(),
        equipped=None,
        completed_missions=(),
        active_quests=("journal_3", "anomaly_hunt_01"),
        completed_quests=("journal_1",),
    )
    save_state.save(p)
    saved = save_state.load()
    assert saved is not None
    assert saved.player.active_quests == ("journal_3", "anomaly_hunt_01")
    assert saved.player.completed_quests == ("journal_1",)


# --- Defensive load paths ---------------------------------------------------

def test_load_missing_file_returns_none(isolated_save):
    assert not isolated_save.exists()
    assert save_state.load() is None


def test_load_malformed_json_returns_none(isolated_save):
    isolated_save.parent.mkdir(parents=True, exist_ok=True)
    isolated_save.write_text("{not valid json")
    assert save_state.load() is None


def test_load_future_schema_version_returns_none(isolated_save):
    isolated_save.parent.mkdir(parents=True, exist_ok=True)
    isolated_save.write_text(json.dumps({"version": 999, "player": {}}))
    # Future-version saves are refused — better fresh-start than corrupt-load.
    assert save_state.load() is None


def test_load_truncated_player_returns_none(isolated_save):
    isolated_save.parent.mkdir(parents=True, exist_ok=True)
    isolated_save.write_text(json.dumps({"version": 2, "player": "broken"}))
    assert save_state.load() is None


# --- Atomic write -----------------------------------------------------------

def test_atomic_save_does_not_leave_tmp_file(isolated_save):
    p = _make_player()
    save_state.save(p)
    tmp = isolated_save.with_suffix(isolated_save.suffix + ".tmp")
    assert not tmp.exists()


# --- Path resolution --------------------------------------------------------

def test_explicit_path_overrides_env_var(tmp_path, monkeypatch):
    env_target = tmp_path / "env.json"
    explicit = tmp_path / "explicit.json"
    monkeypatch.setenv("SANCTUM_SAVE_PATH", str(env_target))
    save_state.save(_make_player(), path=explicit)
    assert explicit.exists()
    assert not env_target.exists()


def test_delete_removes_save(isolated_save):
    save_state.save(_make_player())
    assert isolated_save.exists()
    assert save_state.delete() is True
    assert not isolated_save.exists()


def test_delete_no_op_on_missing(isolated_save):
    assert not isolated_save.exists()
    assert save_state.delete() is False
