"""mood_texture — permanent-objects mood.texture.shifted → Quiet Witness frames.

The "Weather of a Life" atmosphere track. Verifies the directional-diff
dispatch (an absolute snapshot mapped to comparative frames), the boot-prime
that seeds the baseline from history without replaying it, the watermark drain,
and the presentation-only atmosphere read. No bus, no brain — pure mapping.
"""
from __future__ import annotations

from core.systems.mood_texture import (
    FRAME_CALMS,
    FRAME_HARDENS,
    FRAME_RETURNING,
    MoodTexture,
    Shift,
    drain,
    resolve,
)
from core.systems.state_events import DISCOVERY


# -- a minimal fake bus + event (the sanctum_os.bus shape we depend on) --


class _Ev:
    def __init__(self, id, kind, payload, app="permanent-objects"):
        self.id = id
        self.kind = kind
        self.payload = payload
        self.app = app


class _FakeBus:
    def __init__(self, events=None):
        self._events = list(events or [])

    def add(self, ev):
        self._events.append(ev)

    def fetch(self, *, app=None, since_id=0, kind=None, limit=None):
        # id-ASC, since_id watermark — matches the sanctum_os.bus contract.
        return [e for e in sorted(self._events, key=lambda e: e.id)
                if e.id > since_id]


def _tex(valence, intensity, phase="active"):
    return {"window": "7d", "valence": valence, "intensity": intensity,
            "cadence_phase": phase, "confidence": 1.0}


def _shifted(id, valence, intensity, phase="active"):
    return _Ev(id, "mood.texture.shifted", _tex(valence, intensity, phase))


# -- resolve(): the directional dispatch (the correctness crux) -----------


def test_returning_is_absolute_needs_no_prior():
    # cadence_phase == returning is self-contained — frames regardless of prev.
    assert resolve(None, _tex(0.0, 0.0, "returning")) == Shift(
        FRAME_RETURNING, DISCOVERY)
    assert resolve(_tex(0.0, 0.9), _tex(0.0, 0.0, "returning")) == Shift(
        FRAME_RETURNING, DISCOVERY)


def test_intensity_band_rise_hardens():
    # mid (0.5) -> hi (0.8): heavier weather.
    assert resolve(_tex(0.0, 0.5), _tex(0.0, 0.8)) == Shift(
        FRAME_HARDENS, DISCOVERY)


def test_intensity_band_drop_calms():
    # hi (0.8) -> lo (0.2): the air goes still.
    assert resolve(_tex(0.0, 0.8), _tex(0.0, 0.2)) == Shift(
        FRAME_CALMS, DISCOVERY)


def test_valence_drop_hardens_when_intensity_flat():
    # intensity band unchanged (mid); valence hi (0.5) -> lo (-0.5) is heavier.
    assert resolve(_tex(0.5, 0.5), _tex(-0.5, 0.5)) == Shift(
        FRAME_HARDENS, DISCOVERY)


def test_valence_rise_calms_when_intensity_flat():
    # intensity band unchanged (mid); valence lo (-0.5) -> hi (0.5) is lighter.
    assert resolve(_tex(-0.5, 0.5), _tex(0.5, 0.5)) == Shift(
        FRAME_CALMS, DISCOVERY)


def test_first_shift_without_baseline_is_silent():
    # No prior texture and not "returning": update atmosphere, no frame.
    assert resolve(None, _tex(0.0, 0.5, "active")).label == ""


def test_cadence_only_flip_is_silent():
    # Same valence/intensity bands, only active<->quiet: no frame surfaces.
    assert resolve(_tex(0.0, 0.5, "active"),
                   _tex(0.0, 0.5, "quiet")).label == ""


# -- drain(): watermark advance + kind filtering --------------------------


def test_drain_frames_only_shifted_and_advances_watermark_past_all():
    bus = _FakeBus([
        _Ev(1, "entry.added", {"raw_note": "unrelated"}),   # non-KIND
        _shifted(2, 0.0, 0.5, "returning"),                  # -> RETURNING
        _shifted(3, 0.0, 0.9, "active"),                     # mid->hi HARDENS
    ])
    shifts, watermark, prev = drain(bus, 0, None)
    assert [s.label for s in shifts] == [FRAME_RETURNING, FRAME_HARDENS]
    assert watermark == 3                     # advanced past the non-KIND row
    assert prev["intensity"] == 0.9           # baseline advanced to last shift


def test_drain_resumes_from_watermark():
    bus = _FakeBus([
        _shifted(1, 0.0, 0.5, "active"),
        _shifted(2, 0.0, 0.9, "active"),
    ])
    # Already past id 1, baseline at its texture — only id 2 is new.
    shifts, watermark, prev = drain(bus, 1, _tex(0.0, 0.5))
    assert [s.label for s in shifts] == [FRAME_HARDENS]
    assert watermark == 2


# -- MoodTexture: boot-prime, no-replay, live shift, throttle, no-bus -----


def test_boot_primes_past_history_without_replay():
    bus = _FakeBus([
        _shifted(1, 0.0, 0.2, "active"),
        _shifted(2, 0.0, 0.9, "active"),   # latest historical -> the baseline
    ])
    mt = MoodTexture(bus, poll_interval=0.0)
    # No frame for history already on the bus at boot.
    assert mt.poll(now=1.0) == []
    # Atmosphere is seeded from the latest historical shift (presentation read).
    assert mt.atmosphere["intensity"] == 0.9


def test_live_shift_after_boot_frames_directionally():
    bus = _FakeBus([_shifted(1, 0.0, 0.9, "active")])   # baseline: intensity hi
    mt = MoodTexture(bus, poll_interval=0.0)
    assert mt.poll(now=1.0) == []                        # nothing new yet
    bus.add(_shifted(2, 0.0, 0.2, "active"))             # hi -> lo: calms
    shifts = mt.poll(now=2.0)
    assert [s.label for s in shifts] == [FRAME_CALMS]
    assert mt.atmosphere["intensity"] == 0.2


def test_poll_is_throttled():
    bus = _FakeBus([_shifted(1, 0.0, 0.5, "active")])
    mt = MoodTexture(bus, poll_interval=100.0)
    bus.add(_shifted(2, 0.0, 0.9, "active"))
    assert mt.poll(now=50.0) == []      # within the throttle window
    assert mt.poll(now=150.0)           # window elapsed -> drains


def test_no_bus_is_inert():
    mt = MoodTexture(None)
    assert mt.poll(now=999.0) == []
    assert mt.atmosphere is None
