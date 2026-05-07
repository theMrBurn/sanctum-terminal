"""
SimulationRunner.py

Simulation -- headless-safe game loop wrapper around FirstLight.
ScenarioRunner has moved to core/systems/scenario_runner.py.
"""

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
        """Composes and spawns a procedural biome scene."""
        try:
            from core.systems.quest_engine import QuestEngine
            from core.attic.spawn_engine import SpawnEngine

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

        except Exception:
            pass

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


# Backward-compatible import -- tests use `from SimulationRunner import ScenarioRunner`
from core.systems.scenario_runner import ScenarioRunner  # noqa: E402, F401


if __name__ == "__main__":
    Simulation().app.run()
