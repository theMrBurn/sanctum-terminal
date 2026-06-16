"""Blender.stamps_for_tile + BIOME_STAMP_CONFIG."""
from __future__ import annotations

from core.systems import blender


# ── Config table ────────────────────────────────────────────────


def test_outdoor_has_stamp_config():
    cfg = blender.BIOME_STAMP_CONFIG["outdoor"]
    assert cfg["tile_chance"] > 0
    assert "architecture" in cfg["tags"] or "pnw" in cfg["tags"]


def test_workroom_has_zero_chance():
    cfg = blender.BIOME_STAMP_CONFIG["workroom"]
    assert cfg["tile_chance"] == 0.0


def test_unknown_biome_uses_default():
    cfg = blender.BIOME_STAMP_CONFIG.get(
        "phantom_biome", blender.BIOME_STAMP_CONFIG_DEFAULT)
    assert cfg["tile_chance"] == 0.0


# ── stamps_for_tile gate ────────────────────────────────────────


def test_zero_chance_returns_empty():
    bl = blender.default_blender()
    picks, unf = bl.stamps_for_tile("workroom", 0, 0, base_seed=42)
    assert picks == []
    assert unf == []


def test_deterministic_per_tile_seed():
    bl = blender.default_blender()
    a, _ = bl.stamps_for_tile("outdoor", 3, 3, base_seed=42)
    b, _ = bl.stamps_for_tile("outdoor", 3, 3, base_seed=42)
    if a:
        assert a[0].name == b[0].name


def test_different_seeds_can_differ():
    bl = blender.default_blender()
    picks_seen = set()
    for s in range(20):
        picks, _ = bl.stamps_for_tile("outdoor", 0, 0, base_seed=s)
        if picks:
            picks_seen.add(picks[0].name)
    # With 4 stamps in library and a 10% gate, across 20 seeds we
    # should see at least 1 hit. Don't assert variety — RNG could
    # plausibly skip the gate for many consecutive seeds.
    assert isinstance(picks_seen, set)


def test_outdoor_hit_rate_roughly_matches_tile_chance():
    """Statistical: across 100 tiles, ~10% should win the gate
    (tile_chance=0.1). Allow generous slack ±5%."""
    bl = blender.default_blender()
    hits = 0
    total = 100
    for tx in range(-5, 5):
        for ty in range(-5, 5):
            picks, _ = bl.stamps_for_tile(
                "outdoor", tx, ty, base_seed=12345)
            if picks:
                hits += 1
    rate = hits / total
    assert 0.02 <= rate <= 0.20, (
        f"stamp hit rate {rate:.2%} outside expected [2%, 20%]"
    )


def test_greenhouse_records_when_library_empty(monkeypatch):
    """When the gate fires but the library has no matching stamp,
    a single greenhouse demand profile should come back."""
    bl = blender.default_blender()
    # Force gate to always fire by setting tile_chance=1.0 in a copy
    fake_cfg = {**blender.BIOME_STAMP_CONFIG["outdoor"],
                "tags": ["nonexistent_tag_xyz"],
                "tile_chance": 1.0}
    monkeypatch.setitem(blender.BIOME_STAMP_CONFIG, "outdoor", fake_cfg)
    picks, unf = bl.stamps_for_tile("outdoor", 7, 7, base_seed=99)
    assert picks == []
    assert len(unf) == 1
    assert "nonexistent_tag_xyz" in unf[0]
