import sys
from FirstLight import FirstLight
from direct.task import Task
from panda3d.core import (
    LVector3, CollisionTraverser, CollisionHandlerQueue,
    CollisionRay, CollisionNode, BitMask32, NodePath
)


class Simulation:
    GROUND_Z      = 6.0
    MOVE_SPEED    = 40.0
    interact_dist = 5.0

    def __init__(self, headless=False):
        self.headless = headless
        self.app      = FirstLight(headless=headless)
        self.key_map  = {"w": False, "s": False, "a": False, "d": False}

        if not headless:
            self.setup_collision()
            for k in self.key_map:
                self.app.accept(k,         self.set_key, [k, True])
                self.app.accept(f"{k}-up", self.set_key, [k, False])
            self.app.accept("escape", sys.exit)
            self.app.camera.setPos(0, -50, self.GROUND_Z)
            self.app.taskMgr.add(self.loop, "MainLoop")

        self.app.spawn("GLO_Meso_V1", (0, 0, 0))

        if headless:
            self.app.camera = NodePath("headless_camera")
            self.app.camera.setPos(0, -50, self.GROUND_Z)

    def setup_collision(self):
        self.cTrav  = CollisionTraverser()
        self.cQueue = CollisionHandlerQueue()
        ray         = CollisionRay(0, 0, 0, 0, 1, 0)
        rayNode     = CollisionNode("playerRay")
        rayNode.addSolid(ray)
        rayNode.setFromCollideMask(BitMask32.bit(1))
        self.rayNP  = self.app.camera.attachNewNode(rayNode)
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
                if self.cQueue.getEntry(0).getSurfacePoint(
                    self.app.camera
                ).length() < 3.0:
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
        # Ground lock ALWAYS enforced every tick regardless of movement
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
                    (ent_pos.x - cam_pos.x) ** 2 +
                    (ent_pos.y - cam_pos.y) ** 2
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
            self.app.camera.setH(
                self.app.camera.getH() - (md.getX() - cx) * 0.1
            )
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
