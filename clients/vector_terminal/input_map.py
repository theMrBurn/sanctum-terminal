"""input_map — abstracted action layer over raylib-py keyboard/mouse/gamepad.

Mirrors Godot's InputMap pattern, ported to raylib-py. Action names map to a
list of triggers; any matching trigger fires the action. This is the
universal input surface that make-brain instances declare against.

Per `.claude/feature/feat_make-brain-ping-pong.md` PR 2.

Trigger schema
--------------
A trigger is a tuple. Supported kinds:

    ("key",      "KEY_NAME")                     # keyboard key, e.g. "KEY_F"
    ("mouse",    "MOUSE_BUTTON_NAME")            # mouse button, e.g. "MOUSE_BUTTON_LEFT"
    ("gamepad",  "GAMEPAD_BUTTON_NAME")          # gamepad button, e.g. "GAMEPAD_BUTTON_RIGHT_TRIGGER_2"
    ("axis_pos", axis_index: int, threshold: float = 0.5)
    ("axis_neg", axis_index: int, threshold: float = 0.5)

Names are resolved against `rl.KeyboardKey`, `rl.MouseButton`,
`rl.GamepadButton` at call time (so tests can monkeypatch the `rl` import).

API
---
    pressed(action)  — True if the action was pressed THIS frame (rising edge)
    held(action)     — True if the action is currently held (any frame while down)
    bindings_for(a)  — list of trigger tuples bound to that action
    list_actions()   — sorted list of registered actions
    bind(a, triggers)— overwrite bindings for an action (in-process)
    reset_bindings() — restore DEFAULT_BINDINGS (test helper)

Multi-trigger semantics: any trigger matching = action fires. So binding
both LMB and RT to `fire_primary` means either input fires the action.

Scope (V1 / PR 2): main.py call-site migration. build_mode.py /
dial_input.py / journal.py keep direct rl calls; their migration is a
follow-up sub-PR. This module's API is ready for them whenever.
"""
from __future__ import annotations

import pyray as rl


# Default gamepad index (raylib supports 0..3). Single-player default = 0.
DEFAULT_GAMEPAD = 0

# Trigger type alias for readability.
Trigger = tuple


# ----------------------------------------------------------------------
# Default bindings — every action main.py uses + the new volley actions.
#
# Gamepad bindings target Xbox/Sony layout via raylib's universal enum.
# Naming convention for actions is verb_object or domain_verb (e.g.
# `fire_primary`, `journal_toggle`, `console_toggle`).
# ----------------------------------------------------------------------
DEFAULT_BINDINGS: dict[str, list[Trigger]] = {
    # Movement (held)
    "move_forward":     [("key", "KEY_W")],
    "move_back":        [("key", "KEY_S")],
    "move_left":        [("key", "KEY_A")],
    "move_right":       [("key", "KEY_D")],
    "sprint":           [("key", "KEY_LEFT_SHIFT"), ("key", "KEY_RIGHT_SHIFT")],
    "jump":             [
        ("key", "KEY_SPACE"),
        ("gamepad", "GAMEPAD_BUTTON_RIGHT_FACE_DOWN"),       # A
    ],

    # Combat / interact
    "fire_primary":     [
        ("mouse",   "MOUSE_BUTTON_LEFT"),
        ("gamepad", "GAMEPAD_BUTTON_RIGHT_TRIGGER_2"),       # RT
    ],
    "melee":            [
        ("mouse",   "MOUSE_BUTTON_RIGHT"),
        ("gamepad", "GAMEPAD_BUTTON_RIGHT_TRIGGER_1"),       # RB
    ],
    "aim_ads":          [
        ("gamepad", "GAMEPAD_BUTTON_LEFT_TRIGGER_2"),        # LT (Stage 3 reserved)
    ],
    "interact":         [
        ("key",     "KEY_F"),
        ("gamepad", "GAMEPAD_BUTTON_RIGHT_FACE_LEFT"),       # X
    ],

    # State navigation
    "pause":            [
        ("key",     "KEY_ESCAPE"),
        ("gamepad", "GAMEPAD_BUTTON_MIDDLE_RIGHT"),          # START
    ],
    "confirm":          [
        ("key",     "KEY_ENTER"),
    ],
    "submode_toggle":   [
        ("key",     "KEY_ENTER"),
    ],
    "state_back":       [
        ("key",     "KEY_ESCAPE"),
        ("gamepad", "GAMEPAD_BUTTON_MIDDLE_LEFT"),           # BACK / SELECT
    ],

    # Workroom / build
    "build_toggle":     [("key", "KEY_B")],

    # Volley (V1 — new actions)
    "console_toggle":   [("key", "KEY_GRAVE")],              # backtick
    "reset_rally":      [("key", "KEY_R")],

    # ARPG combat (feat/arpg-combat PR 8 — equipped-weapon UX).
    # DOOM-style: cycle with Y, direct-select with 1-4, attack with
    # primary/secondary mouse buttons. Brain receives weapon_kind +
    # mode based on currently equipped weapon, not per-key bindings.
    "weapon_cycle":     [
        ("key",     "KEY_Y"),
        ("gamepad", "GAMEPAD_BUTTON_LEFT_FACE_UP"),           # D-pad up
    ],
    "attack_primary":   [
        ("mouse",   "MOUSE_BUTTON_LEFT"),
        ("gamepad", "GAMEPAD_BUTTON_RIGHT_TRIGGER_2"),        # RT
    ],
    "attack_secondary": [
        ("mouse",   "MOUSE_BUTTON_RIGHT"),
        ("gamepad", "GAMEPAD_BUTTON_RIGHT_TRIGGER_1"),        # RB
    ],
    # Legacy per-weapon bindings (kept as alts so muscle memory still
    # works post-PR-8; primary path is cycle + slot select).
    "weapon_throw":     [("key", "KEY_G")],
    "weapon_whip":      [("key", "KEY_V")],
    "staff_swing":      [("key", "KEY_X")],
    "staff_cast":       [("key", "KEY_C")],

    # Misc UI / debug
    "journal_toggle":   [("key", "KEY_J")],
    "equip_cycle":      [("key", "KEY_E")],
    "light_cycle":      [("key", "KEY_L")],
    "tension_toggle":   [("key", "KEY_T")],
    "inventory_toggle": [("key", "KEY_I")],
    "hud_toggle":       [("key", "KEY_H")],
    "noclip_toggle":    [("key", "KEY_BACKSLASH")],
    "damage_self_debug":[("key", "KEY_K")],

    # Thing tune mode — B-mode equivalent for live-tuning composite
    # things (per spec/notes 2026-05-14). U toggles; while active,
    # arrows/+- nudge the currently-aimed-at part.
    "tune_toggle":      [("key", "KEY_U")],
    "tune_save":        [("key", "KEY_ENTER")],
    "tune_pos_x_plus":  [("key", "KEY_RIGHT")],
    "tune_pos_x_minus": [("key", "KEY_LEFT")],
    "tune_pos_y_plus":  [("key", "KEY_UP")],
    "tune_pos_y_minus": [("key", "KEY_DOWN")],
    "tune_pos_z_plus":  [("key", "KEY_PAGE_UP")],
    "tune_pos_z_minus": [("key", "KEY_PAGE_DOWN")],
    "tune_size_plus":   [("key", "KEY_EQUAL")],            # = / +
    "tune_size_minus":  [("key", "KEY_MINUS")],
    "tune_rot_plus":    [("key", "KEY_PERIOD")],           # >
    "tune_rot_minus":   [("key", "KEY_COMMA")],            # <

    # Numeric slot keys (cast slots / encounter choices — context-gated by callers)
    "slot_1":           [("key", "KEY_ONE")],
    "slot_2":           [("key", "KEY_TWO")],
    "slot_3":           [("key", "KEY_THREE")],
    "slot_4":           [("key", "KEY_FOUR")],
    "slot_5":           [("key", "KEY_FIVE")],
    "slot_6":           [("key", "KEY_SIX")],
    "slot_7":           [("key", "KEY_SEVEN")],
    "slot_8":           [("key", "KEY_EIGHT")],
    "slot_9":           [("key", "KEY_NINE")],
}


# Convenience tuple for callers iterating numbered slot actions in order
# (encounter choices, cast slots, etc.).
SLOT_ACTIONS: tuple[str, ...] = (
    "slot_1", "slot_2", "slot_3", "slot_4", "slot_5",
    "slot_6", "slot_7", "slot_8", "slot_9",
)


# Live mutable bindings dict — starts as a copy of defaults so user/test
# overrides don't mutate DEFAULT_BINDINGS.
_BINDINGS: dict[str, list[Trigger]] = {
    name: list(triggers) for name, triggers in DEFAULT_BINDINGS.items()
}


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------


def list_actions() -> list[str]:
    return sorted(_BINDINGS.keys())


def bindings_for(action: str) -> list[Trigger]:
    if action not in _BINDINGS:
        raise LookupError(f"input_map: unknown action {action!r}")
    return list(_BINDINGS[action])


def bind(action: str, triggers: list[Trigger]) -> None:
    """Replace bindings for an action. Empty list disables the action."""
    if not isinstance(action, str) or not action.strip():
        raise ValueError("input_map.bind: action must be a non-empty string")
    _BINDINGS[action] = list(triggers)


def reset_bindings() -> None:
    """Restore DEFAULT_BINDINGS. Test helper + runtime reset."""
    global _BINDINGS
    _BINDINGS = {
        name: list(triggers) for name, triggers in DEFAULT_BINDINGS.items()
    }


def pressed(action: str, gamepad: int = DEFAULT_GAMEPAD) -> bool:
    """True if the action transitioned from up to down THIS frame.

    Axis triggers (`axis_pos` / `axis_neg`) do NOT contribute to pressed
    semantics — they're for held/analog use. Bind a digital button
    (e.g. `GAMEPAD_BUTTON_RIGHT_TRIGGER_2`) for trigger-press events.
    """
    triggers = _BINDINGS.get(action)
    if triggers is None:
        raise LookupError(f"input_map: unknown action {action!r}")
    for trigger in triggers:
        kind = trigger[0]
        if kind == "key":
            if rl.is_key_pressed(getattr(rl.KeyboardKey, trigger[1])):
                return True
        elif kind == "mouse":
            if rl.is_mouse_button_pressed(getattr(rl.MouseButton, trigger[1])):
                return True
        elif kind == "gamepad":
            if rl.is_gamepad_available(gamepad) and rl.is_gamepad_button_pressed(
                gamepad, getattr(rl.GamepadButton, trigger[1])
            ):
                return True
        elif kind in ("axis_pos", "axis_neg"):
            # Axis triggers are continuous — no rising-edge semantics here.
            continue
        else:
            raise ValueError(
                f"input_map.pressed: unknown trigger kind {kind!r} on {action!r}"
            )
    return False


def pressed_repeat(action: str, gamepad: int = DEFAULT_GAMEPAD) -> bool:
    """True on initial press AND on OS-driven auto-repeat fires while
    held. Use for nudge-style inputs where the user wants continuous
    adjustment (tune mode, list scrolling, etc.). Not for one-shot
    actions — those use `pressed()`.

    Mouse + gamepad triggers fall back to single-press semantics
    (no auto-repeat available from raylib for those input kinds).
    """
    triggers = _BINDINGS.get(action)
    if triggers is None:
        raise LookupError(f"input_map: unknown action {action!r}")
    for trigger in triggers:
        kind = trigger[0]
        if kind == "key":
            if rl.is_key_pressed_repeat(getattr(rl.KeyboardKey, trigger[1])):
                return True
            # is_key_pressed_repeat doesn't fire on the initial press —
            # combine with is_key_pressed so the first-frame edit lands too.
            if rl.is_key_pressed(getattr(rl.KeyboardKey, trigger[1])):
                return True
        elif kind == "mouse":
            if rl.is_mouse_button_pressed(getattr(rl.MouseButton, trigger[1])):
                return True
        elif kind == "gamepad":
            if rl.is_gamepad_available(gamepad) and rl.is_gamepad_button_pressed(
                gamepad, getattr(rl.GamepadButton, trigger[1])
            ):
                return True
        elif kind in ("axis_pos", "axis_neg"):
            continue
        else:
            raise ValueError(
                f"input_map.pressed_repeat: unknown trigger kind {kind!r} on {action!r}"
            )
    return False


def held(action: str, gamepad: int = DEFAULT_GAMEPAD) -> bool:
    """True if any trigger bound to the action is currently down."""
    triggers = _BINDINGS.get(action)
    if triggers is None:
        raise LookupError(f"input_map: unknown action {action!r}")
    gamepad_ok = None  # lazy
    for trigger in triggers:
        kind = trigger[0]
        if kind == "key":
            if rl.is_key_down(getattr(rl.KeyboardKey, trigger[1])):
                return True
        elif kind == "mouse":
            if rl.is_mouse_button_down(getattr(rl.MouseButton, trigger[1])):
                return True
        elif kind == "gamepad":
            if gamepad_ok is None:
                gamepad_ok = rl.is_gamepad_available(gamepad)
            if gamepad_ok and rl.is_gamepad_button_down(
                gamepad, getattr(rl.GamepadButton, trigger[1])
            ):
                return True
        elif kind == "axis_pos":
            if gamepad_ok is None:
                gamepad_ok = rl.is_gamepad_available(gamepad)
            if gamepad_ok:
                threshold = trigger[2] if len(trigger) > 2 else 0.5
                if rl.get_gamepad_axis_movement(gamepad, int(trigger[1])) > threshold:
                    return True
        elif kind == "axis_neg":
            if gamepad_ok is None:
                gamepad_ok = rl.is_gamepad_available(gamepad)
            if gamepad_ok:
                threshold = trigger[2] if len(trigger) > 2 else 0.5
                if rl.get_gamepad_axis_movement(gamepad, int(trigger[1])) < -threshold:
                    return True
        else:
            raise ValueError(
                f"input_map.held: unknown trigger kind {kind!r} on {action!r}"
            )
    return False


def axis(neg_action: str, pos_action: str, gamepad: int = DEFAULT_GAMEPAD) -> float:
    """Composite -1..1 value from two opposing actions.

    Digital-only V1: each side reads as held() → ±1. Analog stick
    integration via `axis_pos`/`axis_neg` triggers can be added later
    by reading the raw axis directly when present.
    """
    pos = 1.0 if held(pos_action, gamepad) else 0.0
    neg = -1.0 if held(neg_action, gamepad) else 0.0
    return pos + neg


def binding_summary() -> dict[str, list[str]]:
    """Human-readable view of bindings — `{action: ['LMB', 'RT', ...]}`.

    Used for HUD overlay / debug. Trigger tuples → short labels.
    """
    out: dict[str, list[str]] = {}
    for name, triggers in _BINDINGS.items():
        labels = []
        for t in triggers:
            kind = t[0]
            if kind == "key":
                labels.append(t[1].replace("KEY_", ""))
            elif kind == "mouse":
                short = t[1].replace("MOUSE_BUTTON_", "")
                labels.append(f"M-{short}")
            elif kind == "gamepad":
                labels.append("GP-" + t[1].replace("GAMEPAD_BUTTON_", ""))
            elif kind == "axis_pos":
                labels.append(f"AX+{t[1]}")
            elif kind == "axis_neg":
                labels.append(f"AX-{t[1]}")
        out[name] = labels
    return out
