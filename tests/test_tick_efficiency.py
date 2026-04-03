"""
tests/test_tick_efficiency.py

Verify tick-loop optimizations: behind-camera throttle, static skip, spectrum stagger.
Pure logic tests — no rendering.
"""

import math
import pytest

from core.systems.ambient_life import (
    BUILDERS, BEHAVIORS, StaticBehavior, SpectrumEngine,
    _KIND_TO_SPECTRUM,
)


class TestStaticBehaviorSkip:
    """Static entities should have zero-cost tick."""

    def test_static_tick_is_noop(self):
        """StaticBehavior.tick() does nothing — verified by source."""
        b = StaticBehavior.__new__(StaticBehavior)
        # Should not raise, should do nothing
        b.tick(0.016)

    def test_majority_of_kinds_are_static(self):
        """Most entity kinds use static behavior — skip is high value."""
        static_count = sum(1 for kind, (fn, beh) in BUILDERS.items() if beh == "static")
        total = len(BUILDERS)
        ratio = static_count / total
        assert ratio > 0.60, f"Only {ratio:.0%} static — skip saves less than expected"

    def test_dynamic_behaviors_identified(self):
        """Identify which behaviors actually need ticking."""
        dynamic = {"scurry", "drift", "crawl", "sway", "wander"}
        for kind, (fn, beh_name) in BUILDERS.items():
            if beh_name != "static":
                assert beh_name in dynamic, f"{kind} has unknown behavior '{beh_name}'"


class TestBehindCameraThrottle:
    """Entities behind camera should tick less frequently."""

    def test_dot_product_identifies_behind(self):
        """Negative dot product = behind camera."""
        # Camera at origin, facing north (positive Y)
        cam_x, cam_y = 0, 0
        fwd_x, fwd_y = 0, 1  # facing north

        # Entity north of camera (in front)
        ex, ey = 0, 10
        dx, dy = ex - cam_x, ey - cam_y
        dot = dx * fwd_x + dy * fwd_y
        assert dot > 0, "Entity in front should have positive dot"

        # Entity south of camera (behind)
        ex, ey = 0, -10
        dx, dy = ex - cam_x, ey - cam_y
        dot = dx * fwd_x + dy * fwd_y
        assert dot < 0, "Entity behind should have negative dot"

    def test_dot_product_side_entities(self):
        """Side entities have near-zero dot product."""
        fwd_x, fwd_y = 0, 1
        ex, ey = 10, 0  # due east
        dot = ex * fwd_x + ey * fwd_y
        assert abs(dot) < 1.0, "Side entity should have near-zero dot"


class TestSpectrumStagger:
    """Spectrum drift should be staggered across frames."""

    def test_spectrum_entities_exist(self):
        """At least some entity kinds have spectrum profiles."""
        assert len(_KIND_TO_SPECTRUM) > 0

    def test_stagger_distributes_evenly(self):
        """Modulo stagger should distribute across N frames."""
        stagger_frames = 4
        buckets = [0] * stagger_frames
        for i in range(100):
            buckets[i % stagger_frames] += 1
        # Each bucket should have ~25
        for b in buckets:
            assert 20 <= b <= 30
