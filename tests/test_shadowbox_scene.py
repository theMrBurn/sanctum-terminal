"""
tests/test_shadowbox_scene.py

Shadow box multi-plane parallax renderer.
Pure logic tests -- no display required.
"""

import pytest

from core.systems.shadowbox_scene import (
    ShadowboxLayer,
    ShadowboxCamera,
    ShadowboxConfig,
    ShadowboxScene,
    CORRIDOR_LAYERS,
    SHADOWBOX_REGISTERS,
    parallax_offset,
    layer_fog_range,
    resolve_palette,
)


# -- Layer definitions ---------------------------------------------------------

class TestShadowboxLayer:

    def test_layer_is_frozen(self):
        layer = ShadowboxLayer("test", depth=10.0, parallax=0.5, fog_density=0.3, sort_order=1)
        with pytest.raises(AttributeError):
            layer.depth = 20.0

    def test_corridor_has_four_layers(self):
        assert len(CORRIDOR_LAYERS) == 4

    def test_corridor_layer_names(self):
        names = [l.name for l in CORRIDOR_LAYERS]
        assert names == ["backdrop", "midground", "stage", "foreground"]

    def test_backdrop_is_deepest(self):
        backdrop = CORRIDOR_LAYERS[0]
        assert backdrop.depth == max(l.depth for l in CORRIDOR_LAYERS)

    def test_foreground_is_closest(self):
        fg = CORRIDOR_LAYERS[3]
        assert fg.depth == min(l.depth for l in CORRIDOR_LAYERS)

    def test_stage_uses_nearest_filtering(self):
        stage = CORRIDOR_LAYERS[2]
        assert stage.use_nearest is True

    def test_other_layers_default_to_linear(self):
        for layer in CORRIDOR_LAYERS:
            if layer.name != "stage":
                assert layer.use_nearest is False

    def test_sort_order_increases_front_to_back(self):
        orders = [l.sort_order for l in CORRIDOR_LAYERS]
        assert orders == sorted(orders)


# -- Camera config -------------------------------------------------------------

class TestShadowboxCamera:

    def test_default_fov(self):
        cam = ShadowboxCamera()
        assert cam.fov == 65.0

    def test_default_eye_height(self):
        cam = ShadowboxCamera()
        assert cam.eye_z == 2.5

    def test_custom_fov(self):
        cam = ShadowboxCamera(fov=28.0)
        assert cam.fov == 28.0


# -- Scene config --------------------------------------------------------------

class TestShadowboxConfig:

    def test_default_config(self):
        config = ShadowboxConfig()
        assert len(config.layers) == 4
        assert config.register == "survival"

    def test_layers_back_to_front(self):
        config = ShadowboxConfig()
        depths = [l.depth for l in config.layers_back_to_front]
        assert depths == sorted(depths, reverse=True)

    def test_layers_front_to_back(self):
        config = ShadowboxConfig()
        depths = [l.depth for l in config.layers_front_to_back]
        assert depths == sorted(depths)


# -- Parallax calculation -----------------------------------------------------

class TestParallax:

    def test_static_backdrop_no_offset(self):
        """Parallax 0.0 = maximum relative drift."""
        layer = ShadowboxLayer("bg", depth=50, parallax=0.0, fog_density=0, sort_order=0)
        ox, oy = parallax_offset(5.0, 3.0, layer)
        assert ox == pytest.approx(-5.0)
        assert oy == pytest.approx(-3.0)

    def test_camera_locked_no_relative_motion(self):
        """Parallax 1.0 = moves with camera = zero offset."""
        layer = ShadowboxLayer("fg", depth=-2, parallax=1.0, fog_density=0, sort_order=3)
        ox, oy = parallax_offset(5.0, 3.0, layer)
        assert ox == pytest.approx(0.0)
        assert oy == pytest.approx(0.0)

    def test_half_parallax(self):
        layer = ShadowboxLayer("mid", depth=20, parallax=0.5, fog_density=0, sort_order=1)
        ox, oy = parallax_offset(10.0, 0.0, layer)
        assert ox == pytest.approx(-5.0)

    def test_exaggerated_foreground(self):
        """Parallax > 1.0 moves opposite to camera (debris flying past)."""
        layer = ShadowboxLayer("fg", depth=-2, parallax=1.2, fog_density=0, sort_order=3)
        ox, oy = parallax_offset(10.0, 0.0, layer)
        # factor = 1.0 - 1.2 = -0.2, offset = -10 * -0.2 = 2.0
        assert ox == pytest.approx(2.0)

    def test_zero_camera_zero_offset(self):
        for layer in CORRIDOR_LAYERS:
            ox, oy = parallax_offset(0.0, 0.0, layer)
            assert ox == 0.0
            assert oy == 0.0

    def test_corridor_layers_relative_order(self):
        """Backdrop drifts more than midground which drifts more than stage."""
        offsets = {}
        for layer in CORRIDOR_LAYERS:
            ox, _ = parallax_offset(10.0, 0.0, layer)
            offsets[layer.name] = abs(ox)
        assert offsets["backdrop"] > offsets["midground"]
        assert offsets["midground"] > offsets["stage"]


# -- Fog calculation -----------------------------------------------------------

class TestFogRange:

    def test_zero_density_no_fog(self):
        layer = ShadowboxLayer("clear", depth=10, parallax=0.5, fog_density=0.0, sort_order=0)
        near, far = layer_fog_range(layer)
        assert near > 9000  # effectively infinite

    def test_full_density_tight_fog(self):
        layer = ShadowboxLayer("thick", depth=50, parallax=0.1, fog_density=1.0, sort_order=0)
        near, far = layer_fog_range(layer)
        assert near == pytest.approx(15.0)
        assert far == pytest.approx(50.0)

    def test_medium_density_intermediate(self):
        layer = ShadowboxLayer("mid", depth=30, parallax=0.3, fog_density=0.5, sort_order=1)
        near, far = layer_fog_range(layer)
        assert 15.0 < near < 9000
        assert far > near

    def test_fog_range_decreases_with_density(self):
        """Higher density = fog starts closer."""
        low = ShadowboxLayer("low", depth=20, parallax=0.5, fog_density=0.2, sort_order=0)
        high = ShadowboxLayer("high", depth=20, parallax=0.5, fog_density=0.8, sort_order=0)
        low_near, _ = layer_fog_range(low)
        high_near, _ = layer_fog_range(high)
        assert high_near < low_near


# -- Register palettes ---------------------------------------------------------

class TestRegisters:

    def test_four_registers_exist(self):
        assert set(SHADOWBOX_REGISTERS.keys()) == {"survival", "tron", "tolkien", "sanrio"}

    def test_each_register_has_required_keys(self):
        required = {"fog", "ambient", "sun", "fill", "sconce",
                     "backdrop", "midground", "stage_wall", "stage_floor",
                     "bloom_intensity", "vignette_radius",
                     "depth_tint_far", "depth_tint_mid",
                     "warmth", "contrast", "saturation",
                     "shadow_lift", "highlight_compress", "flicker_intensity"}
        for name, reg in SHADOWBOX_REGISTERS.items():
            assert required.issubset(reg.keys()), f"{name} missing {required - reg.keys()}"

    def test_resolve_palette_survival(self):
        pal = resolve_palette("survival")
        assert pal["sconce"] == (1.0, 0.7, 0.35)

    def test_resolve_palette_unknown_defaults_to_survival(self):
        pal = resolve_palette("nonexistent")
        assert pal == SHADOWBOX_REGISTERS["survival"]

    def test_tron_bloom_higher_than_survival(self):
        """Tron register should glow harder."""
        assert SHADOWBOX_REGISTERS["tron"]["bloom_intensity"] > \
               SHADOWBOX_REGISTERS["survival"]["bloom_intensity"]

    def test_all_colors_are_rgb_tuples(self):
        color_keys = {"fog", "ambient", "sun", "fill", "sconce",
                       "backdrop", "midground", "stage_wall", "stage_floor"}
        for name, reg in SHADOWBOX_REGISTERS.items():
            for key in color_keys:
                val = reg[key]
                assert isinstance(val, tuple) and len(val) == 3, \
                    f"{name}.{key} = {val} is not an RGB tuple"


# -- Scene manager -------------------------------------------------------------

class TestShadowboxScene:

    def test_create_default(self):
        scene = ShadowboxScene()
        assert len(scene.layers) == 4
        assert scene.palette is not None

    def test_layers_sorted_back_to_front(self):
        scene = ShadowboxScene()
        depths = [l.depth for l in scene.layers]
        assert depths == sorted(depths, reverse=True)

    def test_move_camera(self):
        scene = ShadowboxScene()
        scene.move_camera(5.0, 3.0, 45.0)
        assert scene.camera_x == 5.0
        assert scene.camera_y == 3.0
        assert scene.camera_h == 45.0

    def test_get_layer_offsets(self):
        scene = ShadowboxScene()
        scene.move_camera(10.0, 0.0)
        offsets = scene.get_layer_offsets()
        assert "backdrop" in offsets
        assert "stage" in offsets
        # Backdrop should drift more than stage
        assert abs(offsets["backdrop"][0]) > abs(offsets["stage"][0])

    def test_set_register(self):
        scene = ShadowboxScene()
        scene.set_register("tron")
        assert scene.config.register == "tron"
        assert scene.palette["sconce"] == (0.2, 0.6, 1.0)

    def test_layer_by_name(self):
        scene = ShadowboxScene()
        stage = scene.layer_by_name("stage")
        assert stage is not None
        assert stage.use_nearest is True

    def test_layer_by_name_not_found(self):
        scene = ShadowboxScene()
        assert scene.layer_by_name("nonexistent") is None

    def test_get_fog_range_per_layer(self):
        scene = ShadowboxScene()
        backdrop = scene.layer_by_name("backdrop")
        near, far = scene.get_fog_range(backdrop)
        assert near < far

    def test_custom_config(self):
        config = ShadowboxConfig(
            camera=ShadowboxCamera(fov=28.0),
            register="tolkien",
        )
        scene = ShadowboxScene(config)
        assert scene.config.camera.fov == 28.0
        assert scene.palette["sconce"] == (1.0, 0.8, 0.5)
