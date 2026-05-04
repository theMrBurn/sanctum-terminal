"""Quest predicate target-position resolvers (PR 4 step 4b).

Validates the target-resolver registry on `core.systems.quests.predicates`
+ the built-in resolvers for `destroy_kind` and `cast_at_kind`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from core.systems.quests import predicates as predicates_module


@dataclass
class _FakeWorld:
    entities: list = field(default_factory=list)


# ── Registry ──────────────────────────────────────────────────────


def test_destroy_kind_target_registered():
    assert predicates_module.get_target("destroy_kind") is not None


def test_cast_at_kind_target_registered():
    assert predicates_module.get_target("cast_at_kind") is not None


def test_journal_followup_target_not_registered():
    """Predicates without spatial completion don't register a resolver.
    Brain treats missing registration the same as None return."""
    assert predicates_module.get_target("journal_followup") is None


def test_unknown_target_returns_none():
    assert predicates_module.get_target("does_not_exist") is None


def test_register_target_decorator_overwrites():
    """register_target is idempotent (avoids `clean` fixture pain)."""
    @predicates_module.register_target("test_target")
    def _t1(world, args, px, py):
        return (1.0, 1.0)

    # Re-register with a different fn — should silently overwrite.
    @predicates_module.register_target("test_target")
    def _t2(world, args, px, py):
        return (2.0, 2.0)

    fn = predicates_module.get_target("test_target")
    assert fn(None, {}, 0, 0) == (2.0, 2.0)

    # Cleanup so other tests aren't affected.
    predicates_module._TARGETS.pop("test_target", None)


# ── destroy_kind resolver ────────────────────────────────────────


def test_destroy_kind_finds_nearest_entity():
    world = _FakeWorld(entities=[
        {"kind": "clay_pot", "x": 5.0, "y": 0.0},
        {"kind": "clay_pot", "x": 100.0, "y": 0.0},
        {"kind": "clay_pot", "x": -3.0, "y": 0.0},
    ])
    fn = predicates_module.get_target("destroy_kind")
    assert fn(world, {"kind": "clay_pot"}, 0.0, 0.0) == (-3.0, 0.0)


def test_destroy_kind_filters_by_kind():
    """Other kinds are ignored even if closer."""
    world = _FakeWorld(entities=[
        {"kind": "rat", "x": 1.0, "y": 0.0},
        {"kind": "clay_pot", "x": 10.0, "y": 0.0},
    ])
    fn = predicates_module.get_target("destroy_kind")
    assert fn(world, {"kind": "clay_pot"}, 0.0, 0.0) == (10.0, 0.0)


def test_destroy_kind_returns_none_when_no_entities():
    world = _FakeWorld(entities=[])
    fn = predicates_module.get_target("destroy_kind")
    assert fn(world, {"kind": "clay_pot"}, 0.0, 0.0) is None


def test_destroy_kind_returns_none_when_no_matching_kind():
    world = _FakeWorld(entities=[
        {"kind": "rat", "x": 1.0, "y": 1.0},
        {"kind": "leaf", "x": 2.0, "y": 2.0},
    ])
    fn = predicates_module.get_target("destroy_kind")
    assert fn(world, {"kind": "clay_pot"}, 0.0, 0.0) is None


def test_destroy_kind_handles_missing_kind_arg():
    """Empty/missing kind arg is a no-op (returns None)."""
    world = _FakeWorld(entities=[
        {"kind": "clay_pot", "x": 1.0, "y": 0.0},
    ])
    fn = predicates_module.get_target("destroy_kind")
    assert fn(world, {}, 0.0, 0.0) is None
    assert fn(world, {"kind": ""}, 0.0, 0.0) is None


def test_destroy_kind_handles_dict_entities():
    """BrainWorld.entities can be a {id: dict} mapping; resolver
    iterates values transparently."""
    world = _FakeWorld()
    world.entities = {
        100: {"kind": "clay_pot", "x": 5.0, "y": 5.0},
        200: {"kind": "rat", "x": 1.0, "y": 1.0},
    }
    fn = predicates_module.get_target("destroy_kind")
    assert fn(world, {"kind": "clay_pot"}, 0.0, 0.0) == (5.0, 5.0)


def test_destroy_kind_skips_malformed_entries():
    world = _FakeWorld(entities=[
        "not a dict",
        {"kind": "clay_pot", "x": "bad", "y": 0.0},  # x not numeric
        {"kind": "clay_pot", "x": 10.0, "y": 0.0},
    ])
    fn = predicates_module.get_target("destroy_kind")
    assert fn(world, {"kind": "clay_pot"}, 0.0, 0.0) == (10.0, 0.0)


# ── cast_at_kind resolver ─────────────────────────────────────────


def test_cast_at_kind_finds_nearest_entity():
    world = _FakeWorld(entities=[
        {"kind": "spore_pod", "x": 50.0, "y": 0.0},
        {"kind": "spore_pod", "x": -5.0, "y": 0.0},
    ])
    fn = predicates_module.get_target("cast_at_kind")
    assert fn(world, {"kind": "spore_pod"}, 0.0, 0.0) == (-5.0, 0.0)


def test_cast_at_kind_returns_none_when_empty():
    world = _FakeWorld(entities=[])
    fn = predicates_module.get_target("cast_at_kind")
    assert fn(world, {"kind": "spore_pod"}, 0.0, 0.0) is None


# ── Player position drives "nearest" ──────────────────────────────


def test_nearest_changes_with_player_position():
    world = _FakeWorld(entities=[
        {"kind": "clay_pot", "x": 10.0, "y": 0.0},
        {"kind": "clay_pot", "x": -10.0, "y": 0.0},
    ])
    fn = predicates_module.get_target("destroy_kind")
    # Player at (5, 0) is closer to (10, 0).
    assert fn(world, {"kind": "clay_pot"}, 5.0, 0.0) == (10.0, 0.0)
    # Player at (-5, 0) is closer to (-10, 0).
    assert fn(world, {"kind": "clay_pot"}, -5.0, 0.0) == (-10.0, 0.0)
