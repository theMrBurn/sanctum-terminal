"""Built-in consequence effect handlers — regen_world, restore_hp,
emit_state_event.

Step 3 of PR 3 per the feature file. These are the side-effect
handlers that fire when a consequence resolves. Step 4 wires them
into the brain main loop via a `hp_zero_respawn` config row.

Per `design_death_only_regen` and `design_virtual_hallucination`:
HP=0 is a respawn condition, not a death. The procedural expedition
regenerates; hub, character, quests, and vault persist (the latter
three are handled by other systems — these effects only touch world
tiles/entities/spawns and player HP).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest

from core.systems.consequences import ConsequenceInstance
from core.systems.consequences import effects as effects_module


# ── Test doubles ───────────────────────────────────────────────────


@dataclass
class _FakePlayer:
    """Minimal NamedTuple-shaped player for effect tests. Effects use
    `_replace` so the test double provides one."""
    hp: int = 0
    max_hp: int = 6

    def _replace(self, **kwargs):
        new = _FakePlayer(hp=self.hp, max_hp=self.max_hp)
        for k, v in kwargs.items():
            setattr(new, k, v)
        return new


class _RegenSpy:
    """Records calls to regen_world(new_seed) without mutating world state."""

    def __init__(self):
        self.calls: list[int] = []

    def __call__(self, new_seed: int) -> None:
        self.calls.append(new_seed)


@dataclass
class _StateEventSpy:
    """Records emit() calls. Mirrors StateEventBuffer's signature."""
    emitted: list[dict] = field(default_factory=list)

    def emit(self, kind, label, detail=None, register="system"):
        self.emitted.append({
            "kind": kind,
            "label": label,
            "detail": detail,
            "register": register,
        })


@dataclass
class _FakeWorld:
    player: _FakePlayer = field(default_factory=_FakePlayer)
    regen_world: _RegenSpy = field(default_factory=_RegenSpy)
    state_events: Optional[_StateEventSpy] = field(default_factory=_StateEventSpy)


def _instance() -> ConsequenceInstance:
    return ConsequenceInstance(config_id="test", spawned_tick=0)


# ── regen_world ───────────────────────────────────────────────────


def test_regen_world_random_calls_with_int_seed():
    fn = effects_module.get("regen_world")
    assert fn is not None
    world = _FakeWorld()
    fn(world, {"reseed": "random"}, _instance())
    assert len(world.regen_world.calls) == 1
    assert isinstance(world.regen_world.calls[0], int)
    assert 0 <= world.regen_world.calls[0] <= 2**31 - 1


def test_regen_world_explicit_seed_uses_value():
    fn = effects_module.get("regen_world")
    world = _FakeWorld()
    fn(world, {"reseed": 12345}, _instance())
    assert world.regen_world.calls == [12345]


def test_regen_world_default_is_random():
    """Missing 'reseed' arg defaults to random — same as explicit."""
    fn = effects_module.get("regen_world")
    world = _FakeWorld()
    fn(world, {}, _instance())
    assert len(world.regen_world.calls) == 1
    assert isinstance(world.regen_world.calls[0], int)


# ── restore_hp ────────────────────────────────────────────────────


def test_restore_hp_full_resets_to_max():
    fn = effects_module.get("restore_hp")
    assert fn is not None
    world = _FakeWorld(player=_FakePlayer(hp=0, max_hp=6))
    fn(world, {"to": "full"}, _instance())
    assert world.player.hp == 6
    assert world.player.max_hp == 6


def test_restore_hp_explicit_value():
    fn = effects_module.get("restore_hp")
    world = _FakeWorld(player=_FakePlayer(hp=0, max_hp=6))
    fn(world, {"to": 3}, _instance())
    assert world.player.hp == 3


def test_restore_hp_clamps_to_max():
    """Specifying a value > max_hp clamps to max_hp."""
    fn = effects_module.get("restore_hp")
    world = _FakeWorld(player=_FakePlayer(hp=0, max_hp=6))
    fn(world, {"to": 999}, _instance())
    assert world.player.hp == 6


def test_restore_hp_default_is_full():
    """Missing 'to' arg defaults to full heal."""
    fn = effects_module.get("restore_hp")
    world = _FakeWorld(player=_FakePlayer(hp=0, max_hp=6))
    fn(world, {}, _instance())
    assert world.player.hp == 6


def test_restore_hp_does_not_mutate_other_fields():
    """Effect must use _replace, not in-place mutation."""
    fn = effects_module.get("restore_hp")
    original = _FakePlayer(hp=0, max_hp=10)
    world = _FakeWorld(player=original)
    fn(world, {"to": "full"}, _instance())
    # New instance produced; original unchanged.
    assert original.hp == 0
    assert world.player is not original


# ── emit_state_event ──────────────────────────────────────────────


def test_emit_state_event_basic():
    fn = effects_module.get("emit_state_event")
    assert fn is not None
    world = _FakeWorld()
    fn(world, {
        "kind": "respawn",
        "label": "RESPAWN",
        "detail": "fresh procedural expedition",
        "register": "tense",
    }, _instance())
    assert world.state_events.emitted == [{
        "kind": "respawn",
        "label": "RESPAWN",
        "detail": "fresh procedural expedition",
        "register": "tense",
    }]


def test_emit_state_event_optional_detail():
    fn = effects_module.get("emit_state_event")
    world = _FakeWorld()
    fn(world, {"kind": "x", "label": "X"}, _instance())
    assert world.state_events.emitted[0]["detail"] is None


def test_emit_state_event_default_register_is_system():
    fn = effects_module.get("emit_state_event")
    world = _FakeWorld()
    fn(world, {"kind": "x", "label": "X"}, _instance())
    assert world.state_events.emitted[0]["register"] == "system"


def test_emit_state_event_no_buffer_is_safe():
    """Effect no-ops if world.state_events is missing — defensive for
    minimal test fakes."""
    fn = effects_module.get("emit_state_event")
    world = _FakeWorld()
    world.state_events = None
    # Must not raise.
    fn(world, {"kind": "x", "label": "X"}, _instance())


# ── Builtins survive clean teardown ────────────────────────────────


def test_effect_builtins_present():
    """Module-level register_builtins() runs on import; built-ins
    should always be available unless a test explicitly cleared and
    didn't restore."""
    assert effects_module.get("regen_world") is not None
    assert effects_module.get("restore_hp") is not None
    assert effects_module.get("emit_state_event") is not None


# ── End-to-end: real engine tick with all three effects chained ────


def test_full_chain_via_engine_tick():
    """Trigger fires → resolution runs all three effects in order →
    instance is removed. Mirrors what step 4's hp_zero_respawn config
    will produce when wired into brain."""
    from core.systems.consequences import (
        Consequence,
        Effect,
        clear as clear_registry,
        register,
    )
    from core.systems.consequences import predicates as predicates_module
    from core.systems.consequences import tick as tick_module

    # Snapshot existing registry state to restore later.
    clear_registry()
    predicates_module.clear()
    effects_module.clear()
    predicates_module.register_builtins()  # need hp_zero
    effects_module.register_builtins()      # need built-in effects

    register(Consequence(
        id="hp_zero_chain_test",
        trigger_predicate="hp_zero",
        resolution_predicate=None,  # immediate
        resolution_effects=[
            Effect(name="emit_state_event", args={
                "kind": "respawn",
                "label": "RESPAWN",
                "register": "tense",
            }),
            Effect(name="regen_world", args={"reseed": 42}),
            Effect(name="restore_hp", args={"to": "full"}),
        ],
        one_shot=True,
    ))

    @dataclass
    class _W:
        player: _FakePlayer = field(default_factory=lambda: _FakePlayer(hp=0))
        regen_world: _RegenSpy = field(default_factory=_RegenSpy)
        state_events: _StateEventSpy = field(default_factory=_StateEventSpy)
        consequences: list = field(default_factory=list)
        tick_events: list = field(default_factory=lambda: [{"type": "hp_zero"}])
        tick_count: int = 0
        entities: list = field(default_factory=list)

    world = _W()
    tick_module.tick(world, world.tick_events)

    # All three effects fired in order.
    assert world.regen_world.calls == [42]
    assert world.player.hp == 6
    assert len(world.state_events.emitted) == 1
    assert world.state_events.emitted[0]["kind"] == "respawn"

    # Instance was resolved + removed.
    assert world.consequences == []

    # Cleanup so subsequent tests aren't polluted. Restore both the
    # built-ins AND the JSON-loaded config rows (e.g. hp_zero_respawn)
    # that other test modules expect.
    from core.systems.consequences import definitions as _defs
    clear_registry()
    predicates_module.clear()
    effects_module.clear()
    predicates_module.register_builtins()
    effects_module.register_builtins()
    _defs.load_from_json()
