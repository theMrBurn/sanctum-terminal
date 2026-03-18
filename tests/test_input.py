import pytest
import pygame
import numpy as np
from unittest.mock import patch
from input_handler import InputHandler


class MockKeyStates(dict):
    def __getitem__(self, key):
        return self.get(key, 0)


def test_input_handler_fallback():
    pygame.init()
    handler = InputHandler()
    move = handler.get_movement(0.016)
    assert len(move) == 3


def test_gravity_influence():
    """Verify that vertical velocity decreases due to gravity."""
    pygame.init()
    handler = InputHandler()
    handler.velocity[2] = 1.0  # Start with up momentum
    dt = 0.016

    mock_keys = MockKeyStates({})  # No input
    with patch("pygame.key.get_pressed", return_value=mock_keys):
        v_next = handler.get_movement(dt)

    # Velocity should have dropped below 1.0
    assert v_next[2] < 1.0
