import os
import pytest
import sqlite3
from src.engine import SanctumTerminal

@pytest.fixture
def mock_env(tmp_path):
    # Setup paths
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_file = data_dir / "vault_test.db"
    
    print(f"\n[INTEGRATION] Initializing Mock Vault at: {db_file}")
    terminal = SanctumTerminal(db_path=str(db_file))
    return {"terminal": terminal, "db_path": str(db_file)}

def test_full_acquisition_cycle(mock_env):
    # Initialize engine with debug=True to see the "wire" traffic
    terminal = SanctumTerminal(db_path=mock_env["db_path"], debug=True)
    
    # 1. THE REQUEST
    test_relic = "Metropolis (4K)"
    test_cost = 45.00
    terminal.acquire_relic(test_relic, "Sci-Fi", test_cost)
    
    # 2. THE VERIFICATION (The "Response" Package)
    table = Table(title="POST-ACQUISITION DB SNAPSHOT", box=box.ROUNDED)
    table.add_column("Table", style="cyan")
    table.add_column("Entry", style="white")
    
    # Query Ledger
    ledger_data = terminal._execute("SELECT * FROM ledger ORDER BY id DESC LIMIT 1")
    table.add_row("LEDGER", str(ledger_data[0]))
    
    # Query Archive
    archive_data = terminal._execute("SELECT * FROM archive ORDER BY id DESC LIMIT 1")
    table.add_row("ARCHIVE", str(archive_data[0]))
    
    console.print(table)

def test_directory_resolution():
    terminal = SanctumTerminal()
    print(f"[PATH] Engine resolved Vault location to: {terminal.db_path}")
    assert "data/vault.db" in terminal.db_path
    assert os.path.isabs(terminal.db_path)