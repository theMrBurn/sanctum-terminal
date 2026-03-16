from src.engine import SanctumTerminal
from src.daemon import cooling_tick


def test_daemon_ledger_interaction(tmp_path):
    # Setup mock DB
    db_file = tmp_path / "daemon_test.db"
    terminal = SanctumTerminal(db_path=str(db_file))

    # Manually simulate a daemon yield update
    terminal.update_vault(
        liquid_delta=5.50, note="TEST_PASSIVE_YIELD", is_mission=False
    )

    snapshot = terminal.get_financial_snapshot()
    assert snapshot["liquid"] == 5.50

    # Ensure the 'last_scout' timestamp WAS NOT updated by the daemon
    last_scout = terminal.get_last_scout_time()
    assert last_scout.year == 1970


def test_cooling_tick_reduces_heat(tmp_path):
    """RED: Verify heat drops by 5 units."""
    db_file = tmp_path / "cooling_test.db"
    terminal = SanctumTerminal(db_path=str(db_file))

    # 1. Manually set heat to 50
    terminal.cursor.execute(
        "INSERT OR REPLACE INTO system_state (key, value) VALUES ('heat', '50')"
    )
    terminal.conn.commit()

    # 2. Run the cooling logic
    cooling_tick(terminal)

    # 3. Assert
    res = terminal._execute("SELECT value FROM system_state WHERE key='heat'")
    assert int(res[0][0]) == 45


def test_cooling_tick_stops_at_zero(tmp_path):
    """RED: Verify heat doesn't go negative."""
    db_file = tmp_path / "floor_test.db"
    terminal = SanctumTerminal(db_path=str(db_file))

    # 1. Set heat to a low value
    terminal.cursor.execute(
        "INSERT OR REPLACE INTO system_state (key, value) VALUES ('heat', '2')"
    )
    terminal.conn.commit()

    # 2. Run cooling
    cooling_tick(terminal)

    # 3. Assert it floored at 0, not -3
    res = terminal._execute("SELECT value FROM system_state WHERE key='heat'")
    assert int(res[0][0]) == 0
