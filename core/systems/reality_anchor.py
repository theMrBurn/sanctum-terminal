"""permanent-objects bus → ambient StateEvents — the reality anchor.

The user's real personal-organizer data (the `permanent-objects` sanctum-os
app, on the shared bus at ~/.sanctum-os/events.db) bleeds into Sanctum as
fleeting ambient atmosphere. This is the FEEL-FIRST slice: no quests yet —
just the world noticing. The brain drains new `permanent-objects` events
each loop and emits one StateEvent toast per surfacing event. Quests come
in a later slice (`from_journal.py` is the bridge that will grow them).

Voice (per cultural-eccentric `voice_reality_anchor_toasts`; repo Hard rule
"copy echoes her writing, never D&D-tutorial"): the toast is the WORLD
noticing, not the game prompting — Elite-diegetic, quiet, a little uncanny.
Names, notes, and titles are woven in VERBATIM (raw_note is canon); the
display clamp truncates with `…` rather than paraphrase, exactly as
`from_journal.py` does. Dates are NEVER printed as integers — that would
snap the spell into engineer-voice; the confirmed/guessed distinction is
carried by the wording + register, not by surfacing a number. Committed
facts linger (DISCOVERY register); machine guesses fade fast (SYSTEM).

NO LLM (air-gap) — pure mapping over bus payloads. spaCy did the cooking
upstream in permanent-objects; here we only frame what it surfaced.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.systems.state_events import DISCOVERY, SYSTEM

# The permanent-objects app name on the shared bus.
PO_APP = "permanent-objects"

# Verbatim-detail display clamp. Matches from_journal.py's `…`-truncation
# convention — a display clamp ONLY, never a paraphrase. Generous so most
# notes surface whole.
DETAIL_MAX = 120

# ALL-CAPS evocative labels — CRT-terminal house style (state_events.py).
# Copy from the cultural-eccentric voice pass; this block is the single
# source of truth for the reality-anchor's wording. Tune it here.
LABEL_ENTRY = "SOMETHING HELD"            # a journal note surfaced
LABEL_CONTACT = "A NAME SURFACES"         # a person lifted from the prose
LABEL_EVENT_FIRM = "THE WORLD HOLDS A DATE"  # a committed/added date
LABEL_EVENT_HAZY = "A DATE HALF-FORMS"    # a guessed/unconfirmed date


@dataclass(frozen=True)
class Toast:
    """A resolved ambient toast, ready to hand to StateEventBuffer.emit."""

    kind: str            # routing key, e.g. "reality_anchor.entry"
    label: str
    detail: str | None
    register: str        # DISCOVERY (lingers) | SYSTEM (quick fade)


def _clamp(text: str) -> str:
    """One-line, verbatim-preserving display clamp. Collapses newlines to
    spaces and truncates with `...` past DETAIL_MAX — never paraphrases.

    ASCII-only on the injected chars: the vector terminal's bitmap CRT font
    has no glyphs for typographic punctuation (smart quotes, `…`), which
    render as `?`. The verbatim text itself is left untouched."""
    one_line = " ".join((text or "").split())
    if len(one_line) <= DETAIL_MAX:
        return one_line
    return one_line[: DETAIL_MAX - 3].rstrip() + "..."


def event_to_toast(kind: str, payload: dict | None) -> Toast | None:
    """Map one permanent-objects bus event to an ambient Toast, or None if
    it doesn't surface in the world.

    Confirmed facts (a note you wrote, a name, a date you set) linger via
    DISCOVERY; a machine-guessed date half-forms and fades via SYSTEM. No
    event ever surfaces a literal date integer.
    """
    p = payload or {}

    if kind == "entry.added":
        note = _clamp(p.get("raw_note", ""))
        if not note:
            return None
        return Toast("reality_anchor.entry", LABEL_ENTRY, f'"{note}"', DISCOVERY)

    if kind in ("contact.seen", "contact.added"):
        name = (p.get("name") or "").strip()
        if not name:
            return None
        return Toast("reality_anchor.contact", LABEL_CONTACT, name, DISCOVERY)

    if kind == "calendar.event.added":
        title = _clamp(p.get("title", ""))
        if not title:
            return None
        return Toast("reality_anchor.event", LABEL_EVENT_FIRM, title, DISCOVERY)

    if kind == "calendar.event.extracted":
        title = _clamp(p.get("title", ""))
        if not title:
            return None
        return Toast("reality_anchor.event_hazy", LABEL_EVENT_HAZY, title, SYSTEM)

    # calendar.event.confirmed carries no title (just event_id + date), so
    # there's nothing verbatim to surface — the .added/.extracted toast
    # already announced it. lexicon.term.added / seed.added are below the
    # ambient threshold for now.
    return None


# How often the brain polls the bus for new permanent-objects events.
# Ambient toasts tolerate seconds of latency; this keeps SQLite reads off
# the hot per-frame path. Named const per the "no hardcoded tunables" rule.
POLL_INTERVAL_S = 2.0


def _current_max_id(bus) -> int:
    """Highest event id currently on the bus (0 if empty/unreadable).

    Used to set the boot watermark PAST all history, so a brain start never
    floods the player with toasts for organizer activity that already
    happened. Events are id-ASC, so the last row is the max."""
    try:
        rows = bus.fetch()
        return rows[-1].id if rows else 0
    except Exception:
        return 0


class RealityAnchor:
    """Brain-side pump: holds the bus handle, a watermark, and a throttle.

    `poll(now)` returns new ambient toasts for the brain to emit — non-
    blocking and throttled to POLL_INTERVAL_S. The watermark starts past
    all existing history (boot doesn't replay), then advances past every
    event each poll so nothing is seen twice. Purely additive: if the bus
    is unavailable the brain runs untouched (see `create`)."""

    def __init__(self, bus, *, poll_interval: float = POLL_INTERVAL_S) -> None:
        self._bus = bus
        self._interval = poll_interval
        self._last_poll = 0.0
        self._watermark = _current_max_id(bus)

    def poll(self, now: float) -> list[Toast]:
        if self._bus is None:
            return []
        if now - self._last_poll < self._interval:
            return []
        self._last_poll = now
        try:
            toasts, self._watermark = drain(self._bus, self._watermark)
        except Exception:
            # A bus read hiccup must never stall or crash the brain loop.
            return []
        return toasts


def create(*, app: str = "sanctum-terminal"):
    """Build a RealityAnchor on the shared sanctum-os bus, or return None if
    the bus isn't available (sanctum_os.bus not installed, no bus file). The
    brain treats None as "reality anchor off" and runs normally."""
    try:
        from sanctum_os.bus import Bus
        bus = Bus(app=app)
    except Exception:
        return None
    return RealityAnchor(bus)


def drain(bus, last_id: int) -> tuple[list[Toast], int]:
    """Fetch new permanent-objects events since `last_id`, resolve each to a
    Toast (dropping non-surfacing ones), and return (toasts, new_watermark).

    `bus` is anything exposing `.fetch(app=..., since_id=...) -> [Event]`
    where Event has `.id`, `.kind`, `.payload` (the sanctum_os.bus contract).
    Pure and non-blocking — the brain calls this each loop with its stored
    watermark; the watermark advances past EVERY event, surfacing or not, so
    a below-threshold event is never re-examined.
    """
    toasts: list[Toast] = []
    new_last = last_id
    for ev in bus.fetch(app=PO_APP, since_id=last_id):
        new_last = max(new_last, ev.id)
        toast = event_to_toast(ev.kind, ev.payload)
        if toast is not None:
            toasts.append(toast)
    return toasts, new_last
