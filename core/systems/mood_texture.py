"""permanent-objects `mood.texture.shifted` → ambient "Weather of a Life".

The aggregate TEXTURE of the user's recent journaling (the `permanent-objects`
sanctum-os app, on the shared bus at ~/.sanctum-os/events.db) bleeds into
Sanctum as atmosphere — the world quietly noticing the weather of a life. This
is the reality-anchor's mood track, distinct from the per-entry surfacing:
no name, note, or date rides here; the payload carries only texture bands.

Register — "Quiet Witness" (ratified 2026-07-02,
`docs/reference/reality_anchor_narration_register.md` in the /git workspace):
the world observes in present-tense, sparse, no-second-person frames. These
lines carry NO verbatim span (atmosphere, not authorship). The frames are a
static table — a deterministic template, NOT a model call (keeps the no-LLM
line). permanent-objects did the cooking upstream (severity/recency/cadence,
no sentiment model); here we only frame the shift it surfaced.

Texture, not score (§2.1 of the narrative-runtime design; texture.py at the
source): the atmosphere biases presentation only — palette / density / weather
a renderer may tint from `MoodTexture.atmosphere`. It never loops back into
engine or truth state, so it cannot be farmed into a quantity.

Directional frames from an absolute snapshot: the payload is a snapshot
(`valence`/`intensity`/`cadence_phase`), but "hardens" and "calms" are
comparative. So the consumer holds the last-seen texture and diffs bands
against it — seeded at boot from the latest historical shift, so the first
NEW shift after a cold start diffs against real ground rather than nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.systems.state_events import DISCOVERY

# The permanent-objects app name on the shared bus, and the one kind we frame.
PO_APP = "permanent-objects"
KIND = "mood.texture.shifted"

# Quiet Witness frame lines. Sentence case, NOT the ALL-CAPS house style:
# this ratified per-surface register is the specific contract and outranks
# the general state_events convention (the vector-terminal renderer prints
# the label as-is, no force-uppercase). No span — pure engine class.
FRAME_RETURNING = "The pages open again."   # cadence_phase == returning
FRAME_HARDENS = "The weather turns."        # texture toward heavy
FRAME_CALMS = "The air goes still."         # texture toward calm

# Band thresholds — MUST mirror permanent_objects/texture.py `signature()`,
# so our diff bands line up with the source's band-gated emit signature.
VAL_LO, VAL_HI = -0.33, 0.33
INT_LO, INT_HI = 0.33, 0.66

_RANK = {"lo": 0, "mid": 1, "hi": 2}


def _band(x: float, lo: float, hi: float) -> str:
    return "lo" if x < lo else ("hi" if x > hi else "mid")


def _bands(texture: dict) -> tuple[str, str]:
    """(valence_band, intensity_band) for a texture payload."""
    return (
        _band(float(texture.get("valence", 0.0)), VAL_LO, VAL_HI),
        _band(float(texture.get("intensity", 0.0)), INT_LO, INT_HI),
    )


@dataclass(frozen=True)
class Shift:
    """A resolved atmosphere line, ready for StateEventBuffer.emit. `label`
    is "" when the shift updates atmosphere silently (no frame surfaces)."""

    label: str
    register: str


def resolve(prev: dict | None, texture: dict) -> Shift:
    """Map one `mood.texture.shifted` payload to a Quiet Witness frame.

    Priority:
      1. cadence_phase == "returning" — self-contained (absolute), always the
         "pages open again" frame regardless of prior texture.
      2. else diff bands vs `prev`: a rise in intensity band (heavier), or —
         if intensity is unchanged — a drop in valence band (heavier), reads
         as HARDENS; the reverse reads as CALMS. Intensity leads because it is
         the mean-severity driver; valence is the coarse secondary lean.
      3. else (only cadence flipped active<->quiet, same valence/intensity
         bands; or no baseline yet on first-ever shift) — silent bias update,
         no frame.
    """
    if texture.get("cadence_phase") == "returning":
        return Shift(FRAME_RETURNING, DISCOVERY)

    if prev is not None:
        pv, pi = _bands(prev)
        nv, ni = _bands(texture)
        if ni != pi:
            harden = _RANK[ni] > _RANK[pi]
            return Shift(FRAME_HARDENS if harden else FRAME_CALMS, DISCOVERY)
        if nv != pv:
            harden = _RANK[nv] < _RANK[pv]  # lower valence == heavier
            return Shift(FRAME_HARDENS if harden else FRAME_CALMS, DISCOVERY)

    return Shift("", DISCOVERY)


# How often the brain polls the bus. Ambient atmosphere tolerates seconds of
# latency; this keeps SQLite reads off the hot per-frame path.
POLL_INTERVAL_S = 2.0


def _current_max_id(bus) -> int:
    """Highest event id on the bus (0 if empty/unreadable). Sets the boot
    watermark PAST all history so a brain start never replays old shifts as
    a burst of atmosphere lines. Events are id-ASC; the last row is the max."""
    try:
        rows = bus.fetch()
        return rows[-1].id if rows else 0
    except Exception:
        return 0


def _latest_texture(bus) -> dict | None:
    """The most recent historical `mood.texture.shifted` payload, or None.
    Seeds the diff baseline at boot (no frame emitted), so the first NEW shift
    reads a real direction instead of falling through to a silent update."""
    try:
        rows = [e for e in bus.fetch(app=PO_APP) if e.kind == KIND]
        return rows[-1].payload if rows else None
    except Exception:
        return None


def drain(bus, last_id: int, prev: dict | None):
    """Fetch permanent-objects events since `last_id`; frame each
    `mood.texture.shifted` (directional diff vs the running `prev`) and advance
    the baseline past every shift. Returns (shifts, new_watermark, new_prev).

    The watermark advances past EVERY permanent-objects event (surfacing or
    not), so a below-threshold or unrelated event is never re-examined —
    matching the reality-anchor drain contract.
    """
    shifts: list[Shift] = []
    new_last = last_id
    new_prev = prev
    for ev in bus.fetch(app=PO_APP, since_id=last_id):
        new_last = max(new_last, ev.id)
        if ev.kind != KIND:
            continue
        payload = ev.payload or {}
        shift = resolve(new_prev, payload)
        new_prev = payload  # advance baseline past this shift
        if shift.label:
            shifts.append(shift)
    return shifts, new_last, new_prev


class MoodTexture:
    """Brain-side pump for the "Weather of a Life" atmosphere.

    `poll(now)` returns new Quiet Witness frames to emit — non-blocking and
    throttled to POLL_INTERVAL_S. `atmosphere` exposes the latest texture bands
    for a renderer to tint from (presentation-only; never engine truth). If the
    bus is unavailable the brain runs untouched (see `create`)."""

    def __init__(self, bus, *, poll_interval: float = POLL_INTERVAL_S) -> None:
        self._bus = bus
        self._interval = poll_interval
        self._last_poll = 0.0
        self._watermark = _current_max_id(bus)
        # Seed the diff baseline from history WITHOUT emitting a frame.
        self._prev = _latest_texture(bus)

    @property
    def atmosphere(self) -> dict | None:
        """Latest texture snapshot (bands), or None before any is known.
        Read-only presentation data — renderers tint from it; nothing writes
        back through it."""
        return self._prev

    def poll(self, now: float) -> list[Shift]:
        if self._bus is None:
            return []
        if now - self._last_poll < self._interval:
            return []
        self._last_poll = now
        try:
            shifts, self._watermark, self._prev = drain(
                self._bus, self._watermark, self._prev)
        except Exception:
            # A bus hiccup must never stall or crash the brain loop.
            return []
        return shifts


def create(*, app: str = "sanctum-terminal"):
    """Build a MoodTexture on the shared sanctum-os bus, or return None if the
    bus isn't available (sanctum_os.bus not installed, no bus file). The brain
    treats None as "weather off" and runs normally."""
    try:
        from sanctum_os.bus import Bus
        bus = Bus(app=app)
    except Exception:
        return None
    return MoodTexture(bus)
