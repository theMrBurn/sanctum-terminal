"""
core/systems/billboard_renderer.py

Billboard Entity Renderer -- Anno Mutationem / Octopath style.

Uses the entity template skeleton for hierarchy, positioning, and sockets,
but renders each part as a camera-facing textured quad instead of a 3D box.

This is the correct approach for 2D pixel art characters in 3D space:
- Skeleton gives you hierarchy (hand follows arm follows shoulder)
- Billboard quads give you pixel art that always faces the camera
- Textures are per-part sprite segments from concept art

Usage:
    renderer = BillboardRenderer(loader)
    instance = renderer.build(template, sprite_map, parent=render)
    # sprite_map: {"head": "path/to/head.png", "torso": "path/to/torso.png", ...}
"""

from __future__ import annotations

import json
from pathlib import Path

from panda3d.core import (
    CardMaker,
    NodePath,
    Vec4,
    SamplerState,
    TransparencyAttrib,
)

from core.systems.entity_template import EntityTemplate, EntityInstance


class BillboardRenderer:
    """
    Builds billboard-sprite entities from entity templates.

    Each template part becomes a camera-facing textured quad.
    Parts without sprites become invisible positioning nodes
    (still provide hierarchy for children).
    """

    def __init__(self, loader):
        self.loader = loader
        self._tex_cache: dict[str, object] = {}

    def _load_texture(self, path: str):
        if path in self._tex_cache:
            return self._tex_cache[path]
        tex = self.loader.loadTexture(path)
        tex.setMagfilter(SamplerState.FT_nearest)
        tex.setMinfilter(SamplerState.FT_nearest)
        tex.setWrapU(SamplerState.WM_clamp)
        tex.setWrapV(SamplerState.WM_clamp)
        self._tex_cache[path] = tex
        return tex

    def build(self, template: EntityTemplate,
              sprite_map: dict[str, str],
              parent: NodePath | None = None,
              billboard: bool = True) -> EntityInstance:
        """
        Build a billboard entity from a template + sprite map.

        Parameters
        ----------
        template    : the entity template (hierarchy, positions, sockets)
        sprite_map  : {part_name: texture_path} for parts that have sprites
        parent      : scene graph parent
        billboard   : if True, each sprite faces camera (set False for top-down)
        """
        parts = {}
        sockets = {}

        def _build_recursive(part_def: dict, parent_np: NodePath):
            name = part_def["name"]
            scale = part_def.get("scale", [1.0, 1.0, 1.0])
            offset = part_def.get("offset", [0, 0, 0])
            rotation = part_def.get("rotation", [0, 0, 0])

            sprite_path = sprite_map.get(name)

            if sprite_path:
                # Billboard textured quad
                tex = self._load_texture(sprite_path)
                tex_w = tex.getXSize()
                tex_h = tex.getYSize()

                # Use the template scale for quad dimensions
                # scale[0] = width, scale[1] = height (z in 3D)
                quad_w = scale[0]
                quad_h = scale[1]  # h is second param in template scale

                # If the part has a meaningful width/height from the template,
                # use those. Otherwise derive from texture aspect ratio.
                if quad_w < 0.01:
                    quad_w = 0.5
                if quad_h < 0.01:
                    quad_h = 0.5

                # Maintain texture aspect ratio based on the larger dimension
                aspect = tex_w / tex_h if tex_h > 0 else 1.0
                # Use the height (z-scale) as the reference, derive width
                quad_h = scale[2] if len(scale) > 2 else scale[1]
                quad_w = quad_h * aspect

                cm = CardMaker(name)
                cm.setFrame(-quad_w / 2, quad_w / 2, -quad_h / 2, quad_h / 2)
                cm.setHasUvs(True)

                np = parent_np.attachNewNode(cm.generate())
                np.setTexture(tex)
                np.setTransparency(TransparencyAttrib.MAlpha)

                if billboard:
                    np.setBillboardPointEye()

            else:
                # No sprite — invisible positioning node (hierarchy only)
                np = parent_np.attachNewNode(name)

            np.setName(name)
            np.setPos(offset[0], offset[1], offset[2])

            if any(r != 0 for r in rotation):
                # Only apply rotation to non-billboard nodes
                if not sprite_path:
                    np.setHpr(rotation[0], rotation[1], rotation[2])

            parts[name] = np

            if part_def.get("socket", False):
                sockets[name] = np

            np.setPythonTag("template_part", name)
            if sprite_path:
                np.setPythonTag("sprite_path", sprite_path)

            for child_def in part_def.get("children", []):
                _build_recursive(child_def, np)

        # Root container
        root = NodePath(template.name)
        if parent:
            root.reparentTo(parent)

        _build_recursive(template.root_def, root)

        return EntityInstance(
            template=template,
            root=root,
            parts=parts,
            sockets=sockets,
        )

    def build_from_config(self, template: EntityTemplate,
                          sprite_config_path: str | Path,
                          parent: NodePath | None = None) -> EntityInstance:
        """
        Build from a sprite config JSON file.

        Config format:
        {
            "head": "assets/sprites/textures/parts/monk_head.png",
            "torso": "assets/sprites/textures/parts/monk_torso.png",
            ...
        }
        """
        with open(sprite_config_path) as f:
            sprite_map = json.load(f)
        return self.build(template, sprite_map, parent=parent)
