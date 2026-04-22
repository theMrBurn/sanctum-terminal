"""Snapshot drift tests — config-lock #3.

Exercises flatten/diff/canonical-dumps primitives and asserts the shipped
snapshot matches the shipped config so committing without drift is the
default state.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.systems import kind_config_snapshot as snap


_REPO_ROOT = Path(__file__).resolve().parents[1]


# --- Canonical form --------------------------------------------------------


def test_canonical_dumps_is_stable_across_key_order() -> None:
    a = {"b": 1, "a": 2, "c": {"z": 3, "y": 4}}
    b = {"a": 2, "c": {"y": 4, "z": 3}, "b": 1}
    assert snap.canonical_dumps(a) == snap.canonical_dumps(b)


def test_canonical_dumps_ends_with_newline() -> None:
    assert snap.canonical_dumps({"k": 1}).endswith("\n")


# --- Flatten + diff --------------------------------------------------------


def test_flatten_nested_dicts() -> None:
    data = {"a": {"b": {"c": 1}}, "d": 2}
    assert snap.flatten(data) == {"a.b.c": 1, "d": 2}


def test_flatten_keeps_lists_as_leaves() -> None:
    data = {"color": [0.1, 0.2, 0.3], "nested": {"vec": [1, 2, 3]}}
    flat = snap.flatten(data)
    assert flat == {"color": [0.1, 0.2, 0.3], "nested.vec": [1, 2, 3]}


def test_diff_detects_added_removed_changed() -> None:
    old = snap.flatten({"a": 1, "b": 2, "c": {"d": 3}})
    new = snap.flatten({"b": 2, "c": {"d": 4}, "e": 5})
    d = snap.diff(old, new)
    assert d["added"] == {"e": 5}
    assert d["removed"] == {"a": 1}
    assert d["changed"] == {"c.d": (3, 4)}


def test_diff_empty_on_identical_configs() -> None:
    data = {"k": {"collision_radius": 0.8}}
    flat = snap.flatten(data)
    assert snap.is_empty(snap.diff(flat, flat))


def test_format_diff_emits_one_line_per_change() -> None:
    d = {
        "added": {"new_key": 42},
        "removed": {"gone": "bye"},
        "changed": {"val": (0.8, 0.3)},
    }
    out = snap.format_diff(d)
    assert "+ new_key = 42" in out
    assert '- gone = "bye"' in out
    assert "~ val: 0.8 -> 0.3" in out


def test_format_diff_empty_when_no_drift() -> None:
    d = {"added": {}, "removed": {}, "changed": {}}
    assert snap.format_diff(d) == ""


# --- Snapshot file roundtrip -----------------------------------------------


def test_save_and_load_roundtrip(tmp_path) -> None:
    path = tmp_path / "snap.json"
    config = {"_class_defaults": {"geo": {}}, "kinds": {"rock": {"class": "geo"}}}
    snap.save_snapshot(config, path)
    loaded = snap.load_snapshot(path)
    assert loaded == config


def test_load_snapshot_raises_when_missing(tmp_path) -> None:
    with pytest.raises(snap.SnapshotMissing):
        snap.load_snapshot(tmp_path / "nope.json")


def test_matches_snapshot_true_on_identical(tmp_path) -> None:
    path = tmp_path / "snap.json"
    config = {"kinds": {"x": {"class": "c"}}}
    snap.save_snapshot(config, path)
    assert snap.matches_snapshot(config, path)


def test_matches_snapshot_false_on_drift(tmp_path) -> None:
    path = tmp_path / "snap.json"
    snap.save_snapshot({"kinds": {"x": {"class": "c"}}}, path)
    drifted = {"kinds": {"x": {"class": "c"}, "y": {"class": "c"}}}
    assert not snap.matches_snapshot(drifted, path)


def test_matches_snapshot_false_when_file_missing(tmp_path) -> None:
    assert not snap.matches_snapshot({"k": 1}, tmp_path / "nope.json")


def test_diff_against_snapshot_surfaces_value_change(tmp_path) -> None:
    path = tmp_path / "snap.json"
    snap.save_snapshot(
        {"kinds": {"rat": {"physics": {"collision_radius": 0.8}}}},
        path,
    )
    drifted = {"kinds": {"rat": {"physics": {"collision_radius": 0.3}}}}
    d = snap.diff_against_snapshot(drifted, path)
    assert d["changed"] == {"kinds.rat.physics.collision_radius": (0.8, 0.3)}


# --- Live snapshot guard ----------------------------------------------------


def test_shipped_snapshot_matches_shipped_config() -> None:
    """Committed snapshot must match committed config — clean default state."""
    assert snap.matches_snapshot(), (
        "config/kind_config.snapshot.json is out of sync with "
        "config/kind_config.json. Run "
        "`python scripts/snapshot_kind_config.py --update` to acknowledge "
        "the drift, then commit both files together."
    )
