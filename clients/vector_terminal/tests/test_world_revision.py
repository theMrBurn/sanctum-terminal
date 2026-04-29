"""world_revision diff detection — first manifest sets the baseline,
subsequent bumps signal regen."""
from __future__ import annotations

from clients.vector_terminal.world_revision import WorldRevisionTracker


def test_first_observation_does_not_signal_regen():
    tracker = WorldRevisionTracker()
    assert tracker.observe(0) is False


def test_unchanged_revision_does_not_signal():
    tracker = WorldRevisionTracker()
    tracker.observe(7)
    assert tracker.observe(7) is False
    assert tracker.observe(7) is False


def test_bumped_revision_signals_regen():
    tracker = WorldRevisionTracker()
    tracker.observe(0)
    assert tracker.observe(1) is True


def test_subsequent_bumps_each_signal():
    tracker = WorldRevisionTracker()
    tracker.observe(0)
    assert tracker.observe(1) is True
    assert tracker.observe(2) is True
    assert tracker.observe(3) is True


def test_missing_revision_is_silent():
    tracker = WorldRevisionTracker()
    assert tracker.observe(None) is False
    tracker.observe(0)
    assert tracker.observe(None) is False


def test_baseline_then_bump():
    tracker = WorldRevisionTracker()
    tracker.observe(42)
    assert tracker.observe(42) is False
    assert tracker.observe(43) is True
