import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path):
    """Clean vault.db with archive schema for each test."""
    db = tmp_path / "vault.db"
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE archive (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            archetypal_name TEXT NOT NULL,
            vibe            TEXT,
            impact_rating   INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def seeded_db(tmp_db):
    """Three relics across all three impact tiers."""
    conn = sqlite3.connect(tmp_db)
    conn.executemany(
        "INSERT INTO archive (archetypal_name, vibe, impact_rating) VALUES (?,?,?)",
        [
            ("Morning Run", "Discipline, Grounding", 3),
            ("Launch Side Project", "Ambition, Risk", 7),
            ("Dentist Appointment", "Dread, Obligation", 4),
        ],
    )
    conn.commit()
    conn.close()
    return tmp_db


@pytest.fixture
def engine(seeded_db):
    """QuestEngine pointed at seeded test DB."""
    from core.systems.quest_engine import QuestEngine

    return QuestEngine(db_path=seeded_db)


@pytest.fixture
def empty_engine(tmp_db):
    """QuestEngine with zero relics."""
    from core.systems.quest_engine import QuestEngine

    return QuestEngine(db_path=tmp_db)


# ── Instantiation ─────────────────────────────────────────────────────────────


class TestQuestEngineInit:

    def test_boots_without_error(self, engine):
        assert engine is not None

    def test_loads_relics_from_db(self, engine):
        assert len(engine.relics) == 3

    def test_relic_shape(self, engine):
        for r in engine.relics:
            assert "archetypal_name" in r
            assert "vibe" in r
            assert "impact_rating" in r

    def test_empty_db_does_not_crash(self, empty_engine):
        assert empty_engine.relics == []

    def test_db_path_missing_raises(self):
        from core.systems.quest_engine import QuestEngine

        with pytest.raises(FileNotFoundError):
            QuestEngine(db_path="/nonexistent/path/vault.db")


# ── State Authority ───────────────────────────────────────────────────────────


class TestGetActiveBiomeRules:

    def test_returns_dict(self, engine):
        rules = engine.get_active_biome_rules()
        assert isinstance(rules, dict)

    def test_contains_required_keys(self, engine):
        rules = engine.get_active_biome_rules()
        assert "biome_override" in rules
        assert "atmosphere" in rules
        assert "encounter_density" in rules
        assert "rotation_speed" in rules

    def test_empty_engine_returns_defaults(self, empty_engine):
        rules = empty_engine.get_active_biome_rules()
        assert rules["biome_override"] is None
        assert rules["atmosphere"]["u_exp"] == pytest.approx(1.0)
        assert rules["encounter_density"] == pytest.approx(0.0)
        assert rules["rotation_speed"] == pytest.approx(1.0)

    def test_high_impact_elevates_encounter_density(self, engine):
        rules = engine.get_active_biome_rules()
        assert rules["encounter_density"] > 0.6

    def test_atmosphere_u_exp_scales_with_impact(self, engine):
        rules = engine.get_active_biome_rules()
        assert rules["atmosphere"]["u_exp"] > 1.0

    def test_atmosphere_contains_shader_keys(self, engine):
        rules = engine.get_active_biome_rules()
        atm = rules["atmosphere"]
        assert "u_fog" in atm
        assert "u_exp" in atm


# ── Impact Tier Mapping ───────────────────────────────────────────────────────


class TestImpactTierMapping:

    @pytest.mark.parametrize(
        "rating,expected_tier",
        [
            (1, "surface"),
            (2, "surface"),
            (3, "surface"),
            (4, "dungeon"),
            (5, "dungeon"),
            (6, "dungeon"),
            (7, "boss"),
            (8, "boss"),
            (9, "boss"),
            (10, "boss"),
        ],
    )
    def test_tier_mapping(self, engine, rating, expected_tier):
        assert engine.get_impact_tier(rating) == expected_tier

    def test_surface_tier_u_exp(self, engine):
        atm = engine.get_atmosphere_for_tier("surface")
        assert atm["u_exp"] <= 1.0

    def test_dungeon_tier_u_exp(self, engine):
        atm = engine.get_atmosphere_for_tier("dungeon")
        assert 1.0 < atm["u_exp"] <= 1.5

    def test_boss_tier_u_exp(self, engine):
        atm = engine.get_atmosphere_for_tier("boss")
        assert atm["u_exp"] > 1.5

    def test_unknown_tier_returns_surface(self, engine):
        atm = engine.get_atmosphere_for_tier("unknown_tier")
        assert atm["u_exp"] <= 1.0


# ── Event Registration ────────────────────────────────────────────────────────


class TestRegisterEvent:

    def test_register_persists_to_db(self, engine, seeded_db):
        engine.register_event(
            {
                "archetypal_name": "Weekly Review",
                "vibe": "Clarity, Control",
                "impact_rating": 5,
            }
        )
        conn = sqlite3.connect(seeded_db)
        rows = conn.execute(
            "SELECT * FROM archive WHERE archetypal_name='Weekly Review'"
        ).fetchall()
        conn.close()
        assert len(rows) == 1

    def test_register_updates_in_memory_relics(self, engine):
        before = len(engine.relics)
        engine.register_event(
            {
                "archetypal_name": "Weekly Review",
                "vibe": "Clarity, Control",
                "impact_rating": 5,
            }
        )
        assert len(engine.relics) == before + 1

    def test_register_missing_name_raises(self, engine):
        with pytest.raises(ValueError):
            engine.register_event({"vibe": "Mystery", "impact_rating": 3})

    def test_register_clamps_impact_high(self, engine):
        engine.register_event(
            {"archetypal_name": "Overloaded", "vibe": "Chaos", "impact_rating": 999}
        )
        assert engine.relics[-1]["impact_rating"] == 10

    def test_register_clamps_impact_low(self, engine):
        engine.register_event(
            {"archetypal_name": "Tiny Thing", "vibe": "Quiet", "impact_rating": -5}
        )
        assert engine.relics[-1]["impact_rating"] == 1

    def test_register_empty_dict_raises(self, engine):
        with pytest.raises(ValueError):
            engine.register_event({})


# ── Relic Dict Bridge (FirstLight interface) ──────────────────────────────────


class TestBuildRelicDict:

    def test_returns_dict(self, engine):
        relic = engine.relics[0]
        result = engine.build_relic_dict(relic)
        assert isinstance(result, dict)

    def test_contains_shader_keys(self, engine):
        relic = engine.relics[0]
        result = engine.build_relic_dict(relic)
        assert "u_fog" in result
        assert "u_exp" in result

    def test_values_are_renderable(self, engine):
        for relic in engine.relics:
            relic_dict = engine.build_relic_dict(relic)
            for _k, v in relic_dict.items():
                if isinstance(v, tuple):
                    assert all(isinstance(x, float) for x in v)
                else:
                    assert isinstance(v, (int, float))

    def test_higher_impact_raises_u_exp(self, engine):
        low = {"archetypal_name": "Small Task", "vibe": "Calm", "impact_rating": 2}
        high = {"archetypal_name": "Big Launch", "vibe": "Terror", "impact_rating": 9}
        assert (
            engine.build_relic_dict(high)["u_exp"]
            > engine.build_relic_dict(low)["u_exp"]
        )


# ── Scenario Array ------------------------------------------------------------
# TDD: five quest types as instantiable templates.
# fetch   -- go get a specific object, bring it back
# escort  -- keep an entity within range until destination reached
# hunt    -- find and interact with a hidden/marked target
# key     -- acquire object A to unlock/enable object B
# switch  -- activate N triggers in the world (order may matter)
#
# Every scenario has:
#   type        -- one of the five
#   state       -- PENDING / ACTIVE / COMPLETE / FAILED
#   objective   -- human-readable, world-legible (not UI text)
#   win_fn      -- callable that returns True when complete
#   on_complete -- callback fired on completion

class TestScenarioArray:

    def test_scenario_engine_importable(self):
        from core.systems.scenario_engine import ScenarioEngine
        assert ScenarioEngine is not None

    def test_scenario_state_importable(self):
        from core.systems.scenario_engine import ScenarioState
        assert ScenarioState is not None

    def test_five_scenario_types_defined(self):
        from core.systems.scenario_engine import SCENARIO_TYPES
        assert set(SCENARIO_TYPES) == {"fetch", "escort", "hunt", "key", "switch"}

    def test_create_fetch_scenario(self):
        from core.systems.scenario_engine import ScenarioEngine, ScenarioState
        se  = ScenarioEngine()
        sid = se.create("fetch", {
            "target_id":  "river_stone_01",
            "return_pos": (0, 0, 0),
            "objective":  "Bring the river stone to the workbench.",
        })
        assert sid is not None
        assert se.get_state(sid) is ScenarioState.PENDING

    def test_create_escort_scenario(self):
        from core.systems.scenario_engine import ScenarioEngine
        se  = ScenarioEngine()
        sid = se.create("escort", {
            "entity_id":   "wanderer_01",
            "destination": (50, 50, 0),
            "radius":      5.0,
            "objective":   "Keep the wanderer close until the waypoint.",
        })
        assert sid is not None

    def test_create_hunt_scenario(self):
        from core.systems.scenario_engine import ScenarioEngine
        se  = ScenarioEngine()
        sid = se.create("hunt", {
            "target_id": "flint_shard_01",
            "objective": "Find the flint shard somewhere in the sector.",
        })
        assert sid is not None

    def test_create_key_scenario(self):
        from core.systems.scenario_engine import ScenarioEngine
        se  = ScenarioEngine()
        sid = se.create("key", {
            "key_id":  "iron_key_01",
            "lock_id": "sealed_door_01",
            "objective": "Find the key. The door will know.",
        })
        assert sid is not None

    def test_create_switch_scenario(self):
        from core.systems.scenario_engine import ScenarioEngine
        se  = ScenarioEngine()
        sid = se.create("switch", {
            "trigger_ids": ["switch_a", "switch_b", "switch_c"],
            "ordered":     False,
            "objective":   "Activate all three markers.",
        })
        assert sid is not None

    def test_activate_moves_to_active(self):
        from core.systems.scenario_engine import ScenarioEngine, ScenarioState
        se  = ScenarioEngine()
        sid = se.create("fetch", {
            "target_id":  "river_stone_01",
            "return_pos": (0, 0, 0),
            "objective":  "Bring the river stone to the workbench.",
        })
        se.activate(sid)
        assert se.get_state(sid) is ScenarioState.ACTIVE

    def test_complete_fires_callback(self):
        from core.systems.scenario_engine import ScenarioEngine, ScenarioState
        log = []
        se  = ScenarioEngine()
        sid = se.create("fetch", {
            "target_id":  "river_stone_01",
            "return_pos": (0, 0, 0),
            "objective":  "Bring the river stone to the workbench.",
        }, on_complete=lambda s: log.append(s))
        se.activate(sid)
        se.complete(sid)
        assert se.get_state(sid) is ScenarioState.COMPLETE
        assert sid in log

    def test_fail_moves_to_failed(self):
        from core.systems.scenario_engine import ScenarioEngine, ScenarioState
        se  = ScenarioEngine()
        sid = se.create("fetch", {
            "target_id":  "river_stone_01",
            "return_pos": (0, 0, 0),
            "objective":  "Bring the river stone to the workbench.",
        })
        se.activate(sid)
        se.fail(sid)
        assert se.get_state(sid) is ScenarioState.FAILED

    def test_cannot_complete_pending_scenario(self):
        from core.systems.scenario_engine import ScenarioEngine, ScenarioState
        se  = ScenarioEngine()
        sid = se.create("fetch", {
            "target_id":  "river_stone_01",
            "return_pos": (0, 0, 0),
            "objective":  "Bring the river stone to the workbench.",
        })
        se.complete(sid)
        assert se.get_state(sid) is ScenarioState.PENDING

    def test_get_active_scenarios(self):
        from core.systems.scenario_engine import ScenarioEngine
        se   = ScenarioEngine()
        sid1 = se.create("fetch",  {"target_id": "a", "return_pos": (0,0,0), "objective": "x"})
        sid2 = se.create("hunt",   {"target_id": "b", "objective": "y"})
        sid3 = se.create("switch", {"trigger_ids": ["t1"], "ordered": False, "objective": "z"})
        se.activate(sid1)
        se.activate(sid2)
        active = se.get_active()
        assert sid1 in active
        assert sid2 in active
        assert sid3 not in active

    def test_get_objective(self):
        from core.systems.scenario_engine import ScenarioEngine
        se  = ScenarioEngine()
        sid = se.create("fetch", {
            "target_id":  "river_stone_01",
            "return_pos": (0, 0, 0),
            "objective":  "Bring the river stone to the workbench.",
        })
        assert se.get_objective(sid) == "Bring the river stone to the workbench."

    def test_win_fn_triggers_complete(self):
        from core.systems.scenario_engine import ScenarioEngine, ScenarioState
        resolved = [False]
        se  = ScenarioEngine()
        sid = se.create("fetch", {
            "target_id":  "river_stone_01",
            "return_pos": (0, 0, 0),
            "objective":  "Bring the river stone to the workbench.",
        }, win_fn=lambda: resolved[0])
        se.activate(sid)
        se.tick()
        assert se.get_state(sid) is ScenarioState.ACTIVE
        resolved[0] = True
        se.tick()
        assert se.get_state(sid) is ScenarioState.COMPLETE

    def test_switch_scenario_tracks_triggers(self):
        from core.systems.scenario_engine import ScenarioEngine, ScenarioState
        se  = ScenarioEngine()
        sid = se.create("switch", {
            "trigger_ids": ["sw_a", "sw_b", "sw_c"],
            "ordered":     False,
            "objective":   "Activate all three.",
        })
        se.activate(sid)
        se.trigger(sid, "sw_a")
        se.trigger(sid, "sw_b")
        assert se.get_state(sid) is ScenarioState.ACTIVE
        se.trigger(sid, "sw_c")
        assert se.get_state(sid) is ScenarioState.COMPLETE

    def test_unknown_scenario_id_returns_none(self):
        from core.systems.scenario_engine import ScenarioEngine
        se = ScenarioEngine()
        assert se.get_state("nonexistent_id") is None

    def test_invalid_scenario_type_raises(self):
        from core.systems.scenario_engine import ScenarioEngine
        se = ScenarioEngine()
        with pytest.raises(ValueError):
            se.create("kidnap", {"objective": "nope"})
