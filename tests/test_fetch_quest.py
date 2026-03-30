"""
tests/test_fetch_quest.py

First scripted quest path -- fetch end-to-end.

The script exercises the full pipeline:
    spawn target → create scenario → activate → encounter begins →
    move to target → pick up → stow → move to return pos →
    scenario completes → encounter resolves → provenance recorded.

ScenarioRunner drives headless. AvatarPipeline wires ghost profile
into encounter resolution. The fetch script is a reusable callable.
"""
import pytest
from core.systems.scenario_engine import ScenarioState


@pytest.fixture
def runner():
    from SimulationRunner import ScenarioRunner
    r = ScenarioRunner(headless=True, seed="BURN")
    yield r
    r.cleanup()


@pytest.fixture
def pipeline():
    from core.systems.avatar_pipeline import AvatarPipeline
    return AvatarPipeline(
        answers={"q1": "home", "q5": "heavy", "q6": "deliberately", "q8": "seeker"},
        age=45,
        seed="BURN",
    )


# -- Script import -------------------------------------------------------------

class TestFetchScriptImport:

    def test_importable(self):
        from core.scripts.fetch_quest import fetch_quest
        assert callable(fetch_quest)

    def test_returns_result_dict(self, runner, pipeline):
        from core.scripts.fetch_quest import fetch_quest
        result = fetch_quest(runner, pipeline)
        assert isinstance(result, dict)

    def test_result_has_required_keys(self, runner, pipeline):
        from core.scripts.fetch_quest import fetch_quest
        result = fetch_quest(runner, pipeline)
        for key in ("scenario_id", "state", "provenance", "encounter_result"):
            assert key in result, f"Missing key: {key}"


# -- Scenario lifecycle --------------------------------------------------------

class TestFetchScenarioLifecycle:

    def test_scenario_created(self, runner, pipeline):
        from core.scripts.fetch_quest import fetch_quest
        result = fetch_quest(runner, pipeline)
        assert result["scenario_id"] is not None

    def test_scenario_completes(self, runner, pipeline):
        from core.scripts.fetch_quest import fetch_quest
        result = fetch_quest(runner, pipeline)
        assert result["state"] == "COMPLETE"

    def test_provenance_hash_recorded(self, runner, pipeline):
        from core.scripts.fetch_quest import fetch_quest
        result = fetch_quest(runner, pipeline)
        assert result["provenance"] is not None
        assert len(result["provenance"]) == 16  # SHA256 truncated to 16

    def test_scenario_in_report(self, runner, pipeline):
        from core.scripts.fetch_quest import fetch_quest
        result = fetch_quest(runner, pipeline)
        report = runner.report()
        assert any(
            s["id"] == result["scenario_id"] and s["state"] == "COMPLETE"
            for s in report["scenarios"]
        )


# -- Pickup + inventory --------------------------------------------------------

class TestFetchPickupFlow:

    def test_target_stowed_in_inventory(self, runner, pipeline):
        from core.scripts.fetch_quest import fetch_quest
        result = fetch_quest(runner, pipeline)
        assert runner.inventory.get(result["target_id"]) is not None

    def test_nothing_held_after_stow(self, runner, pipeline):
        from core.scripts.fetch_quest import fetch_quest
        fetch_quest(runner, pipeline)
        assert runner.pickup.held_obj is None


# -- Encounter integration -----------------------------------------------------

class TestFetchEncounterIntegration:

    def test_encounter_resolves(self, runner, pipeline):
        from core.scripts.fetch_quest import fetch_quest
        result = fetch_quest(runner, pipeline)
        enc = result["encounter_result"]
        assert enc["outcome"] == "resolved"

    def test_encounter_uses_verb(self, runner, pipeline):
        from core.scripts.fetch_quest import fetch_quest
        result = fetch_quest(runner, pipeline)
        enc = result["encounter_result"]
        assert enc["verb_used"] is not None

    def test_fingerprint_primed_before_encounter(self, runner, pipeline):
        """Pipeline fingerprint has behavioral data before encounter."""
        from core.scripts.fetch_quest import fetch_quest
        fetch_quest(runner, pipeline)
        # The script should prime the fingerprint so encounters resonate
        fp = pipeline.fingerprint.export()
        assert any(v > 0 for v in fp.values())


# -- Full pipeline run via ScenarioRunner.run() --------------------------------

class TestFetchViaRunnerRun:

    def test_run_with_script_wrapper(self, runner, pipeline):
        from core.scripts.fetch_quest import make_fetch_script
        script = make_fetch_script(pipeline)
        report = runner.run(script)
        assert any(s["state"] == "COMPLETE" for s in report["scenarios"])
