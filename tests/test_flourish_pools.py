"""FLOURISH_POOLS affinity-schema tests.

Guards the 2026-04-21 migration from list-of-strings to the affinity
recipe schema (pool/weights/spawn_chance/radius_range/max_total) mirrored
from COMPANION_SPAWNS. Also smoke-tests that world_gen.generate_tile()
still produces flourish entities after the schema change.
"""
from __future__ import annotations

from collections import Counter

from core.systems.biome_data import (
    CAVERN_FLOURISH_POOLS,
    OUTDOOR_FLOURISH_POOLS,
)


_REQUIRED_RECIPE_KEYS = ("pool", "spawn_chance", "radius_range", "max_total")
_REQUIRED_POOL_ENTRY_KEYS = ("kind", "weight", "max")


def _assert_recipe_shape(pools: dict, label: str) -> None:
    assert pools, f"{label} is empty"
    for anchor, recipe in pools.items():
        assert isinstance(recipe, dict), f"{label}.{anchor} is not a dict"
        for key in _REQUIRED_RECIPE_KEYS:
            assert key in recipe, f"{label}.{anchor} missing {key!r}"

        assert isinstance(recipe["pool"], list) and recipe["pool"], \
            f"{label}.{anchor}.pool empty or wrong type"
        for i, entry in enumerate(recipe["pool"]):
            for key in _REQUIRED_POOL_ENTRY_KEYS:
                assert key in entry, \
                    f"{label}.{anchor}.pool[{i}] missing {key!r}"
            assert isinstance(entry["kind"], str) and entry["kind"]
            assert entry["weight"] > 0, \
                f"{label}.{anchor}.pool[{i}] has non-positive weight"
            assert entry["max"] >= 1, \
                f"{label}.{anchor}.pool[{i}] has max < 1"

        sc = recipe["spawn_chance"]
        assert 0.0 <= sc <= 1.0, f"{label}.{anchor}.spawn_chance out of range"

        rr = recipe["radius_range"]
        assert isinstance(rr, list) and len(rr) == 2, \
            f"{label}.{anchor}.radius_range must be [near, far]"
        assert rr[0] > 0 and rr[1] >= rr[0], \
            f"{label}.{anchor}.radius_range invalid: {rr}"

        assert recipe["max_total"] >= 1, \
            f"{label}.{anchor}.max_total must be >= 1"


def test_cavern_flourish_pools_recipe_shape() -> None:
    _assert_recipe_shape(CAVERN_FLOURISH_POOLS, "CAVERN_FLOURISH_POOLS")


def test_outdoor_flourish_pools_recipe_shape() -> None:
    _assert_recipe_shape(OUTDOOR_FLOURISH_POOLS, "OUTDOOR_FLOURISH_POOLS")


def test_cavern_pools_cover_primary_anchors() -> None:
    # These anchor kinds must have flourish pools — the live brain expects
    # every major landmark to produce ground-density variation around it.
    expected = {
        "boulder", "mega_column", "column", "buttress",
        "giant_fungus", "dead_log",
    }
    assert expected <= set(CAVERN_FLOURISH_POOLS.keys())


def test_outdoor_pools_cover_primary_anchors() -> None:
    expected = {
        "boulder", "mega_column", "column", "buttress",
        "giant_fungus", "dead_log",
    }
    assert expected <= set(OUTDOOR_FLOURISH_POOLS.keys())


def test_generate_tile_produces_flourish_variety() -> None:
    """Live-path smoke test: generate_tile() returns flourish entities."""
    from core.systems.world_gen import generate_tile

    _, entities = generate_tile(42, "cavern")
    kinds = Counter(e[0] for e in entities if isinstance(e, tuple))
    # Should see at least a handful of flourish kinds across a 288m tile.
    assert kinds.get("moss_patch", 0) > 0
    assert kinds.get("rubble", 0) > 0
    # Not all kinds always appear; guard against total disappearance though.
    assert sum(kinds.values()) > 100, "tile produced almost no entities"


def test_generate_tile_flourish_mix_varies_across_seeds() -> None:
    """Weighted selection should produce non-identical mixes across seeds."""
    from core.systems.world_gen import generate_tile

    signatures = set()
    for seed in (1, 7, 13, 29, 101):
        _, entities = generate_tile(seed, "cavern")
        kinds = Counter(e[0] for e in entities if isinstance(e, tuple))
        sig = (
            kinds.get("moss_patch", 0),
            kinds.get("grass_tuft", 0),
            kinds.get("leaf_pile", 0),
            kinds.get("rubble", 0),
            kinds.get("cave_gravel", 0),
            kinds.get("twig_scatter", 0),
        )
        signatures.add(sig)
    # Expect distinct flourish mixes across ≥5 seeds. If they all collapse
    # to identical counts, the weighted-random path likely regressed.
    assert len(signatures) >= 3, \
        f"Flourish mix isn't varying across seeds: {signatures}"
