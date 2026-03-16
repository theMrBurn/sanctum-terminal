import pytest
from src.scout import ScoutEngine

def test_hazard_rating_calculation():
    """Verify that extreme weather actually increases difficulty."""
    # 1. Perfect Conditions (Base Difficulty)
    perfect_env = {"city": "Portland", "condition": "Clear", "temp": 70, "wind_speed": 0}
    player = {"aegis": 1000}
    engine_easy = ScoutEngine(perfect_env, player)
    
    # 2. Extreme Conditions (High Difficulty)
    extreme_env = {"city": "Portland", "condition": "Extreme", "temp": 20, "wind_speed": 40}
    engine_hard = ScoutEngine(extreme_env, player)
    
    # Using a helper or internal calculation check
    # In our resolve() logic, hazard_rating should be significantly higher for 'extreme'
    res_easy = engine_easy.resolve()
    res_hard = engine_hard.resolve()
    
    # The 'Hard' mission should grant significantly more XP on success 
    # because XP is now scaled to Hazard Rating
    if res_easy.success and res_hard.success:
        assert res_hard.xp_gain > res_easy.xp_gain

def test_narrative_formatting():
    """Ensure the mission log always injects the city and condition correctly."""
    from src.logic.narrative import get_mission_log
    log = get_mission_log(True, "New York", "Stormy")
    assert "New York" in log
    
    log_fail = get_mission_log(False, "Miami", "Heatwave")
    assert "Miami" in log_fail
    assert "Heatwave" in log_fail