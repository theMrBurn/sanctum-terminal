import os
import sys

import pytest

# Legacy V1 is deeper, so we go up three levels to hit root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from core.engine import SanctumTerminal


@pytest.fixture
def active_engine():
    return SanctumTerminal()


def test_daemon_status_check(active_engine):
    """Verifies the loader is reachable via the engine."""
    # Updated to check for 'loader' as we move away from 'daemon'
    assert hasattr(active_engine, "loader") or hasattr(active_engine, "daemon")
