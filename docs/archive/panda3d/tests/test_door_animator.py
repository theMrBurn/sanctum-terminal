"""
tests/test_door_animator.py

Door swing animation state machine.
"""

import pytest

from core.systems.door_animator import (
    DoorAnimator, DoorState,
    SWING_DURATION, SWING_ANGLE, _smoothstep,
)


class TestSmoothstep:

    def test_zero(self):
        assert _smoothstep(0.0) == 0.0

    def test_one(self):
        assert _smoothstep(1.0) == 1.0

    def test_half_is_half(self):
        assert _smoothstep(0.5) == pytest.approx(0.5)

    def test_not_linear_at_quarter(self):
        """Smoothstep at 0.25 should NOT be 0.25 (it's cubic)."""
        assert _smoothstep(0.25) != pytest.approx(0.25, abs=0.01)

    def test_clamps_negative(self):
        assert _smoothstep(-1.0) == 0.0

    def test_clamps_above_one(self):
        assert _smoothstep(2.0) == 1.0


class TestDoorAnimator:

    def test_starts_closed(self):
        anim = DoorAnimator(door_count=8)
        assert anim.get_angle(0) == 0.0
        assert anim.get_state(0) == DoorState.CLOSED

    def test_begin_open_starts_animation(self):
        anim = DoorAnimator(door_count=8)
        anim.begin_open(3)
        assert anim.get_state(3) == DoorState.OPENING

    def test_tick_advances_angle(self):
        anim = DoorAnimator(door_count=8)
        anim.begin_open(0)
        anim.tick(0.5)
        angle = anim.get_angle(0)
        assert 0 < angle < SWING_ANGLE

    def test_completes_at_swing_angle(self):
        anim = DoorAnimator(door_count=8)
        anim.begin_open(0)
        anim.tick(SWING_DURATION + 0.1)
        assert anim.get_angle(0) == pytest.approx(SWING_ANGLE)

    def test_is_open_after_duration(self):
        anim = DoorAnimator(door_count=8)
        anim.begin_open(0)
        anim.tick(SWING_DURATION + 0.1)
        assert anim.is_open(0) is True
        assert anim.get_state(0) == DoorState.OPEN

    def test_not_open_before_duration(self):
        anim = DoorAnimator(door_count=8)
        anim.begin_open(0)
        anim.tick(0.3)
        assert anim.is_open(0) is False

    def test_reset_closes_all(self):
        anim = DoorAnimator(door_count=8)
        anim.begin_open(0)
        anim.begin_open(5)
        anim.tick(SWING_DURATION + 0.1)
        anim.reset()
        assert anim.get_angle(0) == 0.0
        assert anim.get_angle(5) == 0.0
        assert anim.get_state(0) == DoorState.CLOSED

    def test_is_animating_during_swing(self):
        anim = DoorAnimator(door_count=8)
        anim.begin_open(2)
        anim.tick(0.1)
        assert anim.is_animating() is True

    def test_not_animating_when_closed(self):
        anim = DoorAnimator(door_count=8)
        assert anim.is_animating() is False

    def test_not_animating_when_open(self):
        anim = DoorAnimator(door_count=8)
        anim.begin_open(0)
        anim.tick(SWING_DURATION + 0.1)
        assert anim.is_animating() is False

    def test_smoothstep_not_linear(self):
        """At half duration, angle should be exactly half due to smoothstep(0.5)=0.5."""
        anim = DoorAnimator(door_count=8)
        anim.begin_open(0)
        anim.tick(SWING_DURATION / 2)
        assert anim.get_angle(0) == pytest.approx(SWING_ANGLE / 2)

    def test_multiple_doors_independent(self):
        anim = DoorAnimator(door_count=8)
        anim.begin_open(0)
        anim.tick(0.5)
        anim.begin_open(3)
        anim.tick(0.2)
        # Door 0 has been ticking for 0.7s total
        # Door 3 has been ticking for 0.2s
        assert anim.get_angle(0) > anim.get_angle(3)

    def test_invalid_index_returns_zero(self):
        anim = DoorAnimator(door_count=8)
        assert anim.get_angle(99) == 0.0

    def test_out_of_range_begin_open_noop(self):
        anim = DoorAnimator(door_count=8)
        anim.begin_open(99)  # should not crash
        assert not anim.is_animating()
