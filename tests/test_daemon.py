from src.engine import SanctumTerminal


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
    # (Passive yield shouldn't trigger a mission cooldown)
    last_scout = terminal.get_last_scout_time()
    assert last_scout.year == 1970
