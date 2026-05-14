"""thing_library + Blender thing-arm — tag-based query for synthesis.

Proves the new pick_thing / things_for_biome surface returns the
right things for the right queries, against a small synthetic
library tree.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.systems import thing_library
from core.systems.blender import default_blender


@pytest.fixture(autouse=True)
def synth_library(tmp_path: Path, monkeypatch):
    """Each test gets a fresh library tree via SANCTUM_THINGS_DIR."""
    things_dir = tmp_path / "things"
    things_dir.mkdir()
    monkeypatch.setenv("SANCTUM_THINGS_DIR", str(things_dir))
    yield things_dir


def _write_thing(dir_path: Path, name: str, tags: list[str]) -> None:
    (dir_path / f"{name}.json").write_text(json.dumps({
        "name":         name,
        "real_size_m":  [0.5, 0.5, 1.0],
        "anchor":       "core",
        "tags":         tags,
        "parts": [
            {
                "primitive": "tapered_vertical",
                "role":      "core",
                "rel_size":  [0.5, 0.5, 1.0],
                "rel_position": [0.0, 0.0, 0.0],
                "tier":      "silhouette",
            },
        ],
    }))


# ── thing_library listing + tag query ───────────────────────────


def test_list_names_empty(synth_library):
    assert thing_library.list_names() == []


def test_list_names_sorted(synth_library):
    _write_thing(synth_library, "zebra", [])
    _write_thing(synth_library, "apple", [])
    _write_thing(synth_library, "mango", [])
    assert thing_library.list_names() == ["apple", "mango", "zebra"]


def test_get_returns_thing(synth_library):
    _write_thing(synth_library, "scarecrow", ["outdoor", "decorative"])
    t = thing_library.get("scarecrow")
    assert t is not None
    assert t.name == "scarecrow"
    assert set(t.tags) == {"outdoor", "decorative"}


def test_get_unknown_returns_none(synth_library):
    assert thing_library.get("nobody") is None


def test_find_by_tags_any_match(synth_library):
    _write_thing(synth_library, "longsword", ["weapon", "blade", "medieval"])
    _write_thing(synth_library, "fence",     ["fixture", "outdoor"])
    _write_thing(synth_library, "skull",     ["prop", "decorative"])
    matches = thing_library.find_by_tags(include=["weapon"])
    names = sorted(t.name for t in matches)
    assert names == ["longsword"]


def test_find_by_tags_any_match_multiple(synth_library):
    _write_thing(synth_library, "longsword", ["weapon", "blade", "medieval"])
    _write_thing(synth_library, "fence",     ["fixture", "outdoor"])
    _write_thing(synth_library, "skull",     ["prop", "decorative"])
    matches = thing_library.find_by_tags(include=["weapon", "fixture"])
    names = sorted(t.name for t in matches)
    assert names == ["fence", "longsword"]


def test_find_by_tags_match_all_strict(synth_library):
    _write_thing(synth_library, "longsword", ["weapon", "blade", "tolkien"])
    _write_thing(synth_library, "rapier",    ["weapon", "blade", "carcosa"])
    _write_thing(synth_library, "fence",     ["fixture", "outdoor"])
    # match_all: must have BOTH 'weapon' AND 'tolkien'
    matches = thing_library.find_by_tags(
        include=["weapon", "tolkien"], match_all=True)
    names = sorted(t.name for t in matches)
    assert names == ["longsword"]


def test_find_by_tags_exclude(synth_library):
    _write_thing(synth_library, "longsword", ["weapon", "blade", "medieval"])
    _write_thing(synth_library, "fence",     ["fixture", "outdoor"])
    _write_thing(synth_library, "skull",     ["prop", "decorative", "carcosa"])
    matches = thing_library.find_by_tags(
        include=None, exclude=["carcosa"])
    names = sorted(t.name for t in matches)
    assert names == ["fence", "longsword"]    # skull excluded


def test_find_by_tags_no_filter_returns_all(synth_library):
    _write_thing(synth_library, "a", [])
    _write_thing(synth_library, "b", ["x"])
    matches = thing_library.find_by_tags()
    assert {t.name for t in matches} == {"a", "b"}


def test_all_tags_counts(synth_library):
    _write_thing(synth_library, "a", ["x", "y"])
    _write_thing(synth_library, "b", ["x"])
    _write_thing(synth_library, "c", [])
    counts = thing_library.all_tags()
    assert counts["x"] == 2
    assert counts["y"] == 1


def test_stats(synth_library):
    _write_thing(synth_library, "a", ["x"])
    _write_thing(synth_library, "b", ["y", "z"])
    _write_thing(synth_library, "c", [])
    s = thing_library.stats()
    assert s["total"] == 3
    assert s["tagged"] == 2
    assert s["untagged"] == 1
    assert s["unique_tags"] == 3


# ── Blender thing-arm ───────────────────────────────────────────


def test_pick_thing_returns_one(synth_library):
    _write_thing(synth_library, "longsword", ["weapon", "blade"])
    _write_thing(synth_library, "fence",     ["fixture"])
    b = default_blender()
    picked = b.pick_thing(include_tags=["weapon"], seed=42)
    assert picked is not None
    assert picked.name == "longsword"


def test_pick_thing_no_match_returns_none(synth_library):
    _write_thing(synth_library, "fence", ["fixture"])
    b = default_blender()
    picked = b.pick_thing(include_tags=["nonexistent_tag"])
    assert picked is None


def test_pick_thing_deterministic_with_seed(synth_library):
    _write_thing(synth_library, "a", ["weapon"])
    _write_thing(synth_library, "b", ["weapon"])
    _write_thing(synth_library, "c", ["weapon"])
    b = default_blender()
    pick1 = b.pick_thing(include_tags=["weapon"], seed=7)
    pick2 = b.pick_thing(include_tags=["weapon"], seed=7)
    assert pick1.name == pick2.name


def test_pick_thing_can_vary_across_seeds(synth_library):
    """With multiple candidates and different seeds, different picks
    SHOULD be possible (statistical, but with 10 seeds × 5 names it
    should hit at least 2 distinct picks)."""
    for n in ("a", "b", "c", "d", "e"):
        _write_thing(synth_library, n, ["weapon"])
    b = default_blender()
    picks = {b.pick_thing(include_tags=["weapon"], seed=s).name
             for s in range(20)}
    assert len(picks) >= 2


def test_things_for_biome_cavern_picks_carcosa_or_tolkien(synth_library):
    _write_thing(synth_library, "skull",   ["prop", "carcosa"])
    _write_thing(synth_library, "shield",  ["fixture", "tolkien"])
    _write_thing(synth_library, "fence",   ["fixture", "outdoor"])  # not in cavern tags
    b = default_blender()
    things = b.things_for_biome("cavern", count=5, seed=1)
    names = {t.name for t in things}
    # Both carcosa + tolkien match cavern; fence doesn't
    assert "fence" not in names
    assert names <= {"skull", "shield"}


def test_things_for_biome_respects_count_cap(synth_library):
    for i in range(10):
        _write_thing(synth_library, f"prop_{i}", ["decorative"])
    b = default_blender()
    things = b.things_for_biome("workroom", count=3, seed=1)
    assert len(things) == 3


def test_things_for_biome_empty_when_no_library(synth_library):
    b = default_blender()
    things = b.things_for_biome("cavern", count=3)
    assert things == []
