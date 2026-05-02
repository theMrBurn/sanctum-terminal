"""Manifest serialization for reflective mode (PR 3.5 step 10).

Validates the `_reflective_to_manifest(world)` helper produces the
client-facing surface and that the manifest dict surfaces it under
the `reflective` key when active.

Tests use a duck-typed world so we can call the helper directly
without spinning up the full brain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.systems.reflective import ReflectiveState
from core.systems.reflective import rules


# Import the manifest helper from brain_server (live brain — needs
# venv with spacy). We do an isolated import so test failures here
# don't cascade into other suites if brain_server is broken.
import importlib
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _import_brain_helper():
    bs = importlib.import_module("brain_server")
    return bs._reflective_to_manifest


# ── Fixtures ──────────────────────────────────────────────────────


@dataclass
class _FakeBrainWorld:
    reflective: ReflectiveState = field(default_factory=ReflectiveState)


def _setup_active_state(world: _FakeBrainWorld) -> None:
    world.reflective.active = True
    world.reflective.trigger = "voluntary"
    world.reflective.current_rule_id = "compose_three"
    world.reflective.magnet_pool = ["the", "river", "moss", "and"]
    world.reflective.composed = ["the", "river"]
    world.reflective.attempt_count = 1


# ── Helper output shape ───────────────────────────────────────────


def test_manifest_helper_includes_active_flag():
    fn = _import_brain_helper()
    world = _FakeBrainWorld()
    _setup_active_state(world)
    out = fn(world)
    assert out["active"] is True


def test_manifest_helper_includes_trigger():
    fn = _import_brain_helper()
    world = _FakeBrainWorld()
    _setup_active_state(world)
    out = fn(world)
    assert out["trigger"] == "voluntary"


def test_manifest_helper_resolves_rule_block():
    fn = _import_brain_helper()
    world = _FakeBrainWorld()
    _setup_active_state(world)
    out = fn(world)
    rule = rules.get("compose_three")
    assert out["rule"] == {
        "id": rule.id,
        "name": rule.name,
        "instructions": rule.instructions,
    }


def test_manifest_helper_includes_pool_and_composed():
    fn = _import_brain_helper()
    world = _FakeBrainWorld()
    _setup_active_state(world)
    out = fn(world)
    assert out["magnet_pool"] == ["the", "river", "moss", "and"]
    assert out["composed"] == ["the", "river"]


def test_manifest_helper_includes_attempt_count():
    fn = _import_brain_helper()
    world = _FakeBrainWorld()
    _setup_active_state(world)
    out = fn(world)
    assert out["attempt_count"] == 1


def test_manifest_helper_handles_unknown_rule():
    """If current_rule_id refers to an unregistered rule (shouldn't
    happen in production, defensive), rule block is None — clients
    still get the magnet pool + composed list."""
    fn = _import_brain_helper()
    world = _FakeBrainWorld()
    world.reflective.active = True
    world.reflective.current_rule_id = "does_not_exist"
    world.reflective.magnet_pool = ["x"]
    out = fn(world)
    assert out["rule"] is None
    assert out["magnet_pool"] == ["x"]


def test_manifest_helper_returns_lists_not_aliases():
    """Manifest output must not share list identity with world.reflective —
    clients mutating manifest copies shouldn't corrupt the source."""
    fn = _import_brain_helper()
    world = _FakeBrainWorld()
    _setup_active_state(world)
    out = fn(world)
    out["magnet_pool"].append("BAD")
    assert "BAD" not in world.reflective.magnet_pool
    out["composed"].append("BAD")
    assert "BAD" not in world.reflective.composed


# ── Manifest surface integration ──────────────────────────────────


def test_manifest_block_present_in_get_manifest():
    """Static check that `reflective` key is added to the manifest dict."""
    src = (Path(__file__).resolve().parents[1] / "brain_server.py").read_text()
    assert '"reflective":' in src
    assert "_reflective_to_manifest" in src


def test_manifest_block_only_when_active():
    """Static check that the manifest entry is None when reflective
    isn't active — clients can branch on the falsy value."""
    src = (Path(__file__).resolve().parents[1] / "brain_server.py").read_text()
    # The conditional expression in the manifest dict.
    assert "if self.reflective.active else None" in src
