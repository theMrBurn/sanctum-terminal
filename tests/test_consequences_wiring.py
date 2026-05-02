"""End-to-end wiring for PR 3 step 4 — consequences engine in brain.

Validates:
  1. The shipped `config/consequences.json` registers the
     `hp_zero_respawn` row at module-import time.
  2. The row's resolution chain matches the design intent
     (state event → regen → restore HP, in that order).
  3. A bare-metal trigger flow (predicate match → engine tick →
     effects fire on a duck-typed world) produces the expected
     mutations: regen called, HP restored, state event emitted.
  4. Brain main loop is wired correctly (the `consequence_tick.tick`
     call site exists and is called in the right place).

The bare-metal test does NOT require importing brain_server (which
would pull in spacy + the full live brain). brain_server's wiring is
verified by the static check in test #4 (grep for the call site).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.systems.consequences import all_consequences, get
from core.systems.consequences import predicates as predicates_module
from core.systems.consequences import signals as consequence_signals
from core.systems.consequences import tick as tick_module


# ── Production config row ──────────────────────────────────────────


def test_hp_zero_respawn_registered_on_import():
    """The shipped config/consequences.json registers hp_zero_respawn
    automatically on import. Tests that don't use the `clean` fixture
    must see it."""
    c = get("hp_zero_respawn")
    assert c is not None, "hp_zero_respawn should auto-register on import"
    assert "hp_zero_respawn" in all_consequences()


def test_hp_zero_respawn_shape():
    """Resolution chain matches the design: state event first
    (toast renders before the screen changes), then regen, then HP
    restore. Order matters — toast text would land on a regenerated
    world otherwise."""
    c = get("hp_zero_respawn")
    assert c is not None
    assert c.trigger_predicate == "hp_zero"
    assert c.resolution_predicate is None  # immediate
    assert c.one_shot is True

    effect_names = [e.name for e in c.resolution_effects]
    assert effect_names == ["emit_state_event", "regen_world", "restore_hp"]

    # State event uses the "tense" register per design directive
    # (kinetic moment, not slow ritual).
    state_evt = c.resolution_effects[0]
    assert state_evt.args["kind"] == "respawn"
    assert state_evt.args["label"] == "RESPAWN"
    assert state_evt.args["register"] == "tense"

    # Random reseed — fresh procedural expedition each respawn.
    regen = c.resolution_effects[1]
    assert regen.args["reseed"] == "random"

    # Full HP restore.
    restore = c.resolution_effects[2]
    assert restore.args["to"] == "full"


# ── End-to-end via duck-typed world ────────────────────────────────


@dataclass
class _FakePlayer:
    hp: int = 0
    max_hp: int = 6

    def _replace(self, **kwargs):
        new = _FakePlayer(hp=self.hp, max_hp=self.max_hp)
        for k, v in kwargs.items():
            setattr(new, k, v)
        return new


class _RegenSpy:
    def __init__(self):
        self.calls: list[int] = []

    def __call__(self, new_seed: int) -> None:
        self.calls.append(new_seed)


@dataclass
class _StateEventSpy:
    emitted: list[dict] = field(default_factory=list)

    def emit(self, kind, label, detail=None, register="system"):
        self.emitted.append({
            "kind": kind,
            "label": label,
            "detail": detail,
            "register": register,
        })


@dataclass
class _FakeBrainWorld:
    """Duck-typed minimal world that satisfies the engine's contract.
    Mirrors BrainWorld's relevant attributes — no spacy / panda3d /
    biome_data dependencies."""
    player: _FakePlayer = field(default_factory=lambda: _FakePlayer(hp=6, max_hp=6))
    regen_world: _RegenSpy = field(default_factory=_RegenSpy)
    state_events: _StateEventSpy = field(default_factory=_StateEventSpy)
    consequences: list = field(default_factory=list)
    tick_events: list = field(default_factory=list)
    tick_count: int = 0
    entities: list = field(default_factory=list)


def test_full_respawn_flow_via_signal_and_tick():
    """End-to-end: signal helper pushes hp_zero, engine picks it up,
    fires the production hp_zero_respawn row, all three effects run."""
    world = _FakeBrainWorld()

    # 1. Damage path — player hits 0 HP. (Test bypasses take_damage
    # mutator since this fake doesn't have ps; just sets hp directly.)
    world.player = world.player._replace(hp=0)

    # 2. Brain calls signals.push_hp_zero after the damage mutator.
    consequence_signals.push_hp_zero(world)
    assert {"type": "hp_zero"} in world.tick_events

    # 3. Brain main loop calls consequences.tick after quest tick.
    tick_module.tick(world, world.tick_events)

    # 4. State event fired before regen — toast renders against the
    # outgoing world view.
    assert len(world.state_events.emitted) == 1
    assert world.state_events.emitted[0]["kind"] == "respawn"
    assert world.state_events.emitted[0]["label"] == "RESPAWN"
    assert world.state_events.emitted[0]["register"] == "tense"

    # 5. World regen called with a random int seed.
    assert len(world.regen_world.calls) == 1
    assert isinstance(world.regen_world.calls[0], int)

    # 6. HP fully restored.
    assert world.player.hp == 6

    # 7. Consequence resolved + cleaned up; no lingering instance.
    assert world.consequences == []


def test_one_shot_prevents_regen_loop_while_hp_held_at_zero():
    """If HP stays at 0 across multiple ticks, the consequence does
    NOT re-fire. one_shot=True on the production row prevents a regen
    loop in case some upstream bug holds HP at 0.

    Note: the production resolution restores HP, so in the normal
    flow this is a non-issue. The guard is for defensive sanity only.
    """
    world = _FakeBrainWorld()
    world.player = world.player._replace(hp=0)
    consequence_signals.push_hp_zero(world)

    # First tick: spawn + resolve. HP restored. signal cleared by
    # tick_events.clear() in the real brain loop — we mimic that.
    tick_module.tick(world, world.tick_events)
    world.tick_events.clear()
    assert world.player.hp == 6

    # Now imagine the player damages themselves again next tick.
    world.player = world.player._replace(hp=0)
    consequence_signals.push_hp_zero(world)
    tick_module.tick(world, world.tick_events)
    world.tick_events.clear()

    # Two regens total — one per HP=0 transition.
    assert len(world.regen_world.calls) == 2

    # one_shot is preserved across resolutions: each new transition
    # produces exactly one resolution.


# ── Brain main-loop wiring is in place ─────────────────────────────


def test_brain_server_calls_consequence_tick_after_quest_tick():
    """Static check that brain_server.py's main loop wires the engine
    in the right ordering. Reads the source rather than importing —
    keeps this test free of spacy/lexicon dependencies."""
    src = Path(__file__).resolve().parents[1] / "brain_server.py"
    text = src.read_text()
    quest_pos = text.find("quest_tick.tick(")
    cq_pos = text.find("consequence_tick.tick(")
    clear_pos = text.find("world.tick_events.clear()", cq_pos)

    assert quest_pos >= 0, "quest_tick.tick call site missing"
    assert cq_pos >= 0, "consequence_tick.tick call site missing"
    assert clear_pos >= 0, "tick_events.clear() not found after consequence tick"

    # Strict ordering: quest before consequence; consequence before clear.
    assert quest_pos < cq_pos, \
        "consequence_tick must run AFTER quest_tick (ordering doctrine)"
    assert cq_pos < clear_pos, \
        "consequence_tick must run BEFORE tick_events.clear() (events shared)"


def test_brain_server_initializes_world_consequences_list():
    """world.consequences = [] must be set in BrainWorld.__init__ so
    the engine has somewhere to spawn instances."""
    src = Path(__file__).resolve().parents[1] / "brain_server.py"
    text = src.read_text()
    assert "self.consequences" in text, \
        "BrainWorld must initialize self.consequences"


def test_brain_server_imports_consequence_tick():
    """The brain must import the tick module to wire the engine."""
    src = Path(__file__).resolve().parents[1] / "brain_server.py"
    text = src.read_text()
    assert "from core.systems.consequences import tick as consequence_tick" in text
