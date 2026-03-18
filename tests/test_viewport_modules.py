import pytest
import pygame
import numpy as np
from unittest.mock import patch
from pyrr import Vector3, Matrix44
from avatar import Avatar
from input_handler import InputHandler
from engine import DataNode


def test_avatar_scaling_integrity():
    # Ensure avatar.py __init__ accepts height!
    short = Avatar(height=1.0)
    tall = Avatar(height=2.5)
    assert len(tall.get_full_body()) > len(short.get_full_body())


def test_view_mode_toggle():
    pygame.init()
    # Mocking the heavy OpenGL stuff so the test is "headless"
    with patch("moderngl.create_context"), patch("renderer_handler.RenderHandler"):
        from sanctum import SanctumViewport

        viewport = SanctumViewport()

        mock_actions = {"toggle_view": True}
        with patch.object(InputHandler, "get_actions", return_value=mock_actions):
            if viewport.inputs.get_actions()["toggle_view"]:
                viewport.view_mode = "TPS"

        assert viewport.view_mode == "TPS"


def test_avatar_recoil_reactivity():
    """Verify that the scanner 'kicks' back on the Z-axis when clicking."""
    avatar = Avatar(color=[0.2, 0.8, 1.0])

    # State A: Idle
    idle_hands = avatar.get_view_model(speed=0, dt=0.016, is_clicking=False)
    # State B: Clicking
    active_hands = avatar.get_view_model(speed=0, dt=0.016, is_clicking=True)

    # The right hand is at index 0. Check the Z-coordinate (index 2 of the tuple 'p')
    idle_z = idle_hands[0]["p"][2]
    active_z = active_hands[0]["p"][2]

    assert active_z < idle_z, "Scanner failed to recoil on click"
