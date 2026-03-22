from panda3d.core import *


class AssemblyFactory:
    @staticmethod
    def build_structure(parent, key, pos, registry):
        data = registry.get(key)
        if not data:
            return

        cm = CardMaker(f"mesh_{key}")
        if key == "COBBLE":
            w = data["width"]
            cm.setFrame(-w / 2, w / 2, 0, 40)
            node = parent.attachNewNode(cm.generate())
            node.setPos(pos)
            node.setP(-90)  # Lay flat
        elif key == "WALL":
            h = data["height"]
            cm.setFrame(-10, 10, 0, h)
            node = parent.attachNewNode(cm.generate())
            node.setPos(pos)
            node.setH(90 if pos.getX() > 0 else -90)

        node.setColor(data["color"])
        node.setTwoSided(True)
        return node
