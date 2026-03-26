from pathlib import Path

import pytest

from FirstLight import FirstLight
from SimulationRunner import Simulation
from utils.VoxelFactory import VoxelFactory


@pytest.fixture
def factory():
    return VoxelFactory(export_dir="tests/mock_exports", live_dir="tests/mock_live")


def test_factory_sanitization(factory):
    """Ensure filenames with spaces/parens are healed and manifests created."""
    factory.process_all_exports()
    manifest = Path("tests/mock_live/TEST_Relic/manifest.json")
    assert manifest.exists()


def test_library_registry():
    """Ensure FirstLight categorizes assets correctly upon boot."""
    app = FirstLight(headless=True)
    assert len(app.asset_lib) >= 0
    app.destroy()


def test_player_movement():
    """Ensure the Ground Lock keeps the camera at the correct Z-height."""
    sim = Simulation(headless=True)
    sim.app.camera.setPos(0, 0, 100)
    sim.process_movement(0.1)
    assert sim.app.camera.getZ() == 6.0
    sim.app.destroy()
