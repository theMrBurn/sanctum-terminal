import pytest

# To this:
from core.engine import SanctumTerminal


@pytest.fixture
def vault(tmp_path):
    """Creates a temporary isolated vault for integration testing."""
    # Setup: Create a data directory in the temp path
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = str(data_dir / "vault_test.db")

    # Initialize engine with the temp path
    terminal = SanctumTerminal(db_path=db_path)

    # Print for visibility in -vs mode
    print(f"\n[INTEGRATION] Initializing Mock Vault at: {db_path}")

    return terminal


# ... rest of the tests follow below ...
