import pytest
from scout import ScoutEngine, ThermalError

def test_hazard_rating_calculation():
    """Verify that the scout engine initializes and produces valid rewards."""
    perfect_env = {"city": "Portland", "condition": "Clear", "temp": 70}
    player = {"aegis": 1000}
    engine = ScoutEngine(perfect_env, player)
    result = engine.resolve()
    assert hasattr(result, "xp_gain")
    assert hasattr(result, "success")

def test_scout_raises_thermal_lockout():
    """Verify that resolve() raises ThermalError at 100% heat."""
    env = {"city": "Portland", "condition": "Clear"}
    player = {"aegis": 1000}
    engine = ScoutEngine(env, player, heat=100)
    with pytest.raises(ThermalError) as excinfo:
        engine.resolve()
    assert "CRITICAL OVERHEAT" in str(excinfo.value)

def test_thermal_lockout_message_integrity():
    """Verify the error string is UI-ready for the 'flush' hint."""
    env = {"city": "Portland"}
    engine = ScoutEngine(env, {}, heat=105)
    with pytest.raises(ThermalError) as excinfo:
        engine.resolve()
    assert "Vent thermal load" in str(excinfo.value)

def test_high_heat_failure_hazard_scaling():
    """Verify that high heat makes the hazard rating climb."""
    env = {"condition": "Clear"}
    player = {"aegis": 1000}
    engine_cool = ScoutEngine(env, player, heat=0)
    engine_hot = ScoutEngine(env, player, heat=80)
    res_cool = engine_cool.resolve()
    res_hot = engine_hot.resolve()
    if res_cool.success and res_hot.success:
        assert res_hot.xp_gain > res_cool.xp_gain

def test_narrative_formatting():
    """Ensure the mission log always injects the city correctly."""
    env = {"city": "New York", "condition": "Clear"}
    player = {"aegis": 1000}
    engine = ScoutEngine(env, player, tactic="stealth")
    result = engine.resolve()
    assert "New York" in result.description
    assert "[STEALTH]" in result.description

def test_critical_failure_triggers_damage_flag():
    """Verify that high-heat failures include the system_damage attribute."""
    env = {"condition": "Extreme"}
    player = {"aegis": 1000}
    engine = ScoutEngine(env, player, heat=90)
    result = engine.resolve()
    assert hasattr(result, "system_damage")

def test_scout_tactic_scaling():
    """Verify that 'Aggressive' tactics increase both heat and potential reward."""
    env = {"condition": "Clear"}
    player = {"aegis": 1000}
    engine_stealth = ScoutEngine(env, player, tactic="stealth")
    engine_aggressive = ScoutEngine(env, player, tactic="aggressive")
    res_stealth = engine_stealth.resolve()
    res_aggressive = engine_aggressive.resolve()
    assert res_aggressive.heat_gain > res_stealth.heat_gain
    if res_stealth.success and res_aggressive.success:
        assert res_aggressive.aegis_delta > res_stealth.aegis_delta

def test_damaged_sensor_penalty():
    """Verify that damaged sensors force a [BLIND SCAN] and spike hazard."""
    env = {"condition": "Clear"}
    player = {"aegis": 1000}
    status = {"sensor_array": False}
    engine = ScoutEngine(env, player, hardware_status=status)
    result = engine.resolve()
    assert "BLIND SCAN" in result.description
    if not result.success:
        assert "SENSOR FAILURE" in result.description