"""Magnet pool composition + JSON loader.

Step 3 of PR 3.5. The pool is what magnets the player has on the
fridge per entry. V1 uses authored constants from
`config/reflective/magnets.json`; lexicon sourcing is post-V1
content arc.

Validates:
- PoolConfig dataclass shape
- compose_pool determinism + sampling logic
- JSON loader installs the pool config
- Default config registers connectives + thematic + wildcards on import
"""
from __future__ import annotations

import json
import random

import pytest

from core.systems.reflective import definitions, magnets
from core.systems.reflective.magnets import PoolConfig


@pytest.fixture
def restore_pool():
    """Snapshot pool config; restore after test."""
    original = magnets.get_pool_config()
    yield
    magnets.set_pool_config(original)


# ── PoolConfig dataclass ──────────────────────────────────────────


def test_pool_config_defaults_empty():
    cfg = PoolConfig()
    assert cfg.connectives == ()
    assert cfg.thematic == ()
    assert cfg.wildcards == ()


def test_pool_config_is_frozen():
    cfg = PoolConfig(connectives=("the",))
    with pytest.raises(Exception):  # FrozenInstanceError
        cfg.connectives = ("a",)  # type: ignore[misc]


def test_pool_config_round_trip(restore_pool):
    cfg = PoolConfig(
        connectives=("the", "a"),
        thematic=("river", "moss"),
        wildcards=("unmade",),
    )
    magnets.set_pool_config(cfg)
    assert magnets.get_pool_config() is cfg


# ── compose_pool ──────────────────────────────────────────────────


def test_compose_pool_includes_all_connectives(restore_pool):
    magnets.set_pool_config(PoolConfig(
        connectives=("the", "a", "and"),
        thematic=("river", "moss", "stone", "bone"),
        wildcards=("unmade",),
    ))
    pool = magnets.compose_pool(random.Random(0), thematic_count=2, wildcard_count=1)
    # All connectives present — they're not sampled, always included.
    assert "the" in pool
    assert "a" in pool
    assert "and" in pool


def test_compose_pool_samples_thematic(restore_pool):
    magnets.set_pool_config(PoolConfig(
        connectives=("the",),
        thematic=("river", "moss", "stone", "bone", "ash"),
        wildcards=(),
    ))
    pool = magnets.compose_pool(random.Random(0), thematic_count=3, wildcard_count=0)
    # 1 connective + 3 thematic = 4 magnets total.
    assert len(pool) == 4
    # All thematic samples come from the source pool (no foreign words).
    thematic_in_pool = [w for w in pool if w in {"river", "moss", "stone", "bone", "ash"}]
    assert len(thematic_in_pool) == 3
    # No duplicates from the thematic pool (sampling without replacement).
    assert len(set(thematic_in_pool)) == 3


def test_compose_pool_deterministic_with_same_seed(restore_pool):
    magnets.set_pool_config(PoolConfig(
        connectives=("the",),
        thematic=("river", "moss", "stone", "bone", "ash"),
        wildcards=("unmade", "almost"),
    ))
    a = magnets.compose_pool(random.Random(42), thematic_count=3, wildcard_count=1)
    b = magnets.compose_pool(random.Random(42), thematic_count=3, wildcard_count=1)
    assert a == b


def test_compose_pool_handles_undersized_source(restore_pool):
    """Requesting more samples than the source pool has returns what's available."""
    magnets.set_pool_config(PoolConfig(
        connectives=(),
        thematic=("river", "moss"),
        wildcards=(),
    ))
    pool = magnets.compose_pool(random.Random(0), thematic_count=10, wildcard_count=0)
    assert len(pool) == 2  # only 2 thematic available
    assert set(pool) == {"river", "moss"}


def test_compose_pool_with_empty_config(restore_pool):
    magnets.set_pool_config(PoolConfig())
    pool = magnets.compose_pool(random.Random(0))
    assert pool == []


def test_compose_pool_default_counts(restore_pool):
    """Defaults: 12 thematic + 3 wildcards (per PR 3.5 plan)."""
    magnets.set_pool_config(PoolConfig(
        connectives=tuple(f"c{i}" for i in range(15)),
        thematic=tuple(f"t{i}" for i in range(20)),
        wildcards=tuple(f"w{i}" for i in range(5)),
    ))
    pool = magnets.compose_pool(random.Random(0))
    # 15 connectives + 12 thematic + 3 wildcards = 30
    assert len(pool) == 30


# ── JSON loader ───────────────────────────────────────────────────


def test_load_magnets_from_json(tmp_path, restore_pool):
    config = {
        "schema_version": 1,
        "connectives": ["x", "y"],
        "thematic": ["river", "moss"],
        "wildcards": ["unmade"],
    }
    path = tmp_path / "magnets.json"
    path.write_text(json.dumps(config))

    definitions.load_magnets_from_json(path)

    cfg = magnets.get_pool_config()
    assert cfg.connectives == ("x", "y")
    assert cfg.thematic == ("river", "moss")
    assert cfg.wildcards == ("unmade",)


def test_load_magnets_handles_missing_file(tmp_path, restore_pool):
    """Missing file leaves existing pool config intact."""
    custom = PoolConfig(connectives=("CUSTOM",))
    magnets.set_pool_config(custom)

    bogus = tmp_path / "does_not_exist.json"
    definitions.load_magnets_from_json(bogus)

    assert magnets.get_pool_config() is custom  # unchanged


def test_load_magnets_partial_config(tmp_path, restore_pool):
    """Missing keys default to empty tuples."""
    path = tmp_path / "magnets.json"
    path.write_text(json.dumps({"schema_version": 1, "connectives": ["a"]}))
    definitions.load_magnets_from_json(path)

    cfg = magnets.get_pool_config()
    assert cfg.connectives == ("a",)
    assert cfg.thematic == ()
    assert cfg.wildcards == ()


# ── Default config integrity ──────────────────────────────────────


def test_default_config_loaded_on_import():
    """The shipped magnets.json populates the pool on package import."""
    cfg = magnets.get_pool_config()
    # Authored V1 has at least connectives + some thematic + some wildcards.
    assert len(cfg.connectives) > 0
    assert len(cfg.thematic) > 0
    assert len(cfg.wildcards) > 0


def test_default_config_path_exists():
    from core.systems.reflective.definitions import MAGNETS_PATH
    assert MAGNETS_PATH.exists()
    data = json.loads(MAGNETS_PATH.read_text())
    assert "schema_version" in data
    assert isinstance(data.get("connectives", []), list)
    assert isinstance(data.get("thematic", []), list)
    assert isinstance(data.get("wildcards", []), list)


def test_no_overlap_between_pool_layers():
    """Connectives, thematic, and wildcards should not share words —
    keeps semantics clean (a word is either functional, content, or rare)."""
    cfg = magnets.get_pool_config()
    cset = set(cfg.connectives)
    tset = set(cfg.thematic)
    wset = set(cfg.wildcards)
    assert cset & tset == set(), f"connective/thematic overlap: {cset & tset}"
    assert cset & wset == set(), f"connective/wildcard overlap: {cset & wset}"
    assert tset & wset == set(), f"thematic/wildcard overlap: {tset & wset}"
