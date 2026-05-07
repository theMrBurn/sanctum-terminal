"""
core/systems/material_system.py

Material System -- the abstraction between geometry and appearance.

A MaterialDef says what a surface looks like: color, texture, emission, opacity.
Each material has a base definition and optional per-register overrides.

The MaterialRegistry loads all materials from JSON and resolves them by
(material_name, register) → final appearance.

This is the missing layer between the template skeleton and what you see.

Material JSON format:
{
    "name": "monk_robe",
    "category": "fabric",
    "base": {
        "color": [0.10, 0.08, 0.07],
        "texture": null,
        "emission": 0.0,
        "opacity": 1.0
    },
    "registers": {
        "survival": { "color": [0.12, 0.10, 0.08] },
        "tron":     { "color": [0.08, 0.12, 0.15], "emission": 0.3 },
        "tolkien":  { "texture": "textures/robe_tolkien.png" },
        "sanrio":   { "color": [0.20, 0.15, 0.18] }
    }
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ResolvedMaterial:
    """Final material values ready to apply to geometry."""
    name: str
    color: tuple[float, float, float] = (0.5, 0.48, 0.45)
    texture: str | None = None
    emission: float = 0.0
    opacity: float = 1.0

    @property
    def has_texture(self) -> bool:
        return self.texture is not None


class MaterialDef:
    """
    A material definition with base values and per-register overrides.
    """

    def __init__(self, data: dict):
        self.name: str = data["name"]
        self.category: str = data.get("category", "generic")
        self._base: dict = data.get("base", {})
        self._registers: dict[str, dict] = data.get("registers", {})
        self._raw = data

    @classmethod
    def from_file(cls, path: str | Path) -> "MaterialDef":
        with open(path) as f:
            return cls(json.load(f))

    @classmethod
    def from_dict(cls, data: dict) -> "MaterialDef":
        return cls(data)

    def resolve(self, register: str | None = None) -> ResolvedMaterial:
        """
        Resolve final material values for a given register.
        Register overrides are merged on top of base values.
        """
        # Start with base
        color = tuple(self._base.get("color", [0.5, 0.48, 0.45]))
        texture = self._base.get("texture")
        emission = self._base.get("emission", 0.0)
        opacity = self._base.get("opacity", 1.0)

        # Apply register overrides
        if register and register in self._registers:
            overrides = self._registers[register]
            if "color" in overrides:
                color = tuple(overrides["color"])
            if "texture" in overrides:
                texture = overrides["texture"]
            if "emission" in overrides:
                emission = overrides["emission"]
            if "opacity" in overrides:
                opacity = overrides["opacity"]

        return ResolvedMaterial(
            name=self.name,
            color=color[:3],
            texture=texture,
            emission=emission,
            opacity=opacity,
        )

    @property
    def register_names(self) -> list[str]:
        return list(self._registers.keys())


class MaterialRegistry:
    """
    Loads and caches all material definitions.
    Resolves materials by (name, register) → ResolvedMaterial.
    """

    def __init__(self, material_dir: str | Path = "assets/materials"):
        self._dir = Path(material_dir)
        self._cache: dict[str, MaterialDef] = {}
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.load_all()
            self._loaded = True

    def load_all(self) -> dict[str, MaterialDef]:
        """Load all .json material files from the directory."""
        if not self._dir.exists():
            return {}
        for path in sorted(self._dir.glob("*.json")):
            try:
                mat = MaterialDef.from_file(path)
                self._cache[mat.name] = mat
            except (json.JSONDecodeError, KeyError):
                continue
        self._loaded = True
        return dict(self._cache)

    def register(self, material: MaterialDef):
        """Register a material definition (e.g., from code rather than file)."""
        self._cache[material.name] = material

    def get(self, name: str) -> MaterialDef | None:
        """Get a material definition by name."""
        self._ensure_loaded()
        return self._cache.get(name)

    def resolve(self, name: str, register: str | None = None) -> ResolvedMaterial | None:
        """Resolve a material to final values for a given register."""
        mat = self.get(name)
        if mat is None:
            return None
        return mat.resolve(register)

    def names(self) -> list[str]:
        self._ensure_loaded()
        return list(self._cache.keys())

    def by_category(self, category: str) -> list[MaterialDef]:
        self._ensure_loaded()
        return [m for m in self._cache.values() if m.category == category]

    def categories(self) -> list[str]:
        self._ensure_loaded()
        return list(set(m.category for m in self._cache.values()))
