import os
import pytest
from src.scout import ScoutEngine
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
    """TDD: The engine must sum the 'amount' column of the ledger."""
    terminal = mock_env["terminal"]
    terminal.log_event(100.00, "DEPOSIT", "Initial Seed")
    terminal.log_event(-40.00, "PURCHASE", "Minor Relic")
    balance = terminal.get_total_balance()
    assert balance == 60.0


def test_asset_valuation(mock_env):
    """TDD: The engine must sum the 'cost' column of the archive."""
    terminal = mock_env["terminal"]
    terminal.acquire_relic("Akira (4K)", "Anime", 30.00)
    terminal.acquire_relic("The Thing (4K)", "Horror", 25.00)
    valuation = terminal.get_total_valuation()
    assert valuation == 55.0


def test_financial_snapshot(mock_env):
    """TDD: Verify the unified financial snapshot."""
    terminal = mock_env["terminal"]
    terminal.log_event(1000.00, "INITIAL_STABILITY", "Vault Seed")
    terminal.acquire_relic("Ghost in the Shell", "Anime", 40.00)
    snapshot = terminal.get_financial_snapshot()
    assert snapshot["liquid"] == 960.0
    assert snapshot["assets"] == 40.0
    assert snapshot["aegis"] == 1000.0


def test_complex_transaction_integrity(mock_env):
    """Stress test mathematical constant: Liquid + Assets = Aegis."""
    terminal = mock_env["terminal"]
    terminal.log_event(500.00, "INITIAL_STABILITY", "Hardening Test Seed")
    terminal.acquire_relic("Criterion: Stalker (4K)", "Sci-Fi", 50.00)
    snapshot = terminal.get_financial_snapshot()
    assert snapshot["liquid"] == 450.0
    assert snapshot["assets"] == 50.0
    assert snapshot["aegis"] == 500.0


def test_scout_generation_logic():
    # 1. Setup Passive (Rainy Night in Portland)
    # Added 'city' here to avoid the KeyError during resolve()
    weather = {"city": "Portland", "condition": "Rain", "visibility": "Low"}

    # 2. Setup Active (High Aegis, Horror Bias)
    player = {"aegis": 15880, "bias": "Horror"}

    # 3. Generate Mission
    engine = ScoutEngine(weather, player)
    mission = engine.resolve()

    assert mission.success is not None
    assert mission.aegis_delta != 0