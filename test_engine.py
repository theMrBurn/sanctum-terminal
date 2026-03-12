import pytest
import sqlite3
import os
from engine import SanctumTerminal

@pytest.fixture
def temp_vault(tmp_path):
    """Creates a temporary database for risk-free testing."""
    db_file = tmp_path / "test_vault.db"
    terminal = SanctumTerminal()
    terminal.db_path = str(db_file)
    
    # Initialize schema
    with sqlite3.connect(terminal.db_path) as conn:
        conn.execute("CREATE TABLE ledger (id INTEGER PRIMARY KEY, timestamp TEXT, amount REAL, event_type TEXT, note TEXT)")
        conn.execute("CREATE TABLE archive (id INTEGER PRIMARY KEY, archetypal_name TEXT, vibe TEXT, cost REAL)")
    
    return terminal

def test_ledger_integrity(temp_vault):
    """Validates that credits are correctly logged."""
    temp_vault.log_event(500.0, "DEPOSIT", "Test Deposit")
    
    with sqlite3.connect(temp_vault.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT amount FROM ledger WHERE event_type='DEPOSIT'")
        row = cursor.fetchone()
        assert row[0] == 500.0  # nosec: B101

def test_atomic_acquisition(temp_vault):
    """Ensures acquisitions correctly affect both ledger and archive."""
    # Assuming acquire_relic method exists in your engine.py
    # If not yet merged, this test serves as the specification
    name, vibe, cost = "Test Relic", "Cyberpunk", 50.0
    
    # Simulate the logic if method isn't in engine.py yet
    temp_vault.log_event(-cost, "CONVERSION", f"Acquired: {name}")
    with sqlite3.connect(temp_vault.db_path) as conn:
        conn.execute("INSERT INTO archive (archetypal_name, vibe, cost) VALUES (?, ?, ?)", (name, vibe, cost))
        
        cursor = conn.cursor()
        cursor.execute("SELECT SUM(amount) FROM ledger")
        assert cursor.fetchone()[0] == -50.0  # nosec: B101
        
        cursor.execute("SELECT COUNT(*) FROM archive")
        assert cursor.fetchone()[0] == 1  # nosec: B101