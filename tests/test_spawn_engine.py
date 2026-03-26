import pytest
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock


@pytest.fixture
def tmp_db(tmp_path):
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
def mock_asset_lib():
    return {
        "GLO_Meso_V1":        {"id": "GLO_Meso_V1",        "file": "Example_Models_6_.obj",  "interactable": False},
        "GLO_Micro_V1":       {"id": "GLO_Micro_V1",       "file": "Example_Models_6_.obj",  "interactable": False},
        "GLO_Master_Town_V1": {"id": "GLO_Master_Town_V1", "file": "Example_Models_6_.obj",  "interactable": False},
        "ACT_Human_Stock_V1": {"id": "ACT_Human_Stock_V1", "file": "Avatars_2_.obj",          "interactable": True},
        "ACT_Human_Thin_V1":  {"id": "ACT_Human_Thin_V1",  "file": "Avatars_2_.obj",          "interactable": True},
        "ACT_Critter_Quad_V1":{"id": "ACT_Critter_Quad_V1","file": "Example_Models_7_.obj",   "interactable": True},
        "ACT_Critter_Tiny_V1":{"id": "ACT_Critter_Tiny_V1","file": "Example_Models_7_.obj",   "interactable": True},
        "ACT_Human_Large_V1": {"id": "ACT_Human_Large_V1", "file": "Avatars_2_.obj",          "interactable": True},
        "ATM_Master_V1":      {"id": "ATM_Master_V1",      "file": "Citadel_-_Ground_1_.obj", "interactable": False},
        "PAS_Flora_V1":       {"id": "PAS_Flora_V1",       "file": "Citadel_-_Ground_1_.obj", "interactable": False},
        "PAS_Furniture_V1":   {"id": "PAS_Furniture_V1",   "file": "Citadel_-_Ground_1_.obj", "interactable": False},
        "TOOL_Major_V1":      {"id": "TOOL_Major_V1",      "file": "Avatars_3_.obj",           "interactable": True},
        "TOOL_Minor_V1":      {"id": "TOOL_Minor_V1",      "file": "Avatars_3_.obj",           "interactable": True},
        "TOOL_Aux_V1":        {"id": "TOOL_Aux_V1",        "file": "Avatars_3_.obj",           "interactable": True},
        "WEAR_Head_V1":       {"id": "WEAR_Head_V1",       "file": "Avatars_4_.obj",           "interactable": False},
        "WEAR_Limb_V1":       {"id": "WEAR_Limb_V1",       "file": "Avatars_4_.obj",           "interactable": False},
        "WEAR_Torso_V1":      {"id": "WEAR_Torso_V1",      "file": "Avatars_4_.obj",           "interactable": False},
    }


@pytest.fixture
def engine(tmp_db, mock_asset_lib):
    from core.systems.spawn_engine import SpawnEngine
    return SpawnEngine(asset_lib=mock_asset_lib, db_path=tmp_db)


# ── Instantiation ─────────────────────────────────────────────────────────────

class TestSpawnEngineInit:

    def test_boots_without_error(self, engine):
        assert engine is not None

    def test_has_asset_lib(self, engine):
        assert engine.asset_lib is not None

    def test_prefix_table_populated(self, engine):
        assert len(engine.prefix_table) > 0

    def test_all_prefixes_present(self, engine):
        for prefix in ["GLO", "ACT", "ATM", "PAS", "TOOL", "WEAR"]:
            assert prefix in engine.prefix_table

    def test_each_prefix_has_assets(self, engine):
        for prefix, assets in engine.prefix_table.items():
            assert len(assets) > 0


# ── Prefix taxonomy ───────────────────────────────────────────────────────────

class TestPrefixTaxonomy:

    def test_glo_assets_are_not_interactable(self, engine):
        for asset_id in engine.prefix_table["GLO"]:
            assert engine.asset_lib[asset_id]["interactable"] is False

    def test_act_assets_are_interactable(self, engine):
        for asset_id in engine.prefix_table["ACT"]:
            assert engine.asset_lib[asset_id]["interactable"] is True

    def test_tool_assets_are_interactable(self, engine):
        for asset_id in engine.prefix_table["TOOL"]:
            assert engine.asset_lib[asset_id]["interactable"] is True


# ── Scene composition ─────────────────────────────────────────────────────────

class TestComposeScene:

    def test_compose_returns_list(self, engine):
        scene = engine.compose_scene(encounter_density=0.5, seed=42)
        assert isinstance(scene, list)

    def test_compose_always_has_glo_base(self, engine):
        scene = engine.compose_scene(encounter_density=0.5, seed=42)
        prefixes = [item["prefix"] for item in scene]
        assert "GLO" in prefixes

    def test_compose_only_one_glo(self, engine):
        scene = engine.compose_scene(encounter_density=0.5, seed=42)
        glo_items = [i for i in scene if i["prefix"] == "GLO"]
        assert len(glo_items) == 1

    def test_compose_low_density_has_fewer_act(self, engine):
        low  = engine.compose_scene(encounter_density=0.1, seed=42)
        high = engine.compose_scene(encounter_density=0.9, seed=42)
        low_act  = len([i for i in low  if i["prefix"] == "ACT"])
        high_act = len([i for i in high if i["prefix"] == "ACT"])
        assert low_act <= high_act

    def test_compose_is_deterministic(self, engine):
        s1 = engine.compose_scene(encounter_density=0.5, seed=42)
        s2 = engine.compose_scene(encounter_density=0.5, seed=42)
        assert [i["asset_id"] for i in s1] == [i["asset_id"] for i in s2]

    def test_compose_different_seeds_differ(self, engine):
        s1 = engine.compose_scene(encounter_density=0.5, seed=42)
        s2 = engine.compose_scene(encounter_density=0.5, seed=99)
        assert [i["asset_id"] for i in s1] != [i["asset_id"] for i in s2]

    def test_each_item_has_required_keys(self, engine):
        scene = engine.compose_scene(encounter_density=0.5, seed=42)
        for item in scene:
            assert "asset_id" in item
            assert "prefix"   in item
            assert "pos"      in item

    def test_pos_is_tuple_of_three(self, engine):
        scene = engine.compose_scene(encounter_density=0.5, seed=42)
        for item in scene:
            assert isinstance(item["pos"], tuple)
            assert len(item["pos"]) == 3

    def test_no_asset_spawns_on_origin(self, engine):
        scene = engine.compose_scene(encounter_density=0.5, seed=42)
        act_items = [i for i in scene if i["prefix"] != "GLO"]
        for item in act_items:
            assert item["pos"] != (0, 0, 0)


# ── Ecological rules ──────────────────────────────────────────────────────────

class TestEcologicalRules:

    def test_wear_never_spawns_without_act(self, engine):
        scene = engine.compose_scene(encounter_density=0.0, seed=42)
        prefixes = [i["prefix"] for i in scene]
        if "WEAR" in prefixes:
            assert "ACT" in prefixes

    def test_tool_count_does_not_exceed_act_count(self, engine):
        scene = engine.compose_scene(encounter_density=0.9, seed=42)
        act_count  = len([i for i in scene if i["prefix"] == "ACT"])
        tool_count = len([i for i in scene if i["prefix"] == "TOOL"])
        assert tool_count <= max(act_count, 1)
