"""
core/systems/postprocess.py

FBO-based post-processing pipeline.

Bloom + vignette + color grading. All screen-space passes.
Uses Panda3D's FilterManager for offscreen buffer management.

The pipeline:
    1. Scene renders to FBO (color + depth)
    2. Bright-pass extraction (bloom threshold)
    3. Gaussian blur (horizontal + vertical)
    4. Composite: scene + bloom + vignette + LUT

Shader code is embedded as string constants -- no external .sha files.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# -- Configuration -------------------------------------------------------------

@dataclass
class BloomConfig:
    """Bloom effect parameters."""
    threshold: float = 0.7     # luminance cutoff for bright pass
    intensity: float = 0.3     # bloom overlay strength
    blur_radius: int = 4       # blur kernel half-size
    enabled: bool = True


@dataclass
class VignetteConfig:
    """Vignette (dark corners) parameters."""
    radius: float = 0.85       # 0=full screen dark, 1=no vignette
    softness: float = 0.4      # edge falloff width
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    enabled: bool = True


@dataclass
class ColorGradeConfig:
    """Color grading + film curves."""
    warmth: float = 0.08       # shift toward warm (positive) or cool (negative)
    contrast: float = 1.1      # 1.0 = neutral
    saturation: float = 0.9    # 1.0 = neutral
    shadow_lift: float = 0.015 # lift dark areas (film stock never hits true black)
    highlight_compress: float = 0.92  # compress bright areas (soft highlight rolloff)
    enabled: bool = True


@dataclass
class PostProcessConfig:
    """Full post-processing pipeline config."""
    bloom: BloomConfig = field(default_factory=BloomConfig)
    vignette: VignetteConfig = field(default_factory=VignetteConfig)
    color_grade: ColorGradeConfig = field(default_factory=ColorGradeConfig)

    @property
    def any_enabled(self) -> bool:
        return self.bloom.enabled or self.vignette.enabled or self.color_grade.enabled


# -- Shader source (GLSL 1.20 — macOS Metal/GL 2.1) --------------------------

# Fragment shader for final composite pass
COMPOSITE_FRAG = """
#version 120

uniform sampler2D scene_tex;
uniform sampler2D bloom_tex;

uniform float bloom_intensity;
uniform float bloom_enabled;
uniform float vignette_radius;
uniform float vignette_softness;
uniform vec3 vignette_color;
uniform float vignette_enabled;
uniform float warmth;
uniform float contrast;
uniform float saturation;
uniform float shadow_lift;
uniform float highlight_compress;

varying vec2 texcoord;

void main() {
    vec4 scene = texture2D(scene_tex, texcoord);
    vec3 color = scene.rgb;

    // Bloom composite
    if (bloom_enabled > 0.5) {
        vec3 bloom = texture2D(bloom_tex, texcoord).rgb;
        color += bloom * bloom_intensity;
    }

    // Film curves — lift shadows, compress highlights
    // Shadow lift: dark areas never reach true black (film stock behavior)
    color = color + shadow_lift * (1.0 - color);
    // Highlight compression: bright areas roll off gently
    color = 1.0 - (1.0 - color) * (1.0 + (1.0 - highlight_compress) * color);

    // Warmth shift (warm = orange push, cool = blue push)
    color.r += warmth * 0.1;
    color.b -= warmth * 0.05;

    // Contrast (pivot around mid-gray)
    color = (color - 0.5) * contrast + 0.5;

    // Saturation
    float lum = dot(color, vec3(0.299, 0.587, 0.114));
    color = mix(vec3(lum), color, saturation);

    // Vignette (last — darkens edges after all grading)
    if (vignette_enabled > 0.5) {
        vec2 uv = texcoord * 2.0 - 1.0;
        float dist = length(uv);
        float vig = smoothstep(vignette_radius, vignette_radius - vignette_softness, dist);
        color = mix(vignette_color, color, vig);
    }

    gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
}
"""

# Bright pass extraction
BRIGHT_PASS_FRAG = """
#version 120

uniform sampler2D input_tex;
uniform float threshold;

varying vec2 texcoord;

void main() {
    vec4 color = texture2D(input_tex, texcoord);
    float lum = dot(color.rgb, vec3(0.299, 0.587, 0.114));
    float brightness = max(0.0, lum - threshold);
    gl_FragColor = vec4(color.rgb * brightness, 1.0);
}
"""

# Gaussian blur (single axis, called twice: H then V)
BLUR_FRAG = """
#version 120

uniform sampler2D input_tex;
uniform vec2 blur_direction;

varying vec2 texcoord;

void main() {
    vec4 result = vec4(0.0);
    float total_weight = 0.0;

    for (int i = -4; i <= 4; i++) {
        float fi = float(i);
        float weight = exp(-0.5 * fi * fi / 4.0);
        vec2 offset = blur_direction * fi;
        result += texture2D(input_tex, texcoord + offset) * weight;
        total_weight += weight;
    }

    gl_FragColor = result / total_weight;
}
"""

# Vertex shader (shared by all passes)
FULLSCREEN_VERT = """
#version 120

uniform mat4 p3d_ModelViewProjectionMatrix;

attribute vec4 p3d_Vertex;
attribute vec2 p3d_MultiTexCoord0;

varying vec2 texcoord;

void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    texcoord = p3d_MultiTexCoord0;
}
"""


# -- Pipeline manager (pure logic) --------------------------------------------

class PostProcessPipeline:
    """
    Manages post-processing state and shader uniforms.

    Pure logic -- the Panda3D wiring happens in the app.
    This class tracks config and provides uniform values for shaders.
    """

    def __init__(self, config: PostProcessConfig | None = None):
        self.config = config or PostProcessConfig()

    def get_composite_uniforms(self) -> dict[str, object]:
        """Return all uniform values for the composite shader."""
        c = self.config
        return {
            "bloom_intensity": c.bloom.intensity,
            "bloom_enabled": 1.0 if c.bloom.enabled else 0.0,
            "vignette_radius": c.vignette.radius,
            "vignette_softness": c.vignette.softness,
            "vignette_color": c.vignette.color,
            "vignette_enabled": 1.0 if c.vignette.enabled else 0.0,
            "warmth": c.color_grade.warmth,
            "contrast": c.color_grade.contrast,
            "saturation": c.color_grade.saturation,
            "shadow_lift": c.color_grade.shadow_lift,
            "highlight_compress": c.color_grade.highlight_compress,
        }

    def get_bright_pass_uniforms(self) -> dict[str, object]:
        """Return uniforms for bright pass extraction."""
        return {"threshold": self.config.bloom.threshold}

    def get_blur_uniforms(self, width: int, height: int,
                          horizontal: bool) -> dict[str, object]:
        """Return uniforms for a blur pass."""
        if horizontal:
            direction = (1.0 / width, 0.0)
        else:
            direction = (0.0, 1.0 / height)
        return {
            "blur_direction": direction,
            "blur_radius": self.config.bloom.blur_radius,
        }

    def apply_register(self, register_params: dict):
        """Apply register-specific post-process tuning from palette dict."""
        self.config.bloom.intensity = register_params.get("bloom_intensity", 0.3)
        self.config.vignette.radius = register_params.get("vignette_radius", 0.85)
        self.config.color_grade.warmth = register_params.get("warmth", 0.08)
        self.config.color_grade.contrast = register_params.get("contrast", 1.1)
        self.config.color_grade.saturation = register_params.get("saturation", 0.9)
        self.config.color_grade.shadow_lift = register_params.get("shadow_lift", 0.015)
        self.config.color_grade.highlight_compress = register_params.get("highlight_compress", 0.92)
