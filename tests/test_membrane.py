"""
tests/test_membrane.py

Membrane system — fade transitions, registration, wake/sleep lifecycle.
Pure logic tests — no display required (uses Panda3D headless NodePaths).
"""

import pytest
from panda3d.core import NodePath, Vec4


# -- Membrane state tests (no rendering needed) --------------------------------

class TestMembraneRegistration:
    """Registration stores config but renders nothing until wake."""

    def _make_membrane(self):
        from core.systems.membrane import Membrane
        root = NodePath("test_root")
        return Membrane(root)

    def test_register_creates_entry(self):
        m = self._make_membrane()
        m.register(42, pos=(0, 0, 0), glow_color=(0.5, 0.1, 0.3), glow_radius=5.0)
        assert 42 in m._entries

    def test_register_not_active(self):
        m = self._make_membrane()
        m.register(42, pos=(0, 0, 0), glow_color=(0.5, 0.1, 0.3), glow_radius=5.0)
        assert m._entries[42]["active"] is False

    def test_register_no_decal(self):
        m = self._make_membrane()
        m.register(42, pos=(0, 0, 0), glow_color=(0.5, 0.1, 0.3), glow_radius=5.0)
        assert m._entries[42]["decal"] is None

    def test_register_defaults_mote_color_to_glow(self):
        m = self._make_membrane()
        m.register(42, pos=(0, 0, 0), glow_color=(0.5, 0.1, 0.3), glow_radius=5.0)
        assert m._entries[42]["mote_color"] == (0.5, 0.1, 0.3)

    def test_register_custom_mote_color(self):
        m = self._make_membrane()
        m.register(42, pos=(0, 0, 0), glow_color=(0.5, 0.1, 0.3),
                   glow_radius=5.0, mote_color=(1.0, 0.0, 0.0))
        assert m._entries[42]["mote_color"] == (1.0, 0.0, 0.0)


class TestMembraneWakeSleep:
    """Wake/sleep lifecycle — decal creation, fade, cleanup."""

    def _make_membrane(self):
        from core.systems.membrane import Membrane
        root = NodePath("test_root")
        return Membrane(root)

    def test_wake_activates(self):
        m = self._make_membrane()
        m.register(1, pos=(5, 10, 0), glow_color=(0.2, 0.4, 0.1), glow_radius=3.0)
        m.wake(1)
        assert m._entries[1]["active"] is True

    def test_wake_creates_decal(self):
        m = self._make_membrane()
        m.register(1, pos=(5, 10, 0), glow_color=(0.2, 0.4, 0.1), glow_radius=3.0)
        m.wake(1)
        assert m._entries[1]["decal"] is not None

    def test_wake_starts_fade_interval(self):
        m = self._make_membrane()
        m.register(1, pos=(5, 10, 0), glow_color=(0.2, 0.4, 0.1), glow_radius=3.0)
        m.wake(1)
        # Should have at least the fade interval
        assert len(m._entries[1]["intervals"]) >= 1

    def test_wake_decal_starts_invisible(self):
        """Decal alpha should start at 0 (fade-in, not snap)."""
        m = self._make_membrane()
        m.register(1, pos=(5, 10, 0), glow_color=(0.2, 0.4, 0.1), glow_radius=3.0)
        m.wake(1)
        decal = m._entries[1]["decal"]
        # The interval is running but the initial colorScale was set to alpha=0
        # (the interval lerps from 0 to 0.45 over 3.0s)
        cs = decal.getColorScale()
        # Alpha should be 0 or very close (interval may have ticked slightly)
        assert cs[3] < 0.1  # not snapped to 0.45

    def test_double_wake_is_noop(self):
        m = self._make_membrane()
        m.register(1, pos=(5, 10, 0), glow_color=(0.2, 0.4, 0.1), glow_radius=3.0)
        m.wake(1)
        n_intervals = len(m._entries[1]["intervals"])
        m.wake(1)  # second call
        assert len(m._entries[1]["intervals"]) == n_intervals

    def test_sleep_deactivates(self):
        m = self._make_membrane()
        m.register(1, pos=(5, 10, 0), glow_color=(0.2, 0.4, 0.1), glow_radius=3.0)
        m.wake(1)
        m.sleep(1)
        assert m._entries[1]["active"] is False

    def test_sleep_removes_decal(self):
        m = self._make_membrane()
        m.register(1, pos=(5, 10, 0), glow_color=(0.2, 0.4, 0.1), glow_radius=3.0)
        m.wake(1)
        m.sleep(1)
        assert m._entries[1]["decal"] is None

    def test_sleep_clears_intervals(self):
        m = self._make_membrane()
        m.register(1, pos=(5, 10, 0), glow_color=(0.2, 0.4, 0.1), glow_radius=3.0)
        m.wake(1)
        m.sleep(1)
        assert m._entries[1]["intervals"] == []

    def test_sleep_clears_motes(self):
        m = self._make_membrane()
        m.register(1, pos=(5, 10, 0), glow_color=(0.2, 0.4, 0.1), glow_radius=3.0)
        m.wake(1)
        m.sleep(1)
        assert m._entries[1]["motes"] == []

    def test_double_sleep_is_noop(self):
        m = self._make_membrane()
        m.register(1, pos=(5, 10, 0), glow_color=(0.2, 0.4, 0.1), glow_radius=3.0)
        m.wake(1)
        m.sleep(1)
        m.sleep(1)  # should not raise
        assert m._entries[1]["active"] is False

    def test_remove_cleans_up(self):
        m = self._make_membrane()
        m.register(1, pos=(5, 10, 0), glow_color=(0.2, 0.4, 0.1), glow_radius=3.0)
        m.wake(1)
        m.remove(1)
        assert 1 not in m._entries

    def test_wake_unknown_entity_is_noop(self):
        m = self._make_membrane()
        m.wake(999)  # should not raise

    def test_sleep_unknown_entity_is_noop(self):
        m = self._make_membrane()
        m.sleep(999)  # should not raise


class TestMembraneWithMotes:
    """Mote spawning on wake."""

    def _make_membrane(self):
        from core.systems.membrane import Membrane
        root = NodePath("test_root")
        return Membrane(root)

    def test_wake_spawns_motes(self):
        m = self._make_membrane()
        m.register(1, pos=(5, 10, 0), glow_color=(0.2, 0.4, 0.1), glow_radius=3.0,
                   mote_count=5, mote_cfg={"radius": 2.0, "height": 3.0})
        m.wake(1)
        assert len(m._entries[1]["motes"]) == 5

    def test_sleep_removes_motes(self):
        m = self._make_membrane()
        m.register(1, pos=(5, 10, 0), glow_color=(0.2, 0.4, 0.1), glow_radius=3.0,
                   mote_count=5, mote_cfg={"radius": 2.0, "height": 3.0})
        m.wake(1)
        m.sleep(1)
        assert len(m._entries[1]["motes"]) == 0


class TestDecalTexture:
    """Stippled gradient is deterministic and cached."""

    def test_texture_cached(self):
        from core.systems.membrane import _get_decal_texture, _DECAL_CACHE
        _DECAL_CACHE.clear()
        t1 = _get_decal_texture(64)
        t2 = _get_decal_texture(64)
        assert t1 is t2

    def test_texture_different_sizes(self):
        from core.systems.membrane import _get_decal_texture, _DECAL_CACHE
        _DECAL_CACHE.clear()
        t1 = _get_decal_texture(32)
        t2 = _get_decal_texture(64)
        assert t1 is not t2
