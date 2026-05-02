"""End-to-end wiring for the reflective consequence chain.

Validates the production config rows in `config/consequences.json`
register correctly, the brain main-loop wiring is in place, and a
duck-typed world flows through the full HP=0 + voluntary chains.

The HP=0 chain is now two-stage (PR 3.5):
  1. hp_zero event → hp_zero_enter_reflective fires
       → emit REFLECT + enter_reflective
  2. (player composes, commits)
     reflective_committed_from_hp_zero event → reflective_commit_resume fires
       → exit_reflective + emit RESPAWN + regen_world + restore_hp

Voluntary chain (single-stage from cmd handler):
  1. (cmd handler calls state_machine.enter directly + transitions
      game_state directly)
  2. reflective_committed_voluntary event → reflective_commit_voluntary fires
       → exit_reflective + emit DONE
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.systems import game_state as gs
from core.systems.consequences import all_consequences, get
from core.systems.consequences import predicates as predicates_module
from core.systems.consequences import signals as consequence_signals
from core.systems.consequences import tick as tick_module
from core.systems.reflective import ReflectiveState
from core.systems.reflective import state_machine as sm


# ── Production config rows registered ──────────────────────────────


def test_hp_zero_enter_reflective_registered():
    c = get("hp_zero_enter_reflective")
    assert c is not None
    assert c.trigger_predicate == "hp_zero"
    assert c.one_shot is True


def test_reflective_commit_resume_registered():
    c = get("reflective_commit_resume")
    assert c is not None
    assert c.trigger_predicate == "reflective_committed_from_hp_zero"
    assert c.one_shot is True


def test_reflective_commit_voluntary_registered():
    c = get("reflective_commit_voluntary")
    assert c is not None
    assert c.trigger_predicate == "reflective_committed_voluntary"
    assert c.one_shot is True


def test_three_production_rows():
    """Three rows total — the chain is symmetrical (one entry, two
    commit paths)."""
    ids = set(all_consequences().keys())
    expected = {
        "hp_zero_enter_reflective",
        "reflective_commit_resume",
        "reflective_commit_voluntary",
    }
    assert expected.issubset(ids)


def test_hp_zero_enter_chain_shape():
    """Entry chain: emit REFLECT (ritual) → enter_reflective."""
    c = get("hp_zero_enter_reflective")
    names = [e.name for e in c.resolution_effects]
    assert names == ["emit_state_event", "enter_reflective"]
    assert c.resolution_effects[0].args["kind"] == "reflective_entry"
    assert c.resolution_effects[0].args["label"] == "REFLECT"
    assert c.resolution_effects[0].args["register"] == "ritual"
    assert c.resolution_effects[1].args["trigger"] == "hp_zero"


def test_resume_chain_shape():
    """HP=0 commit chain: exit → emit RESPAWN (tense) → regen → restore."""
    c = get("reflective_commit_resume")
    names = [e.name for e in c.resolution_effects]
    assert names == ["exit_reflective", "emit_state_event", "regen_world", "restore_hp"]
    assert c.resolution_effects[1].args["kind"] == "respawn"
    assert c.resolution_effects[1].args["label"] == "RESPAWN"
    assert c.resolution_effects[1].args["register"] == "tense"
    assert c.resolution_effects[2].args["reseed"] == "random"
    assert c.resolution_effects[3].args["to"] == "full"


def test_voluntary_chain_shape():
    """Voluntary commit chain: exit → emit DONE (discovery). No regen, no HP touch."""
    c = get("reflective_commit_voluntary")
    names = [e.name for e in c.resolution_effects]
    assert names == ["exit_reflective", "emit_state_event"]
    assert c.resolution_effects[1].args["kind"] == "reflective_complete"
    assert c.resolution_effects[1].args["label"] == "DONE"
    assert c.resolution_effects[1].args["register"] == "discovery"


# ── Duck-typed world for end-to-end tests ──────────────────────────


@dataclass
class _FakePlayer:
    hp: int = 6
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
    """Duck-typed minimal world. Mirrors BrainWorld's relevant
    attributes — no spacy / panda3d / biome_data dependencies."""
    player: _FakePlayer = field(default_factory=_FakePlayer)
    regen_world: _RegenSpy = field(default_factory=_RegenSpy)
    state_events: _StateEventSpy = field(default_factory=_StateEventSpy)
    consequences: list = field(default_factory=list)
    tick_events: list = field(default_factory=list)
    tick_count: int = 0
    entities: list = field(default_factory=list)
    game_state: gs.GameState = field(default_factory=gs.GameState.initial)
    reflective: ReflectiveState = field(default_factory=ReflectiveState)


# ── HP=0 forced-entry chain ────────────────────────────────────────


def test_hp_zero_routes_to_reflective_not_immediate_respawn():
    """HP=0 enters reflective FIRST. Player does not get an immediate
    regen / HP restore — the resume chain only fires after commit."""
    world = _FakeBrainWorld()
    world.player = world.player._replace(hp=0)

    consequence_signals.push_hp_zero(world)
    tick_module.tick(world, world.tick_events)

    # Entry toast emitted (REFLECT, ritual register).
    assert len(world.state_events.emitted) == 1
    assert world.state_events.emitted[0]["label"] == "REFLECT"
    assert world.state_events.emitted[0]["register"] == "ritual"

    # World mutated into reflective mode.
    assert world.reflective.active is True
    assert world.reflective.trigger == "hp_zero"
    assert world.game_state.state == gs.GameStateName.REFLECTIVE

    # NO regen yet, NO HP restore yet — those are part of the resume chain.
    assert world.regen_world.calls == []
    assert world.player.hp == 0


def test_hp_zero_commit_resume_chain():
    """After committing while in HP=0 reflective, the resume chain fires:
    exit + RESPAWN + regen + full HP restore."""
    world = _FakeBrainWorld()
    world.player = world.player._replace(hp=0)

    # Enter reflective via the HP=0 path.
    consequence_signals.push_hp_zero(world)
    tick_module.tick(world, world.tick_events)
    world.tick_events.clear()

    # Place enough magnets to satisfy compose_three.
    for w in world.reflective.magnet_pool[:3]:
        sm.place_magnet(world, w)

    # Brain commit handler would: call sm.commit, on True push the event.
    assert sm.commit(world) is True

    # The brain pushes this event after a successful HP=0 commit.
    world.tick_events.append({"type": "reflective_committed_from_hp_zero"})
    tick_module.tick(world, world.tick_events)

    # Resume chain effects fired.
    assert world.reflective.active is False
    assert world.game_state.state == gs.GameStateName.HUB

    # RESPAWN toast (in addition to the earlier REFLECT toast).
    labels = [e["label"] for e in world.state_events.emitted]
    assert "RESPAWN" in labels

    # World regen + HP full restore.
    assert len(world.regen_world.calls) == 1
    assert world.player.hp == 6


# ── Voluntary entry + commit chain ─────────────────────────────────


def test_voluntary_entry_via_state_machine_then_commit_chain():
    """Voluntary entry doesn't go through the consequence engine —
    brain's engage_fridge cmd handler calls state_machine.enter +
    transitions game_state directly. Commit pushes the voluntary
    event; only the exit chain runs (no regen / no HP touch)."""
    import random
    world = _FakeBrainWorld()
    starting_hp = world.player.hp

    # Brain's engage_fridge handler logic, simulated.
    sm.enter(world, trigger="voluntary", rng=random.Random(0))
    world.game_state = gs.transition(world.game_state, gs.GameStateName.REFLECTIVE)

    assert world.reflective.active is True
    assert world.game_state.state == gs.GameStateName.REFLECTIVE

    # Place + commit.
    for w in world.reflective.magnet_pool[:3]:
        sm.place_magnet(world, w)
    assert sm.commit(world) is True

    # Brain pushes voluntary event after AC success.
    world.tick_events.append({"type": "reflective_committed_voluntary"})
    tick_module.tick(world, world.tick_events)

    # Exit chain ran.
    assert world.reflective.active is False
    assert world.game_state.state == gs.GameStateName.HUB

    # DONE toast in discovery register.
    last_emit = world.state_events.emitted[-1]
    assert last_emit["label"] == "DONE"
    assert last_emit["register"] == "discovery"

    # NO regen, NO HP touched — voluntary doesn't carry respawn payload.
    assert world.regen_world.calls == []
    assert world.player.hp == starting_hp


# ── Brain main-loop wiring is in place ─────────────────────────────


def test_brain_server_calls_consequence_tick_after_quest_tick():
    """Static check that brain_server.py's main loop wires the engine
    correctly. Reads the source rather than importing — keeps this
    test free of spacy/lexicon dependencies."""
    src = Path(__file__).resolve().parents[1] / "brain_server.py"
    text = src.read_text()
    quest_pos = text.find("quest_tick.tick(")
    cq_pos = text.find("consequence_tick.tick(")
    clear_pos = text.find("world.tick_events.clear()", cq_pos)

    assert quest_pos >= 0
    assert cq_pos >= 0
    assert clear_pos >= 0
    assert quest_pos < cq_pos
    assert cq_pos < clear_pos


def test_brain_server_initializes_world_consequences_list():
    src = Path(__file__).resolve().parents[1] / "brain_server.py"
    text = src.read_text()
    assert "self.consequences" in text


def test_brain_server_imports_consequence_tick():
    src = Path(__file__).resolve().parents[1] / "brain_server.py"
    text = src.read_text()
    assert "from core.systems.consequences import tick as consequence_tick" in text


# ── Predicate built-ins ─────────────────────────────────────────────


def test_commit_predicates_registered_on_import():
    """Both commit predicates must be auto-registered for the production
    config rows to resolve."""
    assert predicates_module.get("reflective_committed_from_hp_zero") is not None
    assert predicates_module.get("reflective_committed_voluntary") is not None


def test_commit_predicate_matches_correct_event():
    fn_hp_zero = predicates_module.get("reflective_committed_from_hp_zero")
    fn_vol = predicates_module.get("reflective_committed_voluntary")

    assert fn_hp_zero(None, {}, {}, [{"type": "reflective_committed_from_hp_zero"}]) is True
    assert fn_hp_zero(None, {}, {}, [{"type": "reflective_committed_voluntary"}]) is False

    assert fn_vol(None, {}, {}, [{"type": "reflective_committed_voluntary"}]) is True
    assert fn_vol(None, {}, {}, [{"type": "reflective_committed_from_hp_zero"}]) is False
