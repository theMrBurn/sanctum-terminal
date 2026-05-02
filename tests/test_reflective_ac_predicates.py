"""AC predicate substrate — registry + min_magnet_count built-in.

Step 1 of PR 3.5 per the feature file. Substrate alone — no rules
loaded yet, no state machine wiring, no brain integration.

Validates:
- ReflectiveState dataclass shape + defaults
- AC predicate registry pattern (register/get/clear/duplicate-rejection)
- `min_magnet_count` built-in over the count-vs-composed contract
- register_builtins() restores defaults after fixture teardown
"""
from __future__ import annotations

import pytest

from core.systems.reflective import ReflectiveState
from core.systems.reflective import ac_predicates as ac_module


@pytest.fixture
def clean():
    """Fresh registry per test. Teardown restores built-ins so tests
    not using this fixture still see them."""
    ac_module.clear()
    yield
    ac_module.clear()
    ac_module.register_builtins()


# ── ReflectiveState dataclass ────────────────────────────────────


def test_reflective_state_default_inactive():
    s = ReflectiveState()
    assert s.active is False
    assert s.trigger == ""
    assert s.current_rule_id == ""
    assert s.rule_args == {}
    assert s.magnet_pool == []
    assert s.composed == []
    assert s.attempt_count == 0


def test_reflective_state_composed_is_mutable_list():
    """ReflectiveState is a regular dataclass, not frozen — composed
    list mutates in place during play."""
    s = ReflectiveState()
    s.composed.append("river")
    s.composed.append("moss")
    assert s.composed == ["river", "moss"]


def test_reflective_state_independent_default_lists():
    """Default-factory fields produce distinct lists per instance —
    classic Python mutable-default trap is avoided."""
    a = ReflectiveState()
    b = ReflectiveState()
    a.composed.append("x")
    assert b.composed == []


def test_reflective_state_trigger_round_trip():
    s = ReflectiveState(trigger="hp_zero")
    assert s.trigger == "hp_zero"
    s.trigger = "voluntary"
    assert s.trigger == "voluntary"


# ── Registry ──────────────────────────────────────────────────────


def test_register_and_get(clean):
    @ac_module.register("always_true")
    def _at(world, args, state):
        return True

    assert ac_module.get("always_true") is _at


def test_register_rejects_duplicate(clean):
    @ac_module.register("once")
    def _o(world, args, state):
        return True

    with pytest.raises(ValueError, match="already registered"):
        @ac_module.register("once")
        def _o2(world, args, state):
            return True


def test_unknown_predicate_returns_none(clean):
    assert ac_module.get("does_not_exist") is None


def test_all_predicates_returns_snapshot(clean):
    @ac_module.register("p1")
    def _p1(world, args, state):
        return True

    @ac_module.register("p2")
    def _p2(world, args, state):
        return False

    snap = ac_module.all_predicates()
    assert "p1" in snap and "p2" in snap
    snap.clear()
    assert ac_module.get("p1") is not None  # registry untouched


# ── Built-in: min_magnet_count ────────────────────────────────────


def test_min_magnet_count_below_threshold():
    fn = ac_module.get("min_magnet_count")
    assert fn is not None
    state = ReflectiveState(composed=["the", "river"])
    assert fn(None, {"count": 3}, state) is False


def test_min_magnet_count_at_threshold():
    fn = ac_module.get("min_magnet_count")
    state = ReflectiveState(composed=["the", "river", "moss"])
    assert fn(None, {"count": 3}, state) is True


def test_min_magnet_count_above_threshold():
    fn = ac_module.get("min_magnet_count")
    state = ReflectiveState(composed=["the", "river", "moss", "breath"])
    assert fn(None, {"count": 3}, state) is True


def test_min_magnet_count_default_count_is_three():
    fn = ac_module.get("min_magnet_count")

    state = ReflectiveState(composed=["a", "b", "c"])
    assert fn(None, {}, state) is True

    state = ReflectiveState(composed=["a", "b"])
    assert fn(None, {}, state) is False


def test_min_magnet_count_empty_composition():
    fn = ac_module.get("min_magnet_count")
    state = ReflectiveState(composed=[])
    assert fn(None, {"count": 1}, state) is False


def test_min_magnet_count_count_zero_always_passes():
    """Edge case — a rule with count=0 means 'commit anything'.
    Useful for free-compose modes where the player decides when done."""
    fn = ac_module.get("min_magnet_count")
    state = ReflectiveState(composed=[])
    assert fn(None, {"count": 0}, state) is True


# ── Builtins survive clean teardown ───────────────────────────────


def test_builtins_present_on_module_import():
    """Without using the `clean` fixture, the built-in must always be
    there — module import auto-registers."""
    assert ac_module.get("min_magnet_count") is not None


def test_clean_fixture_restores_builtins(clean):
    """After this test using clean, builtins should be restored in
    teardown so other tests see them."""
    # Inside the fixture: registry is empty.
    assert ac_module.get("min_magnet_count") is None
    # Teardown will re-register.
