"""
core/systems/paper_doll.py

PaperDollRenderer -- layered 2D character composition in 3D space.

Anno Mutationem approach: each body part is a separate textured quad
on a flat plane. Parts are parented in a hierarchy and animate
independently. The whole assembly is a billboard.

Placeholder parts are generated as colored geometry. Replace textures
later with pixel art -- the system stays the same.

Usage:
    doll = PaperDollRenderer(render_root)
    monk = doll.create_monk(pos=(0, 8, 0))
    doll.animate(monk, "walk", dt)
    doll.apply_register(monk, "tron")
"""

from __future__ import annotations

from panda3d.core import (
    CardMaker,
    NodePath,
    Vec4,
    TransparencyAttrib,
)


# -- Part definitions ----------------------------------------------------------
# Each part: {width, height, color, offset_x, offset_z, layer (Y depth)}
# Colors are placeholder -- replace with textures later.
# Proportions based on: robed monk, staff in right hand, level 45 experience.

MONK_PARTS = {
    "shadow": {
        "w": 1.2, "h": 0.3, "color": (0.0, 0.0, 0.0, 0.3),
        "ox": 0.0, "oz": 0.0, "layer": 0.0,
    },
    "legs": {
        "w": 0.5, "h": 0.6, "color": (0.18, 0.14, 0.10, 1.0),
        "ox": 0.0, "oz": 0.05, "layer": 0.01,
    },
    "robe_lower": {
        "w": 0.7, "h": 0.7, "color": (0.22, 0.18, 0.14, 1.0),
        "ox": 0.0, "oz": 0.5, "layer": 0.02,
    },
    "torso": {
        "w": 0.6, "h": 0.5, "color": (0.25, 0.20, 0.16, 1.0),
        "ox": 0.0, "oz": 1.1, "layer": 0.03,
    },
    "robe_upper": {
        "w": 0.7, "h": 0.55, "color": (0.28, 0.22, 0.17, 1.0),
        "ox": 0.0, "oz": 1.05, "layer": 0.04,
    },
    "arm_back": {
        "w": 0.2, "h": 0.5, "color": (0.22, 0.17, 0.13, 1.0),
        "ox": -0.3, "oz": 1.0, "layer": 0.005,
    },
    "arm_front": {
        "w": 0.2, "h": 0.5, "color": (0.24, 0.19, 0.15, 1.0),
        "ox": 0.3, "oz": 1.0, "layer": 0.05,
    },
    "staff": {
        "w": 0.08, "h": 1.8, "color": (0.35, 0.25, 0.12, 1.0),
        "ox": 0.35, "oz": 0.3, "layer": 0.06,
    },
    "staff_gem": {
        "w": 0.15, "h": 0.15, "color": (0.5, 0.8, 0.9, 1.0),
        "ox": 0.35, "oz": 2.05, "layer": 0.065,
    },
    "head": {
        "w": 0.4, "h": 0.4, "color": (0.72, 0.58, 0.45, 1.0),
        "ox": 0.0, "oz": 1.55, "layer": 0.07,
    },
    "hood": {
        "w": 0.5, "h": 0.45, "color": (0.20, 0.16, 0.12, 1.0),
        "ox": 0.0, "oz": 1.6, "layer": 0.08,
    },
}

# Walk animation: per-part transforms over 4 frames
# Each entry: [(ox_offset, oz_offset, rotation), ...]
WALK_ANIM = {
    "legs":      [(0.0, 0.0, 0), (0.02, 0.02, 3), (0.0, 0.0, 0), (-0.02, 0.02, -3)],
    "arm_front": [(0.0, 0.0, 0), (0.03, 0.02, 8), (0.0, 0.0, 0), (-0.03, 0.02, -8)],
    "arm_back":  [(0.0, 0.0, 0), (-0.03, 0.02, -8), (0.0, 0.0, 0), (0.03, 0.02, 8)],
    "staff":     [(0.0, 0.0, 0), (0.02, 0.0, 3), (0.0, 0.0, 0), (-0.02, 0.0, -3)],
    "staff_gem": [(0.0, 0.0, 0), (0.02, 0.0, 3), (0.0, 0.0, 0), (-0.02, 0.0, -3)],
    "torso":     [(0.0, 0.0, 0), (0.0, 0.01, 0), (0.0, 0.0, 0), (0.0, 0.01, 0)],
    "robe_upper":[(0.0, 0.0, 0), (0.0, 0.01, 1), (0.0, 0.0, 0), (0.0, 0.01, -1)],
    "head":      [(0.0, 0.0, 0), (0.0, 0.015, 0), (0.0, 0.0, 0), (0.0, 0.015, 0)],
    "hood":      [(0.0, 0.0, 0), (0.0, 0.015, 0), (0.0, 0.0, 0), (0.0, 0.015, 0)],
}

# Register tints
DOLL_REGISTER_TINTS = {
    "survival": Vec4(1.0, 1.0, 1.0, 1.0),
    "tron":     Vec4(0.2, 0.6, 0.8, 1.0),
    "tolkien":  Vec4(1.1, 0.95, 0.8, 1.0),
    "sanrio":   Vec4(1.0, 0.8, 0.9, 1.0),
}


class PaperDollRenderer:
    """
    Creates layered 2D characters from part definitions.

    Parameters
    ----------
    render_root : Panda3D NodePath
    """

    def __init__(self, render_root):
        self.render_root = render_root
        self._dolls = []

    def create_monk(self, pos: tuple = (0, 0, 0), scale: float = 1.0) -> NodePath:
        """
        Create a Philosopher Monk paper doll.
        Returns root NodePath containing all part quads.
        """
        root = self.render_root.attachNewNode("monk_doll")
        root.setPos(*pos)
        root.setBillboardPointEye()

        parts = {}
        for name, part in MONK_PARTS.items():
            cm = CardMaker(f"part_{name}")
            hw = part["w"] * scale / 2
            h = part["h"] * scale
            cm.setFrame(-hw, hw, 0, h)

            quad = root.attachNewNode(cm.generate())
            quad.setPos(
                part["ox"] * scale,
                part["layer"],  # Y depth for layering
                part["oz"] * scale,
            )
            r, g, b, a = part["color"]
            quad.setColor(r, g, b, a)
            quad.setTransparency(TransparencyAttrib.MAlpha)

            # Store base position for animation
            quad.setPythonTag("base_ox", part["ox"] * scale)
            quad.setPythonTag("base_oz", part["oz"] * scale)
            parts[name] = quad

        root.setPythonTag("parts", parts)
        root.setPythonTag("anim_elapsed", 0.0)
        self._dolls.append(root)
        return root

    def animate(self, doll: NodePath, anim_id: str, dt: float,
                frame_rate: float = 6.0) -> None:
        """
        Animate a paper doll. Moves individual parts per frame.
        """
        if anim_id == "idle":
            return

        parts = doll.getPythonTag("parts")
        if not parts:
            return

        elapsed = doll.getPythonTag("anim_elapsed") or 0.0
        elapsed += dt
        doll.setPythonTag("anim_elapsed", elapsed)

        anim_data = WALK_ANIM if anim_id == "walk" else {}

        for name, frames in anim_data.items():
            if name not in parts:
                continue
            quad = parts[name]
            frame_idx = int(elapsed * frame_rate) % len(frames)
            ox_off, oz_off, rot = frames[frame_idx]

            base_ox = quad.getPythonTag("base_ox")
            base_oz = quad.getPythonTag("base_oz")
            quad.setX(base_ox + ox_off)
            quad.setZ(base_oz + oz_off)
            quad.setR(rot)

    def apply_register(self, doll: NodePath, register: str) -> None:
        """Apply register color tint to all parts."""
        tint = DOLL_REGISTER_TINTS.get(register, DOLL_REGISTER_TINTS["survival"])
        doll.setColorScale(tint)

    def clear(self):
        """Remove all dolls."""
        for d in self._dolls:
            if not d.isEmpty():
                d.removeNode()
        self._dolls = []
