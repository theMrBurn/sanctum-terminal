# tests/test_location.py
from core.session import GameSession


def test_urban_mapping():
    session = GameSession()
    # Archetype 'URBAN' contains 'city'
    session.input_buffer = "i am in a city"
    session.calibrate(session.input_buffer)
    assert session.user_locale == "URBAN"


def test_forest_mapping():
    session = GameSession()
    # Archetype 'FOREST' contains 'woods' and 'trees'
    session.input_buffer = "woods and trees"
    session.calibrate(session.input_buffer)
    assert session.user_locale == "FOREST"


def test_glitch_fallback():
    session = GameSession()
    # No tokens found should trigger GLITCH
    session.input_buffer = "12345 abcde"
    session.calibrate(session.input_buffer)
    assert session.user_locale == "GLITCH"
