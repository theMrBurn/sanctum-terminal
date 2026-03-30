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
    # Anno lesson: contrast between parts, not similarity.
    # Dark robe, light skin, one accent color (gem).
    # Shadow anchors to ground. Silhouette must read.
    "shadow": {
        "w": 1.4, "h": 0.25, "color": (0.0, 0.0, 0.0, 0.35),
        "ox": 0.0, "oz": -0.02, "layer": 0.0,
    },
    "legs": {
        "w": 0.45, "h": 0.55, "color": (0.08, 0.06, 0.05, 1.0),  # near-black
        "ox": 0.0, "oz": 0.05, "layer": 0.01,
    },
    "robe_lower": {
        "w": 0.75, "h": 0.75, "color": (0.10, 0.08, 0.07, 1.0),  # very dark
        "ox": 0.0, "oz": 0.45, "layer": 0.02,
    },
    "torso": {
        "w": 0.55, "h": 0.5, "color": (0.12, 0.10, 0.08, 1.0),   # dark
        "ox": 0.0, "oz": 1.1, "layer": 0.03,
    },
    "robe_upper": {
        "w": 0.72, "h": 0.55, "color": (0.10, 0.08, 0.07, 1.0),  # matches lower
        "ox": 0.0, "oz": 1.0, "layer": 0.04,
    },
    "sash": {
        "w": 0.65, "h": 0.1, "color": (0.35, 0.15, 0.10, 1.0),   # dark red accent
        "ox": 0.0, "oz": 1.15, "layer": 0.045,
    },
    "arm_back": {
        "w": 0.18, "h": 0.55, "color": (0.08, 0.06, 0.05, 1.0),  # dark sleeve
        "ox": -0.32, "oz": 0.95, "layer": 0.005,
    },
    "hand_back": {
        "w": 0.12, "h": 0.12, "color": (0.65, 0.50, 0.38, 1.0),  # skin
        "ox": -0.32, "oz": 0.88, "layer": 0.006,
    },
    "arm_front": {
        "w": 0.18, "h": 0.55, "color": (0.09, 0.07, 0.06, 1.0),  # dark sleeve
        "ox": 0.32, "oz": 0.95, "layer": 0.05,
    },
    "hand_front": {
        "w": 0.12, "h": 0.12, "color": (0.65, 0.50, 0.38, 1.0),  # skin
        "ox": 0.32, "oz": 0.88, "layer": 0.051,
    },
    "staff": {
        "w": 0.07, "h": 2.0, "color": (0.30, 0.20, 0.10, 1.0),   # warm wood
        "ox": 0.38, "oz": 0.2, "layer": 0.06,
    },
    "staff_gem": {
        "w": 0.18, "h": 0.18, "color": (0.4, 0.75, 0.85, 1.0),   # ACCENT: identity color
        "ox": 0.38, "oz": 2.15, "layer": 0.065,
    },
    "staff_glow": {
        "w": 0.3, "h": 0.3, "color": (0.3, 0.6, 0.7, 0.25),      # soft glow halo
        "ox": 0.38, "oz": 2.1, "layer": 0.064,
    },
    "head": {
        "w": 0.35, "h": 0.35, "color": (0.72, 0.55, 0.42, 1.0),  # warm skin — POP
        "ox": 0.0, "oz": 1.58, "layer": 0.07,
    },
    "eyes": {
        "w": 0.2, "h": 0.06, "color": (0.15, 0.12, 0.10, 1.0),   # dark slit
        "ox": 0.0, "oz": 1.68, "layer": 0.075,
    },
    "hood": {
        "w": 0.52, "h": 0.5, "color": (0.08, 0.06, 0.05, 1.0),   # near-black hood
        "ox": 0.0, "oz": 1.62, "layer": 0.08,
    },
}

# Walk animation: per-part transforms over 4 frames
# Each entry: [(ox_offset, oz_offset, rotation), ...]
_WALK_PARTS = {
    "legs":       [(0.0, 0.0, 0), (0.02, 0.02, 4), (0.0, 0.0, 0), (-0.02, 0.02, -4)],
    "arm_front":  [(0.0, 0.0, 0), (0.04, 0.02, 10), (0.0, 0.0, 0), (-0.04, 0.02, -10)],
    "hand_front": [(0.0, 0.0, 0), (0.04, 0.02, 10), (0.0, 0.0, 0), (-0.04, 0.02, -10)],
    "arm_back":   [(0.0, 0.0, 0), (-0.04, 0.02, -10), (0.0, 0.0, 0), (0.04, 0.02, 10)],
    "hand_back":  [(0.0, 0.0, 0), (-0.04, 0.02, -10), (0.0, 0.0, 0), (0.04, 0.02, 10)],
    "staff":      [(0.0, 0.0, 0), (0.02, 0.0, 4), (0.0, 0.0, 0), (-0.02, 0.0, -4)],
    "staff_gem":  [(0.0, 0.0, 0), (0.02, 0.0, 4), (0.0, 0.0, 0), (-0.02, 0.0, -4)],
    "staff_glow": [(0.0, 0.0, 0), (0.02, 0.0, 4), (0.0, 0.0, 0), (-0.02, 0.0, -4)],
    "torso":      [(0.0, 0.0, 0), (0.0, 0.01, 0), (0.0, 0.0, 0), (0.0, 0.01, 0)],
    "robe_upper": [(0.0, 0.0, 0), (0.0, 0.01, 1), (0.0, 0.0, 0), (0.0, 0.01, -1)],
    "robe_lower": [(0.0, 0.0, 0), (0.0, 0.005, 0), (0.0, 0.0, 0), (0.0, 0.005, 0)],
    "sash":       [(0.0, 0.0, 0), (0.01, 0.01, 1), (0.0, 0.0, 0), (-0.01, 0.01, -1)],
    "head":       [(0.0, 0.0, 0), (0.0, 0.015, 0), (0.0, 0.0, 0), (0.0, 0.015, 0)],
    "eyes":       [(0.0, 0.0, 0), (0.0, 0.015, 0), (0.0, 0.0, 0), (0.0, 0.015, 0)],
    "hood":       [(0.0, 0.0, 0), (0.0, 0.015, 0), (0.0, 0.0, 0), (0.0, 0.015, 0)],
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

        anim_data = _WALK_PARTS if anim_id == "walk" else {}

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
