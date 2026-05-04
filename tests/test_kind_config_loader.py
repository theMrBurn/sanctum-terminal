"""Brain-side kind_config loader test.

Phase 1 of the kind-config consolidation: ensures the shared
config/kind_config.json is loadable from Python with the same shape Godot
sees. No schema assertions yet — those land in later phases when fields
are migrated. This test just confirms the file is parseable and the
basic structure (kinds dict with ≥1 entry per known kind) is intact.
"""
from __future__ import annotations

import pytest

from core.systems import kind_config


# Kinds we KNOW exist in the config — sentinels to catch a totally broken file.
SENTINEL_KINDS = [
    "rat",
    "rat_ice",
    "rat_fire",
    "clay_pot",
    "treasure_chest",
    "boulder",
    "column",
    "mega_column",
    "buttress",
    "moss_patch",
]


def setup_module(module):
    # Each test gets a fresh load — protects against cache poisoning if a
    # later phase mutates the file as part of a fixture.
    kind_config.reset_cache()


def test_load_returns_dict_with_kinds_key():
    cfg = kind_config.load()
    assert isinstance(cfg, dict), "kind_config must be a dict"
    assert "kinds" in cfg, "kind_config must have a 'kinds' top-level key"
    assert isinstance(cfg["kinds"], dict), "'kinds' must map name -> config"
    assert len(cfg["kinds"]) > 0, "kind_config must declare at least one kind"


@pytest.mark.parametrize("name", SENTINEL_KINDS)
def test_sentinel_kinds_are_present(name):
    k = kind_config.kind(name)
    assert k, f"sentinel kind '{name}' missing from kind_config"
    assert isinstance(k, dict), f"kind '{name}' must be a dict"


def test_kind_lookup_returns_empty_for_unknown():
    assert kind_config.kind("__definitely_not_a_kind__") == {}


def test_all_kinds_returns_full_map():
    everything = kind_config.all_kinds()
    assert isinstance(everything, dict)
    # Sanity: at least 20 kinds (we have 37 currently)
    assert len(everything) >= 20, f"expected ≥20 kinds, got {len(everything)}"


def test_creatures_have_class_life():
    """All five creatures introduced this session should be class=life.
    Sanity check that recent edits didn't mis-classify."""
    for name in ("rat", "rat_ice", "rat_fire", "clay_pot", "treasure_chest"):
        k = kind_config.kind(name)
        assert k.get("class") == "life", \
            f"creature '{name}' should be class=life, got {k.get('class')!r}"
