from engine import SanctumTerminal
from daemon import cooling_tick


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
    """Verify heat drops by 5 units under standard conditions."""
    db_file = tmp_path / "cooling_test.db"
    terminal = SanctumTerminal(db_path=str(db_file))

    # 1. Manually set heat to 50
    terminal.cursor.execute(
        "INSERT OR REPLACE INTO system_state (key, value) VALUES ('heat', '50')"
    )
    terminal.conn.commit()

    # 2. Run the cooling logic (defaults to 'Clear' weather)
    cooling_tick(terminal)

    # 3. Assert
    res = terminal._execute("SELECT value FROM system_state WHERE key='heat'")
    assert int(res[0][0]) == 45


def test_cooling_rate_scales_with_weather(tmp_path):
    """GREEN: Verify that 'Snow' cools faster than 'Clear' weather using functional logic."""
    # Setup an isolated terminal
    db_file = tmp_path / "daemon_weather_test.db"
    terminal = SanctumTerminal(db_path=str(db_file))

    # 1. Test Clear Weather (Base 5% dissipation)
    terminal.cursor.execute("UPDATE system_state SET value = '50' WHERE key = 'heat'")
    terminal.conn.commit()
    res_clear = cooling_tick(terminal, condition="Clear")

    # 2. Test Snow Weather (Double 10% dissipation)
    # Reset heat to 50 for a fair comparison
    terminal.cursor.execute("UPDATE system_state SET value = '50' WHERE key = 'heat'")
    terminal.conn.commit()
    res_snow = cooling_tick(terminal, condition="Snow")

    # Clear should result in 45, Snow should result in 40
    assert res_clear == 45
    assert res_snow == 40
    assert res_snow < res_clear
