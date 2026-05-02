"""Consequences engine substrate — registry, lifecycle, JSON load.

Step 1 of PR 3 per the feature file: substrate alone, no built-in
triggers/effects, no brain wiring. Validates the engine machinery
in isolation. Subsequent steps add `hp_zero` predicate, world regen
effects, and brain main-loop integration.

Per `design_reflective_loop` and `feedback_iterate_then_formalize`,
the engine ships with a context snapshot at spawn so resolution can
branch dynamically without freezing the resolution shape early.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from core.systems.consequences import (
    Consequence,
    ConsequenceInstance,
    Effect,
    all_consequences,
    clear as clear_registry,
    get,
    register,
)
from core.systems.consequences import definitions
from core.systems.consequences import effects as effects_module
from core.systems.consequences import predicates as predicates_module
from core.systems.consequences import tick as tick_module


# ── Fixtures ──────────────────────────────────────────────────────


@dataclass
class FakePlayer:
    hp: int = 100
    x: float = 0.0
    z: float = 0.0


@dataclass
class FakeWorld:
    player: FakePlayer = field(default_factory=FakePlayer)
    entities: list = field(default_factory=list)
    consequences: list = field(default_factory=list)
    tick_events: list = field(default_factory=list)
    tick_count: int = 0


@pytest.fixture
def clean():
    """Each test gets fresh registries. Teardown restores built-in
    predicates AND effect handlers so non-fixture tests still see them."""
    clear_registry()
    predicates_module.clear()
    effects_module.clear()
    yield
    clear_registry()
    predicates_module.clear()
    predicates_module.register_builtins()
    effects_module.clear()
    effects_module.register_builtins()


# ── Registry ──────────────────────────────────────────────────────


def test_register_and_get(clean):
    consequence = Consequence(
        id="test_one",
        trigger_predicate="never",
        resolution_effects=[],
    )
    register(consequence)
    assert get("test_one") is consequence
    assert "test_one" in all_consequences()


def test_register_rejects_duplicate(clean):
    c = Consequence(id="dup", trigger_predicate="never", resolution_effects=[])
    register(c)
    with pytest.raises(ValueError, match="already registered"):
        register(c)


def test_consequence_is_immutable(clean):
    c = Consequence(id="frozen", trigger_predicate="never", resolution_effects=[])
    register(c)
    with pytest.raises(Exception):  # FrozenInstanceError
        c.id = "different"  # type: ignore[misc]


def test_all_consequences_returns_snapshot(clean):
    register(Consequence(id="a", trigger_predicate="never", resolution_effects=[]))
    register(Consequence(id="b", trigger_predicate="never", resolution_effects=[]))
    snap = all_consequences()
    snap.clear()
    assert get("a") is not None
    assert get("b") is not None


# ── Predicate registry ────────────────────────────────────────────


def test_predicate_register_and_get(clean):
    @predicates_module.register("always")
    def _always(world, args, progress, events):
        return True

    assert predicates_module.get("always") is _always


def test_predicate_register_rejects_duplicate(clean):
    @predicates_module.register("once")
    def _once(world, args, progress, events):
        return True

    with pytest.raises(ValueError, match="already registered"):
        @predicates_module.register("once")
        def _again(world, args, progress, events):
            return True


# ── Effect registry ───────────────────────────────────────────────


def test_effect_register_and_call(clean):
    received: list = []

    @effects_module.register("noop")
    def _noop(world, args, instance):
        received.append((args, instance))

    fn = effects_module.get("noop")
    inst = ConsequenceInstance(config_id="x", spawned_tick=0)
    fn(None, {"a": 1}, inst)
    assert received == [({"a": 1}, inst)]


def test_effect_register_rejects_duplicate(clean):
    @effects_module.register("once_eff")
    def _e(world, args, instance):
        pass

    with pytest.raises(ValueError, match="already registered"):
        @effects_module.register("once_eff")
        def _e2(world, args, instance):
            pass


# ── Tick safety ───────────────────────────────────────────────────


def test_tick_on_bare_world_no_op():
    """Engine must no-op on a world without `consequences` attribute."""

    class Bare:
        pass

    tick_module.tick(Bare(), [])  # should not raise


def test_tick_with_no_registered_consequences(clean):
    world = FakeWorld()
    tick_module.tick(world, [])
    assert world.consequences == []


# ── Lifecycle ─────────────────────────────────────────────────────


def test_trigger_spawns_instance_and_resolves_immediately(clean):
    """resolution_predicate=None means resolve on the same tick as spawn."""

    @predicates_module.register("hp_below")
    def _hp_below(world, args, progress, events):
        return world.player.hp < int(args["threshold"])

    fired: list = []

    @effects_module.register("flag")
    def _flag(world, args, instance):
        fired.append(args["tag"])

    register(Consequence(
        id="hp_alert",
        trigger_predicate="hp_below",
        trigger_args={"threshold": 50},
        resolution_predicate=None,
        resolution_effects=[Effect(name="flag", args={"tag": "low_hp"})],
        one_shot=True,
    ))

    world = FakeWorld(player=FakePlayer(hp=30))
    tick_module.tick(world, [])

    assert fired == ["low_hp"]
    assert world.consequences == []  # resolved + cleaned same tick


def test_one_shot_prevents_double_spawn(clean):
    """one_shot=True skips spawn while an instance for same id exists."""

    @predicates_module.register("always_true")
    def _t(world, args, progress, events):
        return True

    @predicates_module.register("never")
    def _n(world, args, progress, events):
        return False

    register(Consequence(
        id="sticky",
        trigger_predicate="always_true",
        resolution_predicate="never",
        resolution_effects=[],
        one_shot=True,
    ))

    world = FakeWorld()
    tick_module.tick(world, [])
    tick_module.tick(world, [])
    tick_module.tick(world, [])

    assert len(world.consequences) == 1
    assert world.consequences[0].config_id == "sticky"
    assert world.consequences[0].state == "pending"


def test_resolution_predicate_gates_effects(clean):
    """Effects only run when resolution predicate returns True."""

    @predicates_module.register("trigger_now")
    def _t(world, args, progress, events):
        return True

    @predicates_module.register("done_when_count")
    def _done(world, args, progress, events):
        progress["count"] = progress.get("count", 0) + 1
        return progress["count"] >= int(args["n"])

    fired: list = []

    @effects_module.register("ping")
    def _ping(world, args, instance):
        fired.append(instance.progress["count"])

    register(Consequence(
        id="multi",
        trigger_predicate="trigger_now",
        resolution_predicate="done_when_count",
        resolution_args={"n": 3},
        resolution_effects=[Effect(name="ping")],
        one_shot=True,
    ))

    world = FakeWorld()
    tick_module.tick(world, [])  # spawn + first count attempt → 1
    assert fired == []
    assert len(world.consequences) == 1
    tick_module.tick(world, [])  # count → 2
    assert fired == []
    tick_module.tick(world, [])  # count → 3, resolve
    assert fired == [3]
    assert world.consequences == []


def test_context_snapshot_captures_player_state(clean):
    """Spawn-time context records HP, position, tick — for downstream branching."""

    @predicates_module.register("trigger")
    def _t(world, args, progress, events):
        return True

    @predicates_module.register("never_resolve")
    def _n(world, args, progress, events):
        return False

    register(Consequence(
        id="snap",
        trigger_predicate="trigger",
        resolution_predicate="never_resolve",
        resolution_effects=[],
    ))

    world = FakeWorld(player=FakePlayer(hp=42, x=3.0, z=-7.0))
    world.tick_count = 99
    tick_module.tick(world, [])

    assert len(world.consequences) == 1
    inst = world.consequences[0]
    assert inst.context["tick"] == 99
    assert inst.context["player_hp"] == 42
    assert inst.context["player_pos"] == (3.0, -7.0)
    assert inst.spawned_tick == 99


def test_missing_predicate_does_not_crash(clean):
    """A typo'd predicate name in a Consequence is silently skipped."""
    register(Consequence(
        id="bad",
        trigger_predicate="does_not_exist",
        resolution_effects=[],
    ))

    world = FakeWorld()
    tick_module.tick(world, [])  # must not raise
    assert world.consequences == []


def test_missing_effect_does_not_crash(clean):
    """A typo'd effect name is silently skipped — engine survives bad config."""

    @predicates_module.register("trigger")
    def _t(world, args, progress, events):
        return True

    register(Consequence(
        id="bad_effect",
        trigger_predicate="trigger",
        resolution_predicate=None,
        resolution_effects=[Effect(name="does_not_exist")],
        one_shot=True,
    ))

    world = FakeWorld()
    tick_module.tick(world, [])  # must not raise
    # Instance still gets resolved + removed even if effects no-op.
    assert world.consequences == []


# ── JSON loader ───────────────────────────────────────────────────


def test_json_loader_registers_rows(tmp_path, clean):
    config = {
        "schema_version": 1,
        "consequences": [
            {
                "id": "from_json",
                "trigger": {"predicate": "p1", "args": {"x": 1}},
                "resolution": {
                    "predicate": "p2",
                    "args": {"y": 2},
                    "effects": [
                        {"name": "e1", "args": {"z": 3}},
                        {"name": "e2"},
                    ],
                },
                "one_shot": True,
            }
        ],
    }
    json_path = tmp_path / "consequences.json"
    json_path.write_text(json.dumps(config))

    definitions.load_from_json(json_path)

    c = get("from_json")
    assert c is not None
    assert c.trigger_predicate == "p1"
    assert c.trigger_args == {"x": 1}
    assert c.resolution_predicate == "p2"
    assert c.resolution_args == {"y": 2}
    assert len(c.resolution_effects) == 2
    assert c.resolution_effects[0].name == "e1"
    assert c.resolution_effects[0].args == {"z": 3}
    assert c.resolution_effects[1].name == "e2"
    assert c.resolution_effects[1].args == {}
    assert c.one_shot is True


def test_json_loader_handles_missing_file(tmp_path, clean):
    """No-op when config file doesn't exist (early-bringup safety)."""
    bogus = tmp_path / "does_not_exist.json"
    definitions.load_from_json(bogus)
    assert all_consequences() == {}


def test_json_loader_empty_consequences_list(tmp_path, clean):
    json_path = tmp_path / "consequences.json"
    json_path.write_text(json.dumps({"schema_version": 1, "consequences": []}))
    definitions.load_from_json(json_path)
    assert all_consequences() == {}


def test_hp_zero_predicate_returns_false_with_no_events():
    """The hp_zero built-in predicate matches on tick_event presence only."""
    fn = predicates_module.get("hp_zero")
    assert fn is not None
    assert fn(FakeWorld(), {}, {}, []) is False


def test_hp_zero_predicate_matches_on_event():
    fn = predicates_module.get("hp_zero")
    events = [{"type": "hp_zero"}]
    assert fn(FakeWorld(), {}, {}, events) is True


def test_hp_zero_predicate_ignores_other_events():
    fn = predicates_module.get("hp_zero")
    events = [
        {"type": "kind_destroyed", "kind": "clay_pot"},
        {"type": "journal_entry", "raw_note": "x"},
    ]
    assert fn(FakeWorld(), {}, {}, events) is False


def test_hp_zero_predicate_survives_clean_fixture():
    """Built-in predicates re-register after a `clean` fixture cycle."""
    # The `clean` fixture clears the predicate registry, but step 2's
    # built-ins live in the module body — re-importing reinstates them.
    # This test runs WITHOUT the fixture so the auto-loaded built-ins
    # are still present.
    assert predicates_module.get("hp_zero") is not None


def test_default_config_loads_clean():
    """The shipped config/consequences.json must be parseable without
    error. Step 1 ships an empty consequences list; future steps add
    rows. This test guards against malformed JSON."""
    # Force re-load of the default path. Don't clear first — the auto-
    # load on import already populated whatever's in the file.
    from core.systems.consequences.definitions import CONFIG_PATH
    assert CONFIG_PATH.exists()
    data = json.loads(CONFIG_PATH.read_text())
    assert "schema_version" in data
    assert isinstance(data.get("consequences", []), list)
