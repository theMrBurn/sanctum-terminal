from engine import SanctumTerminal


def test_system_initialization(tmp_path):
    db_file = tmp_path / "progression.db"
    terminal = SanctumTerminal(db_path=str(db_file))

    specs = terminal.get_system_specs()
    assert "fidelity" in specs
    assert specs["fidelity"]["level"] == 0  # Verification of BIOS mode
    assert specs["uplink"]["level"] == 1


def test_level_up_logic(tmp_path):
    db_file = tmp_path / "level_up.db"
    terminal = SanctumTerminal(db_path=str(db_file))

    # Fidelity starts at 0 XP, 50 needed for Level 1
    terminal.add_system_xp("fidelity", 60)

    specs = terminal.get_system_specs()
    assert specs["fidelity"]["level"] == 1
    assert specs["fidelity"]["xp"] == 10  # Remainder carried over
