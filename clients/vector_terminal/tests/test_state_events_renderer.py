"""StateEvent renderer — watermark tracking, expiration semantics."""
from __future__ import annotations

from clients.vector_terminal.state_events import (
    DEFAULT_DURATION,
    DURATIONS,
    _ActiveToast,
    update,
)


def _evt(id_, label="X", register="loop"):
    return {"id": id_, "label": label, "register": register, "detail": None, "kind": "test", "timestamp": 0.0}


def test_first_frame_syncs_watermark_no_active():
    """First connect: watermark goes to max id in buffer, no toasts spawn.
    Suppresses historical events on join."""
    events = [_evt(1), _evt(2), _evt(3)]
    seen, active = update(events, 0, [], now=10.0)
    assert seen == 3
    assert active == []


def test_new_event_after_first_frame_creates_toast():
    seen, active = update([_evt(1), _evt(2)], 0, [], now=10.0)
    # Now id=3 arrives
    seen2, active2 = update([_evt(1), _evt(2), _evt(3, "NEW")], seen, active, now=10.5)
    assert seen2 == 3
    assert len(active2) == 1
    assert active2[0].event["label"] == "NEW"


def test_existing_actives_drop_when_expired():
    """A toast older than its duration falls off."""
    register = "loop"
    duration = DURATIONS[register]
    old_toast = _ActiveToast(event=_evt(5, "OLD", register), started_at=0.0)
    # now is past expiration
    seen, active = update([], 5, [old_toast], now=duration + 1.0)
    assert active == []


def test_active_persists_within_duration():
    register = "ritual"
    duration = DURATIONS[register]
    fresh = _ActiveToast(event=_evt(7, "FRESH", register), started_at=0.0)
    seen, active = update([], 7, [fresh], now=duration / 2)
    assert len(active) == 1
    assert active[0].event["label"] == "FRESH"


def test_unknown_register_uses_default_duration():
    fresh = _ActiveToast(event=_evt(1, "X", register="weird-unknown"), started_at=0.0)
    # Just before default expires
    _, active = update([], 1, [fresh], now=DEFAULT_DURATION - 0.1)
    assert len(active) == 1
    # Just after default expires
    _, active = update([], 1, [fresh], now=DEFAULT_DURATION + 0.1)
    assert active == []


def test_no_events_in_manifest_preserves_state():
    fresh = _ActiveToast(event=_evt(3, "STILL HERE", "loop"), started_at=10.0)
    seen, active = update([], 3, [fresh], now=10.5)
    assert seen == 3
    assert len(active) == 1


def test_multiple_new_events_in_one_tick():
    events = [_evt(1), _evt(2), _evt(3), _evt(4)]
    # Watermark at 1; events 2, 3, 4 are new
    seen, active = update(events, 1, [], now=10.0)
    assert seen == 4
    assert len(active) == 3


def test_seen_id_only_advances_forward():
    """Watermark never goes backward even if a stale event slipped in."""
    seen, active = update([_evt(5, "FIVE")], 0, [], now=10.0)
    assert seen == 5
    # Brain restarts and emits id=1 fresh; we should ignore (id <= seen)
    seen2, active2 = update([_evt(1, "ONE")], seen, active, now=11.0)
    assert seen2 == 5
    assert active2 == []  # nothing new, no fresh actives
