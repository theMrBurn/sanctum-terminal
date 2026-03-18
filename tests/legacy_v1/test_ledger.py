import pytest
from engine import SanctumTerminal
from scout import ScoutResult


@pytest.fixture
def temp_terminal(tmp_path):
    """Provides a clean, temporary database for ledger testing."""
    db_file = tmp_path / "test_vault.db"
    return SanctumTerminal(db_path=str(db_file))


def test_mission_ledger_persistence(temp_terminal):
    """Verify that recording a mission creates a retrievable row in the ledger."""
    # 1. Setup a dummy result
    mock_result = ScoutResult(
        success=True,
        description="Uplink stable in Portland.",
        aegis_delta=100.0,
        xp_gain=15,
        heat_gain=10,
    )

    # 2. Record the mission
    temp_terminal.record_mission(mock_result, "portland", "aggressive")

    # 3. Query the ledger directly
    temp_terminal.cursor.execute(
        "SELECT city, tactic, success, xp_gain FROM mission_ledger"
    )
    row = temp_terminal.cursor.fetchone()

    assert row is not None
    assert row[0] == "portland"
    assert row[1] == "aggressive"
    assert row[2] == 1  # Success stored as integer
    assert row[3] == 15


def test_ledger_chronology(temp_terminal):
    """Verify that missions are recorded with timestamps in order."""
    mock_result = ScoutResult(True, "Log 1", 50.0, 10, 5)

    temp_terminal.record_mission(mock_result, "nyc", "stealth")
    temp_terminal.record_mission(mock_result, "sea", "standard")

    temp_terminal.cursor.execute(
        "SELECT city FROM mission_ledger ORDER BY timestamp DESC"
    )
    results = temp_terminal.cursor.fetchall()

    # Last mission (Seattle) should be first in a DESC query
    assert results[0][0] == "sea"
    assert results[1][0] == "nyc"
