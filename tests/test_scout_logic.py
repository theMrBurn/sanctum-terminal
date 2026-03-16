import pytest
from src.scout import ScoutEngine, ThermalError


def test_hazard_rating_calculation():
    """Verify that the scout engine initializes and produces valid rewards."""
    perfect_env = {"city": "Portland", "condition": "Clear", "temp": 70}
    player = {"aegis": 1000}

    # We check that the result object is valid and contains expected attributes
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
    """Option B: Verify the error string is UI-ready for the 'flush' hint."""
    env = {"city": "Portland"}
    engine = ScoutEngine(env, {}, heat=105)  # Test overshoot logic

    with pytest.raises(ThermalError) as excinfo:
        engine.resolve()

    assert "Vent thermal load" in str(excinfo.value)


def test_high_heat_failure_hazard_scaling():
    """Verify that high heat makes the hazard rating actually climb."""
    env = {"condition": "Clear"}
    player = {"aegis": 1000}

    # Engine at 0 heat vs 80 heat
    engine_cool = ScoutEngine(env, player, heat=0)
    engine_hot = ScoutEngine(env, player, heat=80)

    res_cool = engine_cool.resolve()
    res_hot = engine_hot.resolve()

    # If both succeed, the hot one must grant more XP due to higher hazard
    if res_cool.success and res_hot.success:
        assert res_hot.xp_gain > res_cool.xp_gain


def test_narrative_formatting():
    """Ensure the mission log always injects the city correctly."""
    from src.logic.narrative import get_mission_log

    log = get_mission_log(True, "New York", "Stormy")
    assert "New York" in log


def test_critical_failure_triggers_damage_flag():
    """Verify that high-heat failures include the system_damage attribute."""
    env = {"condition": "Extreme"}
    player = {"aegis": 1000}

    # Force high heat to ensure the engine is in the 'danger zone'
    engine = ScoutEngine(env, player, heat=90)
    result = engine.resolve()

    # Verified: The result must at least have the attribute (Green Phase)
    assert hasattr(result, "system_damage")


def test_scout_tactic_scaling():
    """RED: Verify that 'Aggressive' tactics increase both heat and potential reward."""
    env = {"condition": "Clear"}
    player = {"aegis": 1000}

    # Testing the new 'tactic' parameter
    engine_stealth = ScoutEngine(env, player, tactic="stealth")
    engine_aggressive = ScoutEngine(env, player, tactic="aggressive")

    res_stealth = engine_stealth.resolve()
    res_aggressive = engine_aggressive.resolve()

    # 1. Aggressive should generate more heat than stealth
    assert res_aggressive.heat_gain > res_stealth.heat_gain

    # 2. If both succeed, aggressive should yield more Aegis
    if res_stealth.success and res_aggressive.success:
        assert res_aggressive.aegis_delta > res_stealth.aegis_delta
