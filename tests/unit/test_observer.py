import pytest
import numpy as np
from unittest.mock import MagicMock
from core.systems.observer import ObserverSystem


@pytest.fixture
def observer():
    config = MagicMock()
    return ObserverSystem(config)


def test_observer_sensor_fusion(observer):
    # Pass 0.0 magnitude for a static check
    observer.update(0.1, 0.0)
    params = observer.get_shader_params(city="portland")
    assert "u_intensity" in params
    assert "u_pulse_origin" in params


def test_observer_heat_generation(observer):
    # Simulate high world velocity (2.0 m/s)
    observer.update(0.1, 2.0)
    assert observer.heat > 0.0


def test_sonar_pulse_timing(observer):
    origin = MagicMock()
    origin.x, origin.y, origin.z = 0.0, 0.0, 0.0
    observer.trigger_pulse(origin)
    assert observer.is_pulsing is True
    assert observer.pulse_time == 0.0
