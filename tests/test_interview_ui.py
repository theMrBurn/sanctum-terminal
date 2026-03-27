import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_render():
    return MagicMock()


@pytest.fixture
def ui(mock_render):
    from core.systems.interview_ui import InterviewUI
    return InterviewUI(render_root=mock_render, on_complete=None)


class TestInterviewUIInit:

    def test_boots_without_error(self, ui):
        assert ui is not None

    def test_has_engine(self, ui):
        assert ui.engine is not None

    def test_starts_inactive(self, ui):
        assert ui.active is False

    def test_current_prompt_starts_none(self, ui):
        assert ui.current_prompt is None


class TestInterviewUIFlow:

    def test_start_sets_active(self, ui):
        ui.start()
        assert ui.active is True

    def test_start_sets_current_prompt(self, ui):
        ui.start()
        assert ui.current_prompt is not None

    def test_start_sets_first_prompt(self, ui):
        ui.start()
        assert ui.current_prompt["id"] == "q1"

    def test_submit_advances_prompt(self, ui):
        ui.start()
        ui.submit("city")
        assert ui.current_prompt["id"] == "q2"

    def test_submit_stores_answer(self, ui):
        ui.start()
        ui.submit("city")
        assert ui.engine.answers.get("q1") == "city"

    def test_skip_advances_prompt(self, ui):
        ui.start()
        ui.skip()
        assert ui.current_prompt["id"] == "q2"

    def test_complete_after_all_prompts(self, ui):
        ui.start()
        for answer in ["city", "evening", "too_long",
                       "enclosed", "heavy", "quickly", "pressure"]:
            ui.submit(answer)
        assert ui.engine.complete is True

    def test_complete_fires_callback(self, ui):
        results = []
        ui.on_complete = lambda r: results.append(r)
        ui.engine.on_complete = ui.on_complete
        ui.start()
        for answer in ["city", "evening", "too_long",
                       "enclosed", "heavy", "quickly", "pressure"]:
            ui.submit(answer)
        assert len(results) == 1

    def test_result_has_torch(self, ui):
        results = []
        ui.on_complete = lambda r: results.append(r)
        ui.engine.on_complete = ui.on_complete
        ui.start()
        for answer in ["city", "evening", "too_long",
                       "enclosed", "heavy", "quickly", "pressure"]:
            ui.submit(answer)
        assert "torch" in results[0]


class TestDepthInvitation:

    def test_low_commitment_triggers_depth_invite(self, ui):
        ui.start()
        for _ in range(6):
            ui.skip()
        ui.submit("torch")
        assert ui.awaiting_depth is True

    def test_depth_invite_has_follow_prompt(self, ui):
        ui.start()
        for _ in range(6):
            ui.skip()
        ui.submit("torch")
        assert ui.depth_prompt is not None

    def test_depth_response_resolves(self, ui):
        ui.start()
        for _ in range(6):
            ui.skip()
        ui.submit("torch")
        ui.submit_depth("the path forward")
        assert ui.engine.complete is True
