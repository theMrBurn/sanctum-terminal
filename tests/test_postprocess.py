"""
tests/test_postprocess.py

FBO-based post-processing pipeline.
Pure logic tests -- no display, no shaders.
"""

import pytest

from core.systems.postprocess import (
    BloomConfig,
    VignetteConfig,
    ColorGradeConfig,
    PostProcessConfig,
    PostProcessPipeline,
    COMPOSITE_FRAG,
    BRIGHT_PASS_FRAG,
    BLUR_FRAG,
    FULLSCREEN_VERT,
)


# -- Config dataclasses --------------------------------------------------------

class TestBloomConfig:

    def test_defaults(self):
        b = BloomConfig()
        assert b.threshold == 0.7
        assert b.intensity == 0.3
        assert b.blur_radius == 4
        assert b.enabled is True

    def test_custom(self):
        b = BloomConfig(threshold=0.5, intensity=0.6)
        assert b.threshold == 0.5
        assert b.intensity == 0.6


class TestVignetteConfig:

    def test_defaults(self):
        v = VignetteConfig()
        assert v.radius == 0.85
        assert v.softness == 0.4
        assert v.color == (0.0, 0.0, 0.0)
        assert v.enabled is True

    def test_custom_color(self):
        v = VignetteConfig(color=(0.1, 0.0, 0.0))
        assert v.color == (0.1, 0.0, 0.0)


class TestColorGradeConfig:

    def test_enabled_by_default(self):
        c = ColorGradeConfig()
        assert c.enabled is True

    def test_default_values(self):
        c = ColorGradeConfig()
        assert c.contrast == 1.1
        assert c.saturation == 0.9
        assert c.shadow_lift == 0.015
        assert c.highlight_compress == 0.92


class TestPostProcessConfig:

    def test_any_enabled_when_bloom_on(self):
        config = PostProcessConfig()
        assert config.any_enabled is True

    def test_not_enabled_when_all_off(self):
        config = PostProcessConfig(
            bloom=BloomConfig(enabled=False),
            vignette=VignetteConfig(enabled=False),
            color_grade=ColorGradeConfig(enabled=False),
        )
        assert config.any_enabled is False


# -- Pipeline ------------------------------------------------------------------

class TestPostProcessPipeline:

    def test_create_default(self):
        pipe = PostProcessPipeline()
        assert pipe.config.bloom.enabled is True

    def test_composite_uniforms(self):
        pipe = PostProcessPipeline()
        u = pipe.get_composite_uniforms()
        assert "bloom_intensity" in u
        assert "vignette_radius" in u
        assert "vignette_enabled" in u
        assert "shadow_lift" in u
        assert "highlight_compress" in u
        assert u["bloom_intensity"] == 0.3
        assert u["bloom_enabled"] == 1.0  # float, not bool

    def test_bright_pass_uniforms(self):
        pipe = PostProcessPipeline()
        u = pipe.get_bright_pass_uniforms()
        assert u["threshold"] == 0.7

    def test_blur_uniforms_horizontal(self):
        pipe = PostProcessPipeline()
        u = pipe.get_blur_uniforms(1280, 720, horizontal=True)
        assert u["blur_direction"][0] == pytest.approx(1.0 / 1280)
        assert u["blur_direction"][1] == 0.0
        assert u["blur_radius"] == 4

    def test_blur_uniforms_vertical(self):
        pipe = PostProcessPipeline()
        u = pipe.get_blur_uniforms(1280, 720, horizontal=False)
        assert u["blur_direction"][0] == 0.0
        assert u["blur_direction"][1] == pytest.approx(1.0 / 720)

    def test_apply_register(self):
        pipe = PostProcessPipeline()
        pipe.apply_register({
            "bloom_intensity": 0.6,
            "vignette_radius": 0.75,
            "warmth": -0.1,
            "contrast": 1.2,
            "saturation": 1.1,
            "shadow_lift": 0.005,
            "highlight_compress": 0.88,
        })
        assert pipe.config.bloom.intensity == 0.6
        assert pipe.config.vignette.radius == 0.75
        assert pipe.config.color_grade.warmth == -0.1
        assert pipe.config.color_grade.shadow_lift == 0.005


# -- Shader source exists -----------------------------------------------------

class TestShaderSource:

    def test_composite_frag_has_main(self):
        assert "void main()" in COMPOSITE_FRAG

    def test_bright_pass_has_threshold(self):
        assert "threshold" in BRIGHT_PASS_FRAG

    def test_blur_has_direction(self):
        assert "blur_direction" in BLUR_FRAG

    def test_vertex_shader_has_texcoord(self):
        assert "texcoord" in FULLSCREEN_VERT

    def test_composite_has_bloom(self):
        assert "bloom_intensity" in COMPOSITE_FRAG

    def test_composite_has_vignette(self):
        assert "vignette_radius" in COMPOSITE_FRAG

    def test_composite_has_film_curves(self):
        assert "shadow_lift" in COMPOSITE_FRAG
        assert "highlight_compress" in COMPOSITE_FRAG

    def test_all_shaders_version_120(self):
        for shader in [COMPOSITE_FRAG, BRIGHT_PASS_FRAG, BLUR_FRAG, FULLSCREEN_VERT]:
            assert "#version 120" in shader
