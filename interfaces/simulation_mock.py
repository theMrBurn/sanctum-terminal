import math
from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import TextNode, Fog, TransparencyAttrib, PointLight, Vec4
from core.registry import OBJECT_REGISTRY
from core.geometry import GeoFactory

class FirstContactSim(ShowBase):
    def __init__(self, key="4004"):
        super().__init__()
        self.setBackgroundColor(0, 0, 0.02)
        
        # LIGHTING
        self.plight = PointLight('octo_light')
        self.plight.setColor(Vec4(0.8, 0.3, 1.0, 1))
        self.plnp = self.camera.attachNewNode(self.plight)
        self.plnp.setPos(0, -5, 10)
        self.render.setLight(self.plnp)

        # FOG
        self.fog = Fog("MythicFog")
        self.fog.setExpDensity(0.02)
        self.render.setFog(self.fog)

        # GENERATE AND REPARENT
        self.floor = GeoFactory.generate("0001", OBJECT_REGISTRY["0001"])
        self.floor.reparentTo(self.render)
        
        sprite_dna = OBJECT_REGISTRY[key]
        self.target = GeoFactory.generate(key, sprite_dna)
        self.target.reparentTo(self.render)
        self.target.setPos(0, 60, 0)
        self.target.setBillboardPointEye()
        self.target.setTransparency(TransparencyAttrib.MDual)

        # HUD
        self.status = OnscreenText(text="HD-2D SYNC: SUCCESSFUL", pos=(-1.2, 0.9), 
                                  scale=0.05, fg=(0, 1, 0.8, 1), align=TextNode.ALeft)

        self.disableMouse()
        self.camera.setPos(0, -20, 8) 
        self.taskMgr.add(self.update, "Update")

    def update(self, task):
        dt = globalClock.getDt()
        pulse = (math.sin(task.time * 2.5) * 0.4) + 0.6
        self.plight.setColor(Vec4(pulse * 0.8, 0.2, pulse, 1))
        self.camera.setY(self.camera.getY() + 15 * dt)
        if task.time > 5.0: return task.done
        return task.cont

if __name__ == "__main__":
    sim = FirstContactSim()
    sim.run()