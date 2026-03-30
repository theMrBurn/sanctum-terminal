"""
tests/test_compound_objects.py

Compound objects -- multi-primitive composition with visual registers.

Same grammar (geometry), different palette (skin).
Survival / TRON / Tolkien / Sanrio -- four registers, one schema.

Blueprint schema:
    grammar[]       -- primitives with role, parent, offset [x,y,z]
    registers{}     -- named palettes {survival, tron, tolkien, sanrio}
    tags[]          -- fingerprint dimensions
    encounter_verb  -- THINK/ACT/MOVE/DEFEND/TOOLS
    weight          -- kg
    use_line        -- REACHABLE label text
"""
import pytest
from core.systems.primitive_factory import PrimitiveFactory, Primitive


@pytest.fixture
def factory():
    return PrimitiveFactory()


@pytest.fixture
def torch_blueprint():
    """Torch: handle PILLAR + wrap WEDGE + flame SPIKE."""
    return {
        "grammar": [
            {"primitive": "PILLAR", "role": "handle", "scale": [0.08, 0.7, 0.08],
             "color": "wood"},
            {"primitive": "WEDGE",  "role": "wrap",   "scale": [0.12, 0.15, 0.12],
             "color": "fiber",  "parent": "handle"},
            {"primitive": "SPIKE",  "role": "flame",  "scale": [0.14, 0.3, 0.14],
             "color": "fire",   "parent": "wrap"},
        ],
        "registers": {
            "survival": {
                "wood":  {"base": [0.35, 0.25, 0.12], "edge": [0.0, 0.0, 0.0],  "emission": 0.0},
                "fiber": {"base": [0.30, 0.22, 0.10], "edge": [0.0, 0.0, 0.0],  "emission": 0.0},
                "fire":  {"base": [0.95, 0.65, 0.15], "edge": [1.0, 0.8, 0.3],  "emission": 0.6},
            },
            "tron": {
                "wood":  {"base": [0.03, 0.03, 0.04], "edge": [0.0, 0.6, 0.8],  "emission": 0.3},
                "fiber": {"base": [0.02, 0.02, 0.03], "edge": [0.0, 0.5, 0.7],  "emission": 0.2},
                "fire":  {"base": [0.02, 0.02, 0.02], "edge": [0.0, 0.9, 1.0],  "emission": 1.0},
            },
            "tolkien": {
                "wood":  {"base": [0.28, 0.18, 0.08], "edge": [0.0, 0.0, 0.0],  "emission": 0.0},
                "fiber": {"base": [0.22, 0.15, 0.07], "edge": [0.0, 0.0, 0.0],  "emission": 0.0},
                "fire":  {"base": [0.90, 0.50, 0.10], "edge": [0.95, 0.6, 0.2], "emission": 0.4},
            },
            "sanrio": {
                "wood":  {"base": [0.90, 0.75, 0.85], "edge": [1.0, 0.8, 0.9],  "emission": 0.15},
                "fiber": {"base": [0.85, 0.70, 0.80], "edge": [1.0, 0.75, 0.9], "emission": 0.1},
                "fire":  {"base": [1.0,  0.85, 0.50], "edge": [1.0, 0.9, 0.7],  "emission": 0.5},
            },
        },
        "tags": ["crafting_time", "precision_score"],
        "encounter_verb": "TOOLS",
        "weight": 0.4,
        "use_line": "Lights what needs seeing.",
    }


@pytest.fixture
def book_blueprint():
    """Book: cover SLAB + pages SLAB + spine PILLAR."""
    return {
        "grammar": [
            {"primitive": "SLAB",   "role": "cover",  "scale": [0.3, 0.04, 0.4],
             "color": "leather"},
            {"primitive": "SLAB",   "role": "pages",  "scale": [0.28, 0.03, 0.38],
             "color": "paper",   "parent": "cover"},
            {"primitive": "PILLAR", "role": "spine",  "scale": [0.04, 0.07, 0.4],
             "color": "leather", "parent": "cover", "offset": [-0.15, 0.0, 0.0]},
        ],
        "registers": {
            "survival": {
                "leather": {"base": [0.25, 0.18, 0.10], "edge": [0.0, 0.0, 0.0],  "emission": 0.0},
                "paper":   {"base": [0.78, 0.72, 0.62], "edge": [0.0, 0.0, 0.0],  "emission": 0.0},
            },
            "tron": {
                "leather": {"base": [0.04, 0.03, 0.05], "edge": [0.8, 0.4, 0.0],  "emission": 0.3},
                "paper":   {"base": [0.03, 0.03, 0.04], "edge": [1.0, 0.6, 0.0],  "emission": 0.5},
            },
            "tolkien": {
                "leather": {"base": [0.30, 0.15, 0.05], "edge": [0.4, 0.3, 0.1],  "emission": 0.0},
                "paper":   {"base": [0.82, 0.78, 0.68], "edge": [0.0, 0.0, 0.0],  "emission": 0.0},
            },
            "sanrio": {
                "leather": {"base": [0.85, 0.60, 0.75], "edge": [1.0, 0.7, 0.85], "emission": 0.2},
                "paper":   {"base": [1.0,  0.95, 0.98], "edge": [1.0, 0.9, 0.95], "emission": 0.1},
            },
        },
        "tags": ["observation_time", "precision_score"],
        "encounter_verb": "THINK",
        "weight": 0.8,
        "use_line": "Something written inside.",
    }


# -- XYZ offset support -------------------------------------------------------

class TestXYZOffsets:

    def test_no_offset_stacks_on_parent_z(self, factory):
        """Default parent stacking: child sits on top of parent (Z offset = parent height)."""
        blueprint = {
            "grammar": [
                {"primitive": "PILLAR", "role": "base", "scale": [0.1, 1.0, 0.1],
                 "color": "a"},
                {"primitive": "SPIKE", "role": "top", "scale": [0.1, 0.3, 0.1],
                 "color": "a", "parent": "base"},
            ],
        }
        parts = factory.from_blueprint(blueprint, palette={"a": (0.5, 0.5, 0.5)})
        base = next(p for p in parts if p.role == "base")
        top = next(p for p in parts if p.role == "top")
        # Child Z offset equals parent's final height (after profile scaling)
        assert top.offset_z == pytest.approx(base.scale[1])

    def test_explicit_offset_overrides_stacking(self, factory):
        """Explicit offset [x,y,z] overrides default parent Z stacking."""
        blueprint = {
            "grammar": [
                {"primitive": "SLAB", "role": "cover", "scale": [0.3, 0.04, 0.4],
                 "color": "a"},
                {"primitive": "PILLAR", "role": "spine", "scale": [0.04, 0.07, 0.4],
                 "color": "a", "parent": "cover", "offset": [-0.15, 0.0, 0.0]},
            ],
        }
        parts = factory.from_blueprint(blueprint, palette={"a": (0.5, 0.5, 0.5)})
        spine = next(p for p in parts if p.role == "spine")
        assert spine.offset_x == pytest.approx(-0.15)
        assert spine.offset_y == pytest.approx(0.0)
        assert spine.offset_z == pytest.approx(0.0)

    def test_offset_without_parent_ignored(self, factory):
        """Offset on root primitive has no effect."""
        blueprint = {
            "grammar": [
                {"primitive": "BLOCK", "role": "root", "scale": [1.0, 1.0, 1.0],
                 "color": "a", "offset": [5.0, 5.0, 5.0]},
            ],
        }
        parts = factory.from_blueprint(blueprint, palette={"a": (0.5, 0.5, 0.5)})
        assert parts[0].offset_z == pytest.approx(0.0)


# -- Register palette support -------------------------------------------------

class TestRegisterPalettes:

    def test_resolve_register_returns_flat_palette(self, factory, torch_blueprint):
        """resolve_register() extracts base colors from a named register."""
        palette = factory.resolve_register(
            torch_blueprint["registers"], "survival"
        )
        assert "wood" in palette
        assert len(palette["wood"]) == 3  # RGB tuple

    def test_different_registers_different_colors(self, factory, torch_blueprint):
        """Survival and TRON produce different base colors."""
        surv = factory.resolve_register(torch_blueprint["registers"], "survival")
        tron = factory.resolve_register(torch_blueprint["registers"], "tron")
        assert surv["wood"] != tron["wood"]

    def test_resolve_register_extracts_emission(self, factory, torch_blueprint):
        """resolve_register_full() returns base + edge + emission."""
        full = factory.resolve_register_full(
            torch_blueprint["registers"], "tron"
        )
        assert full["fire"]["emission"] == pytest.approx(1.0)
        assert full["fire"]["edge"] == [0.0, 0.9, 1.0]

    def test_unknown_register_raises(self, factory, torch_blueprint):
        with pytest.raises(KeyError):
            factory.resolve_register(torch_blueprint["registers"], "steampunk")

    def test_all_four_registers_exist(self, factory, torch_blueprint):
        for reg in ("survival", "tron", "tolkien", "sanrio"):
            palette = factory.resolve_register(
                torch_blueprint["registers"], reg
            )
            assert len(palette) > 0, f"Register {reg} is empty"


# -- Compound building with registers -----------------------------------------

class TestCompoundBuilding:

    def test_build_torch_survival(self, factory, torch_blueprint):
        palette = factory.resolve_register(
            torch_blueprint["registers"], "survival"
        )
        parts = factory.from_blueprint(torch_blueprint, palette)
        assert len(parts) == 3
        roles = {p.role for p in parts}
        assert roles == {"handle", "wrap", "flame"}

    def test_build_torch_tron(self, factory, torch_blueprint):
        palette = factory.resolve_register(
            torch_blueprint["registers"], "tron"
        )
        parts = factory.from_blueprint(torch_blueprint, palette)
        assert len(parts) == 3

    def test_build_book_all_registers(self, factory, book_blueprint):
        for reg in ("survival", "tron", "tolkien", "sanrio"):
            palette = factory.resolve_register(
                book_blueprint["registers"], reg
            )
            parts = factory.from_blueprint(book_blueprint, palette)
            assert len(parts) == 3, f"Register {reg} failed"

    def test_same_grammar_different_colors(self, factory, torch_blueprint):
        surv = factory.resolve_register(torch_blueprint["registers"], "survival")
        tron = factory.resolve_register(torch_blueprint["registers"], "tron")
        parts_surv = factory.from_blueprint(torch_blueprint, surv)
        parts_tron = factory.from_blueprint(torch_blueprint, tron)
        # Same number of parts, same roles
        assert len(parts_surv) == len(parts_tron)
        for ps, pt in zip(parts_surv, parts_tron):
            assert ps.role == pt.role
            # Different colors
            assert ps.color != pt.color


# -- Emission on primitives ---------------------------------------------------

class TestEmission:

    def test_primitive_has_emission_field(self, factory):
        p = factory.build("SPIKE", scale=(0.1, 0.3, 0.1), color=(0.9, 0.6, 0.1),
                          emission=0.6)
        assert p.emission == pytest.approx(0.6)

    def test_default_emission_is_zero(self, factory):
        p = factory.build("BLOCK", scale=(1.0, 1.0, 1.0), color=(0.5, 0.5, 0.5))
        assert p.emission == pytest.approx(0.0)

    def test_edge_color_stored(self, factory):
        p = factory.build("SPIKE", scale=(0.1, 0.3, 0.1), color=(0.9, 0.6, 0.1),
                          edge_color=(1.0, 0.8, 0.3), emission=0.6)
        assert p.edge_color == (1.0, 0.8, 0.3)

    def test_compound_with_emission(self, factory, torch_blueprint):
        """Building from register with emission stores emission per part."""
        full = factory.resolve_register_full(
            torch_blueprint["registers"], "tron"
        )
        parts = factory.from_blueprint_full(torch_blueprint, full)
        flame = next(p for p in parts if p.role == "flame")
        assert flame.emission == pytest.approx(1.0)
        handle = next(p for p in parts if p.role == "handle")
        assert handle.emission == pytest.approx(0.3)


# -- Blueprint metadata passthrough -------------------------------------------

class TestBlueprintMetadata:

    def test_blueprint_has_tags(self, torch_blueprint):
        assert torch_blueprint["tags"] == ["crafting_time", "precision_score"]

    def test_blueprint_has_encounter_verb(self, torch_blueprint):
        assert torch_blueprint["encounter_verb"] == "TOOLS"

    def test_blueprint_has_weight(self, torch_blueprint):
        assert torch_blueprint["weight"] == pytest.approx(0.4)

    def test_blueprint_has_use_line(self, torch_blueprint):
        assert torch_blueprint["use_line"] == "Lights what needs seeing."

    def test_book_has_think_verb(self, book_blueprint):
        assert book_blueprint["encounter_verb"] == "THINK"
