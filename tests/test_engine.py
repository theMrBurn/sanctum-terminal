import pytest
from engine import SanctumTerminal


@pytest.fixture
def temp_vault(tmp_path):
    """Isolated vault for unit testing."""
    db_file = tmp_path / "vault_test.db"
    # Initialize with debug=True so we can see internal level-ups
    return SanctumTerminal(db_path=str(db_file), debug=True)


def test_ledger_integrity(temp_vault):
    """Validates that credits are correctly logged and retrieved."""
    # Use the restored log_event method
    temp_vault.log_event(500.0, "DEPOSIT", "Test Deposit")

    # Verify using the engine's own balance logic
    balance = temp_vault.get_total_balance()
    assert balance == 500.0


def test_atomic_acquisition(temp_vault):
    """Ensures acquisitions correctly affect both ledger and archive."""
    name, vibe, cost = "Test Relic", "Cyberpunk", 50.0

    # This uses the restored acquire_relic which also grants Core XP
    temp_vault.acquire_relic(name, vibe, cost)

    snapshot = temp_vault.get_financial_snapshot()

    # Logic: Liquid drops by cost, Assets increase by cost, Aegis (total) is 0
    assert snapshot["liquid"] == -50.0
    assert snapshot["assets"] == 50.0
    assert snapshot["aegis"] == 0.0

    # Bonus: Verify the 'Core' system gained XP from the acquisition
    specs = temp_vault.get_system_specs()
    assert specs["core"]["xp"] > 0


def test_hardware_integrity_persistence(temp_vault):
    """Verify that we can store and retrieve hardware damage status."""
    # 1. Set damage to True in the isolated test DB
    temp_vault.apply_hardware_damage("sensor_array", damaged=True)

    # 2. Retrieve it
    is_damaged = temp_vault.get_hardware_status("sensor_array")

    assert is_damaged is True


def test_hardware_repair_restores_integrity(temp_vault):
    """RED: Verify that repairing a component resets its damage flag and costs Aegis."""
    # 1. Force a damaged state
    temp_vault.apply_hardware_damage("sensor_array", damaged=True)

    # 2. Add some funds to cover the repair cost
    temp_vault.log_event(500.0, "DEPOSIT", "Repair Fund")

    # 3. Call the repair method
    # This will trigger the AttributeError because the method doesn't exist yet
    temp_vault.repair_hardware("sensor_array", cost=200.0)

    # 4. Assertions
    assert temp_vault.get_hardware_status("sensor_array") is False
    assert temp_vault.get_total_balance() == 300.0
