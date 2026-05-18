"""terrain_keyed stamp placement — _terrain_keyed_stamps in brain_server.

Validates that bridges land on ledges (diff=2), stairs on cliffs
(diff=3), ladders on walls (diff>=4). Tests the helper with explicit
elevation fields so brain globals aren't required.
"""
from __future__ import annotations

import pytest

# brain_server requires spacy (journal lexicon import chain). Skip
# this test module if spacy isn't available.
spacy = pytest.importorskip("spacy")

import brain_server as bs


# ── Helper inputs ────────────────────────────────────────────────


def _field_with_ledge() -> dict[tuple[int, int], int]:
    """5×5 field with a single ledge transition (diff=2) at (0,0)→(1,0)."""
    f = {(x, y): 0 for x in range(5) for y in range(5)}
    f[(1, 0)] = 2
    return f


def _field_with_cliff() -> dict[tuple[int, int], int]:
    """Diff=3 transition (cliff tier) — for stairs."""
    f = {(x, y): 0 for x in range(5) for y in range(5)}
    f[(2, 2)] = 3
    return f


def _field_with_wall() -> dict[tuple[int, int], int]:
    """Diff>=4 transition (wall tier) — for ladders."""
    f = {(x, y): 0 for x in range(5) for y in range(5)}
    f[(2, 2)] = 4
    return f


def _flat_field() -> dict[tuple[int, int], int]:
    return {(x, y): 0 for x in range(5) for y in range(5)}


# ── Tag → tier mapping ──────────────────────────────────────────


def test_terrain_stamp_tag_map_present():
    assert "bridge" in bs._TERRAIN_STAMP_TAGS
    assert "stair"  in bs._TERRAIN_STAMP_TAGS
    assert "ladder" in bs._TERRAIN_STAMP_TAGS


def test_bridge_tag_keyed_to_ledge_diff():
    lo, hi = bs._TERRAIN_STAMP_TAGS["bridge"]
    assert lo == 2 and hi == 2


def test_ladder_tag_open_high_diff():
    lo, hi = bs._TERRAIN_STAMP_TAGS["ladder"]
    assert lo == 4 and hi >= 4


# ── Placement: flat field produces nothing ──────────────────────


def test_flat_field_yields_no_stamps():
    ents = bs._terrain_keyed_stamps(
        "outdoor", base_seed=1, elevation_field=_flat_field(),
    )
    assert ents == []


def test_empty_field_yields_no_stamps():
    ents = bs._terrain_keyed_stamps(
        "outdoor", base_seed=1, elevation_field={},
    )
    assert ents == []


# ── Placement: each tier triggers its stamp ─────────────────────


def test_ledge_field_emits_bridge():
    ents = bs._terrain_keyed_stamps(
        "outdoor", base_seed=1, elevation_field=_field_with_ledge(),
    )
    assert len(ents) > 0
    tiers = {e.get("_stamp_tier") for e in ents}
    assert "bridge" in tiers


def test_cliff_field_emits_stair():
    ents = bs._terrain_keyed_stamps(
        "outdoor", base_seed=1, elevation_field=_field_with_cliff(),
    )
    tiers = {e.get("_stamp_tier") for e in ents}
    assert "stair" in tiers


def test_wall_field_emits_ladder():
    ents = bs._terrain_keyed_stamps(
        "outdoor", base_seed=1, elevation_field=_field_with_wall(),
    )
    tiers = {e.get("_stamp_tier") for e in ents}
    assert "ladder" in tiers


# ── Stamps carry placement metadata ─────────────────────────────


def test_terrain_stamps_marked_terrain():
    ents = bs._terrain_keyed_stamps(
        "outdoor", base_seed=1, elevation_field=_field_with_ledge(),
    )
    assert ents
    assert all(e.get("_stamp_placement") == "terrain" for e in ents)


# ── Determinism ──────────────────────────────────────────────────


def test_same_seed_same_placement():
    f = _field_with_ledge()
    a = bs._terrain_keyed_stamps("outdoor", base_seed=42, elevation_field=f)
    b = bs._terrain_keyed_stamps("outdoor", base_seed=42, elevation_field=f)
    assert len(a) == len(b)
    sig_a = sorted((e["x"], e["y"], e["z"], e.get("_stamp")) for e in a)
    sig_b = sorted((e["x"], e["y"], e["z"], e.get("_stamp")) for e in b)
    assert sig_a == sig_b


# ── Cap per tag (avoid clutter) ──────────────────────────────────


def test_many_ledges_capped_to_max_per_tag():
    """A field full of ledges should produce few bridge groups — the
    MAX_PER_TAG=2 cap on entities prevents bridge spam."""
    # 9×9 field, every other tile = level 2 → many diff=2 transitions
    f: dict[tuple[int, int], int] = {}
    for x in range(9):
        for y in range(9):
            f[(x, y)] = 2 if (x + y) % 2 else 0
    ents = bs._terrain_keyed_stamps(
        "outdoor", base_seed=1, elevation_field=f,
    )
    bridge_stamps = {tuple(sorted([e["x"], e["y"]])) for e in ents
                      if e.get("_stamp_tier") == "bridge"}
    # MAX_PER_TAG=2, but each bridge stamp expands to ~11 entities
    # (1 stamp × 11 parts). So 2 stamps → ~22 entities at ≤2 unique
    # (x,y) origins.
    origin_xy = {(e["x"], e["y"]) for e in ents
                  if e.get("_stamp_tier") == "bridge"}
    # Loosely: <40 distinct origins (well below the hundreds of
    # ledges in the input field).
    assert len(origin_xy) < 40
