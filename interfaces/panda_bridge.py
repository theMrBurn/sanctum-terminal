import math
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    loadPrcFileData,
    ClockObject,
    Fog,
    PointLight,
    AmbientLight,
    Vec4,
    WindowProperties,
)
from core.geometry import GeoFactory
from engines.world import WorldEngine

loadPrcFileData("", "show-frame-rate-meter #t")


class PandaCleanroomBridge(ShowBase):
    def __init__(self):
        super().__init__()
        self.world = WorldEngine(seed=42)
        self.heading, self.pitch = 0.0, 0.0
        self.mouse_locked = False
        self.active_objects = {}  # Dictionary of rendered models

        # 1. VISIBILITY SETUP
        self.setBackgroundColor(0.05, 0.05, 0.1)
        self.fog = Fog("HorizonFog")
        self.fog.setColor(0.05, 0.05, 0.1)
        self.fog.setExpDensity(0.005)  # Thin fog to see further
        self.render.setFog(self.fog)

        # 2. MODELS CACHE
        self.models = {
            "101": GeoFactory.create_data_vault(),
            "301": GeoFactory.create_void_wall(),
        }

        # 3. BASE INFRASTRUCTURE
        self.floor = self.render.attachNewNode(GeoFactory.create_textured_grid())
        self.obj_root = self.render.attachNewNode("world_objects")

        # 4. LIGHTING
        self.setup_lighting()

        # 5. CAMERA & INPUT
        self.disableMouse()
        self.camLens.setFov(95)
        self.camLens.setNear(1.0)

        self.accept("mouse1", self.toggle_mouse, [True])
        self.accept("escape", self.toggle_mouse, [False])

        self.key_map = {"up": False, "down": False, "left": False, "right": False}
        for k, m in [("w", "up"), ("s", "down"), ("a", "left"), ("d", "right")]:
            self.accept(k, self.set_key, [m, True])
            self.accept(f"{k}-up", self.set_key, [m, False])

        self.taskMgr.add(self.update_loop, "CleanroomUpdate")

    def setup_lighting(self):
        pl = PointLight("flash")
        pl.setColor(Vec4(1.5, 1.5, 1.5, 1))
        pl.setAttenuation((0.1, 0, 0.001))
        self.camera.attachNewNode(pl)
        self.render.setLight(self.camera.find("**/+PointLight"))
        al = AmbientLight("amb")
        al.setColor(Vec4(0.3, 0.3, 0.4, 1))
        self.render.setLight(self.render.attachNewNode(al))

    def toggle_mouse(self, val):
        self.mouse_locked = val
        p = WindowProperties()
        p.setCursorHidden(val)
        p.setMouseMode(
            WindowProperties.M_relative if val else WindowProperties.M_absolute
        )
        self.win.requestProperties(p)

    def set_key(self, k, v):
        self.key_map[k] = v

    def sync_objects(self, px, py):
        ix, iy = int(px / 10), int(py / 10)
        radius = 20
        visible_coords = set()

        for dy in range(-radius, radius):
            for dx in range(-radius, radius):
                cx, cy = ix + dx, iy + dy
                key = self.world.get_object_at(cx, cy)
                if key:
                    coord = (cx, cy)
                    visible_coords.add(coord)
                    # FIXED: Changed active_blocks to active_objects
                    if coord not in self.active_objects:
                        node = self.obj_root.attachNewNode(self.models[key])
                        node.setPos(cx * 10, cy * 10, 0)
                        self.active_objects[coord] = node

        to_remove = [c for c in self.active_objects if c not in visible_coords]
        for c in to_remove:
            self.active_objects[c].removeNode()
            del self.active_objects[c]

    def update_loop(self, task):
        dt = ClockObject.getGlobalClock().getDt()

        # POV
        if self.mouse_locked and self.mouseWatcherNode.hasMouse():
            m = self.mouseWatcherNode.getMouse()
            self.heading -= m.getX() * 30
            self.pitch += m.getY() * 20
            self.pitch = max(-80, min(80, self.pitch))
            self.win.movePointer(0, self.win.getXSize() // 2, self.win.getYSize() // 2)
        self.camera.setHpr(self.heading, self.pitch, 0)

        # WASD
        speed = 50.0
        if self.key_map["up"]:
            self.camera.setPos(self.camera, 0, speed * dt, 0)
        if self.key_map["down"]:
            self.camera.setPos(self.camera, 0, -speed * dt, 0)
        if self.key_map["left"]:
            self.camera.setPos(self.camera, -speed * dt, 0, 0)
        if self.key_map["right"]:
            self.camera.setPos(self.camera, speed * dt, 0, 0)

        px, py = self.camera.getX(), self.camera.getY()
        self.camera.setZ(10.0)

        # Floor Wrap
        self.floor.setPos(px - (px % 100), py - (py % 100), 0)
        if task.frame % 3 == 0:
            self.sync_objects(px, py)

        return task.cont


if __name__ == "__main__":
    app = PandaCleanroomBridge()
    app.run()
