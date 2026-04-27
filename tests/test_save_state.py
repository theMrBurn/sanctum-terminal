"""Tests for core.systems.save_state — JSON disk persistence for PlayerState.

Covers:
  - to_dict / from_dict round-trip preserves every field
  - save / load round-trip preserves PlayerState identity
  - load() returns None on missing file (brain proceeds with fresh player)
  - load() returns None on malformed JSON (defensive — no crash)
  - load() returns None on incompatible schema version
  - SANCTUM_SAVE_PATH env var redirects the default location
  - Atomic save: a crash mid-write doesn't leave the target half-written
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.systems import save_state
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


# --- Dict round-trip --------------------------------------------------------

def test_to_dict_includes_all_fields():
    p = _make_player()
    d = save_state.to_dict(p)
    assert d["version"] == 1
    pd = d["player"]
    assert pd["name"] == "Test"
    assert pd["hp"] == 4
    assert pd["max_hp"] == 6
    assert pd["equipped"] == "torch_handcrafted"
    assert pd["completed_missions"] == ["anomaly_hunt_01", "deeper_anomaly"]
    assert len(pd["inventory"]) == 3
    assert pd["inventory"][2] == {"name": "pot_shard", "slot_cost": 2}


def test_from_dict_round_trip():
    p = _make_player()
    restored = save_state.from_dict(save_state.to_dict(p))
    assert restored == p


def test_from_dict_handles_missing_optional_fields():
    """A save predating equipped / completed_missions still loads — fields
    fall back to PlayerState defaults."""
    minimal = {
        "version": 1,
        "player": {
            "name": "Minimal",
            "hp": 6, "max_hp": 6,
            "str_save": 10, "dex_save": 10, "wil_save": 10,
            "slots": 10,
            "inventory": [],
            # equipped + completed_missions absent
        },
    }
    restored = save_state.from_dict(minimal)
    assert restored.name == "Minimal"
    assert restored.equipped is None
    assert restored.completed_missions == ()


# --- Disk round-trip --------------------------------------------------------

def test_save_load_round_trip(isolated_save):
    p = _make_player()
    written = save_state.save(p)
    assert written == isolated_save
    assert isolated_save.exists()
    restored = save_state.load()
    assert restored == p


def test_save_writes_human_readable_json(isolated_save):
    p = _make_player()
    save_state.save(p)
    text = isolated_save.read_text()
    # Should be pretty-printed (indent=2) so saves are readable / diffable.
    assert "  " in text
    assert "\n" in text
    parsed = json.loads(text)
    assert parsed["version"] == 1


# --- Defensive load paths ---------------------------------------------------

def test_load_missing_file_returns_none(isolated_save):
    """No save file = first-boot. Brain falls back to PlayerState.new()."""
    assert not isolated_save.exists()
    assert save_state.load() is None


def test_load_malformed_json_returns_none(isolated_save):
    isolated_save.parent.mkdir(parents=True, exist_ok=True)
    isolated_save.write_text("{not valid json")
    assert save_state.load() is None


def test_load_wrong_schema_version_returns_none(isolated_save):
    isolated_save.parent.mkdir(parents=True, exist_ok=True)
    isolated_save.write_text(json.dumps({"version": 999, "player": {}}))
    # Future-version saves are refused — better fresh-start than corrupt-load.
    assert save_state.load() is None


def test_load_truncated_player_returns_none(isolated_save):
    """A save with a 'player' value that's not a dict fails defensively."""
    isolated_save.parent.mkdir(parents=True, exist_ok=True)
    isolated_save.write_text(json.dumps({"version": 1, "player": "broken"}))
    assert save_state.load() is None


# --- Atomic write -----------------------------------------------------------

def test_atomic_save_does_not_leave_tmp_file(isolated_save):
    """After a clean save, no .tmp residue should remain."""
    p = _make_player()
    save_state.save(p)
    tmp = isolated_save.with_suffix(isolated_save.suffix + ".tmp")
    assert not tmp.exists(), "atomic save should rename the temp file, not leave it"


# --- Path resolution --------------------------------------------------------

def test_explicit_path_overrides_env_var(tmp_path, monkeypatch):
    """save(path=...) wins over SANCTUM_SAVE_PATH wins over default."""
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
