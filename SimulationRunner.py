import json
import sys
from pathlib import Path

from direct.task import Task
from panda3d.core import (
    BitMask32,
    CollisionHandlerQueue,
    CollisionNode,
    CollisionRay,
    CollisionTraverser,
    LVector3,
    NodePath,
)

from FirstLight import FirstLight


def _load_manifest():
    path = Path(__file__).parent / "config" / "manifest.json"
    if path.exists():
        return json.load(open(path))
    return {}


class Simulation:
    """
    Headless-safe game loop wrapper around FirstLight.
    World constants loaded from config/manifest.json.
    SpawnEngine composes biome scene on init.
    """

    def __init__(self, headless=False, config=None):
        self._config = config or _load_manifest()
        world = self._config.get("world", {})

        self.GROUND_Z = world.get("ground_z", 6.0)
        self.MOVE_SPEED = world.get("move_speed", 40.0)
        self.interact_dist = world.get("interact_dist", 5.0)
        cam_start = world.get("camera_start", [0, -50, 6.0])

        self.headless = headless
        self.app = FirstLight(headless=headless)
        self.key_map = {"w": False, "s": False, "a": False, "d": False}

        if not headless:
            self.setup_collision()
            for k in self.key_map:
                self.app.accept(k, self.set_key, [k, True])
                self.app.accept(f"{k}-up", self.set_key, [k, False])
            self.app.accept("escape", sys.exit)
            self.app.camera.setPos(*cam_start)
            self.app.taskMgr.add(self.loop, "MainLoop")

        self._spawn_biome_scene()

        if headless:
            self.app.camera = NodePath("headless_camera")
            self.app.camera.setPos(*cam_start)

    def _spawn_biome_scene(self):
        """
        Composes and spawns a procedural biome scene using SpawnEngine.
        Falls back to GLO_Meso_V1 if SpawnEngine fails.
        """
        try:
            from core.systems.quest_engine import QuestEngine
            from core.systems.spawn_engine import SpawnEngine

            db_path = Path(__file__).parent / "data" / "vault.db"
            quest = QuestEngine(db_path=db_path) if db_path.exists() else None
            spawner = SpawnEngine(
                asset_lib=self.app.asset_lib,
                db_path=db_path if db_path.exists() else None,
            )

            if quest:
                rules = quest.get_active_biome_rules()
                scene = spawner.scene_from_quest_rules(rules)
            else:
                scene = spawner.compose_scene(encounter_density=0.3)

            for item in scene:
                self.app.spawn(item["asset_id"], item["pos"])

            print(f"SpawnEngine: {len(scene)} objects placed in biome scene.")

        except Exception as e:
            print(f"SpawnEngine: fallback to GLO_Meso_V1 — {e}")
            self.app.spawn("GLO_Meso_V1", (0, 0, 0))

    def setup_collision(self):
        self.cTrav = CollisionTraverser()
        self.cQueue = CollisionHandlerQueue()
        ray = CollisionRay(0, 0, 0, 0, 1, 0)
        rayNode = CollisionNode("playerRay")
        rayNode.addSolid(ray)
        rayNode.setFromCollideMask(BitMask32.bit(1))
        self.rayNP = self.app.camera.attachNewNode(rayNode)
        self.cTrav.addCollider(self.rayNP, self.cQueue)

    def set_key(self, key, val):
        self.key_map[key] = val

    def process_movement(self, dt):
        if not self.app.camera:
            return
        can_move_fwd = True
        if hasattr(self, "cTrav"):
            self.cTrav.traverse(self.app.render)
            if self.cQueue.getNumEntries() > 0:
                self.cQueue.sortEntries()
                if (
                    self.cQueue.getEntry(0).getSurfacePoint(self.app.camera).length()
                    < 3.0
                ):
                    can_move_fwd = False
        try:
            move = LVector3(0, 0, 0)
            if self.key_map["w"] and can_move_fwd:
                move += self.app.camera.getQuat().getForward()
            if self.key_map["s"]:
                move -= self.app.camera.getQuat().getForward()
            if self.key_map["a"]:
                move -= self.app.camera.getQuat().getRight()
            if self.key_map["d"]:
                move += self.app.camera.getQuat().getRight()
            if move.length() > 0:
                move.normalize()
                self.app.camera.setPos(
                    self.app.camera.getPos() + move * self.MOVE_SPEED * dt
                )
        except Exception:
            pass
        self.app.camera.setZ(self.GROUND_Z)

    def process_interactions(self):
        if not self.app.camera:
            return []
        results = []
        cam_pos = self.app.camera.getPos()
        for entity in self.app.entities:
            if entity.getPythonTag("interactable"):
                ent_pos = entity.getPos()
                dist_2d = (
                    (ent_pos.x - cam_pos.x) ** 2 + (ent_pos.y - cam_pos.y) ** 2
                ) ** 0.5
                if dist_2d < self.interact_dist:
                    results.append(entity)
        return results

    def process_mouse_look(self):
        if self.headless or not self.app.camera:
            return
        if not self.app.mouseWatcherNode.hasMouse():
            return
        md = self.app.win.getPointer(0)
        cx = self.app.win.getXSize() // 2
        cy = self.app.win.getYSize() // 2
        if self.app.win.movePointer(0, cx, cy):
            self.app.camera.setH(self.app.camera.getH() - (md.getX() - cx) * 0.1)
            self.app.camera.setP(
                max(min(self.app.camera.getP() - (md.getY() - cy) * 0.1, 80), -80)
            )

    def loop(self, task):
        dt = globalClock.getDt()
        self.process_movement(dt)
        self.process_mouse_look()
        return Task.cont


if __name__ == "__main__":
    Simulation().app.run()


# ── ScenarioRunner ────────────────────────────────────────────────────────────
# Headed + auto   = default. Watch it run. No input needed.
# Headless + auto = CI / difficulty calibration.
# Headed + manual = you drive. Diagnose a known bug live.
#
# Usage:
#   auto:    runner = ScenarioRunner()           # headed, auto
#   ci:      runner = ScenarioRunner(headless=True)
#   debug:   runner = ScenarioRunner(manual=True) # headed, you drive
#
# Scripts are callables that receive the runner:
#   def my_script(r): r.move_to(...); r.press("e"); r.tick(1.0)
#   runner.run(my_script)
#
# report() returns full ledger -- all scenarios, states, provenance hashes.
# Feed into difficulty tuning, biome calibration, QA harness.

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
        self.headless = headless
        self.manual   = manual
        self.seed     = seed
        self.dt       = dt
        self.elapsed  = 0.0

        # Headless sim -- camera is a plain NodePath, no window
        self.sim = Simulation(headless=True)

        # If headed and not manual, open a window via a second ShowBase
        # For now: headed mode uses the same headless sim but logs visually
        # Full viewport integration is a future AtmosphereModule concern
        # TODO: wire to CreationLab viewport when ScenarioRunner matures

        # Core systems
        self.inventory = Inventory()
        self.se        = ScenarioEngine(seed=seed)

        # Ensure headless camera is parented to render so world-space
        # distance calculations in InteractionEngine work correctly
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
        obj: override dict -- if None, minimal dict from asset_id.
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
        """
        Simulate a key press.
        Supported: "e" (pickup), "g" (drop)
        Returns status string from the system that handled it.
        """
        if key == "e":
            return self.pickup.on_e_pressed()
        if key == "g":
            return self.pickup.on_drop_pressed()
        return f"unhandled_key:{key}"

    def tick(self, seconds: float = None) -> None:
        """
        Advance simulation by seconds (default: one frame dt).
        Drives pickup tween, interaction states, scenario win checks.
        """
        duration = seconds if seconds is not None else self.dt
        steps    = max(1, int(duration / self.dt))
        for _ in range(steps):
            self.pickup.update(self.dt)
            self.ie.tick()
            self.se.tick()
            self.elapsed += self.dt

    # -- Script execution ------------------------------------------------------

    def run(self, script: callable) -> dict:
        """
        Execute a script callable against this runner.
        Returns report() after script completes.
        script signature: def script(runner) -> None
        """
        script(self)
        return self.report()

    # -- Reporting -------------------------------------------------------------

    def report(self) -> dict:
        """
        Full ledger snapshot.
        Scenarios, states, provenance hashes, elapsed time.
        Feed into difficulty tuning and QA harness.
        """
        return {
            "seed":      self.seed,
            "elapsed":   round(self.elapsed, 4),
            "headless":  self.headless,
            "manual":    self.manual,
            "scenarios": self.se.all_scenarios(),
        }

    # -- Cleanup ---------------------------------------------------------------

    def cleanup(self) -> None:
        """Release Panda3D resources. Call after each test."""
        try:
            self.sim.app.destroy()
        except Exception:
            pass
