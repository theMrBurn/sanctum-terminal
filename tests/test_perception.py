import pytest
import pygame
from unittest.mock import MagicMock
from perception import PerceptionController  # RENAME FIX


def test_sonar_pulse_lifecycle():
    """Verify that the sonar pulse expands and eventually deactivates."""
    mock_sensors = MagicMock()
    # Mocking the sensor return for consistency
    mock_sensors.fetch_passive_data.return_value = {"temp": 60}

    pc = PerceptionController(mock_sensors)

    # 1. TRIGGER
    # Using a simple Mock for the origin vector
    origin = MagicMock()
    origin.x, origin.y, origin.z = 0.0, 0.0, 0.0
    pc.trigger_pulse(origin)
    assert pc.pulse_active is True

    # 2. EXPANSION (Mocking time pass via the new current_time override)
    # At 1.0s, u_pulse_time should be 1.0
    state = pc.get_shader_state(current_time=pc.pulse_start_time + 1.0)
    assert state["u_pulse_time"] == 1.0

    # 3. EXPIRATION
    # At 4.0s (beyond duration), it should be inactive
    state = pc.get_shader_state(current_time=pc.pulse_start_time + 4.0)
    assert pc.pulse_active is False
    assert state["u_pulse_time"] == 0.0
