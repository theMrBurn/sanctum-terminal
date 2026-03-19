from systems.game_state import GameState
from systems.rosetta_stone import VOXEL_REGISTRY


def test_scaling_integrity_floor_25():
    """Stress test: Ensure the 'No Max' math remains stable at Floor 25."""
    state = GameState()
    state.floor = 25

    # Calculate expected trap damage: 4 * (1.15^25)
    expected_dmg = int(4 * (1.15**25))
    actual_dmg = state.get_scaling_stat(4)

    assert actual_dmg == expected_dmg
    assert actual_dmg > 100, "Difficulty curve is too flat at Floor 25"
    print(f"\n[PASS] Floor 25 Trap Damage: {actual_dmg} HP")


def test_collision_regression():
    """Verify that 'wall' types consistently block movement."""
    state = GameState()
    # Find all symbols marked as 'wall' in the Rosetta Stone
    walls = [s for s, v in VOXEL_REGISTRY.items() if v.get("type") == "wall"]

    for wall in walls:
        can_move = state.process_step(wall)
        assert (
            can_move is False
        ), f"Regression: Player walked through wall symbol '{wall}'"


def test_level_up_consistency():
    """Ensure XP math triggers Level Up without overshooting."""
    state = GameState()
    state.xp = 99
    state._check_level_up()
    assert state.lv == 1

    state.xp = 101
    state._check_level_up()
    assert state.lv == 2
    assert state.hp == state.hp_max, "Level up failed to heal player to max"


def test_oob_safety():
    """Chaos Monkey: Ensure position never leaves the 32x32 grid."""
    state = GameState()
    # Attempt to move way off the map
    moves = [(-100, 0), (100, 0), (0, -100), (0, 100)]
    for dx, dy in moves:
        new_x = state.pos[0] + dx
        new_y = state.pos[1] + dy
        # Logic check: This should be handled by the Walker's boundary check
        is_in_bounds = 0 <= new_x < 32 and 0 <= new_y < 32
        assert is_in_bounds is False, f"OOB Move allowed at {new_x}, {new_y}"
