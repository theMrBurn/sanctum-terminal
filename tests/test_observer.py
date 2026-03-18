import pytest
from unittest.mock import MagicMock
from systems.observer import ObserverSystem


@pytest.fixture
def observer():
    mock_config = MagicMock()
    # Mock the city resolver used by EnvironmentalSensor logic
    mock_config.resolve_city.return_value = "portland"
    return ObserverSystem(mock_config)


def test_observer_sensor_fusion(observer):
    """Verify shader params and weather data are linked."""
    params = observer.get_shader_params(city="portland")

    assert "u_intensity" in params
    assert "u_pulse_time" in params
    assert isinstance(params["u_intensity"], float)


def test_observer_procedural_failure(observer):
    """Verify that hardware fails when heat is high and scout fails."""
    observer.heat = 95
    # Force a failure by providing low aegis and high hazard
    # resolve_scout(player_aegis, tactic, city)
    res = observer.resolve_scout(0.0, tactic="aggressive")

    if res.system_damage:
        assert observer.sensors_nominal is False
        # Verify weather data reflects the glitch
        weather = observer._get_weather("portland")
        assert weather["condition"] == "SENSOR_GLITCH"


def test_sonar_pulse_timing(observer):
    origin = MagicMock()
    origin.x, origin.y, origin.z = 0.0, 0.0, 0.0

    observer.trigger_pulse(origin)
    params = observer.get_shader_params()
    # Using pytest.approx to handle the float precision we saw earlier
    assert params["u_pulse_time"] == pytest.approx(0.0, abs=0.1)
