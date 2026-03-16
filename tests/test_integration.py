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


def test_asset_valuation(mock_env):
    """
    TDD REQUIREMENT:
    The engine must sum the 'cost' column of the archive
    to return the total value of all physical relics.
    """
    terminal = mock_env["terminal"]
    print("\n[TDD] Testing Asset Valuation...")

    # Seed the archive with two relics
    terminal.acquire_relic("Akira (4K)", "Anime", 30.00)
    terminal.acquire_relic("The Thing (4K)", "Horror", 25.00)

    # This call will trigger the 'AttributeError' we're looking for
    valuation = terminal.get_total_valuation()

    print(f"[VERIFY] Expected: 55.0, Received: {valuation}")
    assert valuation == 55.0


def test_financial_snapshot(mock_env):
    """
    TDD REQUIREMENT:
    The engine must provide a unified dictionary containing
    both liquid balance and asset valuation for the UI layer.
    """
    terminal = mock_env["terminal"]

    print("\n[TDD] Testing Financial Snapshot...")
    # Seed data: $1000 in, $40 out for a relic
    terminal.log_event(1000.00, "INITIAL_STABILITY", "Vault Seed")
    terminal.acquire_relic("Ghost in the Shell", "Anime", 40.00)

    # Logic:
    # Liquid = 1000 - 40 = 960.0
    # Assets = 40.0
    # Aegis (Total) = 1000.0

    snapshot = terminal.get_financial_snapshot()

    print(f"[VERIFY] Snapshot Payload: {snapshot}")
    assert snapshot["liquid"] == 960.0
    assert snapshot["assets"] == 40.0
    assert snapshot["aegis"] == 1000.0


def test_complex_transaction_integrity(mock_env):
    """
    STRESS TEST:
    Verifies that a relic acquisition correctly:
    1. Subtracts from Liquid
    2. Adds to Assets
    3. Keeps Total Aegis constant
    """
    terminal = mock_env["terminal"]

    # 1. Establish Baseline
    terminal.log_event(500.00, "INITIAL_STABILITY", "Hardening Test Seed")

    # 2. Execute High-Value Conversion
    # This should trigger the BEGIN TRANSACTION / COMMIT panels in telemetry
    terminal.acquire_relic("Criterion: Stalker (4K)", "Sci-Fi", 50.00)

    # 3. Pull Snapshot
    snapshot = terminal.get_financial_snapshot()

    # 4. Verify Math Integrity
    # Liquid (500-50=450) + Assets (50) must equal 500
    print(f"[VERIFY] Snapshot Audit: {snapshot}")
    assert snapshot["liquid"] == 450.0
    assert snapshot["assets"] == 50.0
    assert snapshot["aegis"] == 500.0


def test_scout_generation_logic():
    # 1. Setup Passive (Rainy Night in Portland)
    weather = {"condition": "Rain", "visibility": "Low"}

    # 2. Setup Active (High Aegis, Horror Bias)
    player = {"aegis": 15880, "bias": "Horror"}

    # 3. Generate Mission (Synchronized with hardened engine signature)
    engine = ScoutEngine(weather, player)
    mission = engine.resolve()

    assert mission.success is not None
    assert mission.aegis_delta != 0

    # 4. Assert
    assert mission.difficulty == "Hard"  # Because of Rain
    assert "Resilience" in mission.buffs  # Because of Horror bias
