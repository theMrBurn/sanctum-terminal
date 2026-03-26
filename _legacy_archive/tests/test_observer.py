import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from core.systems.observer import ObserverSystem


def test_observer_registration():
    obs = ObserverSystem()
    assert obs.active is False
    obs.activate()
    assert obs.active is True
