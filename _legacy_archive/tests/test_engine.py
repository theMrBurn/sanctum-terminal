from core.engine import SanctumTerminal
from core.vault import vault


def test_engine_initialization():
    """Test that the engine starts and loads the vault correctly."""
    engine = SanctumTerminal()
    assert engine is not None
    # Verify the vault is an instance of the vault class
    assert isinstance(engine.vault, vault)


def test_engine_viewport_attachment():
    """Test if the viewport and camera are correctly linked."""
    engine = SanctumTerminal()
    assert engine.viewport is not None
    assert hasattr(engine.viewport, "camera")
    # Verify the camera is initialized
    assert engine.viewport.camera.position == [0.0, 0.0, 0.0]
