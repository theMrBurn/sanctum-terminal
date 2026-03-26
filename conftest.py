import pytest
import builtins
from direct.showbase.ShowBase import ShowBase


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
