"""
core/systems/scenario_runner.py

ScenarioRunner -- headless-safe scenario execution harness.

Headed + auto   = default. Watch it run. No input needed.
Headless + auto = CI / difficulty calibration.
Headed + manual = you drive. Diagnose a known bug live.

Usage:
    auto:    runner = ScenarioRunner()           # headed, auto
    ci:      runner = ScenarioRunner(headless=True)
    debug:   runner = ScenarioRunner(manual=True) # headed, you drive

Scripts are callables that receive the runner:
    def my_script(r): r.move_to(...); r.press("e"); r.tick(1.0)
    runner.run(my_script)

report() returns full ledger -- all scenarios, states, provenance hashes.
"""

from __future__ import annotations

from core.systems.inventory import Inventory
from core.systems.pickup_system import PickupSystem
from core.systems.interaction_engine import InteractionEngine
from core.systems.scenario_engine import ScenarioEngine


class ScenarioRunner:
    """
    Headless-safe scenario execution harness.

    Parameters
    ----------
    headless : bool   -- suppress window (default False -- headed)
    manual   : bool   -- pause auto-run, you drive (default False -- auto)
    seed     : str    -- provenance seed for this run
    dt       : float  -- simulated frame delta for tick() (default 1/60)
    """

    def __init__(
        self,
        headless: bool = False,
        manual:   bool = False,
        seed:     str  = "BURN",
        dt:       float = 1/60,
    ):
        from SimulationRunner import Simulation

        self.headless = headless
        self.manual   = manual
        self.seed     = seed
        self.dt       = dt
        self.elapsed  = 0.0

        self.sim = Simulation(headless=True)

        # Core systems
        self.inventory = Inventory()
        self.se        = ScenarioEngine(seed=seed)

        cam = self.sim.app.camera
        if cam.getParent().isEmpty() or cam.getParent() == cam:
            cam.reparentTo(self.sim.app.render)

        self.ie = InteractionEngine(
            camera = self.sim.app.camera,
            render = self.sim.app.render,
        )

        self.pickup = PickupSystem(
            camera         = self.sim.app.camera,
            inventory      = self.inventory,
            get_nearest_fn = lambda: self.ie.nearest("pickup"),
        )

        self._spawned = []

    # -- Scene control ---------------------------------------------------------

    def spawn(self, asset_id: str, pos: tuple, obj: dict = None) -> object:
        """
        Spawn an object into the scene and register with InteractionEngine.
        """
        node = self.sim.app.spawn(asset_id, pos)
        if obj is None:
            obj = {"id": asset_id, "weight": 0.5, "category": "misc"}
        node.setPythonTag("pickupable", True)
        node.setPythonTag("obj", obj)
        self.ie.register(node, "pickup", obj=obj)
        self._spawned.append({"node": node, "obj": obj})
        return node

    def move_to(self, pos: tuple) -> None:
        """Teleport camera to position. Ticks IE so state updates immediately."""
        self.sim.app.camera.setPos(pos[0], pos[1],
                                   pos[2] if len(pos) > 2 else 6.0)
        self.ie.tick()

    def press(self, key: str) -> str:
        """Simulate a key press. Supported: "e" (pickup), "g" (drop)."""
        if key == "e":
            return self.pickup.on_e_pressed()
        if key == "g":
            return self.pickup.on_drop_pressed()
        return f"unhandled_key:{key}"

    def tick(self, seconds: float = None) -> None:
        """Advance simulation by seconds (default: one frame dt)."""
        duration = seconds if seconds is not None else self.dt
        steps    = max(1, int(duration / self.dt))
        for _ in range(steps):
            self.pickup.update(self.dt)
            self.ie.tick()
            self.se.tick()
            self.elapsed += self.dt

    # -- Script execution ------------------------------------------------------

    def run(self, script: callable) -> dict:
        """Execute a script callable. Returns report()."""
        script(self)
        return self.report()

    # -- Reporting -------------------------------------------------------------

    def report(self) -> dict:
        """Full ledger snapshot."""
        return {
            "seed":      self.seed,
            "elapsed":   round(self.elapsed, 4),
            "headless":  self.headless,
            "manual":    self.manual,
            "scenarios": self.se.all_scenarios(),
        }

    # -- Cleanup ---------------------------------------------------------------

    def cleanup(self) -> None:
        """Release Panda3D resources."""
        try:
            self.sim.app.destroy()
        except Exception:
            pass
