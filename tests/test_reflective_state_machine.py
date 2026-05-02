"""Reflective-mode state machine — pure operations on world.reflective.

Step 4 of PR 3.5. Validates enter/place/remove/commit/exit/pick_rule
in isolation. Game state transitions live with the callers (consequence
effect, brain cmd handler) and are not part of these tests.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

import pytest

from core.systems.reflective import (
    ReflectiveState,
    ac_predicates,
    magnets,
    rules,
    state_machine,
)
from core.systems.reflective.magnets import PoolConfig
from core.systems.reflective.rules import Rule


@dataclass
class _FakeWorld:
    reflective: ReflectiveState = field(default_factory=ReflectiveState)


@pytest.fixture
def stage():
    """Set up clean rules + magnets pool for predictable tests.
    Restores defaults in teardown."""
    saved_pool = magnets.get_pool_config()
    rules.clear()
    rules.register(Rule(
        id="compose_three",
        name="Compose",
        instructions="Place three magnets.",
        ac_predicates=["min_magnet_count"],
        ac_args={"min_magnet_count": {"count": 3}},
    ))
    magnets.set_pool_config(PoolConfig(
        connectives=("the", "a", "and"),
        thematic=("river", "moss", "stone", "bone"),
        wildcards=("unmade",),
    ))
    yield
    rules.clear()
    from core.systems.reflective import definitions
    definitions.load_rules_from_json()
    magnets.set_pool_config(saved_pool)


# ── enter ─────────────────────────────────────────────────────────


def test_enter_populates_reflective_state(stage):
    world = _FakeWorld()
    rng = random.Random(0)
    ok = state_machine.enter(world, trigger="hp_zero", rng=rng)
    assert ok is True
    assert world.reflective.active is True
    assert world.reflective.trigger == "hp_zero"
    assert world.reflective.current_rule_id == "compose_three"
    assert world.reflective.rule_args == {"min_magnet_count": {"count": 3}}
    assert world.reflective.composed == []
    assert world.reflective.attempt_count == 0
    # Pool: 3 connectives + 4 thematic (sampled with default count=12, capped) + 1 wildcard
    assert len(world.reflective.magnet_pool) == 8
    assert "the" in world.reflective.magnet_pool


def test_enter_returns_false_when_no_rules(stage):
    rules.clear()
    world = _FakeWorld()
    ok = state_machine.enter(world, trigger="voluntary", rng=random.Random(0))
    assert ok is False
    assert world.reflective.active is False


def test_enter_resets_previous_state(stage):
    """Enter should overwrite — previous attempt_count and composed
    don't leak between sessions."""
    world = _FakeWorld()
    world.reflective = ReflectiveState(
        active=True,
        trigger="voluntary",
        composed=["leftover"],
        attempt_count=99,
    )
    state_machine.enter(world, trigger="hp_zero", rng=random.Random(0))
    assert world.reflective.composed == []
    assert world.reflective.attempt_count == 0


def test_enter_voluntary_trigger(stage):
    world = _FakeWorld()
    state_machine.enter(world, trigger="voluntary", rng=random.Random(0))
    assert world.reflective.trigger == "voluntary"


# ── place_magnet ──────────────────────────────────────────────────


def test_place_magnet_appends_to_composed(stage):
    world = _FakeWorld()
    state_machine.enter(world, "voluntary", random.Random(0))
    placed = state_machine.place_magnet(world, "the")
    assert placed is True
    assert world.reflective.composed == ["the"]


def test_place_magnet_rejects_unknown_word(stage):
    world = _FakeWorld()
    state_machine.enter(world, "voluntary", random.Random(0))
    placed = state_machine.place_magnet(world, "completely_unknown_word")
    assert placed is False
    assert world.reflective.composed == []


def test_place_magnet_allows_duplicates(stage):
    """V1: no scarcity. The same pool word can be placed multiple times."""
    world = _FakeWorld()
    state_machine.enter(world, "voluntary", random.Random(0))
    state_machine.place_magnet(world, "the")
    state_machine.place_magnet(world, "the")
    state_machine.place_magnet(world, "the")
    assert world.reflective.composed == ["the", "the", "the"]


def test_place_magnet_no_op_when_inactive(stage):
    """Placing magnets while not in reflective mode is rejected."""
    world = _FakeWorld()
    placed = state_machine.place_magnet(world, "the")
    assert placed is False


# ── remove_magnet ────────────────────────────────────────────────


def test_remove_magnet_by_index(stage):
    world = _FakeWorld()
    state_machine.enter(world, "voluntary", random.Random(0))
    state_machine.place_magnet(world, "the")
    state_machine.place_magnet(world, "a")
    state_machine.place_magnet(world, "and")

    removed = state_machine.remove_magnet(world, 1)
    assert removed is True
    assert world.reflective.composed == ["the", "and"]


def test_remove_magnet_invalid_index(stage):
    world = _FakeWorld()
    state_machine.enter(world, "voluntary", random.Random(0))
    state_machine.place_magnet(world, "the")
    assert state_machine.remove_magnet(world, 99) is False
    assert state_machine.remove_magnet(world, -1) is False
    assert world.reflective.composed == ["the"]


def test_remove_magnet_no_op_when_inactive(stage):
    world = _FakeWorld()
    assert state_machine.remove_magnet(world, 0) is False


# ── commit ────────────────────────────────────────────────────────


def test_commit_succeeds_when_ac_satisfied(stage):
    world = _FakeWorld()
    state_machine.enter(world, "hp_zero", random.Random(0))
    for w in ("the", "a", "and"):
        state_machine.place_magnet(world, w)

    assert state_machine.commit(world) is True
    assert world.reflective.attempt_count == 1


def test_commit_fails_below_threshold(stage):
    world = _FakeWorld()
    state_machine.enter(world, "voluntary", random.Random(0))
    state_machine.place_magnet(world, "the")
    state_machine.place_magnet(world, "a")
    # Only 2 magnets — threshold is 3.
    assert state_machine.commit(world) is False
    assert world.reflective.attempt_count == 1


def test_commit_increments_attempt_count_per_call(stage):
    world = _FakeWorld()
    state_machine.enter(world, "voluntary", random.Random(0))
    state_machine.place_magnet(world, "the")
    state_machine.commit(world)  # fail, attempt 1
    state_machine.commit(world)  # fail, attempt 2
    assert world.reflective.attempt_count == 2


def test_commit_no_op_when_inactive(stage):
    world = _FakeWorld()
    assert state_machine.commit(world) is False


def test_commit_fails_on_typo_predicate(stage):
    """A rule referencing an unknown AC predicate fails-safe (denies commit)."""
    rules.clear()
    rules.register(Rule(
        id="bad_rule",
        name="Bad",
        instructions="…",
        ac_predicates=["does_not_exist"],
    ))
    world = _FakeWorld()
    state_machine.enter(world, "voluntary", random.Random(0))
    assert state_machine.commit(world) is False


# ── exit ──────────────────────────────────────────────────────────


def test_exit_resets_state(stage):
    world = _FakeWorld()
    state_machine.enter(world, "hp_zero", random.Random(0))
    state_machine.place_magnet(world, "the")
    state_machine.place_magnet(world, "a")

    state_machine.exit(world)

    assert world.reflective.active is False
    assert world.reflective.trigger == ""
    assert world.reflective.current_rule_id == ""
    assert world.reflective.rule_args == {}
    assert world.reflective.magnet_pool == []
    assert world.reflective.composed == []
    assert world.reflective.attempt_count == 0


def test_exit_idempotent(stage):
    """Exit on inactive world is a no-op (no exception)."""
    world = _FakeWorld()
    state_machine.exit(world)
    state_machine.exit(world)  # safe to call twice
    assert world.reflective.active is False


# ── pick_rule ─────────────────────────────────────────────────────


def test_pick_rule_returns_known_id(stage):
    rid = state_machine.pick_rule(random.Random(0))
    assert rid == "compose_three"


def test_pick_rule_returns_none_on_empty_registry():
    rules.clear()
    rid = state_machine.pick_rule(random.Random(0))
    assert rid is None
    # Restore for downstream tests.
    from core.systems.reflective import definitions
    definitions.load_rules_from_json()


def test_pick_rule_deterministic_with_seed(stage):
    """Same RNG seed → same pick. Important for replay testing."""
    a = state_machine.pick_rule(random.Random(42))
    b = state_machine.pick_rule(random.Random(42))
    assert a == b


# ── End-to-end: enter → play → commit → exit ──────────────────────


def test_full_cycle_succeeds(stage):
    world = _FakeWorld()
    state_machine.enter(world, "hp_zero", random.Random(0))

    state_machine.place_magnet(world, "the")
    state_machine.place_magnet(world, "river")  # might or might not be in pool depending on RNG
    state_machine.place_magnet(world, "and")
    # Maybe one of those was rejected. Pad with more known-pool words.
    while len(world.reflective.composed) < 3 and world.reflective.magnet_pool:
        # Fall back: pull any pool word.
        for w in world.reflective.magnet_pool:
            state_machine.place_magnet(world, w)
            if len(world.reflective.composed) >= 3:
                break

    assert state_machine.commit(world) is True
    state_machine.exit(world)
    assert world.reflective.active is False
