"""
core/systems/sprite_renderer.py

SpriteRenderer -- 2D pixel art billboard sprites in 3D world.

The Anno Mutationem register: 3D environment + 2D character sprites.
Sprites are textured quads that always face the camera (billboard mode).
Register tint applies via setColorScale -- same [R] cycle as 3D objects.

Usage:
    renderer = SpriteRenderer(render_root, loader)
    monk = renderer.spawn_sprite("monk", pos=(0, 5, 0), scale=3.0)
    renderer.set_frame(monk, col=0, row=0)  # change animation frame
    renderer.apply_register(monk, "tron")
"""

from __future__ import annotations

from pathlib import Path

from panda3d.core import (
    CardMaker,
    NodePath,
    SamplerState,
    Texture,
    TransparencyAttrib,
    Vec4,
)


# -- Sprite sheet config -------------------------------------------------------

SPRITE_SHEETS = {
    "roguelike": {
        "path": "assets/kenney/characters/roguelike/Spritesheet/roguelikeChar_transparent.png",
        "tile_size": 16,
        "margin": 1,
        "cols": 54,
        "rows": 11,
    },
}

# Named sprite definitions -- column, row on the sheet
SPRITE_CATALOG = {
    # Player characters
    "monk":         {"sheet": "roguelike", "col": 0,  "row": 0},
    "monk_walk1":   {"sheet": "roguelike", "col": 1,  "row": 0},
    "monk_walk2":   {"sheet": "roguelike", "col": 2,  "row": 0},
    # NPCs / creatures
    "knight":       {"sheet": "roguelike", "col": 0,  "row": 1},
    "mage":         {"sheet": "roguelike", "col": 0,  "row": 2},
    "rogue":        {"sheet": "roguelike", "col": 0,  "row": 3},
    "skeleton":     {"sheet": "roguelike", "col": 0,  "row": 4},
    "goblin":       {"sheet": "roguelike", "col": 0,  "row": 5},
    "orc":          {"sheet": "roguelike", "col": 0,  "row": 6},
    "demon":        {"sheet": "roguelike", "col": 0,  "row": 7},
    "ghost":        {"sheet": "roguelike", "col": 0,  "row": 8},
    "slime":        {"sheet": "roguelike", "col": 0,  "row": 9},
}

# Register tints for sprites (same system as models)
SPRITE_REGISTER_TINTS = {
    "survival": Vec4(1.0,  1.0,  1.0,  1.0),    # natural colors
    "tron":     Vec4(0.3,  0.7,  0.9,  1.0),     # cyan shift
    "tolkien":  Vec4(1.1,  0.95, 0.85, 1.0),     # warm gold
    "sanrio":   Vec4(1.0,  0.85, 0.95, 1.0),     # pink tint
}


class SpriteRenderer:
    """
    Renders 2D pixel art sprites as billboard quads in 3D space.

    Parameters
    ----------
    render_root : Panda3D NodePath (scene root for sprites)
    panda_loader : Panda3D Loader instance
    """

    def __init__(self, render_root, panda_loader):
        self.render_root = render_root
        self._loader     = panda_loader
        self._textures   = {}   # sheet_id -> Texture
        self._sprites    = []   # all spawned sprite NodePaths

    def _load_sheet(self, sheet_id: str) -> Texture:
        """Load and cache a sprite sheet texture."""
        if sheet_id in self._textures:
            return self._textures[sheet_id]

        info = SPRITE_SHEETS.get(sheet_id)
        if not info:
            return None

        path = Path(info["path"])
        if not path.exists():
            return None

        tex = self._loader.loadTexture(str(path))
        if tex:
            # Nearest-neighbor filtering for pixel art (no blurring)
            tex.setMagfilter(SamplerState.FT_nearest)
            tex.setMinfilter(SamplerState.FT_nearest)
            self._textures[sheet_id] = tex

        return tex

    def spawn_sprite(
        self,
        sprite_id: str,
        pos: tuple = (0, 0, 0),
        scale: float = 3.0,
    ) -> NodePath:
        """
        Spawn a sprite as a billboard textured quad.
        Returns the NodePath for positioning/animation.
        """
        entry = SPRITE_CATALOG.get(sprite_id)
        if not entry:
            return None

        sheet_id = entry["sheet"]
        info = SPRITE_SHEETS[sheet_id]
        tex = self._load_sheet(sheet_id)
        if not tex:
            return None

        # Create a textured quad via CardMaker
        cm = CardMaker(f"sprite_{sprite_id}")
        cm.setFrame(-0.5, 0.5, 0, 1.0)  # centered X, bottom-aligned Z

        sprite_np = self.render_root.attachNewNode(cm.generate())
        sprite_np.setTexture(tex)
        sprite_np.setTransparency(TransparencyAttrib.MAlpha)
        sprite_np.setBillboardPointEye()
        sprite_np.setScale(scale)
        sprite_np.setPos(*pos)

        # Set initial UV to the correct tile
        self._set_uv(sprite_np, info, entry["col"], entry["row"])

        sprite_np.setPythonTag("sprite_id", sprite_id)
        sprite_np.setPythonTag("sheet_info", info)
        self._sprites.append(sprite_np)
        return sprite_np

    def set_frame(self, sprite_np: NodePath, col: int, row: int) -> None:
        """Change the displayed frame on a sprite (for animation)."""
        info = sprite_np.getPythonTag("sheet_info")
        if info:
            self._set_uv(sprite_np, info, col, row)

    def apply_register(self, sprite_np: NodePath, register: str) -> None:
        """Apply register color tint to a sprite."""
        tint = SPRITE_REGISTER_TINTS.get(register, SPRITE_REGISTER_TINTS["survival"])
        sprite_np.setColorScale(tint)

    def clear(self) -> None:
        """Remove all spawned sprites."""
        for sp in self._sprites:
            if not sp.isEmpty():
                sp.removeNode()
        self._sprites = []

    def _set_uv(self, sprite_np, info, col, row):
        """Set UV coordinates to display a specific tile from the sheet."""
        tile = info["tile_size"]
        margin = info["margin"]
        cols = info["cols"]
        rows = info["rows"]

        # Calculate UV coordinates (Panda3D UV: 0,0 = bottom-left)
        sheet_w = cols * (tile + margin)
        sheet_h = rows * (tile + margin)

        u_left   = col * (tile + margin) / sheet_w
        u_right  = (col * (tile + margin) + tile) / sheet_w
        # Panda3D V is bottom-up, sheet row 0 is top
        v_top    = 1.0 - (row * (tile + margin)) / sheet_h
        v_bottom = 1.0 - (row * (tile + margin) + tile) / sheet_h

        sprite_np.setTexOffset(sprite_np.findTextureStage("*"), u_left, v_bottom)
        sprite_np.setTexScale(sprite_np.findTextureStage("*"),
                             u_right - u_left, v_top - v_bottom)
