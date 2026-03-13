import os
import pytest
import sqlite3
from src.engine import SanctumTerminal
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

@pytest.fixture
def mock_env(tmp_path):
    """Isolated sandbox for testing."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_file = data_dir / "vault_test.db"
    
    # Initialize with debug=True so we see the telemetry during tests
    print(f"\n[INTEGRATION] Initializing Mock Vault at: {db_file}")
    terminal = SanctumTerminal(db_path=str(db_file), debug=True)
    return {"terminal": terminal, "db_path": str(db_file)}

def test_full_acquisition_cycle(mock_env):
    """Verifies that acquiring a relic correctly updates Ledger and Archive."""
    terminal = mock_env["terminal"]
    
    test_relic = "Metropolis (4K)"
    test_cost = 45.00
    terminal.acquire_relic(test_relic, "Sci-Fi", test_cost)
    
    table = Table(title="POST-ACQUISITION DB SNAPSHOT", box=box.ROUNDED)
    table.add_column("Table", style="cyan")
    table.add_column("Entry", style="white")
    
    ledger_data = terminal._execute("SELECT * FROM ledger ORDER BY id DESC LIMIT 1")
    archive_data = terminal._execute("SELECT * FROM archive ORDER BY id DESC LIMIT 1")
    
    table.add_row("LEDGER", str(ledger_data[0]))
    table.add_row("ARCHIVE", str(archive_data[0]))
    console.print(table)

def test_directory_resolution():
    """Ensures the engine finds the production /data folder correctly."""
    terminal = SanctumTerminal()
    print(f"[PATH] Engine resolved Vault location to: {terminal.db_path}")
    assert "data/vault.db" in terminal.db_path
    assert os.path.isabs(terminal.db_path)

def test_balance_calculation(mock_env):
    """
    TDD REQUIREMENT:
    The engine must sum the 'amount' column of the ledger
    to return the current liquid balance.
    """
    terminal = mock_env["terminal"]

    print("\n[TDD] Testing Balance Calculation...")
    # Seed with two events: +100 and -40
    terminal.log_event(100.00, "DEPOSIT", "Initial Seed")
    terminal.log_event(-40.00, "PURCHASE", "Minor Relic")

    # This call is the 'RED' phase—it will fail if the method is missing
    balance = terminal.get_total_balance()

    print(f"[VERIFY] Expected: 60.0, Received: {balance}")
    assert balance == 60.0