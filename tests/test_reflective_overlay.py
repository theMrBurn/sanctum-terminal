"""Vector terminal reflective overlay — wiring + state checks.

Static-text checks of the overlay module + main.py wiring. Pyray-
dependent code paths (handle_input dispatch on rl.is_key_pressed,
draw_overlay) need a graphical context to test directly; for V1 we
verify the wiring shape and let the UAT cover behavior.
"""
from __future__ import annotations

from pathlib import Path


_OVERLAY_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "clients" / "vector_terminal" / "reflective.py"
).read_text()

_MAIN_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "clients" / "vector_terminal" / "main.py"
).read_text()


# ── Overlay module shape ──────────────────────────────────────────


def test_overlay_module_exports_reflective_state():
    assert "class ReflectiveState" in _OVERLAY_SOURCE


def test_overlay_module_exports_handle_input():
    assert "def handle_input(" in _OVERLAY_SOURCE


def test_overlay_module_exports_draw_overlay():
    assert "def draw_overlay(" in _OVERLAY_SOURCE


def test_overlay_handles_arrow_keys():
    assert "KEY_DOWN" in _OVERLAY_SOURCE
    assert "KEY_UP" in _OVERLAY_SOURCE
    assert "KEY_LEFT" in _OVERLAY_SOURCE
    assert "KEY_RIGHT" in _OVERLAY_SOURCE


def test_overlay_emits_place_action_on_enter():
    """ENTER → place dispatch with {'magnet': str} payload."""
    assert "KEY_ENTER" in _OVERLAY_SOURCE
    assert '"place"' in _OVERLAY_SOURCE


def test_overlay_emits_remove_action_on_backspace():
    assert "KEY_BACKSPACE" in _OVERLAY_SOURCE
    assert '"remove"' in _OVERLAY_SOURCE


def test_overlay_emits_commit_action_on_c():
    assert "KEY_C" in _OVERLAY_SOURCE
    assert '"commit"' in _OVERLAY_SOURCE


def test_overlay_emits_abort_action_on_esc():
    assert "KEY_ESCAPE" in _OVERLAY_SOURCE
    assert '"abort"' in _OVERLAY_SOURCE


# ── main.py wiring ────────────────────────────────────────────────


def test_main_imports_reflective_overlay():
    assert "from clients.vector_terminal import reflective" in _MAIN_SOURCE


def test_main_initializes_reflective_state():
    assert "reflective_overlay.ReflectiveState()" in _MAIN_SOURCE


def test_main_dispatches_place_magnet_cmd():
    assert '"cmd": "place_magnet"' in _MAIN_SOURCE


def test_main_dispatches_remove_magnet_cmd():
    assert '"cmd": "remove_magnet"' in _MAIN_SOURCE


def test_main_dispatches_commit_reflective_cmd():
    assert '"cmd": "commit_reflective"' in _MAIN_SOURCE


def test_main_dispatches_abort_reflective_cmd():
    assert '"cmd": "abort_reflective"' in _MAIN_SOURCE


def test_main_dispatches_engage_fridge_on_f_key_at_fridge():
    """F key on fridge entity sends engage_fridge cmd."""
    assert '"cmd": "engage_fridge"' in _MAIN_SOURCE
    # The dispatch is gated on target_kind == "fridge".
    assert 'target_kind == "fridge"' in _MAIN_SOURCE


def test_main_yields_other_input_when_reflective_active():
    """Reflective overlay must own ARROW/ENTER/BKSP/C/ESC. Other input
    (J toggle, ENTER state transition) gates on `not reflective_active`."""
    assert "not reflective_active" in _MAIN_SOURCE


def test_main_draws_reflective_overlay_when_active():
    assert "reflective_overlay.draw_overlay(" in _MAIN_SOURCE
