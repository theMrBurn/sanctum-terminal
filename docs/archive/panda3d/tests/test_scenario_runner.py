"""
tests/test_scenario_runner.py

ScenarioRunner -- headless auto-play with optional viewport.

Usage:
    headless:  ScenarioRunner(headless=True)
    viewport:  ScenarioRunner(headless=False)  or  make scenario

Scripts are deterministic sequences of actions + assertions.
Pass/fail output feeds difficulty calibration.
Provenance hash on every run -- the ledger remembers.
"""
import pytest
from core.systems.scenario_engine import ScenarioEngine, ScenarioState


class TestScenarioRunnerContract:

    def test_scenario_runner_importable(self):
        from SimulationRunner import ScenarioRunner
        assert ScenarioRunner is not None

    def test_boots_headless(self):
        from SimulationRunner import ScenarioRunner
        runner = ScenarioRunner(headless=True)
        assert runner is not None
        runner.cleanup()

    def test_has_scenario_engine(self):
        from SimulationRunner import ScenarioRunner
        runner = ScenarioRunner(headless=True)
        assert isinstance(runner.se, ScenarioEngine)
        runner.cleanup()

    def test_spawn_places_object(self):
        from SimulationRunner import ScenarioRunner
        runner = ScenarioRunner(headless=True)
        node = runner.spawn("TOOL_Minor_V1", pos=(2, 11, 0.5),
                            obj={"id": "tool_01", "weight": 0.5})
        assert node is not None
        runner.cleanup()

    def test_move_to_updates_camera(self):
        from SimulationRunner import ScenarioRunner
        runner = ScenarioRunner(headless=True)
        runner.move_to((2, 11, 0))
        pos = runner.sim.app.camera.getPos()
        assert abs(pos.x - 2) < 0.1
        assert abs(pos.y - 11) < 0.1
        runner.cleanup()

    def test_tick_advances_time(self):
        from SimulationRunner import ScenarioRunner
        runner = ScenarioRunner(headless=True)
        runner.tick(seconds=0.5)
        assert runner.elapsed >= 0.499
        runner.cleanup()

    def test_press_e_lifts_nearby_object(self):
        from SimulationRunner import ScenarioRunner
        runner = ScenarioRunner(headless=True)
        runner.spawn("TOOL_Minor_V1", pos=(0, 0, 0.5),
                     obj={"id": "tool_01", "weight": 0.5})
        runner.move_to((0, 0, 0))
        runner.press("e")
        assert runner.pickup.held_obj is not None
        runner.cleanup()

    def test_press_e_twice_stows_object(self):
        from SimulationRunner import ScenarioRunner
        runner = ScenarioRunner(headless=True)
        runner.spawn("TOOL_Minor_V1", pos=(0, 0, 0.5),
                     obj={"id": "tool_01", "weight": 0.5})
        runner.move_to((0, 0, 0))
        runner.press("e")
        runner.press("e")
        runner.tick(seconds=0.5)
        assert runner.inventory.get("tool_01") is not None
        runner.cleanup()

    def test_fetch_scenario_completes_on_stow(self):
        from SimulationRunner import ScenarioRunner
        runner = ScenarioRunner(headless=True)
        runner.spawn("TOOL_Minor_V1", pos=(0, 0, 0.5),
                     obj={"id": "tool_01", "weight": 0.5})

        sid = runner.se.create("fetch", {
            "target_id":  "tool_01",
            "return_pos": (0, 2, 0),
            "objective":  "Pick up the tool.",
        }, win_fn=lambda: runner.inventory.get("tool_01") is not None)
        runner.se.activate(sid)

        runner.move_to((0, 0, 0))
        runner.press("e")   # lift
        runner.press("e")   # stow
        runner.tick(seconds=0.5)

        assert runner.se.get_state(sid) is ScenarioState.COMPLETE

    def test_run_script_returns_report(self):
        from SimulationRunner import ScenarioRunner
        runner = ScenarioRunner(headless=True)

        def script(r):
            node = r.spawn("TOOL_Minor_V1", pos=(0, 0, 0.5),
                           obj={"id": "tool_01", "weight": 0.5})
            sid = r.se.create("fetch", {
                "target_id":  "tool_01",
                "return_pos": (0, 2, 0),
                "objective":  "Pick up the tool.",
            }, win_fn=lambda: r.inventory.get("tool_01") is not None)
            r.se.activate(sid)
            r.move_to((0, 0, 0))
            r.press("e")
            r.press("e")
            r.tick(seconds=0.5)
            return sid

        sid    = script(runner)
        report = runner.report()

        assert "scenarios" in report
        assert any(s["id"] == sid for s in report["scenarios"])
        assert any(s["state"] == "COMPLETE" for s in report["scenarios"])
        runner.cleanup()

    def test_report_includes_provenance(self):
        from SimulationRunner import ScenarioRunner
        runner = ScenarioRunner(headless=True)
        sid = runner.se.create("fetch", {
            "target_id": "x", "return_pos": (0,0,0),
            "objective": "test"
        })
        report = runner.report()
        assert any(s["provenance_hash"] for s in report["scenarios"])
        runner.cleanup()

    def test_headless_flag_suppresses_window(self):
        from SimulationRunner import ScenarioRunner
        runner = ScenarioRunner(headless=True)
        # In headless mode win is None or window is offscreen
        assert runner.sim.headless is True
        runner.cleanup()
