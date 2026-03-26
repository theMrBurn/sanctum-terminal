import pytest
import sqlite3
import sys
import os

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
            for k, v in relic_dict.items():
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
