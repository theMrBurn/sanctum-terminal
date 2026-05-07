"""
core/systems/door_animator.py

Door swing animation state machine.

Each door: CLOSED → OPENING → OPEN.
Smoothstep interpolation. Same pattern as pickup_system._Tween.
"""

from __future__ import annotations

from enum import Enum, auto


class DoorState(Enum):
    CLOSED  = auto()
    OPENING = auto()
    OPEN    = auto()


SWING_DURATION = 1.0    # seconds to fully open
SWING_ANGLE    = 90.0   # degrees


def _smoothstep(t: float) -> float:
    """Hermite smoothstep: t²(3 - 2t)"""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


class DoorAnimator:
    """
    Manages swing animation for multiple doors.

    Pure logic — produces angle values for the renderer to apply.
    """

    def __init__(self, door_count: int = 8):
        self._states: dict[int, DoorState] = {}
        self._elapsed: dict[int, float] = {}
        self.door_count = door_count
        self.reset()

    def reset(self):
        """Close all doors."""
        for i in range(self.door_count):
            self._states[i] = DoorState.CLOSED
            self._elapsed[i] = 0.0

    def begin_open(self, door_index: int):
        """Start opening a door."""
        if 0 <= door_index < self.door_count:
            self._states[door_index] = DoorState.OPENING
            self._elapsed[door_index] = 0.0

    def tick(self, dt: float):
        """Advance all animations."""
        for i in range(self.door_count):
            if self._states[i] == DoorState.OPENING:
                self._elapsed[i] += dt
                if self._elapsed[i] >= SWING_DURATION:
                    self._elapsed[i] = SWING_DURATION
                    self._states[i] = DoorState.OPEN

    def get_angle(self, door_index: int) -> float:
        """Current swing angle (0.0 to SWING_ANGLE degrees)."""
        if door_index not in self._states:
            return 0.0
        if self._states[door_index] == DoorState.CLOSED:
            return 0.0
        t = self._elapsed[door_index] / SWING_DURATION
        return _smoothstep(t) * SWING_ANGLE

    def get_state(self, door_index: int) -> DoorState:
        """Current state of a door."""
        return self._states.get(door_index, DoorState.CLOSED)

    def is_open(self, door_index: int) -> bool:
        """True if door has finished opening."""
        return self._states.get(door_index) == DoorState.OPEN

    def is_animating(self) -> bool:
        """True if any door is mid-swing."""
        return any(s == DoorState.OPENING for s in self._states.values())
