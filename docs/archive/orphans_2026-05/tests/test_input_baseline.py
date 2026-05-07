import pytest
from unittest.mock import MagicMock, patch


def test_interview_ui_key_bindings():
    """
    Validate that InterviewUI correctly routes single-key input
    to the right choice options.
    Uses Panda3D messenger simulation — no window needed.
    """
    from core.systems.interview_ui import InterviewUI
    ui = InterviewUI(render_root=None)
    ui.start()

    # q1 options: city, nature, home, between
    # pressing 'c' should match 'city' (first-letter match)
    ui.handle_char("c")
    assert ui.engine.answers.get("q1") == "city"


def test_interview_ui_enter_skips():
    from core.systems.interview_ui import InterviewUI
    ui = InterviewUI(render_root=None)
    ui.start()
    ui.handle_char("\n")
    assert ui.engine.answers.get("q1") is None
    assert ui.current_prompt["id"] == "q2"


def test_interview_ui_full_flow_keys():
    from core.systems.interview_ui import InterviewUI
    results = []
    ui = InterviewUI(render_root=None, on_complete=lambda r: results.append(r))
    ui.engine.on_complete = lambda r: results.append(r)
    ui.start()

    # q1-q8 choice, q9-q10 open
    key_answers = ["c", "n", "t", "o", "c", "d", "p", "s"]
    for key in key_answers:
        ui.handle_char(key)

    # q9 open — type then enter
    for ch in "The Test":
        ui.handle_char(ch)
    ui.handle_char("\n")

    # q10 open — type then enter
    for ch in "focused":
        ui.handle_char(ch)
    ui.handle_char("\n")

    assert ui.engine.complete is True
    assert len(results) == 1


def test_panda3d_messenger_key_routing():
    """
    Confirm Panda3D messenger fires key events correctly.
    This is the baseline for all in-game key input.
    """
    from panda3d.core import loadPrcFileData
    loadPrcFileData("", "window-type none")
    loadPrcFileData("", "audio-library-name null")
    from direct.showbase.ShowBase import ShowBase
    from direct.showbase.MessengerGlobal import messenger

    app = ShowBase()
    fired = []

    app.accept("c", lambda: fired.append("c"))
    app.accept("h", lambda: fired.append("h"))
    app.accept("n", lambda: fired.append("n"))

    messenger.send("c")
    messenger.send("h")
    messenger.send("n")

    assert fired == ["c", "h", "n"]
    app.destroy()
