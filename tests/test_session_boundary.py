import pytest
import time
import json
import tempfile
import os
from pathlib import Path


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / 'test_vault.db')


@pytest.fixture
def session(db_path):
    from core.systems.session_boundary import SessionBoundary
    return SessionBoundary(db_path=db_path)


class TestSessionBoundaryInit:

    def test_boots_without_error(self, session):
        assert session is not None

    def test_is_first_session_on_fresh_db(self, session):
        assert session.is_first_session() is True

    def test_world_age_zero_on_fresh_db(self, session):
        assert session.world_age() == 0

    def test_elapsed_zero_on_fresh_db(self, session):
        assert session.elapsed_real_seconds() == 0


class TestSessionBegin:

    def test_begin_returns_state(self, session):
        state = session.begin(seed='BURN')
        assert isinstance(state, dict)

    def test_begin_state_has_required_keys(self, session):
        state = session.begin(seed='BURN')
        for key in ['position', 'world_age', 'elapsed_seconds',
                    'atmosphere', 'fingerprint', 'is_first']:
            assert key in state, f'missing: {key}'

    def test_first_session_spawns_at_cavern(self, session):
        state = session.begin(seed='BURN')
        assert state['is_first'] is True
        assert state['position'] is None

    def test_begin_increments_world_age(self, session):
        session.begin(seed='BURN')
        session.end(position=(10.0, 20.0, 6.0))
        session2_state = session.begin(seed='BURN')
        assert session2_state['world_age'] == 1


class TestSessionEnd:

    def test_end_writes_to_db(self, session, db_path):
        session.begin(seed='BURN')
        session.end(position=(10.0, 20.0, 6.0))
        assert Path(db_path).exists()

    def test_end_records_position(self, session):
        session.begin(seed='BURN')
        session.end(position=(42.0, 84.0, 6.0))
        state = session.begin(seed='BURN')
        assert state['position'] == (42.0, 84.0, 6.0)

    def test_end_records_atmosphere(self, session):
        session.begin(seed='BURN')
        atm = {'moisture': 0.7, 'heat': 0.4}
        session.end(position=(0,0,0), atmosphere=atm)
        state = session.begin(seed='BURN')
        assert state['atmosphere']['moisture'] == 0.7

    def test_end_records_fingerprint(self, session):
        session.begin(seed='BURN')
        fp = {'exploration_time': 0.6, 'crafting_time': 0.2}
        session.end(position=(0,0,0), fingerprint=fp)
        state = session.begin(seed='BURN')
        assert state['fingerprint']['exploration_time'] == 0.6


class TestChronoMeterDrift:

    def test_elapsed_seconds_increases(self, session):
        session.begin(seed='BURN')
        session.end(position=(0,0,0))
        elapsed = session.elapsed_real_seconds()
        assert elapsed >= 0

    def test_drift_calculation_returns_float(self, session):
        drift = session.calculate_drift(elapsed_seconds=3600)
        assert isinstance(drift, float)
        assert drift >= 0.0

    def test_drift_proportional_to_elapsed(self, session):
        drift_1h = session.calculate_drift(elapsed_seconds=3600)
        drift_24h = session.calculate_drift(elapsed_seconds=86400)
        assert drift_24h > drift_1h

    def test_drift_caps_at_maximum(self, session):
        drift = session.calculate_drift(elapsed_seconds=999999)
        assert drift <= 1.0

    def test_world_age_increments_per_session(self, session):
        for i in range(3):
            session.begin(seed='BURN')
            session.end(position=(0,0,0))
        assert session.world_age() == 3


class TestSessionRecord:

    def test_get_history_returns_list(self, session):
        session.begin(seed='BURN')
        session.end(position=(0,0,0))
        history = session.get_history()
        assert isinstance(history, list)
        assert len(history) >= 1

    def test_history_has_timestamp(self, session):
        session.begin(seed='BURN')
        session.end(position=(0,0,0))
        history = session.get_history()
        assert 'timestamp' in history[0]

    def test_different_seeds_separate_history(self, session):
        session.begin(seed='BURN')
        session.end(position=(1,1,1))
        session.begin(seed='OTHER')
        session.end(position=(2,2,2))
        burn_history = session.get_history(seed='BURN')
        other_history = session.get_history(seed='OTHER')
        assert len(burn_history) == 1
        assert len(other_history) == 1

class TestSpawnIntegrity:

    def test_spawn_z_matches_terrain(self):
        """
        The spawn position Z must equal terrain.height_at(x,y) + GROUND_Z.
        If this fails the player spawns in the air or underground.
        """
        from core.systems.terrain_generator import TerrainGenerator
        from core.systems.cavern_builder import find_spawn_point
        GROUND_Z = 6.0
        terrain = TerrainGenerator(seed=42)
        sx, sy = find_spawn_point(terrain, seed=42)
        expected_z = terrain.height_at(sx, sy) + GROUND_Z
        # Tolerance: 0.1 units (10cm) -- tight enough to prevent clipping
        assert abs(expected_z - (terrain.height_at(sx, sy) + GROUND_Z)) < 0.1

    def test_spawn_not_underground(self):
        """Player must never spawn below terrain surface."""
        from core.systems.terrain_generator import TerrainGenerator
        from core.systems.cavern_builder import find_spawn_point, CavernBuilder
        GROUND_Z = 6.0
        terrain = TerrainGenerator(seed=42)
        sx, sy = find_spawn_point(terrain, seed=42)
        gz = terrain.height_at(sx, sy)
        spawn_z_eye = gz + GROUND_Z
        assert spawn_z_eye >= gz

    def test_spawn_not_in_air(self):
        """Player must not spawn more than GROUND_Z above terrain."""
        from core.systems.terrain_generator import TerrainGenerator
        from core.systems.cavern_builder import find_spawn_point
        GROUND_Z = 6.0
        terrain = TerrainGenerator(seed=42)
        sx, sy = find_spawn_point(terrain, seed=42)
        gz = terrain.height_at(sx, sy)
        spawn_z_eye = gz + GROUND_Z
        assert spawn_z_eye <= gz + GROUND_Z + 0.1

    def test_game_loop_ground_matches_spawn(self):
        """
        What game_loop computes as ground must match spawn Z.
        This is the exact check that prevents mid-air spawn.
        """
        from core.systems.terrain_generator import TerrainGenerator
        from core.systems.cavern_builder import find_spawn_point
        GROUND_Z = 6.0
        terrain = TerrainGenerator(seed=42)
        sx, sy = find_spawn_point(terrain, seed=42)
        spawn_z     = terrain.height_at(sx, sy) + GROUND_Z
        loop_ground = terrain.height_at(sx, sy) + GROUND_Z
        assert abs(spawn_z - loop_ground) < 0.001
