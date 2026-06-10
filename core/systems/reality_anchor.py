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
    spaces and truncates with `…` past DETAIL_MAX — never paraphrases."""
    one_line = " ".join((text or "").split())
    if len(one_line) <= DETAIL_MAX:
        return one_line
    return one_line[: DETAIL_MAX - 1].rstrip() + "…"


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
        return Toast("reality_anchor.entry", LABEL_ENTRY, f"“{note}”", DISCOVERY)

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
