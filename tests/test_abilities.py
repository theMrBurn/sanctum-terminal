"""Ability library validation — all starter abilities are well-formed."""
from __future__ import annotations

import pytest

from core.systems.abilities import (
    MONK_ABILITIES,
    PHILOSOPHER_ABILITIES,
    ROGUE_ABILITIES,
    abilities_by_kind,
    find_ability,
)


ALL_LIBRARIES = {
    "rogue": ROGUE_ABILITIES,
    "monk": MONK_ABILITIES,
    "philosopher": PHILOSOPHER_ABILITIES,
}

VALID_STATS = {"DEX", "WIS", "INT", "CHA", "STR", "CON"}
VALID_KINDS = {"active", "passive"}


def test_each_class_has_four_abilities():
    for class_name, lib in ALL_LIBRARIES.items():
        assert len(lib) == 4, f"{class_name} has {len(lib)} abilities, expected 4"


def test_class_origin_matches_library():
    for class_name, lib in ALL_LIBRARIES.items():
        for ab in lib:
            assert ab.class_origin == class_name


def test_all_kinds_are_valid():
    for lib in ALL_LIBRARIES.values():
        for ab in lib:
            assert ab.kind in VALID_KINDS


def test_all_stats_are_valid():
    for lib in ALL_LIBRARIES.values():
        for ab in lib:
            assert ab.stat in VALID_STATS


def test_active_abilities_have_no_bonus():
    """Active abilities trigger; they don't passively modify stats."""
    for lib in ALL_LIBRARIES.values():
        for ab in lib:
            if ab.kind == "active":
                assert ab.bonus == {}


def test_passive_abilities_have_no_target_save():
    """Passives are always-on, not triggered against a target."""
    for lib in ALL_LIBRARIES.values():
        for ab in lib:
            if ab.kind == "passive":
                assert ab.target_save is None


def test_each_class_has_two_active_two_passive():
    """Balance directive: half active, half passive per class library."""
    for class_name, lib in ALL_LIBRARIES.items():
        actives = abilities_by_kind(list(lib), "active")
        passives = abilities_by_kind(list(lib), "passive")
        assert len(actives) == 2, f"{class_name}: {len(actives)} actives, expected 2"
        assert len(passives) == 2, f"{class_name}: {len(passives)} passives, expected 2"


def test_find_ability_returns_match():
    pool = list(ROGUE_ABILITIES)
    found = find_ability("Sneak Attack", pool)
    assert found is not None
    assert found.kind == "active"


def test_find_ability_returns_none_for_missing():
    assert find_ability("Nonexistent Power", list(ROGUE_ABILITIES)) is None


def test_no_duplicate_names_across_libraries():
    """Names should be unique across the entire library — they're identifiers."""
    all_names = []
    for lib in ALL_LIBRARIES.values():
        all_names.extend(ab.name for ab in lib)
    assert len(all_names) == len(set(all_names))


def test_descriptions_are_non_empty():
    for lib in ALL_LIBRARIES.values():
        for ab in lib:
            assert ab.description.strip(), f"{ab.name} has empty description"
