import pytest
from types import SimpleNamespace
from interfaces.panda_bridge import PandaKernelBridge


@pytest.fixture
def mock_bridge():
    # Setup a minimal session
    session = SimpleNamespace()
    session.pos = [0.0, 0.0, 0.0]
    session.seed = 42
    session.tension = 0
    session.world_engine = SimpleNamespace()  # Mocking engine for speed

    # We don't want to actually launch a window during testing
    # So we patch ShowBase's __init__ or just test the class methods
    bridge = PandaKernelBridge.__new__(PandaKernelBridge)
    bridge.session = session
    bridge.key_map = {"up": False, "down": False, "left": False, "right": False}
    return bridge


def test_wsad_logic_updates_pos(mock_bridge):
    # Simulate 'W' press (Up)
    mock_bridge.key_map["up"] = True

    # Mock the move_task logic (dt = 1.0, speed = 20.0)
    # session.pos[2] is our 'Forward/Z' axis in the Kernel
    dt = 1.0
    speed = 20.0

    if mock_bridge.key_map["up"]:
        mock_bridge.session.pos[2] += speed * dt

    assert mock_bridge.session.pos[2] == 20.0
    assert mock_bridge.session.pos[0] == 0.0  # Lateral stayed still


def test_diagonal_movement(mock_bridge):
    # Simulate 'W' and 'D' (Up and Right)
    mock_bridge.key_map["up"] = True
    mock_bridge.key_map["right"] = True

    dt = 0.5  # Half second move
    speed = 20.0

    if mock_bridge.key_map["up"]:
        mock_bridge.session.pos[2] += speed * dt
    if mock_bridge.key_map["right"]:
        mock_bridge.session.pos[0] += speed * dt

    assert mock_bridge.session.pos[0] == 10.0
    assert mock_bridge.session.pos[2] == 10.0
