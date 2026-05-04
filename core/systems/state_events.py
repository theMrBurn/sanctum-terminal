"""StateEvent — universal player-feedback primitive.

Every brain state change the player should know about emits a StateEvent.
Vector terminal (and future renderers) consume them off the manifest and
render context-appropriate toasts. One primitive, infinite registrations.

Per the UAT-driven design directive: every state change is a feedback
event. Pillar seals, state transitions, mission events, save writes,
reconnects all become single-line registrations on the brain side.

Design notes
------------
- Monotonic `id` per event so clients can track watermarks ("last seen")
  and suppress historical events on first connect (no toast spam).
- Ring buffer caps memory at MAX_BUFFERED. Older events drop off; clients
  that miss them via slow polling lose only the oldest.
- `register` field drives client-side timing (per `design_dial_input`'s
  atmospheric register table extended): ritual/loop/system/tense/discovery.
- `kind` field is for routing logic and audio mapping (eventual).
- `label` is short, ALL-CAPS, evocative (CRT terminal aesthetic).
- `detail` is optional second line for context.

Cross-references
- `design_dial_input` — same register vocabulary
- `feedback_visual_demo` — the player needs to SEE state change
- `design_brain_ground_truth` — brain ships truth; client renders
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


# Register vocabulary — drives client-side toast timing curves
RITUAL = "ritual"        # slow breath; sacred moments (pillar seals)
LOOP = "loop"            # normal pacing; mission/state transitions
SYSTEM = "system"        # quick blip; saves, reconnects
TENSE = "tense"          # tight kinetic; encounter starts/parley
DISCOVERY = "discovery"  # lingering; lexicon recognition, voice echo


# Default ring buffer capacity — last 8 events ride on every manifest.
# Tunable per-deployment if needed; not a load-bearing number.
MAX_BUFFERED = 8


@dataclass(frozen=True)
class StateEvent:
    id: int             # monotonic, brain-assigned
    timestamp: float
    kind: str           # routing key: "pillar_sealed", "state_transition", ...
    label: str          # short evocative top line ("PILLAR SEALED · NAME")
    detail: str | None  # optional second line ("themrburn · age 30")
    register: str       # client renderer hint


class StateEventBuffer:
    """Ring buffer of recent state events with monotonic id assignment.

    Pure data structure. Brain owns one instance; emits on every state
    change worth player feedback. Manifest serializes the current contents
    each frame.
    """

    def __init__(self, capacity: int = MAX_BUFFERED) -> None:
        self._capacity = capacity
        self._events: list[StateEvent] = []
        self._next_id = 1

    def emit(
        self,
        kind: str,
        label: str,
        detail: str | None = None,
        register: str = SYSTEM,
    ) -> StateEvent:
        """Append a new event with the next monotonic id. Returns the event."""
        evt = StateEvent(
            id=self._next_id,
            timestamp=time.time(),
            kind=kind,
            label=label,
            detail=detail,
            register=register,
        )
        self._next_id += 1
        self._events.append(evt)
        if len(self._events) > self._capacity:
            # Drop the oldest; clients past the watermark won't notice
            self._events = self._events[-self._capacity:]
        return evt

    def all(self) -> list[StateEvent]:
        return list(self._events)

    def latest_id(self) -> int:
        return self._events[-1].id if self._events else 0


def to_manifest(buffer: StateEventBuffer) -> list[dict[str, Any]]:
    """Serialize buffer contents for transmission in the manifest."""
    return [
        {
            "id": e.id,
            "timestamp": e.timestamp,
            "kind": e.kind,
            "label": e.label,
            "detail": e.detail,
            "register": e.register,
        }
        for e in buffer.all()
    ]
