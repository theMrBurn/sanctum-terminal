import builtins

import pytest

# Force headless rendering for all tests — no windows, no audio
try:
    from panda3d.core import loadPrcFileData
    loadPrcFileData("", "window-type none")
    loadPrcFileData("", "audio-library-name null")
except ImportError:
    pass


@pytest.fixture(autouse=True)
def cleanup_showbase():
    yield
    if hasattr(builtins, "base"):
        try:
            builtins.base.destroy()
        except Exception:
            pass
        try:
            delattr(builtins, "base")
        except AttributeError:
            pass
