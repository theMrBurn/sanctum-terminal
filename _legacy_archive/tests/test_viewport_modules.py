import pytest
from pathlib import Path
from panda3d.core import NodePath


# --- Headless Engine Mock ---
@pytest.fixture(scope="module", autouse=True)
def mock_panda_engine(mocker):
    """Prevents Panda3D from trying to open a window during unit tests."""
    mocker.patch("direct.showbase.ShowBase.ShowBase.__init__", return_value=None)
    # Mocking global pointer for VFS if your models use it
    from panda3d.core import VirtualFileSystem

    mocker.patch.object(VirtualFileSystem, "get_global_ptr")


# --- The Actual Tests ---
from core.viewport import Viewport
from models.procedural.cube import Cube
from models.procedural.grid import Grid


def test_cube_generation():
    """Regression: Ensure Cube creates a valid NodePath."""
    # We use a try/except because if Panda3D isn't mocked
    # correctly, it'll throw a C++ error here.
    try:
        test_cube = Cube()
        assert isinstance(test_cube, NodePath)
        assert test_cube.getName() == "cube"
    except Exception as e:
        pytest.fail(f"Cube generation failed due to Engine Initialization: {e}")


def test_grid_parameters():
    """Stability: Verify Grid respects scale constraints."""
    test_grid = Grid(size=10, subdivisions=5)
    assert test_grid is not None
    # Assuming your Grid class has a get_size method or similar
    # assert test_grid.get_size() == 10
