"""
Tests for the Material System.

Covers: MaterialDef, ResolvedMaterial, MaterialRegistry,
register resolution, file loading, categories.
"""

import json
import pytest
from pathlib import Path

from core.systems.material_system import (
    MaterialDef,
    MaterialRegistry,
    ResolvedMaterial,
)


BASIC_MATERIAL = {
    "name": "test_stone",
    "category": "mineral",
    "base": {
        "color": [0.5, 0.48, 0.44],
        "texture": None,
        "emission": 0.0,
        "opacity": 1.0,
    },
}

FULL_MATERIAL = {
    "name": "test_crystal",
    "category": "mineral",
    "base": {
        "color": [0.4, 0.55, 0.7],
        "texture": "textures/crystal.png",
        "emission": 0.3,
        "opacity": 0.85,
    },
    "registers": {
        "survival": {"color": [0.5, 0.45, 0.4]},
        "tron": {"color": [0.2, 0.8, 1.0], "emission": 0.8},
        "tolkien": {"texture": "textures/crystal_tolkien.png"},
        "sanrio": {"color": [0.8, 0.5, 0.7], "opacity": 0.9},
    },
}

MINIMAL_MATERIAL = {
    "name": "test_minimal",
}


class TestResolvedMaterial:

    def test_defaults(self):
        m = ResolvedMaterial(name="x")
        assert m.color == (0.5, 0.48, 0.45)
        assert m.texture is None
        assert m.emission == 0.0
        assert m.opacity == 1.0
        assert not m.has_texture

    def test_has_texture(self):
        m = ResolvedMaterial(name="x", texture="foo.png")
        assert m.has_texture


class TestMaterialDef:

    def test_from_dict_basic(self):
        m = MaterialDef.from_dict(BASIC_MATERIAL)
        assert m.name == "test_stone"
        assert m.category == "mineral"

    def test_from_dict_minimal(self):
        m = MaterialDef.from_dict(MINIMAL_MATERIAL)
        assert m.name == "test_minimal"
        assert m.category == "generic"

    def test_resolve_base(self):
        m = MaterialDef.from_dict(BASIC_MATERIAL)
        r = m.resolve()
        assert r.name == "test_stone"
        assert r.color == (0.5, 0.48, 0.44)
        assert r.texture is None
        assert r.emission == 0.0
        assert r.opacity == 1.0

    def test_resolve_no_register(self):
        m = MaterialDef.from_dict(FULL_MATERIAL)
        r = m.resolve()
        assert r.color == (0.4, 0.55, 0.7)
        assert r.texture == "textures/crystal.png"

    def test_resolve_register_color_override(self):
        m = MaterialDef.from_dict(FULL_MATERIAL)
        r = m.resolve("survival")
        assert r.color == (0.5, 0.45, 0.4)
        # texture should remain from base
        assert r.texture == "textures/crystal.png"

    def test_resolve_register_emission_override(self):
        m = MaterialDef.from_dict(FULL_MATERIAL)
        r = m.resolve("tron")
        assert r.emission == 0.8
        assert r.color == (0.2, 0.8, 1.0)

    def test_resolve_register_texture_override(self):
        m = MaterialDef.from_dict(FULL_MATERIAL)
        r = m.resolve("tolkien")
        assert r.texture == "textures/crystal_tolkien.png"
        # color stays base
        assert r.color == (0.4, 0.55, 0.7)

    def test_resolve_register_opacity_override(self):
        m = MaterialDef.from_dict(FULL_MATERIAL)
        r = m.resolve("sanrio")
        assert r.opacity == 0.9

    def test_resolve_unknown_register(self):
        m = MaterialDef.from_dict(FULL_MATERIAL)
        r = m.resolve("nonexistent")
        # Should return base values
        assert r.color == (0.4, 0.55, 0.7)

    def test_register_names(self):
        m = MaterialDef.from_dict(FULL_MATERIAL)
        names = m.register_names
        assert set(names) == {"survival", "tron", "tolkien", "sanrio"}

    def test_from_file(self, tmp_path):
        path = tmp_path / "test.json"
        path.write_text(json.dumps(BASIC_MATERIAL))
        m = MaterialDef.from_file(path)
        assert m.name == "test_stone"


class TestMaterialRegistry:

    def test_load_all(self, tmp_path):
        (tmp_path / "a.json").write_text(json.dumps(BASIC_MATERIAL))
        (tmp_path / "b.json").write_text(json.dumps(FULL_MATERIAL))
        reg = MaterialRegistry(tmp_path)
        mats = reg.load_all()
        assert len(mats) == 2

    def test_get(self, tmp_path):
        (tmp_path / "a.json").write_text(json.dumps(BASIC_MATERIAL))
        reg = MaterialRegistry(tmp_path)
        m = reg.get("test_stone")
        assert m is not None
        assert m.name == "test_stone"

    def test_get_missing(self, tmp_path):
        reg = MaterialRegistry(tmp_path)
        assert reg.get("nope") is None

    def test_resolve(self, tmp_path):
        (tmp_path / "a.json").write_text(json.dumps(FULL_MATERIAL))
        reg = MaterialRegistry(tmp_path)
        r = reg.resolve("test_crystal", "tron")
        assert r is not None
        assert r.emission == 0.8

    def test_resolve_missing(self, tmp_path):
        reg = MaterialRegistry(tmp_path)
        assert reg.resolve("nope") is None

    def test_names(self, tmp_path):
        (tmp_path / "a.json").write_text(json.dumps(BASIC_MATERIAL))
        reg = MaterialRegistry(tmp_path)
        assert "test_stone" in reg.names()

    def test_by_category(self, tmp_path):
        (tmp_path / "a.json").write_text(json.dumps(BASIC_MATERIAL))
        (tmp_path / "b.json").write_text(json.dumps(FULL_MATERIAL))
        reg = MaterialRegistry(tmp_path)
        minerals = reg.by_category("mineral")
        assert len(minerals) == 2

    def test_categories(self, tmp_path):
        (tmp_path / "a.json").write_text(json.dumps(BASIC_MATERIAL))
        reg = MaterialRegistry(tmp_path)
        assert "mineral" in reg.categories()

    def test_register_programmatic(self, tmp_path):
        reg = MaterialRegistry(tmp_path)
        mat = MaterialDef.from_dict(BASIC_MATERIAL)
        reg.register(mat)
        assert reg.get("test_stone") is not None

    def test_empty_dir(self, tmp_path):
        reg = MaterialRegistry(tmp_path)
        assert reg.load_all() == {}

    def test_nonexistent_dir(self):
        reg = MaterialRegistry("/nonexistent")
        assert reg.load_all() == {}

    def test_invalid_json_skipped(self, tmp_path):
        (tmp_path / "bad.json").write_text("not json{{{")
        (tmp_path / "good.json").write_text(json.dumps(BASIC_MATERIAL))
        reg = MaterialRegistry(tmp_path)
        mats = reg.load_all()
        assert len(mats) == 1
