"""
Tests for the Entity Template System.

Covers: loading, building, nesting, sockets, part access,
register tinting, attachment, catalog.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from panda3d.core import NodePath, Vec4

from core.systems.entity_template import (
    EntityTemplate,
    EntityBuilder,
    EntityInstance,
    TemplateCatalog,
    _resolve_color,
)


# -- Fixtures ------------------------------------------------------------------

MINIMAL_TEMPLATE = {
    "name": "test_block",
    "category": "object",
    "size_class": "small",
    "root": {
        "name": "base",
        "primitive": "BLOCK",
        "scale": [1.0, 1.0, 1.0],
        "offset": [0, 0, 0],
        "color": "base",
        "socket": False,
        "children": [],
    },
}

NESTED_TEMPLATE = {
    "name": "test_nested",
    "category": "creature",
    "size_class": "medium",
    "root": {
        "name": "body",
        "primitive": "BLOCK",
        "scale": [1.0, 1.0, 1.0],
        "offset": [0, 0, 0.5],
        "color": "base",
        "socket": True,
        "children": [
            {
                "name": "head",
                "primitive": "BLOCK",
                "scale": [0.5, 0.5, 0.5],
                "offset": [0, 0, 0.75],
                "color": "flesh",
                "socket": True,
                "children": [
                    {
                        "name": "eye_l",
                        "primitive": "BLOCK",
                        "scale": [0.1, 0.1, 0.1],
                        "offset": [-0.1, 0.2, 0.1],
                        "color": "glow",
                        "children": [],
                    },
                    {
                        "name": "eye_r",
                        "primitive": "BLOCK",
                        "scale": [0.1, 0.1, 0.1],
                        "offset": [0.1, 0.2, 0.1],
                        "color": "glow",
                        "children": [],
                    },
                ],
            },
            {
                "name": "arm_l",
                "primitive": "BLOCK",
                "scale": [0.2, 0.2, 0.6],
                "offset": [-0.6, 0, 0],
                "color": "base",
                "socket": True,
                "children": [
                    {
                        "name": "hand_l",
                        "primitive": "BLOCK",
                        "scale": [0.15, 0.1, 0.15],
                        "offset": [0, 0, -0.4],
                        "color": "flesh",
                        "socket": True,
                        "children": [],
                    },
                ],
            },
        ],
    },
}

ALL_PRIMITIVES_TEMPLATE = {
    "name": "test_all_prims",
    "category": "object",
    "root": {
        "name": "block_part",
        "primitive": "BLOCK",
        "scale": [1.0, 1.0, 1.0],
        "offset": [0, 0, 0],
        "color": "base",
        "children": [
            {
                "name": "wedge_part",
                "primitive": "WEDGE",
                "scale": [0.5, 0.5, 0.5],
                "offset": [2, 0, 0],
                "color": "accent",
                "children": [],
            },
            {
                "name": "spike_part",
                "primitive": "SPIKE",
                "scale": [0.5, 0.8, 0.5],
                "offset": [4, 0, 0],
                "color": "ember",
                "children": [],
            },
            {
                "name": "arch_part",
                "primitive": "ARCH",
                "scale": [1.0, 0.3, 1.0],
                "offset": [6, 0, 0],
                "color": "stone",
                "children": [],
            },
            {
                "name": "slab_part",
                "primitive": "SLAB",
                "scale": [2.0, 0.2, 1.0],
                "offset": [0, 0, -1],
                "color": "dark",
                "children": [],
            },
            {
                "name": "pillar_part",
                "primitive": "PILLAR",
                "scale": [0.3, 2.0, 0.3],
                "offset": [-2, 0, 0],
                "color": "metal",
                "children": [],
            },
        ],
    },
}

ROTATION_TEMPLATE = {
    "name": "test_rotation",
    "category": "object",
    "root": {
        "name": "base",
        "primitive": "BLOCK",
        "scale": [1.0, 1.0, 1.0],
        "offset": [0, 0, 0],
        "rotation": [45, 30, 0],
        "color": "base",
        "children": [
            {
                "name": "tilted",
                "primitive": "WEDGE",
                "scale": [0.5, 0.5, 0.5],
                "offset": [0, 0, 1],
                "rotation": [0, -20, 15],
                "color": "accent",
                "children": [],
            },
        ],
    },
}


# -- EntityTemplate tests ------------------------------------------------------

class TestEntityTemplate:

    def test_from_dict_basic(self):
        t = EntityTemplate.from_dict(MINIMAL_TEMPLATE)
        assert t.name == "test_block"
        assert t.category == "object"
        assert t.size_class == "small"

    def test_from_dict_defaults(self):
        t = EntityTemplate.from_dict({"name": "x", "root": {"name": "r", "children": []}})
        assert t.category == "object"
        assert t.size_class == "medium"

    def test_part_names_minimal(self):
        t = EntityTemplate.from_dict(MINIMAL_TEMPLATE)
        assert t.part_names() == ["base"]

    def test_part_names_nested(self):
        t = EntityTemplate.from_dict(NESTED_TEMPLATE)
        names = t.part_names()
        assert "body" in names
        assert "head" in names
        assert "eye_l" in names
        assert "eye_r" in names
        assert "arm_l" in names
        assert "hand_l" in names
        assert len(names) == 6

    def test_socket_names(self):
        t = EntityTemplate.from_dict(NESTED_TEMPLATE)
        sockets = t.socket_names()
        assert "body" in sockets
        assert "head" in sockets
        assert "arm_l" in sockets
        assert "hand_l" in sockets
        # eyes are NOT sockets
        assert "eye_l" not in sockets
        assert "eye_r" not in sockets

    def test_from_file(self, tmp_path):
        path = tmp_path / "test.json"
        path.write_text(json.dumps(MINIMAL_TEMPLATE))
        t = EntityTemplate.from_file(path)
        assert t.name == "test_block"

    def test_all_primitives_parts(self):
        t = EntityTemplate.from_dict(ALL_PRIMITIVES_TEMPLATE)
        names = t.part_names()
        assert len(names) == 6  # root + 5 children
        for expected in ["block_part", "wedge_part", "spike_part", "arch_part", "slab_part", "pillar_part"]:
            assert expected in names


# -- Color resolution ----------------------------------------------------------

class TestColorResolution:

    def test_list_color(self):
        assert _resolve_color([0.5, 0.3, 0.1]) == (0.5, 0.3, 0.1)

    def test_tuple_color(self):
        assert _resolve_color((0.5, 0.3, 0.1)) == (0.5, 0.3, 0.1)

    def test_named_default(self):
        r, g, b = _resolve_color("base")
        assert 0 < r < 1
        assert 0 < g < 1
        assert 0 < b < 1

    def test_palette_override(self):
        palette = {"base": [1.0, 0.0, 0.0]}
        assert _resolve_color("base", palette) == (1.0, 0.0, 0.0)

    def test_unknown_name_fallback(self):
        r, g, b = _resolve_color("nonexistent_color_name")
        assert isinstance(r, float)

    def test_all_named_colors_resolve(self):
        for name in ["base", "dark", "light", "accent", "wood", "metal",
                      "stone", "bone", "leaf", "bark", "flesh", "crystal",
                      "ember", "shadow", "glow"]:
            r, g, b = _resolve_color(name)
            assert 0 <= r <= 1 and 0 <= g <= 1 and 0 <= b <= 1


# -- EntityBuilder tests -------------------------------------------------------

class TestEntityBuilder:

    def test_build_minimal(self):
        t = EntityTemplate.from_dict(MINIMAL_TEMPLATE)
        builder = EntityBuilder()
        inst = builder.build(t)
        assert isinstance(inst, EntityInstance)
        assert inst.name == "test_block"
        assert "base" in inst.parts

    def test_build_nested_hierarchy(self):
        t = EntityTemplate.from_dict(NESTED_TEMPLATE)
        builder = EntityBuilder()
        inst = builder.build(t)

        # All parts exist
        assert len(inst.parts) == 6
        for name in ["body", "head", "eye_l", "eye_r", "arm_l", "hand_l"]:
            assert name in inst.parts

    def test_build_deep_nesting(self):
        """Verify 3+ levels of nesting work (body→arm_l→hand_l)."""
        t = EntityTemplate.from_dict(NESTED_TEMPLATE)
        builder = EntityBuilder()
        inst = builder.build(t)

        hand = inst.get_part("hand_l")
        assert hand is not None
        # hand's parent should be arm_l
        assert hand.getParent().getName() == "arm_l"
        # arm's parent should be body
        arm = inst.get_part("arm_l")
        assert arm.getParent().getName() == "body"

    def test_build_sockets(self):
        t = EntityTemplate.from_dict(NESTED_TEMPLATE)
        builder = EntityBuilder()
        inst = builder.build(t)
        assert len(inst.sockets) == 4  # body, head, arm_l, hand_l

    def test_build_with_parent(self):
        t = EntityTemplate.from_dict(MINIMAL_TEMPLATE)
        builder = EntityBuilder()
        parent = NodePath("world")
        inst = builder.build(t, parent=parent)
        assert inst.root.getParent() == parent

    def test_build_all_primitive_types(self):
        t = EntityTemplate.from_dict(ALL_PRIMITIVES_TEMPLATE)
        builder = EntityBuilder()
        inst = builder.build(t)
        assert len(inst.parts) == 6

    def test_build_with_rotation(self):
        t = EntityTemplate.from_dict(ROTATION_TEMPLATE)
        builder = EntityBuilder()
        inst = builder.build(t)
        base = inst.get_part("base")
        assert abs(base.getH() - 45) < 0.01
        assert abs(base.getP() - 30) < 0.01

    def test_build_positions(self):
        t = EntityTemplate.from_dict(NESTED_TEMPLATE)
        builder = EntityBuilder()
        inst = builder.build(t)
        body = inst.get_part("body")
        assert abs(body.getZ() - 0.5) < 0.01
        head = inst.get_part("head")
        assert abs(head.getZ() - 0.75) < 0.01

    def test_build_with_palette(self):
        palette = {"base": [1.0, 0.0, 0.0], "flesh": [0.9, 0.8, 0.7]}
        t = EntityTemplate.from_dict(NESTED_TEMPLATE)
        builder = EntityBuilder(palette=palette)
        inst = builder.build(t)
        # Should build without error
        assert len(inst.parts) == 6

    def test_python_tags(self):
        t = EntityTemplate.from_dict(MINIMAL_TEMPLATE)
        builder = EntityBuilder()
        inst = builder.build(t)
        base = inst.get_part("base")
        assert base.getPythonTag("template_part") == "base"
        assert base.getPythonTag("primitive_type") == "BLOCK"


# -- EntityInstance tests ------------------------------------------------------

class TestEntityInstance:

    def _make_instance(self):
        t = EntityTemplate.from_dict(NESTED_TEMPLATE)
        return EntityBuilder().build(t)

    def test_get_part(self):
        inst = self._make_instance()
        assert inst.get_part("body") is not None
        assert inst.get_part("nonexistent") is None

    def test_get_socket(self):
        inst = self._make_instance()
        assert inst.get_socket("hand_l") is not None
        assert inst.get_socket("eye_l") is None

    def test_attach_to_socket(self):
        inst = self._make_instance()
        sword = NodePath("sword")
        assert inst.attach_to_socket("hand_l", sword) is True
        assert sword.getParent().getName() == "hand_l"

    def test_attach_to_invalid_socket(self):
        inst = self._make_instance()
        thing = NodePath("thing")
        assert inst.attach_to_socket("nonexistent", thing) is False

    def test_set_register_tint(self):
        inst = self._make_instance()
        inst.set_register_tint((0.5, 0.8, 1.0, 1.0))
        cs = inst.root.getColorScale()
        assert abs(cs.getX() - 0.5) < 0.01

    def test_set_part_color(self):
        inst = self._make_instance()
        inst.set_part_color("head", 1.0, 0.0, 0.0)
        cs = inst.get_part("head").getColorScale()
        assert abs(cs.getX() - 1.0) < 0.01

    def test_hide_show_part(self):
        inst = self._make_instance()
        inst.hide_part("eye_l")
        assert inst.get_part("eye_l").isHidden()
        inst.show_part("eye_l")
        assert not inst.get_part("eye_l").isHidden()

    def test_cleanup(self):
        inst = self._make_instance()
        root = inst.root
        inst.cleanup()
        assert root.isEmpty()

    def test_category(self):
        inst = self._make_instance()
        assert inst.category == "creature"


# -- TemplateCatalog tests -----------------------------------------------------

class TestTemplateCatalog:

    def test_load_all(self, tmp_path):
        (tmp_path / "a.json").write_text(json.dumps(MINIMAL_TEMPLATE))
        data2 = dict(NESTED_TEMPLATE)
        (tmp_path / "b.json").write_text(json.dumps(data2))
        catalog = TemplateCatalog(tmp_path)
        templates = catalog.load_all()
        assert len(templates) == 2

    def test_get(self, tmp_path):
        (tmp_path / "a.json").write_text(json.dumps(MINIMAL_TEMPLATE))
        catalog = TemplateCatalog(tmp_path)
        t = catalog.get("test_block")
        assert t is not None
        assert t.name == "test_block"

    def test_get_missing(self, tmp_path):
        catalog = TemplateCatalog(tmp_path)
        assert catalog.get("nope") is None

    def test_names(self, tmp_path):
        (tmp_path / "a.json").write_text(json.dumps(MINIMAL_TEMPLATE))
        catalog = TemplateCatalog(tmp_path)
        assert "test_block" in catalog.names()

    def test_by_category(self, tmp_path):
        (tmp_path / "a.json").write_text(json.dumps(MINIMAL_TEMPLATE))
        (tmp_path / "b.json").write_text(json.dumps(NESTED_TEMPLATE))
        catalog = TemplateCatalog(tmp_path)
        creatures = catalog.by_category("creature")
        assert len(creatures) == 1
        assert creatures[0].name == "test_nested"

    def test_empty_dir(self, tmp_path):
        catalog = TemplateCatalog(tmp_path)
        assert catalog.load_all() == {}

    def test_nonexistent_dir(self):
        catalog = TemplateCatalog("/nonexistent/path")
        assert catalog.load_all() == {}


# -- Real template file tests --------------------------------------------------

class TestRealTemplates:
    """Test that all shipped template files load and build correctly."""

    TEMPLATE_DIR = Path("assets/templates")

    @pytest.fixture(params=[
        "humanoid", "quadruped", "object_small", "object_mid",
        "object_large", "building_module", "flora", "fauna",
    ])
    def template_name(self, request):
        return request.param

    def test_template_loads(self, template_name):
        path = self.TEMPLATE_DIR / f"{template_name}.json"
        t = EntityTemplate.from_file(path)
        assert t.name == template_name

    def test_template_builds(self, template_name):
        path = self.TEMPLATE_DIR / f"{template_name}.json"
        t = EntityTemplate.from_file(path)
        inst = EntityBuilder().build(t)
        assert len(inst.parts) >= 1
        inst.cleanup()

    def test_template_has_sockets(self, template_name):
        path = self.TEMPLATE_DIR / f"{template_name}.json"
        t = EntityTemplate.from_file(path)
        # Every template should have at least one socket
        assert len(t.socket_names()) >= 1

    def test_template_part_names_unique(self, template_name):
        path = self.TEMPLATE_DIR / f"{template_name}.json"
        t = EntityTemplate.from_file(path)
        names = t.part_names()
        assert len(names) == len(set(names)), f"Duplicate part names in {template_name}: {names}"

    def test_template_deep_nesting(self, template_name):
        """Verify at least 2 levels of nesting."""
        path = self.TEMPLATE_DIR / f"{template_name}.json"
        t = EntityTemplate.from_file(path)
        inst = EntityBuilder().build(t)

        max_depth = 0
        def _measure_depth(np, depth):
            nonlocal max_depth
            max_depth = max(max_depth, depth)
            for child in np.getChildren():
                _measure_depth(child, depth + 1)

        _measure_depth(inst.root, 0)
        assert max_depth >= 2, f"{template_name} only has depth {max_depth}"
        inst.cleanup()
