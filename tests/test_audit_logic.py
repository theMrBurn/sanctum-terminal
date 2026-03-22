# tests/test_logic_audit.py
from core.session import GameSession
from engines.world import WorldEngine


def test_lab_mode_bypasses_game_logic():
    """Verify that --lab mode safely bypasses standard procedural logic."""
    session = GameSession()
    session.is_lab_mode = True

    world = WorldEngine(session.seed)

    # 1. The default POI coordinates must be explicitly handled (prevent AttributeError)
    assert world.poi_coords == (0, 0)

    # 2. Check a location far off the 20x20 Lab Stage (-10 to 10)
    # This should be "The Void" (empty space). Normal logic might try to generate things.
    void_node = world.get_node(50, 50, session)
    assert void_node["color"] == (0, 0, 0)
    assert void_node["char"] == " "
    assert void_node["passable"] is False

    # 3. Check the Center Point (0,0) of the Lab
    # Should be the Diagnostic Lantern (ID: 201)
    center_node = world.get_node(0, 0, session)
    assert center_node["char"] == "L"
    assert center_node["passable"] is False
    assert "dither_step" in center_node["meta"]

    # 4. Check a standard Stage Point (e.g., 5, 5)
    # Should be the Neutral Grey Stage
    stage_node = world.get_node(5, 5, session)
    assert stage_node["char"] == "."
    assert stage_node["color"] == (100, 100, 100)
    assert stage_node["passable"] is True
