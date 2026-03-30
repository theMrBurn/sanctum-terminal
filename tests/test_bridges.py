"""
tests/test_bridges.py

The 4 bridges -- systems that connect the islands into a game loop.

Bridge 1: EncounterGenerator -- proximity triggers encounters
Bridge 2: ScenarioChain -- scenarios link into sequences
Bridge 3: CraftingIntegration -- crafting connects to world
Bridge 4: ConsolidationTrigger -- rest events consolidate depth
"""
import pytest
from core.systems.fingerprint_engine import FingerprintEngine
from core.systems.encounter_engine import EncounterEngine
from core.systems.scenario_engine import ScenarioEngine, ScenarioState


# -- Fixtures ------------------------------------------------------------------

@pytest.fixture
def fingerprint():
    fp = FingerprintEngine()
    for _ in range(5):
        fp.record("precision_score", 0.9)
        fp.record("crafting_time", 0.8)
        fp.record("observation_time", 0.7)
    return fp


@pytest.fixture
def ghost_blend():
    return {"PRECISION_HAND": 0.3, "SEEKER": 0.2, "MAKER": 0.15}


@pytest.fixture
def encounter(fingerprint, ghost_blend):
    return EncounterEngine(fingerprint=fingerprint, ghost_blend=ghost_blend, age=30)


@pytest.fixture
def scenario():
    return ScenarioEngine(seed="BRIDGE_TEST")


# -- Bridge 1: EncounterGenerator ---------------------------------------------

class TestEncounterGenerator:

    def test_importable(self):
        from core.systems.encounter_generator import EncounterGenerator
        assert EncounterGenerator is not None

    def test_generates_from_obj_with_tags(self, encounter):
        from core.systems.encounter_generator import EncounterGenerator
        gen = EncounterGenerator(encounter)
        obj = {"id": "test_rock", "tags": ["precision_score", "crafting_time"]}
        result = gen.try_encounter(obj)
        assert result is not None
        assert result["worth_knowing"] is True

    def test_no_encounter_without_tags(self, encounter):
        from core.systems.encounter_generator import EncounterGenerator
        gen = EncounterGenerator(encounter)
        obj = {"id": "plain_rock"}
        result = gen.try_encounter(obj)
        assert result is None

    def test_no_encounter_on_cooldown(self, encounter):
        from core.systems.encounter_generator import EncounterGenerator
        gen = EncounterGenerator(encounter)
        obj = {"id": "test_rock", "tags": ["precision_score"]}
        gen.try_encounter(obj)
        encounter.resolve()
        # Now on cooldown
        result = gen.try_encounter(obj)
        assert result is None

    def test_no_duplicate_encounter_same_object(self, encounter):
        from core.systems.encounter_generator import EncounterGenerator
        gen = EncounterGenerator(encounter)
        obj = {"id": "test_rock", "tags": ["precision_score"]}
        gen.try_encounter(obj)
        # Same object while encounter active
        result = gen.try_encounter(obj)
        assert result is None


# -- Bridge 2: ScenarioChain --------------------------------------------------

class TestScenarioChain:

    def test_importable(self):
        from core.systems.scenario_chain import ScenarioChain
        assert ScenarioChain is not None

    def test_create_chain(self, scenario):
        from core.systems.scenario_chain import ScenarioChain
        chain = ScenarioChain(scenario)
        steps = [
            {"type": "fetch", "params": {"target_id": "stone", "objective": "Get stone"}},
            {"type": "fetch", "params": {"target_id": "branch", "objective": "Get branch"}},
        ]
        ids = chain.create(steps)
        assert len(ids) == 2

    def test_first_step_activates(self, scenario):
        from core.systems.scenario_chain import ScenarioChain
        chain = ScenarioChain(scenario)
        steps = [
            {"type": "fetch", "params": {"target_id": "stone", "objective": "Get stone"}},
            {"type": "fetch", "params": {"target_id": "branch", "objective": "Get branch"}},
        ]
        ids = chain.create(steps)
        assert scenario.get_state(ids[0]) is ScenarioState.ACTIVE

    def test_second_step_pending(self, scenario):
        from core.systems.scenario_chain import ScenarioChain
        chain = ScenarioChain(scenario)
        steps = [
            {"type": "fetch", "params": {"target_id": "stone", "objective": "Get stone"}},
            {"type": "fetch", "params": {"target_id": "branch", "objective": "Get branch"}},
        ]
        ids = chain.create(steps)
        assert scenario.get_state(ids[1]) is ScenarioState.PENDING

    def test_completing_first_activates_second(self, scenario):
        from core.systems.scenario_chain import ScenarioChain
        chain = ScenarioChain(scenario)
        steps = [
            {"type": "fetch", "params": {"target_id": "stone", "objective": "Get stone"}},
            {"type": "fetch", "params": {"target_id": "branch", "objective": "Get branch"}},
        ]
        ids = chain.create(steps)
        scenario.complete(ids[0])
        assert scenario.get_state(ids[1]) is ScenarioState.ACTIVE

    def test_chain_tracks_progress(self, scenario):
        from core.systems.scenario_chain import ScenarioChain
        chain = ScenarioChain(scenario)
        steps = [
            {"type": "fetch", "params": {"target_id": "a", "objective": "1"}},
            {"type": "fetch", "params": {"target_id": "b", "objective": "2"}},
            {"type": "fetch", "params": {"target_id": "c", "objective": "3"}},
        ]
        ids = chain.create(steps)
        assert chain.current_step() == 0
        scenario.complete(ids[0])
        assert chain.current_step() == 1

    def test_chain_complete_when_all_done(self, scenario):
        from core.systems.scenario_chain import ScenarioChain
        chain = ScenarioChain(scenario)
        steps = [
            {"type": "fetch", "params": {"target_id": "a", "objective": "1"}},
            {"type": "fetch", "params": {"target_id": "b", "objective": "2"}},
        ]
        ids = chain.create(steps)
        scenario.complete(ids[0])
        scenario.complete(ids[1])
        assert chain.is_complete()


# -- Bridge 3: CraftingIntegration --------------------------------------------

class TestCraftingIntegration:

    def test_importable(self):
        from core.systems.crafting_integration import CraftingIntegration
        assert CraftingIntegration is not None

    def test_craft_from_inventory(self):
        from core.systems.crafting_integration import CraftingIntegration
        from core.systems.crafting_engine import CraftingEngine
        from core.systems.inventory import Inventory
        ci = CraftingIntegration(CraftingEngine(), Inventory())
        ci.inventory.pickup({"id": "stripped_branch", "weight": 0.3})
        ci.inventory.pickup({"id": "sap_vessel", "weight": 0.2})
        result = ci.craft("stripped_branch", "sap_vessel")
        assert result is not None
        assert "provenance_hash" in result

    def test_craft_removes_from_inventory(self):
        from core.systems.crafting_integration import CraftingIntegration
        from core.systems.crafting_engine import CraftingEngine
        from core.systems.inventory import Inventory
        ci = CraftingIntegration(CraftingEngine(), Inventory())
        ci.inventory.pickup({"id": "stripped_branch", "weight": 0.3})
        ci.inventory.pickup({"id": "sap_vessel", "weight": 0.2})
        ci.craft("stripped_branch", "sap_vessel")
        assert ci.inventory.get("stripped_branch") is None
        assert ci.inventory.get("sap_vessel") is None

    def test_craft_adds_result_to_inventory(self):
        from core.systems.crafting_integration import CraftingIntegration
        from core.systems.crafting_engine import CraftingEngine
        from core.systems.inventory import Inventory
        ci = CraftingIntegration(CraftingEngine(), Inventory())
        ci.inventory.pickup({"id": "stripped_branch", "weight": 0.3})
        ci.inventory.pickup({"id": "sap_vessel", "weight": 0.2})
        result = ci.craft("stripped_branch", "sap_vessel")
        assert ci.inventory.get(result["name"]) is not None

    def test_craft_fails_without_both_items(self):
        from core.systems.crafting_integration import CraftingIntegration
        from core.systems.crafting_engine import CraftingEngine
        from core.systems.inventory import Inventory
        ci = CraftingIntegration(CraftingEngine(), Inventory())
        ci.inventory.pickup({"id": "stripped_branch", "weight": 0.3})
        result = ci.craft("stripped_branch", "sap_vessel")
        assert result is None

    def test_craft_completes_active_key_scenario(self, scenario):
        from core.systems.crafting_integration import CraftingIntegration
        from core.systems.crafting_engine import CraftingEngine
        from core.systems.inventory import Inventory
        ci = CraftingIntegration(CraftingEngine(), Inventory(), scenario_engine=scenario)
        ci.inventory.pickup({"id": "stripped_branch", "weight": 0.3})
        ci.inventory.pickup({"id": "sap_vessel", "weight": 0.2})
        # Create key scenario that requires crafting Field Torch
        sid = scenario.create("key", {
            "target_id": "Field Torch",
            "objective": "Craft a torch",
        })
        scenario.activate(sid)
        result = ci.craft("stripped_branch", "sap_vessel")
        # Torch recipe should produce "Torch" and complete the scenario
        assert scenario.get_state(sid) is ScenarioState.COMPLETE


# -- Bridge 4: ConsolidationTrigger -------------------------------------------

class TestConsolidationTrigger:

    def test_importable(self):
        from core.systems.consolidation import ConsolidationTrigger
        assert ConsolidationTrigger is not None

    def test_rest_consolidates(self, encounter):
        from core.systems.consolidation import ConsolidationTrigger
        ct = ConsolidationTrigger(encounter)
        encounter.stage_xp(5.0)
        report = ct.rest()
        assert report["xp_consumed"] == pytest.approx(5.0)
        assert encounter.staged_xp == 0.0

    def test_rest_returns_depth(self, encounter):
        from core.systems.consolidation import ConsolidationTrigger
        ct = ConsolidationTrigger(encounter)
        encounter.stage_xp(10.0)
        report = ct.rest()
        assert report["depth_total"] > 0.0

    def test_session_end_consolidates(self, encounter):
        from core.systems.consolidation import ConsolidationTrigger
        ct = ConsolidationTrigger(encounter)
        encounter.stage_xp(3.0)
        report = ct.session_end()
        assert report["reason"] == "session_end"
        assert report["xp_consumed"] > 0.0

    def test_milestone_consolidates(self, encounter):
        from core.systems.consolidation import ConsolidationTrigger
        ct = ConsolidationTrigger(encounter)
        encounter.stage_xp(20.0)
        report = ct.milestone("first_craft")
        assert report["reason"] == "first_craft"

    def test_ability_check_on_consolidation(self, encounter):
        from core.systems.consolidation import ConsolidationTrigger
        ct = ConsolidationTrigger(encounter)
        # Stage enough XP to reach CORE depth (0.1)
        encounter.stage_xp(15.0)
        report = ct.rest()
        assert len(report["abilities_checked"]) > 0 or report["depth_total"] > 0
