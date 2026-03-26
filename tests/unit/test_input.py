import pytest
import pygame
from unittest.mock import MagicMock
from core.input_handler import InputHandler


@pytest.fixture
def ih():
    return InputHandler()


class TestInputHandlerInit:

    def test_boots_without_error(self, ih):
        assert ih is not None

    def test_mapping_exists(self, ih):
        assert ih.mapping is not None

    def test_mapping_is_dict(self, ih):
        assert isinstance(ih.mapping, dict)

    def test_mapping_contains_wsad(self, ih):
        for key in ["w", "s", "a", "d"]:
            assert key in ih.mapping

    def test_active_keys_starts_empty(self, ih):
        assert isinstance(ih.active_keys, set)
        assert len(ih.active_keys) == 0

    def test_mouse_sensitivity_default(self, ih):
        assert ih.mouse_sensitivity == pytest.approx(0.1)

    def test_yaw_pitch_start_at_zero(self, ih):
        assert ih.yaw == pytest.approx(0.0)
        assert ih.pitch == pytest.approx(0.0)


class TestProcessInput:

    def test_keydown_adds_to_active_keys(self, ih):
        event = MagicMock()
        event.type = pygame.KEYDOWN
        event.key = "w"
        ih.process_input(event)
        assert "w" in ih.active_keys

    def test_keyup_removes_from_active_keys(self, ih):
        event_down = MagicMock()
        event_down.type = pygame.KEYDOWN
        event_down.key = "w"
        ih.process_input(event_down)
        event_up = MagicMock()
        event_up.type = pygame.KEYUP
        event_up.key = "w"
        ih.process_input(event_up)
        assert "w" not in ih.active_keys

    def test_unknown_key_does_not_crash(self, ih):
        event = MagicMock()
        event.type = pygame.KEYDOWN
        event.key = "z"
        ih.process_input(event)

    def test_multiple_keys_tracked(self, ih):
        for k in ["w", "a"]:
            event = MagicMock()
            event.type = pygame.KEYDOWN
            event.key = k
            ih.process_input(event)
        assert "w" in ih.active_keys
        assert "a" in ih.active_keys

    def test_quit_event_returns_true(self, ih):
        event = MagicMock()
        event.type = pygame.QUIT
        result = ih.process_input(event)
        assert result is True

    def test_escape_returns_true(self, ih):
        event = MagicMock()
        event.type = pygame.KEYDOWN
        event.key = pygame.K_ESCAPE
        result = ih.process_input(event)
        assert result is True

    def test_normal_key_returns_false(self, ih):
        event = MagicMock()
        event.type = pygame.KEYDOWN
        event.key = "w"
        result = ih.process_input(event)
        assert result is False


class TestHandleKeyboard:

    def test_returns_list_of_three(self, ih):
        keys = {
            pygame.K_w: False,
            pygame.K_s: False,
            pygame.K_a: False,
            pygame.K_d: False,
            pygame.K_SPACE: False,
            pygame.K_LCTRL: False,
        }
        result = ih.handle_keyboard(keys, 0.016)
        assert isinstance(result, list)
        assert len(result) == 3

    def test_w_moves_forward(self, ih):
        keys = {
            pygame.K_w: True,
            pygame.K_s: False,
            pygame.K_a: False,
            pygame.K_d: False,
            pygame.K_SPACE: False,
            pygame.K_LCTRL: False,
        }
        result = ih.handle_keyboard(keys, 0.016)
        assert result[2] > 0

    def test_s_moves_backward(self, ih):
        keys = {
            pygame.K_w: False,
            pygame.K_s: True,
            pygame.K_a: False,
            pygame.K_d: False,
            pygame.K_SPACE: False,
            pygame.K_LCTRL: False,
        }
        result = ih.handle_keyboard(keys, 0.016)
        assert result[2] < 0

    def test_no_keys_returns_zero_vector(self, ih):
        keys = {
            pygame.K_w: False,
            pygame.K_s: False,
            pygame.K_a: False,
            pygame.K_d: False,
            pygame.K_SPACE: False,
            pygame.K_LCTRL: False,
        }
        result = ih.handle_keyboard(keys, 0.016)
        assert result == [0, 0, 0]


class TestHandleMouse:

    def test_returns_yaw_pitch_tuple(self, ih):
        result = ih.handle_mouse()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_pitch_clamped_max(self, ih):
        ih.pitch = 85.0
        for _ in range(20):
            ih.handle_mouse()
        assert ih.pitch <= 90.0

    def test_pitch_clamped_min(self, ih):
        ih.pitch = -85.0
        for _ in range(20):
            ih.handle_mouse()
        assert ih.pitch >= -90.0
