"""Activity-loop tests — PR 9.

Old-dev discipline coverage: saturating cap, slot-decay rotation, edge
detection (one fire per crossing), StateEvent emission, no-op when
uninstalled. Per `feat_make-brain-ping-pong.md` PR 9 — T10.
"""
from __future__ import annotations

import pytest

from core.systems import activity_loop
from core.systems.activity_loop import (
    ActivityClass,
    ActivityLoop,
    CLASS_COUNT,
    COUNTER_MAX,
    DECAY_PERIOD_SECONDS,
    DWELL_UNWIND_SLICE_SECONDS,
    PreferenceCounters,
    REWARD_TABLE,
)
from core.systems.state_events import StateEventBuffer


@pytest.fixture(autouse=True)
def _reset_singletons():
    activity_loop._reset_for_tests()
    yield
    activity_loop._reset_for_tests()


# ── ActivityClass invariant ──────────────────────────────────────────


def test_seven_classes_pinned():
    """factor_of_7 invariant — adding an 8th class is a real migration."""
    assert CLASS_COUNT == 7
    names = [cls.name for cls in ActivityClass]
    assert names == ["HUNT", "MAKE", "SNEAK", "UNWIND", "SOLVE", "WANDER", "RITUAL"]


# ── PreferenceCounters: emit + saturation ────────────────────────────


def test_emit_increments_counter():
    p = PreferenceCounters()
    p.emit(ActivityClass.HUNT, 1)
    assert p.counts[int(ActivityClass.HUNT)] == 1
    p.emit(ActivityClass.HUNT, 4)
    assert p.counts[int(ActivityClass.HUNT)] == 5


def test_emit_saturates_at_counter_max():
    p = PreferenceCounters()
    p.emit(ActivityClass.MAKE, COUNTER_MAX + 100)
    assert p.counts[int(ActivityClass.MAKE)] == COUNTER_MAX
    p.emit(ActivityClass.MAKE, 50)
    assert p.counts[int(ActivityClass.MAKE)] == COUNTER_MAX  # still saturated


def test_emit_negative_intensity_is_noop():
    p = PreferenceCounters()
    p.emit(ActivityClass.RITUAL, 5)
    p.emit(ActivityClass.RITUAL, -3)        # ignored
    p.emit(ActivityClass.RITUAL, 0)         # ignored
    assert p.counts[int(ActivityClass.RITUAL)] == 5


def test_emit_only_touches_target_class():
    p = PreferenceCounters()
    p.emit(ActivityClass.HUNT, 7)
    for cls in ActivityClass:
        if cls != ActivityClass.HUNT:
            assert p.counts[int(cls)] == 0


# ── PreferenceCounters: slot-decay rotation ──────────────────────────


def test_decay_below_period_is_noop():
    p = PreferenceCounters()
    for cls in ActivityClass:
        p.emit(cls, 10)
    p.tick(DECAY_PERIOD_SECONDS - 0.001)
    assert all(p.counts[int(c)] == 10 for c in ActivityClass)


def test_decay_rotates_through_all_classes():
    """One slot per period, cycling through CLASS_COUNT."""
    p = PreferenceCounters()
    for cls in ActivityClass:
        p.emit(cls, 10)
    # Advance exactly CLASS_COUNT periods → each class loses exactly 1.
    for _ in range(CLASS_COUNT):
        p.tick(DECAY_PERIOD_SECONDS)
    assert all(p.counts[int(c)] == 9 for c in ActivityClass)


def test_decay_handles_multiple_periods_per_tick():
    """Big dt drains accumulator in a loop without losing periods."""
    p = PreferenceCounters()
    for cls in ActivityClass:
        p.emit(cls, 5)
    p.tick(DECAY_PERIOD_SECONDS * CLASS_COUNT * 2)   # two full sweeps
    assert all(p.counts[int(c)] == 3 for c in ActivityClass)


def test_decay_does_not_underflow():
    p = PreferenceCounters()
    p.emit(ActivityClass.HUNT, 1)
    # Tick enough periods that HUNT's slot has fired many times.
    for _ in range(CLASS_COUNT * 5):
        p.tick(DECAY_PERIOD_SECONDS)
    assert p.counts[int(ActivityClass.HUNT)] == 0


def test_decay_zero_dt_noop():
    p = PreferenceCounters()
    p.emit(ActivityClass.HUNT, 5)
    p.tick(0.0)
    p.tick(-1.0)
    assert p.counts[int(ActivityClass.HUNT)] == 5


# ── ActivityLoop: edge detection ─────────────────────────────────────


def test_loop_fires_reward_on_threshold_crossing():
    p = PreferenceCounters()
    se = StateEventBuffer()
    loop = ActivityLoop(p, se)

    # Below threshold — no fire.
    p.emit(ActivityClass.HUNT, 49)
    fired = loop.tick(0.0)
    assert fired == []
    assert se.latest_id() == 0

    # Cross threshold — exactly one fire.
    p.emit(ActivityClass.HUNT, 1)
    fired = loop.tick(0.0)
    assert "hunt_recognized" in fired
    assert any(e.kind == "hunt_recognized" for e in se.all())


def test_loop_fires_each_reward_only_once():
    p = PreferenceCounters()
    se = StateEventBuffer()
    loop = ActivityLoop(p, se)
    p.emit(ActivityClass.HUNT, 50)
    loop.tick(0.0)                              # fires hunt_recognized
    p.emit(ActivityClass.HUNT, 1)
    fired = loop.tick(0.0)
    assert "hunt_recognized" not in fired       # already fired, no re-fire


def test_loop_fires_higher_threshold_after_lower():
    p = PreferenceCounters()
    se = StateEventBuffer()
    loop = ActivityLoop(p, se)
    # Cross 50 first.
    p.emit(ActivityClass.HUNT, 50)
    fired_a = loop.tick(0.0)
    assert "hunt_recognized" in fired_a
    # Then cross 200.
    p.emit(ActivityClass.HUNT, 150)
    fired_b = loop.tick(0.0)
    assert "hunt_deepened" in fired_b


def test_loop_emits_state_event_with_register():
    p = PreferenceCounters()
    se = StateEventBuffer()
    loop = ActivityLoop(p, se)
    p.emit(ActivityClass.HUNT, 50)
    loop.tick(0.0)
    events = se.all()
    assert len(events) == 1
    e = events[0]
    assert e.kind == "hunt_recognized"
    assert e.label == "HUNT — RECOGNIZED"
    assert e.register == "ritual"


def test_loop_does_not_fire_for_non_table_classes():
    """No reward rows yet for MAKE/SNEAK/SOLVE/WANDER/RITUAL — counters
    advance but no StateEvent emits."""
    p = PreferenceCounters()
    se = StateEventBuffer()
    loop = ActivityLoop(p, se)
    p.emit(ActivityClass.MAKE, 100)
    p.emit(ActivityClass.SNEAK, 100)
    p.emit(ActivityClass.SOLVE, 100)
    p.emit(ActivityClass.WANDER, 100)
    p.emit(ActivityClass.RITUAL, 100)
    fired = loop.tick(0.0)
    assert fired == []
    assert se.latest_id() == 0


# ── PR 10: UNWIND class wiring ───────────────────────────────────────


def test_unwind_slice_constant_legible():
    """Slice is a positive float; thresholds 30 and 100 yield session-
    legible durations (~5 min and ~17 min at 10s slice)."""
    assert DWELL_UNWIND_SLICE_SECONDS > 0.0
    # If the slice is tuned, the doc comment promised legible durations;
    # this asserts the math is in the legible band (1–60 min for either
    # threshold).
    for threshold in (30, 100):
        seconds = threshold * DWELL_UNWIND_SLICE_SECONDS
        assert 60.0 <= seconds <= 3600.0, (
            f"unwind threshold {threshold} × {DWELL_UNWIND_SLICE_SECONDS}s "
            f"= {seconds}s; expected 1–60 min for legibility"
        )


def test_unwind_recognized_fires_at_30():
    p = PreferenceCounters()
    se = StateEventBuffer()
    loop = ActivityLoop(p, se)
    p.emit(ActivityClass.UNWIND, 29)
    assert loop.tick(0.0) == []
    p.emit(ActivityClass.UNWIND, 1)        # crosses 30
    fired = loop.tick(0.0)
    assert "unwind_recognized" in fired


def test_unwind_deepened_fires_at_100():
    p = PreferenceCounters()
    se = StateEventBuffer()
    loop = ActivityLoop(p, se)
    p.emit(ActivityClass.UNWIND, 30)
    loop.tick(0.0)                          # fires unwind_recognized
    p.emit(ActivityClass.UNWIND, 70)        # total 100, crosses
    fired = loop.tick(0.0)
    assert "unwind_deepened" in fired
    assert "unwind_recognized" not in fired # not re-fired


def test_unwind_emit_label_uses_ritual_register():
    p = PreferenceCounters()
    se = StateEventBuffer()
    loop = ActivityLoop(p, se)
    p.emit(ActivityClass.UNWIND, 30)
    loop.tick(0.0)
    events = se.all()
    assert any(e.kind == "unwind_recognized"
               and e.label == "UNWIND — RECOGNIZED"
               and e.register == "ritual"
               for e in events)


def test_reward_table_has_both_hunt_and_unwind_rows():
    """PR 10 expanded table; rows for HUNT + UNWIND should both exist."""
    classes_with_rows = {row.cls for row in REWARD_TABLE}
    assert ActivityClass.HUNT in classes_with_rows
    assert ActivityClass.UNWIND in classes_with_rows


# ── Module-level singletons ─────────────────────────────────────────


def test_emit_activity_noop_when_not_installed():
    """Producers can call before BrainWorld init without exploding."""
    activity_loop._reset_for_tests()
    activity_loop.emit_activity(ActivityClass.HUNT, 1)
    assert activity_loop.summary() == {"installed": False}


def test_install_idempotent():
    se = StateEventBuffer()
    p1, l1 = activity_loop.install(se)
    p2, l2 = activity_loop.install(se)
    assert p1 is p2
    assert l1 is l2


def test_module_emit_and_tick_after_install():
    se = StateEventBuffer()
    activity_loop.install(se)
    activity_loop.emit_activity(ActivityClass.HUNT, 50)
    fired = activity_loop.tick(0.0)
    assert "hunt_recognized" in fired


def test_summary_shape_includes_all_seven_classes():
    se = StateEventBuffer()
    activity_loop.install(se)
    activity_loop.emit_activity(ActivityClass.RITUAL, 7)
    snap = activity_loop.summary()
    assert snap["installed"] is True
    assert set(snap["counts"].keys()) == {
        "HUNT", "MAKE", "SNEAK", "UNWIND", "SOLVE", "WANDER", "RITUAL"
    }
    assert snap["counts"]["RITUAL"] == 7


def test_summary_reward_rows_match_reward_table():
    se = StateEventBuffer()
    activity_loop.install(se)
    snap = activity_loop.summary()
    assert len(snap["rewards"]) == len(REWARD_TABLE)
    for snap_row, table_row in zip(snap["rewards"], REWARD_TABLE):
        assert snap_row["class"] == table_row.cls.name
        assert snap_row["threshold"] == table_row.threshold
        assert snap_row["kind"] == table_row.kind
