"""Reality-anchor mapper — permanent-objects bus events → ambient toasts.

Feel-first slice (no quests): verifies the verbatim weaving, the no-literal-
date rule, the confirmed-lingers / guess-fades register split, and the
non-blocking watermark drain. No bus, no brain — pure mapping.
"""
from __future__ import annotations

from core.systems.reality_anchor import (
    DETAIL_MAX,
    LABEL_CONTACT,
    LABEL_ENTRY,
    LABEL_EVENT_FIRM,
    LABEL_EVENT_HAZY,
    Toast,
    drain,
    event_to_toast,
)
from core.systems.state_events import DISCOVERY, SYSTEM


# -- a minimal fake bus + event (the sanctum_os.bus shape we depend on) --


class _Ev:
    def __init__(self, id, kind, payload):
        self.id = id
        self.kind = kind
        self.payload = payload


class _FakeBus:
    def __init__(self, events):
        self._events = events

    def fetch(self, *, app=None, since_id=0, kind=None, limit=None):
        return [e for e in self._events if e.id > since_id]


# -- per-event mapping ---------------------------------------------------


def test_entry_added_frames_raw_note_verbatim():
    t = event_to_toast("entry.added", {"raw_note": "left the kettle on again"})
    assert t.label == LABEL_ENTRY
    assert t.detail == '"left the kettle on again"'   # verbatim, ASCII-framed
    assert t.register == DISCOVERY                      # a fact — it lingers


def test_contact_seen_surfaces_name_verbatim():
    t = event_to_toast("contact.seen", {"name": "Sarah Chen"})
    assert t.label == LABEL_CONTACT
    assert t.detail == "Sarah Chen"
    assert t.register == DISCOVERY


def test_calendar_added_is_firm_and_lingers():
    t = event_to_toast(
        "calendar.event.added",
        {"title": "dentist", "when_start": "2026-06-16 09:00"},
    )
    assert t.label == LABEL_EVENT_FIRM
    assert t.detail == "dentist"
    assert t.register == DISCOVERY


def test_calendar_extracted_is_hazy_and_fades():
    t = event_to_toast(
        "calendar.event.extracted",
        {"title": "Call dentist next Tuesday", "when_start": None},
    )
    assert t.label == LABEL_EVENT_HAZY
    assert t.register == SYSTEM                          # a guess — fades fast


def test_no_event_ever_surfaces_a_literal_date():
    # The spell-breaker: a raw date integer must never reach the toast.
    for kind, payload in [
        ("calendar.event.added", {"title": "dentist", "when_start": "2026-06-16"}),
        ("calendar.event.extracted", {"title": "soon", "when_start": "2026-06-16"}),
    ]:
        t = event_to_toast(kind, payload)
        assert t is not None
        assert "2026" not in (t.label + (t.detail or ""))


def test_confirmed_carries_no_title_so_nothing_surfaces():
    # confirmed payload is {event_id, when_start} — no verbatim text.
    assert event_to_toast("calendar.event.confirmed", {"event_id": 1}) is None


def test_below_threshold_and_empty_events_drop():
    assert event_to_toast("lexicon.term.added", {"term": "kettle"}) is None
    assert event_to_toast("seed.added", {"term": "x", "category": "y"}) is None
    assert event_to_toast("entry.added", {"raw_note": "   "}) is None
    assert event_to_toast("contact.seen", {"name": ""}) is None


def test_long_note_clamps_with_ascii_ellipsis_not_paraphrase():
    long = "x" * (DETAIL_MAX + 50)
    t = event_to_toast("entry.added", {"raw_note": long})
    inner = t.detail.strip('"')
    assert inner.endswith("...")                        # ASCII, not U+2026
    assert inner[:-3] == "x" * (DETAIL_MAX - 3)         # verbatim prefix, just clamped


def test_injected_chars_are_pure_ascii():
    # The bug that shipped: smart quotes / `…` render as `?` in the CRT
    # font. Guard every label + injected frame against non-ASCII.
    samples = [
        ("entry.added", {"raw_note": "a note"}),
        ("contact.seen", {"name": "Ada"}),
        ("calendar.event.added", {"title": "dentist"}),
        ("calendar.event.extracted", {"title": "x" * (DETAIL_MAX + 5)}),
    ]
    for kind, payload in samples:
        t = event_to_toast(kind, payload)
        for s in (t.label, t.detail):
            s.encode("ascii")  # raises UnicodeEncodeError if a glyph would `?`-out


# -- drain / watermark ---------------------------------------------------


def test_drain_maps_and_advances_watermark_past_all_events():
    bus = _FakeBus([
        _Ev(5, "entry.added", {"raw_note": "a thought"}),
        _Ev(6, "lexicon.term.added", {"term": "thought"}),   # below threshold
        _Ev(7, "contact.seen", {"name": "Mara"}),
    ])
    toasts, new_last = drain(bus, last_id=4)
    # Two surface; the below-threshold one is skipped...
    assert [t.label for t in toasts] == [LABEL_ENTRY, LABEL_CONTACT]
    # ...but the watermark still advances past it, so it's never re-seen.
    assert new_last == 7


def test_drain_is_idempotent_at_watermark():
    bus = _FakeBus([_Ev(2, "contact.seen", {"name": "Ada"})])
    toasts, new_last = drain(bus, last_id=2)   # already past it
    assert toasts == []
    assert new_last == 2


# -- RealityAnchor pump (throttle + boot-history skip) ------------------


def test_anchor_skips_boot_history():
    from core.systems.reality_anchor import RealityAnchor
    bus = _FakeBus([
        _Ev(1, "entry.added", {"raw_note": "old note"}),
        _Ev(2, "contact.seen", {"name": "Old Friend"}),
    ])
    anchor = RealityAnchor(bus)                 # watermark inits to 2 (max)
    assert anchor.poll(now=100.0) == []         # pre-existing history never surfaces


def test_anchor_surfaces_only_new_events_and_throttles():
    from core.systems.reality_anchor import RealityAnchor
    events = [_Ev(1, "entry.added", {"raw_note": "old"})]
    bus = _FakeBus(events)
    anchor = RealityAnchor(bus, poll_interval=2.0)
    assert anchor.poll(now=10.0) == []          # only history so far

    # A new organizer event lands AFTER boot.
    events.append(_Ev(2, "contact.seen", {"name": "Mara"}))
    assert anchor.poll(now=10.5) == []          # throttled — within interval
    out = anchor.poll(now=12.1)                 # past interval → surfaces
    assert [t.label for t in out] == [LABEL_CONTACT]
    assert anchor.poll(now=14.5) == []          # nothing new since


def test_anchor_none_bus_is_silent():
    from core.systems.reality_anchor import RealityAnchor
    anchor = RealityAnchor(None)
    assert anchor.poll(now=999.0) == []
