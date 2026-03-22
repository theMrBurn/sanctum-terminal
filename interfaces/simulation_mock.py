import math
from direct.showbase.ShowBase import ShowBase
from panda3d.core import *

class GlobalResyncSim(ShowBase):
    def __init__(self):
        super().__init__()
        # 1. FIX THE LENS (No more blank screens)
        self.setBackgroundColor(0, 0, 0.1) # Navy Blue for visibility
        self.camLens.setNearFar(0.1, 2000.0)

        # 2. THE AVATAR (The Anchor)
        self.avatar = self.render.attachNewNode("Avatar")
        self.camera.reparentTo(self.avatar)
        self.camera.setPos(0, -50, 8) # Back and up
        self.camera.lookAt(0, 100, 0) # Look down the road

        # 3. GUARANTEED LIGHTING (Moon + Fill)
        # Global Fill (Passive)
        fill = AmbientLight('fill')
        fill.setColor(Vec4(0.2, 0.2, 0.4, 1))
        self.render.setLight(self.render.attachNewNode(fill))
        
        # Moonlight (Active)
        moon = DirectionalLight('moon')
        moon.setColor(Vec4(0.4, 0.5, 0.8, 1))
        moon_np = self.render.attachNewNode(moon)
        moon_np.setHpr(0, -60, 0)
        self.render.setLight(moon_np)

        # 4. ON-DEMAND TEST OBJECTS
        # Building a visible corridor to prove the engine is alive
        for i in range(10):
            y = i * 40
            # The Road (Device)
            road_cm = CardMaker("road")
            road_cm.setFrame(-15, 15, 0, 40)
            road = self.render.attachNewNode(road_cm.generate())
            road.setPos(0, y, 0); road.setP(-90)
            road.setColor(0.2, 0.2, 0.5, 1)

            # The Walls (Device)
            wall_cm = CardMaker("wall")
            wall_cm.setFrame(-20, 20, 0, 30)
            for x in [-25, 25]:
                w = self.render.attachNewNode(wall_cm.generate())
                w.setPos(x, y, 0); w.setH(90 if x > 0 else -90)
                w.setColor(0.1, 0.1, 0.2, 1)

        self.disableMouse()
        self.taskMgr.add(self.update, "Update")

    def update(self, task):
        # Walk through the corridor
        self.avatar.setY(self.avatar.getY() + 3.0 * globalClock.getDt())
        return task.cont

if __name__ == "__main__":
    GlobalResyncSim().run()