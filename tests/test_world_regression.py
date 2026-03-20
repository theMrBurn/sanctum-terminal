# tests/test_world_regression.py
from core.session import GameSession
from core.atlas import ARCHETYPES


def test_atlas_initialization():
    """Verify archetypes are loaded."""
    assert "URBAN" in ARCHETYPES
    assert "FOREST" in ARCHETYPES


def test_neural_sync_resolution():
    """Verify tokenized resolution."""
    session = GameSession()
    session.input_buffer = "vegas neon"
    session.calibrate(session.input_buffer)
    assert session.user_locale == "DESERT"
    # Verify neon tag (0x10) is active
    assert 0x10 in session.biome_tags
