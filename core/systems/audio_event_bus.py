"""
core/systems/audio_event_bus.py

Control voltage event bus — captures every render event that SHOULD produce audio.
No sound. No OSC. Just the blueprint: events fire, listeners receive, tests verify.

Every possible contact the video renderer makes is mapped here as a CV pulse.
When the audio engine hooks in, it subscribes and translates to OSC/MIDI.

Architecture:
    Renderer → AudioEventBus.emit(event) → listeners[] → (future: OSC out)

CV event types mirror audio signal flow:
    GATE    — on/off (note on, note off)
    TRIGGER — momentary pulse (percussive hit, contact)
    CV      — continuous value (proximity, velocity, phase)
    CC      — control change (register switch, day/night, fog density)
"""

from collections import deque


# -- CV Event Types ------------------------------------------------------------

GATE = "gate"         # sustained on/off (entity wake/sleep, band enter/exit)
TRIGGER = "trigger"   # momentary pulse (contact, step, collision)
CV = "cv"             # continuous 0.0-1.0 (proximity, velocity, blend)
CC = "cc"             # control change (global state shifts)


# -- Every possible render event that should produce audio ---------------------

EVENT_CATALOG = {
    # Entity lifecycle
    "entity.wake":              GATE,     # entity enters wake radius
    "entity.sleep":             GATE,     # entity exits sleep radius
    "entity.band_enter":        GATE,     # entity enters LOD band (1, 2, or 3)
    "entity.band_exit":         GATE,     # entity exits LOD band
    "entity.band_crossfade":    CV,       # alpha during band transition (0.0→1.0)

    # Membrane events
    "membrane.decal_on":        GATE,     # decal activates (glow pool appears)
    "membrane.decal_off":       GATE,     # decal deactivates
    "membrane.mote_spawn":      TRIGGER,  # mote group spawned

    # Player movement
    "player.step":              TRIGGER,  # footfall (periodic based on velocity)
    "player.velocity":          CV,       # movement speed 0.0→1.0 (normalized)
    "player.heading_delta":     CV,       # turning rate (look speed)
    "player.altitude_delta":    CV,       # height change (slope traversal)

    # Proximity (continuous)
    "proximity.nearest":        CV,       # distance to nearest entity (normalized)
    "proximity.density":        CV,       # entity count in near band (normalized)

    # Chunk/tile transitions
    "chunk.enter":              TRIGGER,  # stepped onto new chunk
    "chunk.build":              TRIGGER,  # new chunk materialized
    "chunk.despawn":            TRIGGER,  # chunk removed
    "tile.enter":               TRIGGER,  # crossed 288m tile boundary
    "tile.build":               TRIGGER,  # new tile queued

    # Contact (future: collision response)
    "contact.hard":             TRIGGER,  # collide with boulder/column/stalagmite
    "contact.soft":             TRIGGER,  # brush against moss/grass/vine
    "contact.creature":         TRIGGER,  # near-miss with rat/beetle/spider
    "contact.surface":          TRIGGER,  # foot-to-ground type change

    # Environment
    "chrono.phase":             CC,       # day/night phase change (dawn/day/dusk/night)
    "chrono.night_weight":      CV,       # 0.0 (noon) → 1.0 (midnight), continuous
    "chrono.moon_phase":        CV,       # 0.0 (new) → 0.5 (full) → 1.0 (new)
    "register.switch":          CC,       # visual register changed (survival/tron/etc)
    "fog.density":              CV,       # current fog near/far as normalized value

    # Torch
    "torch.flicker":            CV,       # flicker intensity (sin modulation value)
    "torch.proximity":          CV,       # how close nearest entity is to torch center
}


# -- Event data ----------------------------------------------------------------

class AudioEvent:
    """Single CV pulse. Immutable after creation."""
    __slots__ = ("name", "kind", "value", "channel", "note", "velocity",
                 "entity_kind", "pos", "timestamp")

    def __init__(self, name, kind, value=1.0, channel=0, note=60,
                 velocity=100, entity_kind=None, pos=None, timestamp=0.0):
        self.name = name
        self.kind = kind
        self.value = value          # 0.0-1.0 for CV/CC, 1=on/0=off for GATE
        self.channel = channel      # 1-8 mapped from AUDIO_GHOST_SEEDS
        self.note = note            # MIDI note
        self.velocity = velocity    # 0-127
        self.entity_kind = entity_kind  # "rat", "crystal_cluster", etc.
        self.pos = pos              # (x, y, z) world position
        self.timestamp = timestamp  # game time


# -- Bus -----------------------------------------------------------------------

class AudioEventBus:
    """Collects CV events from the renderer. Listeners subscribe by event name or pattern.

    Usage:
        bus = AudioEventBus()
        bus.subscribe("entity.*", my_callback)
        bus.emit("entity.wake", value=1.0, channel=3, entity_kind="crystal_cluster")
        # my_callback receives AudioEvent

        # Or batch-read for testing:
        events = bus.drain()  # returns and clears buffer
    """

    def __init__(self, buffer_size=512):
        self._listeners = {}          # pattern -> [callback, ...]
        self._buffer = deque(maxlen=buffer_size)  # ring buffer for TDD drain
        self._clock = 0.0
        self._enabled = True

    def subscribe(self, pattern, callback):
        """Subscribe to events. Pattern: exact name or prefix with '*' (e.g. 'entity.*')."""
        if pattern not in self._listeners:
            self._listeners[pattern] = []
        self._listeners[pattern].append(callback)

    def unsubscribe(self, pattern, callback):
        """Remove a specific callback from a pattern."""
        if pattern in self._listeners:
            self._listeners[pattern] = [cb for cb in self._listeners[pattern] if cb is not callback]

    def emit(self, name, value=1.0, channel=0, note=60, velocity=100,
             entity_kind=None, pos=None):
        """Fire a CV event. Dispatches to matching listeners + buffer."""
        if not self._enabled:
            return
        kind = EVENT_CATALOG.get(name, TRIGGER)
        event = AudioEvent(
            name=name, kind=kind, value=value, channel=channel,
            note=note, velocity=velocity, entity_kind=entity_kind,
            pos=pos, timestamp=self._clock,
        )
        self._buffer.append(event)
        self._dispatch(event)

    def tick(self, dt):
        """Advance internal clock."""
        self._clock += dt

    def drain(self):
        """Return all buffered events and clear. Primary TDD interface."""
        events = list(self._buffer)
        self._buffer.clear()
        return events

    def drain_named(self, name):
        """Return only events matching a name, remove them from buffer."""
        matched = [e for e in self._buffer if e.name == name]
        self._buffer = deque(
            (e for e in self._buffer if e.name != name),
            maxlen=self._buffer.maxlen,
        )
        return matched

    def count(self, name=None):
        """Count buffered events, optionally filtered by name."""
        if name is None:
            return len(self._buffer)
        return sum(1 for e in self._buffer if e.name == name)

    def last(self, name=None):
        """Most recent event, optionally filtered by name."""
        if name is None:
            return self._buffer[-1] if self._buffer else None
        for e in reversed(self._buffer):
            if e.name == name:
                return e
        return None

    def clear(self):
        """Flush buffer."""
        self._buffer.clear()

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    def _dispatch(self, event):
        """Route event to matching listeners."""
        for pattern, callbacks in self._listeners.items():
            if self._matches(pattern, event.name):
                for cb in callbacks:
                    cb(event)

    @staticmethod
    def _matches(pattern, name):
        """Simple pattern match: exact or prefix.* glob."""
        if pattern == name:
            return True
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            return name.startswith(prefix + ".")
        if pattern == "*":
            return True
        return False
