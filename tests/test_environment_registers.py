"""
tests/test_environment_registers.py

Environment registers -- the whole room transforms with [R].

Floor, walls, grid, background, lighting all shift per register.
Same geometry, different atmosphere. survival / tron / tolkien / sanrio.
"""
import pytest


# -- Register data -------------------------------------------------------------

class TestEnvironmentRegisterData:

    def test_registers_importable(self):
        from creation_lab import ENVIRONMENT_REGISTERS
        assert isinstance(ENVIRONMENT_REGISTERS, dict)

    def test_all_four_registers_defined(self):
        from creation_lab import ENVIRONMENT_REGISTERS
        for reg in ("survival", "tron", "tolkien", "sanrio"):
            assert reg in ENVIRONMENT_REGISTERS, f"Missing register: {reg}"

    def test_each_register_has_required_keys(self):
        from creation_lab import ENVIRONMENT_REGISTERS
        required = ["background", "floor", "wall", "grid", "ambient", "sun", "fill"]
        for reg, palette in ENVIRONMENT_REGISTERS.items():
            for key in required:
                assert key in palette, f"{reg} missing {key}"

    def test_colors_are_rgb_tuples(self):
        from creation_lab import ENVIRONMENT_REGISTERS
        color_keys = ["background", "floor", "wall", "grid", "ambient", "sun", "fill", "fog"]
        for reg, palette in ENVIRONMENT_REGISTERS.items():
            for key in color_keys:
                color = palette[key]
                assert len(color) == 3, f"{reg}.{key} is not RGB: {color}"

    def test_tron_is_dark(self):
        from creation_lab import ENVIRONMENT_REGISTERS
        tron = ENVIRONMENT_REGISTERS["tron"]
        assert sum(tron["background"]) < 0.1
        assert sum(tron["floor"]) < 0.2

    def test_sanrio_is_bright(self):
        from creation_lab import ENVIRONMENT_REGISTERS
        sanrio = ENVIRONMENT_REGISTERS["sanrio"]
        assert sum(sanrio["background"]) > 0.5
        assert sum(sanrio["floor"]) > 1.0

    def test_survival_matches_original_lab(self):
        from creation_lab import ENVIRONMENT_REGISTERS, _CFG
        surv = ENVIRONMENT_REGISTERS["survival"]
        assert surv["background"] == _CFG["bg"]
        assert surv["floor"] == _CFG["floor_color"]
