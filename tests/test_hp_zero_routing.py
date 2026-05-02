"""HP=0 signal helper — `consequences.signals.push_hp_zero(world)`.

Step 2 of PR 3 per the feature file. The helper pushes a `hp_zero`
event onto `world.tick_events` when player HP reaches zero. The
consequences engine watches the event via the `hp_zero` predicate;
resolution effects regenerate the world and restore HP (steps 3-4).

Per `design_virtual_hallucination`, this is JUST a respawn signal —
no perma-death framing. Single detection site so the engine sees
exactly one signal per HP-zero transition. Lives outside
`brain_server.py` so it's testable without panda3d in the venv —
brain_server's transitive import of `core.systems.ambient_life`
brings panda3d along otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.systems.consequences.signals import push_hp_zero


@dataclass
class _FakePlayer:
    hp: int = 0


@dataclass
class _FakeWorld:
    player: _FakePlayer = field(default_factory=_FakePlayer)
    tick_events: list = field(default_factory=list)


def test_pushes_event_at_hp_zero():
    world = _FakeWorld(player=_FakePlayer(hp=0))
    push_hp_zero(world)
    assert world.tick_events == [{"type": "hp_zero"}]


def test_pushes_event_below_zero():
    """Negative HP also triggers — overkill damage shouldn't get missed."""
    world = _FakeWorld(player=_FakePlayer(hp=-5))
    push_hp_zero(world)
    assert world.tick_events == [{"type": "hp_zero"}]


def test_no_push_when_hp_positive():
    world = _FakeWorld(player=_FakePlayer(hp=10))
    push_hp_zero(world)
    assert world.tick_events == []


def test_idempotent_within_a_tick():
    """Multiple mutators in the same frame don't double-push."""
    world = _FakeWorld(player=_FakePlayer(hp=0))
    push_hp_zero(world)
    push_hp_zero(world)
    push_hp_zero(world)
    assert world.tick_events == [{"type": "hp_zero"}]


def test_preserves_other_events():
    """Helper appends without clearing existing tick_events."""
    world = _FakeWorld(player=_FakePlayer(hp=0))
    world.tick_events.append({"type": "kind_destroyed", "kind": "clay_pot"})
    push_hp_zero(world)
    assert {"type": "kind_destroyed", "kind": "clay_pot"} in world.tick_events
    assert {"type": "hp_zero"} in world.tick_events


def test_idempotent_with_other_events_present():
    """Existing non-hp_zero events don't confuse the dedup check."""
    world = _FakeWorld(player=_FakePlayer(hp=0))
    world.tick_events.append({"type": "journal_entry"})
    push_hp_zero(world)
    push_hp_zero(world)
    hp_zero_count = sum(1 for e in world.tick_events if e.get("type") == "hp_zero")
    assert hp_zero_count == 1


def test_predicate_matches_pushed_event():
    """Round-trip: signal pushed by helper is seen by the predicate."""
    from core.systems.consequences import predicates as predicates_module

    world = _FakeWorld(player=_FakePlayer(hp=0))
    push_hp_zero(world)

    predicate = predicates_module.get("hp_zero")
    assert predicate is not None
    assert predicate(world, {}, {}, world.tick_events) is True
