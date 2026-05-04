"""Make-brain registry — register / get / dispatch contract tests.

T2 of `feat_make-brain-ping-pong` PR 1. Pins the contract of the
universal instance registry that every make-brain plugs into.
"""
from __future__ import annotations

import pytest

from core.systems import make_brain_registry as reg


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test starts with an empty registry."""
    reg._reset_for_tests()
    yield
    reg._reset_for_tests()


class _StubHandler:
    """Tiny fake handler with a couple of methods to dispatch into."""
    def __init__(self):
        self.calls = []

    def on_command(self, *args, **kwargs):
        self.calls.append(("on_command", args, kwargs))
        return {"ok": True}

    def tick(self, *args, **kwargs):
        self.calls.append(("tick", args, kwargs))
        return None


def _valid_kwargs(**overrides):
    base = dict(
        instance_id       = "ping_pong",
        entry_point       = "biome:volley_chamber",
        default_profile   = "vanilla",
        state_event_types = [
            "make_brain_started", "make_brain_ended",
            "profile_loaded", "peak_recorded",
        ],
        handler           = _StubHandler(),
    )
    base.update(overrides)
    return base


# ── register() happy path ─────────────────────────────────────────────


def test_register_returns_spec_with_normalized_fields():
    spec = reg.register(**_valid_kwargs(
        instance_id="  ping_pong  ",
        entry_point="biome:volley_chamber",
    ))
    assert spec.instance_id == "ping_pong"            # whitespace stripped
    assert spec.entry_point == "biome:volley_chamber"
    assert spec.default_profile == "vanilla"
    assert "make_brain_started" in spec.state_event_types
    assert isinstance(spec.state_event_types, tuple)  # frozen


def test_register_then_get_round_trips():
    h = _StubHandler()
    reg.register(**_valid_kwargs(handler=h))
    assert reg.get("ping_pong").handler is h


def test_list_instances_sorted():
    reg.register(**_valid_kwargs(instance_id="ping_pong"))
    reg.register(**_valid_kwargs(instance_id="archery"))
    reg.register(**_valid_kwargs(instance_id="reflective"))
    assert reg.list_instances() == ["archery", "ping_pong", "reflective"]


def test_unregister_removes_instance():
    reg.register(**_valid_kwargs())
    assert reg.unregister("ping_pong") is True
    assert reg.unregister("ping_pong") is False
    with pytest.raises(LookupError):
        reg.get("ping_pong")


# ── register() validation errors ──────────────────────────────────────


def test_register_blank_instance_id_raises():
    with pytest.raises(ValueError, match="instance_id"):
        reg.register(**_valid_kwargs(instance_id=""))
    with pytest.raises(ValueError, match="instance_id"):
        reg.register(**_valid_kwargs(instance_id="   "))


def test_register_blank_entry_point_raises():
    with pytest.raises(ValueError, match="entry_point"):
        reg.register(**_valid_kwargs(entry_point=""))


def test_register_blank_default_profile_raises():
    with pytest.raises(ValueError, match="default_profile"):
        reg.register(**_valid_kwargs(default_profile=""))


def test_register_empty_state_event_types_raises():
    with pytest.raises(ValueError, match="state_event_types"):
        reg.register(**_valid_kwargs(state_event_types=[]))


def test_register_blank_state_event_type_raises():
    with pytest.raises(ValueError, match="state_event_types"):
        reg.register(**_valid_kwargs(
            state_event_types=["make_brain_started", "  "]
        ))


def test_register_duplicate_instance_id_raises():
    reg.register(**_valid_kwargs())
    with pytest.raises(ValueError, match="already registered"):
        reg.register(**_valid_kwargs())


# ── get() / dispatch() error paths ────────────────────────────────────


def test_get_unknown_instance_raises_lookup():
    with pytest.raises(LookupError):
        reg.get("ghost")


def test_dispatch_unknown_instance_raises_lookup():
    with pytest.raises(LookupError):
        reg.dispatch("ghost", "on_command", payload={})


def test_dispatch_unknown_method_raises_attribute():
    reg.register(**_valid_kwargs())
    with pytest.raises(AttributeError, match="not_a_method"):
        reg.dispatch("ping_pong", "not_a_method")


# ── dispatch() happy path ─────────────────────────────────────────────


def test_dispatch_routes_to_handler_method_with_args():
    handler = _StubHandler()
    reg.register(**_valid_kwargs(handler=handler))
    out = reg.dispatch(
        "ping_pong", "on_command", {"foo": 1}, kw="bar",
    )
    assert out == {"ok": True}
    assert len(handler.calls) == 1
    method, args, kwargs = handler.calls[0]
    assert method == "on_command"
    assert args == ({"foo": 1},)
    assert kwargs == {"kw": "bar"}


def test_two_instances_dispatch_independently():
    h1 = _StubHandler()
    h2 = _StubHandler()
    reg.register(**_valid_kwargs(instance_id="ping_pong", handler=h1))
    reg.register(**_valid_kwargs(instance_id="archery", handler=h2))
    reg.dispatch("ping_pong", "tick", 0.016)
    reg.dispatch("archery", "tick", 0.032)
    assert h1.calls == [("tick", (0.016,), {})]
    assert h2.calls == [("tick", (0.032,), {})]
