"""input_map — action → trigger mapping contract tests.

T3 of `feat_make-brain-ping-pong` PR 2. Pins the abstraction layer over
raylib-py keyboard / mouse / gamepad. Tests monkeypatch the module's
`rl` reference so they don't need a live raylib window.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from clients.vector_terminal import input_map


# ----------------------------------------------------------------------
# Fake `rl` — minimal raylib-py stand-in.
#
# - rl.KeyboardKey.KEY_X = "KEY_X" (string sentinel, easy to compare in fakes)
# - rl.MouseButton.MOUSE_BUTTON_LEFT = "MOUSE_BUTTON_LEFT"
# - rl.GamepadButton.GAMEPAD_BUTTON_RIGHT_TRIGGER_2 = "GAMEPAD_BUTTON_RIGHT_TRIGGER_2"
# - rl.is_key_pressed(token) consults a settable set
# Tests flip the sets to simulate input.
# ----------------------------------------------------------------------


class _Enum:
    """Trivial namespace where attribute access returns the attribute name."""
    def __getattr__(self, name: str) -> str:
        return name


class _FakeRl:
    def __init__(self):
        self.KeyboardKey = _Enum()
        self.MouseButton = _Enum()
        self.GamepadButton = _Enum()
        self.keys_pressed: set[str] = set()
        self.keys_down: set[str] = set()
        self.mouse_pressed: set[str] = set()
        self.mouse_down: set[str] = set()
        self.gamepad_buttons_pressed: set[tuple[int, str]] = set()
        self.gamepad_buttons_down: set[tuple[int, str]] = set()
        self.gamepad_axes: dict[tuple[int, int], float] = {}
        self.available_gamepads: set[int] = {0}

    def is_key_pressed(self, k):     return k in self.keys_pressed
    def is_key_down(self, k):        return k in self.keys_down
    def is_mouse_button_pressed(self, b): return b in self.mouse_pressed
    def is_mouse_button_down(self, b):    return b in self.mouse_down
    def is_gamepad_available(self, g):    return g in self.available_gamepads
    def is_gamepad_button_pressed(self, g, b): return (g, b) in self.gamepad_buttons_pressed
    def is_gamepad_button_down(self, g, b):    return (g, b) in self.gamepad_buttons_down
    def get_gamepad_axis_movement(self, g, idx): return self.gamepad_axes.get((g, idx), 0.0)


@pytest.fixture
def rl(monkeypatch):
    fake = _FakeRl()
    monkeypatch.setattr(input_map, "rl", fake)
    input_map.reset_bindings()
    yield fake
    input_map.reset_bindings()


# ----------------------------------------------------------------------
# Default bindings sanity
# ----------------------------------------------------------------------


def test_default_bindings_register_expected_actions(rl):
    actions = set(input_map.list_actions())
    # Movement
    for a in ("move_forward", "move_back", "move_left", "move_right",
              "sprint", "jump"):
        assert a in actions, f"missing action {a!r}"
    # Combat / interact
    for a in ("fire_primary", "melee", "aim_ads", "interact"):
        assert a in actions
    # Volley new
    for a in ("console_toggle", "reset_rally"):
        assert a in actions
    # Slots
    for i in range(1, 10):
        assert f"slot_{i}" in actions


def test_unknown_action_raises_lookup(rl):
    with pytest.raises(LookupError):
        input_map.pressed("ghost")
    with pytest.raises(LookupError):
        input_map.held("ghost")
    with pytest.raises(LookupError):
        input_map.bindings_for("ghost")


# ----------------------------------------------------------------------
# Single-trigger pressed / held
# ----------------------------------------------------------------------


def test_key_press_fires_action(rl):
    assert input_map.pressed("interact") is False
    rl.keys_pressed.add("KEY_F")
    assert input_map.pressed("interact") is True


def test_mouse_press_fires_action(rl):
    assert input_map.pressed("fire_primary") is False
    rl.mouse_pressed.add("MOUSE_BUTTON_LEFT")
    assert input_map.pressed("fire_primary") is True


def test_held_returns_true_for_keydown(rl):
    rl.keys_down.add("KEY_W")
    assert input_map.held("move_forward") is True


def test_pressed_does_not_fire_on_held_only(rl):
    """is_key_down ≠ is_key_pressed — pressed is rising-edge only."""
    rl.keys_down.add("KEY_F")          # held but not freshly pressed
    assert input_map.pressed("interact") is False


# ----------------------------------------------------------------------
# Multi-trigger OR semantics
# ----------------------------------------------------------------------


def test_lmb_or_rt_both_fire_fire_primary(rl):
    # Default fire_primary = LMB OR RT
    assert input_map.pressed("fire_primary") is False
    rl.mouse_pressed.add("MOUSE_BUTTON_LEFT")
    assert input_map.pressed("fire_primary") is True
    rl.mouse_pressed.discard("MOUSE_BUTTON_LEFT")
    assert input_map.pressed("fire_primary") is False
    rl.gamepad_buttons_pressed.add((0, "GAMEPAD_BUTTON_RIGHT_TRIGGER_2"))
    assert input_map.pressed("fire_primary") is True


def test_left_or_right_shift_both_count_as_sprint(rl):
    assert input_map.held("sprint") is False
    rl.keys_down.add("KEY_LEFT_SHIFT")
    assert input_map.held("sprint") is True
    rl.keys_down.discard("KEY_LEFT_SHIFT")
    rl.keys_down.add("KEY_RIGHT_SHIFT")
    assert input_map.held("sprint") is True


# ----------------------------------------------------------------------
# Gamepad axis triggers (analog held, not pressed)
# ----------------------------------------------------------------------


def test_axis_pos_held_above_threshold(rl):
    input_map.bind("test_axis", [("axis_pos", 5, 0.5)])
    rl.gamepad_axes[(0, 5)] = 0.3
    assert input_map.held("test_axis") is False
    rl.gamepad_axes[(0, 5)] = 0.7
    assert input_map.held("test_axis") is True


def test_axis_neg_held_below_negative_threshold(rl):
    input_map.bind("test_axis_neg", [("axis_neg", 5, 0.5)])
    rl.gamepad_axes[(0, 5)] = -0.3
    assert input_map.held("test_axis_neg") is False
    rl.gamepad_axes[(0, 5)] = -0.8
    assert input_map.held("test_axis_neg") is True


def test_axis_does_not_contribute_to_pressed(rl):
    """`pressed` ignores axis triggers — they have no rising-edge semantics."""
    input_map.bind("axis_only", [("axis_pos", 5, 0.5)])
    rl.gamepad_axes[(0, 5)] = 1.0
    assert input_map.pressed("axis_only") is False


# ----------------------------------------------------------------------
# Gamepad availability
# ----------------------------------------------------------------------


def test_gamepad_button_ignored_when_no_gamepad(rl):
    rl.available_gamepads.clear()
    rl.gamepad_buttons_pressed.add((0, "GAMEPAD_BUTTON_RIGHT_TRIGGER_2"))
    assert input_map.pressed("fire_primary") is False


def test_gamepad_axis_ignored_when_no_gamepad(rl):
    input_map.bind("test_axis", [("axis_pos", 5, 0.5)])
    rl.available_gamepads.clear()
    rl.gamepad_axes[(0, 5)] = 1.0
    assert input_map.held("test_axis") is False


# ----------------------------------------------------------------------
# bind() / reset_bindings() / axis()
# ----------------------------------------------------------------------


def test_bind_overrides_default(rl):
    input_map.bind("interact", [("key", "KEY_TAB")])
    rl.keys_pressed.add("KEY_F")
    assert input_map.pressed("interact") is False    # F no longer wired
    rl.keys_pressed.add("KEY_TAB")
    assert input_map.pressed("interact") is True


def test_bind_blank_action_raises(rl):
    with pytest.raises(ValueError):
        input_map.bind("", [])
    with pytest.raises(ValueError):
        input_map.bind("   ", [])


def test_reset_bindings_restores_defaults(rl):
    input_map.bind("interact", [("key", "KEY_TAB")])
    input_map.reset_bindings()
    rl.keys_pressed.add("KEY_F")
    assert input_map.pressed("interact") is True


def test_axis_combines_two_actions(rl):
    rl.keys_down.add("KEY_W")
    assert input_map.axis("move_back", "move_forward") == 1.0
    rl.keys_down.discard("KEY_W")
    rl.keys_down.add("KEY_S")
    assert input_map.axis("move_back", "move_forward") == -1.0
    rl.keys_down.discard("KEY_S")
    assert input_map.axis("move_back", "move_forward") == 0.0


# ----------------------------------------------------------------------
# Binding summary (debug helper)
# ----------------------------------------------------------------------


def test_binding_summary_returns_short_labels(rl):
    summary = input_map.binding_summary()
    assert "F" in summary["interact"]
    assert "GP-RIGHT_FACE_LEFT" in summary["interact"]
    assert "M-LEFT" in summary["fire_primary"]
    assert "GP-RIGHT_TRIGGER_2" in summary["fire_primary"]
