"""
core/systems/entity_template.py

Entity Template System -- hierarchical construction primitives.

Every visible thing in the world is assembled from the same 7 primitives
arranged in a named skeleton. Templates define the skeleton; the builder
instantiates it as a Panda3D scene graph with proper parent/child nesting.

Template JSON format:
{
    "name": "humanoid",
    "category": "avatar",           # avatar | creature | object | building | flora | fauna
    "size_class": "medium",         # small | medium | large
    "root": {
        "name": "hip",
        "primitive": "BLOCK",       # BLOCK | SLAB | PILLAR | WEDGE | SPIKE | ARCH | PLANE
        "scale": [0.6, 0.3, 0.4],  # w, h, d in meters
        "offset": [0, 0, 0],       # xyz offset from parent
        "rotation": [0, 0, 0],     # hpr in degrees
        "color": "base",           # palette key or [r, g, b]
        "texture": null,           # optional texture path
        "socket": true,            # named attachment point for runtime parenting
        "children": [ ... ]        # recursive part definitions
    }
}

Sockets: any part with "socket": true can have objects attached at runtime.
The builder returns a dict of {part_name: NodePath} for direct access.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from panda3d.core import (
    NodePath, Vec4, SamplerState, Material, Texture,
    TransparencyAttrib,
)

from core.systems.geometry import (
    make_box, make_plane, make_wedge, make_spike, make_arch,
    make_textured_quad, TEXTURED_BUILDERS,
)
from core.systems.material_system import MaterialRegistry, ResolvedMaterial


# -- Primitive dispatch --------------------------------------------------------

_PRIMITIVE_BUILDERS = {
    "BLOCK":  make_box,
    "SLAB":   make_box,
    "PILLAR": make_box,
    "WEDGE":  make_wedge,
    "SPIKE":  make_spike,
    "ARCH":   make_arch,
}


def _resolve_color(color_spec, palette=None):
    """Resolve a color spec to (r, g, b) tuple."""
    if isinstance(color_spec, (list, tuple)):
        return tuple(color_spec[:3])
    if palette and color_spec in palette:
        c = palette[color_spec]
        if isinstance(c, (list, tuple)):
            return tuple(c[:3])
    # Fallback grays by semantic name
    _defaults = {
        "base":     (0.45, 0.42, 0.40),
        "dark":     (0.25, 0.22, 0.20),
        "light":    (0.65, 0.62, 0.58),
        "accent":   (0.55, 0.35, 0.25),
        "wood":     (0.50, 0.35, 0.22),
        "metal":    (0.40, 0.42, 0.45),
        "stone":    (0.50, 0.48, 0.44),
        "bone":     (0.70, 0.68, 0.60),
        "leaf":     (0.30, 0.50, 0.25),
        "bark":     (0.35, 0.25, 0.18),
        "flesh":    (0.60, 0.45, 0.40),
        "crystal":  (0.40, 0.55, 0.70),
        "ember":    (0.70, 0.30, 0.15),
        "shadow":   (0.15, 0.13, 0.12),
        "glow":     (0.80, 0.75, 0.50),
    }
    return _defaults.get(color_spec, (0.50, 0.48, 0.45))


def _build_primitive(part_def: dict, palette: dict | None = None,
                     resolved_mat: ResolvedMaterial | None = None,
                     loader=None) -> NodePath:
    """
    Build a single primitive NodePath from a part definition.

    If resolved_mat is provided, uses textured geometry with material applied.
    Otherwise falls back to vertex-colored geometry (backward compatible).
    """
    ptype = part_def.get("primitive", "BLOCK")
    scale = part_def.get("scale", [1.0, 1.0, 1.0])
    name = part_def.get("name", "part")

    use_textured = resolved_mat is not None and resolved_mat.has_texture

    if use_textured and ptype in TEXTURED_BUILDERS:
        # Textured path — UV-mapped geometry + texture
        w, h, d = scale
        geom = TEXTURED_BUILDERS[ptype](w, h, d, name=name)
        np = NodePath(geom)
        np.setName(name)

        # Apply texture
        if loader:
            tex = loader.loadTexture(resolved_mat.texture)
            tex.setMagfilter(SamplerState.FT_nearest)
            tex.setMinfilter(SamplerState.FT_nearest)
            np.setTexture(tex)

        # Apply color tint on top of texture
        r, g, b = resolved_mat.color
        np.setColorScale(Vec4(r * 2, g * 2, b * 2, resolved_mat.opacity))

        # Emission glow
        if resolved_mat.emission > 0:
            mat = Material()
            mat.setEmission(Vec4(r * resolved_mat.emission,
                                 g * resolved_mat.emission,
                                 b * resolved_mat.emission, 1))
            np.setMaterial(mat)

        # Transparency
        if resolved_mat.opacity < 1.0:
            np.setTransparency(TransparencyAttrib.MAlpha)

    elif resolved_mat is not None:
        # Material but no texture — use vertex-colored primitives
        color = resolved_mat.color
        w, h, d = scale
        if ptype == "PLANE":
            geom = make_plane(int(w), int(d), color)
        elif ptype in _PRIMITIVE_BUILDERS:
            geom = _PRIMITIVE_BUILDERS[ptype](w, h, d, color)
        else:
            geom = make_box(w, h, d, color)
        np = NodePath(geom)
        np.setName(name)

        r, g, b = color
        if resolved_mat.emission > 0:
            mat = Material()
            mat.setEmission(Vec4(r * resolved_mat.emission,
                                 g * resolved_mat.emission,
                                 b * resolved_mat.emission, 1))
            np.setMaterial(mat)

        if resolved_mat.opacity < 1.0:
            np.setColorScale(Vec4(1, 1, 1, resolved_mat.opacity))
            np.setTransparency(TransparencyAttrib.MAlpha)

    else:
        # Legacy path — vertex-colored geometry
        color = _resolve_color(part_def.get("color", "base"), palette)
        if ptype == "PLANE":
            geom = make_plane(int(scale[0]), int(scale[2]), color)
        elif ptype in _PRIMITIVE_BUILDERS:
            w, h, d = scale
            geom = _PRIMITIVE_BUILDERS[ptype](w, h, d, color)
        else:
            w, h, d = scale
            geom = make_box(w, h, d, color)
        np = NodePath(geom)
        np.setName(name)

    # Position and rotation
    offset = part_def.get("offset", [0, 0, 0])
    np.setPos(offset[0], offset[1], offset[2])

    rotation = part_def.get("rotation", [0, 0, 0])
    if any(r != 0 for r in rotation):
        np.setHpr(rotation[0], rotation[1], rotation[2])

    return np


# -- Template loading ----------------------------------------------------------

class EntityTemplate:
    """
    A loaded template definition (data only, no scene graph).
    """

    def __init__(self, data: dict):
        self.name: str = data["name"]
        self.category: str = data.get("category", "object")
        self.size_class: str = data.get("size_class", "medium")
        self.root_def: dict = data["root"]
        self._raw = data

    @classmethod
    def from_file(cls, path: str | Path) -> "EntityTemplate":
        with open(path) as f:
            return cls(json.load(f))

    @classmethod
    def from_dict(cls, data: dict) -> "EntityTemplate":
        return cls(data)

    def part_names(self) -> list[str]:
        """Return all part names in the template (depth-first)."""
        names = []
        def _walk(part):
            names.append(part["name"])
            for child in part.get("children", []):
                _walk(child)
        _walk(self.root_def)
        return names

    def socket_names(self) -> list[str]:
        """Return names of all socket parts."""
        sockets = []
        def _walk(part):
            if part.get("socket", False):
                sockets.append(part["name"])
            for child in part.get("children", []):
                _walk(child)
        _walk(self.root_def)
        return sockets


# -- Template builder ----------------------------------------------------------

class EntityBuilder:
    """
    Builds a Panda3D scene graph from an EntityTemplate.

    Supports two modes:
      1. Legacy (color only): EntityBuilder(palette={...})
      2. Material: EntityBuilder(material_registry=reg, register="tron")

    Returns an EntityInstance with:
      - root: the top-level NodePath
      - parts: dict of {name: NodePath} for every part
      - sockets: dict of {name: NodePath} for attachment points
    """

    def __init__(self, palette: dict | None = None,
                 material_registry: MaterialRegistry | None = None,
                 register: str | None = None,
                 loader=None):
        self.palette = palette or {}
        self.material_registry = material_registry
        self.register = register
        self.loader = loader

    def build(self, template: EntityTemplate, parent: NodePath | None = None) -> "EntityInstance":
        parts = {}
        sockets = {}

        def _build_recursive(part_def: dict, parent_np: NodePath) -> NodePath:
            # Resolve material if specified
            resolved_mat = None
            mat_name = part_def.get("material")
            if mat_name and self.material_registry:
                resolved_mat = self.material_registry.resolve(mat_name, self.register)

            np = _build_primitive(part_def, self.palette,
                                  resolved_mat=resolved_mat,
                                  loader=self.loader)
            np.reparentTo(parent_np)

            name = part_def["name"]
            parts[name] = np

            if part_def.get("socket", False):
                sockets[name] = np

            # Tag for runtime identification
            np.setPythonTag("template_part", name)
            np.setPythonTag("primitive_type", part_def.get("primitive", "BLOCK"))
            if mat_name:
                np.setPythonTag("material_name", mat_name)

            # Recurse into children
            for child_def in part_def.get("children", []):
                _build_recursive(child_def, np)

            return np

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


class EntityInstance:
    """
    A built entity -- scene graph + part/socket access.
    """

    def __init__(self, template: EntityTemplate, root: NodePath,
                 parts: dict[str, NodePath], sockets: dict[str, NodePath]):
        self.template = template
        self.root = root
        self.parts = parts
        self.sockets = sockets

    @property
    def name(self) -> str:
        return self.template.name

    @property
    def category(self) -> str:
        return self.template.category

    def get_part(self, name: str) -> NodePath | None:
        return self.parts.get(name)

    def get_socket(self, name: str) -> NodePath | None:
        return self.sockets.get(name)

    def attach_to_socket(self, socket_name: str, child_np: NodePath) -> bool:
        """Parent a NodePath to a named socket."""
        socket = self.sockets.get(socket_name)
        if socket is None:
            return False
        child_np.reparentTo(socket)
        return True

    def set_register_tint(self, color: tuple[float, float, float, float]):
        """Apply a global register color tint."""
        self.root.setColorScale(Vec4(*color))

    def set_part_color(self, part_name: str, r: float, g: float, b: float):
        """Override color on a specific part."""
        part = self.parts.get(part_name)
        if part:
            part.setColorScale(Vec4(r, g, b, 1.0))

    def apply_material(self, part_name: str, resolved_mat: ResolvedMaterial,
                       loader=None):
        """Apply a resolved material to a specific part at runtime."""
        part = self.parts.get(part_name)
        if not part:
            return False

        r, g, b = resolved_mat.color

        if resolved_mat.has_texture and loader:
            tex = loader.loadTexture(resolved_mat.texture)
            tex.setMagfilter(SamplerState.FT_nearest)
            tex.setMinfilter(SamplerState.FT_nearest)
            part.setTexture(tex)
            # Tint texture with color
            part.setColorScale(Vec4(r * 2, g * 2, b * 2, resolved_mat.opacity))
        else:
            # No texture — color is baked into vertex-colored geometry
            # Can't change vertex colors at runtime, but can tint
            part.setColorScale(Vec4(1, 1, 1, resolved_mat.opacity))

        if resolved_mat.emission > 0:
            mat = Material()
            mat.setEmission(Vec4(r * resolved_mat.emission,
                                 g * resolved_mat.emission,
                                 b * resolved_mat.emission, 1))
            part.setMaterial(mat)

        if resolved_mat.opacity < 1.0:
            part.setTransparency(TransparencyAttrib.MAlpha)

        part.setPythonTag("material_name", resolved_mat.name)
        return True

    def apply_register(self, material_registry: MaterialRegistry,
                       register: str, loader=None):
        """Re-resolve all materials for a new register. Runtime register switch."""
        for name, part in self.parts.items():
            mat_name = part.getPythonTag("material_name")
            if mat_name:
                resolved = material_registry.resolve(mat_name, register)
                if resolved:
                    self.apply_material(name, resolved, loader)

    def hide_part(self, part_name: str):
        part = self.parts.get(part_name)
        if part:
            part.hide()

    def show_part(self, part_name: str):
        part = self.parts.get(part_name)
        if part:
            part.show()

    def cleanup(self):
        """Remove from scene graph."""
        self.root.removeNode()


# -- Template catalog ----------------------------------------------------------

class TemplateCatalog:
    """
    Loads and caches all templates from a directory.
    """

    def __init__(self, template_dir: str | Path = "assets/templates"):
        self._dir = Path(template_dir)
        self._cache: dict[str, EntityTemplate] = {}

    def load_all(self) -> dict[str, EntityTemplate]:
        """Load all .json templates from the directory."""
        if not self._dir.exists():
            return {}
        for path in sorted(self._dir.glob("*.json")):
            template = EntityTemplate.from_file(path)
            self._cache[template.name] = template
        return dict(self._cache)

    def get(self, name: str) -> EntityTemplate | None:
        if not self._cache:
            self.load_all()
        return self._cache.get(name)

    def names(self) -> list[str]:
        if not self._cache:
            self.load_all()
        return list(self._cache.keys())

    def by_category(self, category: str) -> list[EntityTemplate]:
        if not self._cache:
            self.load_all()
        return [t for t in self._cache.values() if t.category == category]
