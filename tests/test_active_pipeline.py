import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from FirstLight import FirstLight


def test_headless_load():
    app = FirstLight(headless=True)
    # Testing the core town load
    relic = app.inject_relic("GLO_Master_Town_V1")
    assert relic is not None
    assert relic["node"].getTightBounds() is not None
