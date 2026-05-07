"""
core/systems/shadowbox_scene.py

Multi-plane parallax renderer -- the Shadow Box.

Frustum partitioned into depth slices. Billboard stage-flats for 2D elements.
Narrow FOV (long focal length) flattens the scene, prevents pixel stretch.
Each layer is a render container at a specific depth with its own fog density.

Layer stack (back to front):
    0  BACKDROP   — infinite skybox, slow UV-scroll, parallax=0.1
    1  MIDGROUND  — distant silhouettes + atmospheric fog, parallax=0.3
    2  STAGE      — active environment, NEAREST filtering, parallax=0.7
    3  FOREGROUND — close debris, fast parallax=1.2

(Entity/player layers omitted — first-person POV, monk never rendered in-game.)

The artist's secret is warmth. Volumetric lighting through mist
achieves the Japanese shadow box aesthetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# -- Layer definitions ---------------------------------------------------------

@dataclass(frozen=True)
class ShadowboxLayer:
    """One depth slice in the shadow box."""
    name: str
    depth: float            # Y-position in world (distance from camera)
    parallax: float         # movement multiplier (0=static, 1=camera-locked)
    fog_density: float      # 0.0=clear, 1.0=fully fogged
    sort_order: int         # render bin order (lower=behind)
    use_nearest: bool = False  # pixel art filtering


# Default layer stack for dungeon corridors
CORRIDOR_LAYERS = [
    ShadowboxLayer("backdrop",   depth=50.0,  parallax=0.1, fog_density=0.9, sort_order=0),
    ShadowboxLayer("midground",  depth=30.0,  parallax=0.3, fog_density=0.6, sort_order=1),
    ShadowboxLayer("stage",      depth=10.0,  parallax=0.7, fog_density=0.2, sort_order=2, use_nearest=True),
    ShadowboxLayer("foreground", depth=-2.0,  parallax=1.2, fog_density=0.0, sort_order=3),
]


# -- Camera config -------------------------------------------------------------

@dataclass
class ShadowboxCamera:
    """FOV camera for shadowbox perspective."""
    fov: float = 65.0       # comfortable FPS FOV, still flatter than 90
    eye_z: float = 2.5      # eye height (meters)
    near: float = 0.5
    far: float = 200.0


# -- Scene config --------------------------------------------------------------

@dataclass
class ShadowboxConfig:
    """Full scene configuration."""
    camera: ShadowboxCamera = field(default_factory=ShadowboxCamera)
    layers: list[ShadowboxLayer] = field(default_factory=lambda: list(CORRIDOR_LAYERS))
    fog_color: tuple[float, float, float] = (0.04, 0.03, 0.03)
    ambient_color: tuple[float, float, float] = (0.03, 0.025, 0.03)
    register: str = "survival"

    @property
    def layers_back_to_front(self) -> list[ShadowboxLayer]:
        """Layers sorted for rendering (farthest first)."""
        return sorted(self.layers, key=lambda l: -l.depth)

    @property
    def layers_front_to_back(self) -> list[ShadowboxLayer]:
        """Layers sorted for alpha compositing."""
        return sorted(self.layers, key=lambda l: l.depth)


# -- Parallax calculator ------------------------------------------------------

def parallax_offset(camera_x: float, camera_y: float,
                    layer: ShadowboxLayer) -> tuple[float, float]:
    """
    Calculate lateral offset for a layer given camera position.

    Returns (offset_x, offset_y) to apply to the layer's root node.
    A parallax of 0 means static (backdrop). A parallax of 1.0 means
    the layer moves 1:1 with the camera (foreground). Values > 1.0
    create exaggerated foreground motion.

    The offset is the INVERSE of camera movement scaled by parallax,
    because layers closer to camera should appear to move faster in
    the opposite direction of camera motion.
    """
    # Parallax 1.0 = moves with camera (no relative motion)
    # Parallax 0.0 = stays fixed (maximum relative motion)
    # We want layers with low parallax to drift slowly opposite camera
    factor = 1.0 - layer.parallax
    return (-camera_x * factor, -camera_y * factor)


def layer_fog_range(layer: ShadowboxLayer,
                    base_near: float = 15.0,
                    base_far: float = 50.0) -> tuple[float, float]:
    """
    Calculate fog range for a layer based on its fog_density.

    Higher fog_density = fog starts closer (more obscured).
    Zero density = no fog (range pushed to infinity).
    """
    if layer.fog_density <= 0.0:
        return (9999.0, 10000.0)  # effectively no fog

    # Scale fog near/far inversely with density
    # High density = tight fog, low density = distant fog
    inv = 1.0 - layer.fog_density
    near = base_near + inv * base_far
    far = base_far + inv * base_far * 2
    return (near, far)


# -- Register palettes for shadowbox ------------------------------------------

SHADOWBOX_REGISTERS = {
    "survival": {
        "fog":        (0.04, 0.03, 0.03),
        "ambient":    (0.05, 0.04, 0.06),
        "sun":        (1.3, 0.85, 0.55),
        "fill":       (0.06, 0.12, 0.20),
        "sconce":     (1.0, 0.7, 0.35),
        "backdrop":   (0.03, 0.02, 0.02),
        "midground":  (0.06, 0.05, 0.04),
        "stage_wall": (0.10, 0.08, 0.07),
        "stage_floor":(0.08, 0.06, 0.05),
        "bloom_intensity": 0.3,
        "vignette_radius": 0.85,
        # Depth color shift — far layers desaturate + blue-shift
        "depth_tint_far":  (0.70, 0.75, 0.90),
        "depth_tint_mid":  (0.85, 0.87, 0.92),
        # Color grading
        "warmth":             0.08,
        "contrast":           1.12,
        "saturation":         0.88,
        # Film curves
        "shadow_lift":        0.015,
        "highlight_compress": 0.92,
        # Torch flicker amplitude
        "flicker_intensity":  0.15,
        "weathering":         0.7,
    },
    "tron": {
        "fog":        (0.0, 0.02, 0.04),
        "ambient":    (0.01, 0.03, 0.06),
        "sun":        (0.2, 0.5, 0.8),
        "fill":       (0.0, 0.08, 0.18),
        "sconce":     (0.2, 0.6, 1.0),
        "backdrop":   (0.0, 0.0, 0.02),
        "midground":  (0.01, 0.03, 0.06),
        "stage_wall": (0.03, 0.03, 0.06),
        "stage_floor":(0.02, 0.02, 0.04),
        "bloom_intensity": 0.6,
        "vignette_radius": 0.75,
        "depth_tint_far":  (0.60, 0.70, 1.00),
        "depth_tint_mid":  (0.75, 0.82, 0.95),
        "warmth":            -0.10,
        "contrast":           1.20,
        "saturation":         1.10,
        "shadow_lift":        0.005,
        "highlight_compress": 0.88,
        "flicker_intensity":  0.05,
        "weathering":         0.3,
    },
    "tolkien": {
        "fog":        (0.05, 0.04, 0.03),
        "ambient":    (0.08, 0.06, 0.04),
        "sun":        (1.2, 0.85, 0.55),
        "fill":       (0.06, 0.05, 0.03),
        "sconce":     (1.0, 0.8, 0.5),
        "backdrop":   (0.04, 0.03, 0.02),
        "midground":  (0.08, 0.06, 0.04),
        "stage_wall": (0.15, 0.12, 0.08),
        "stage_floor":(0.12, 0.09, 0.06),
        "bloom_intensity": 0.25,
        "vignette_radius": 0.9,
        "depth_tint_far":  (0.75, 0.72, 0.82),
        "depth_tint_mid":  (0.88, 0.85, 0.90),
        "warmth":             0.12,
        "contrast":           1.08,
        "saturation":         0.92,
        "shadow_lift":        0.020,
        "highlight_compress": 0.94,
        "flicker_intensity":  0.18,
        "weathering":         0.8,
    },
    "sanrio": {
        "fog":        (0.40, 0.32, 0.38),
        "ambient":    (0.25, 0.20, 0.28),
        "sun":        (1.0, 0.85, 0.90),
        "fill":       (0.30, 0.25, 0.35),
        "sconce":     (1.0, 0.85, 0.95),
        "backdrop":   (0.30, 0.24, 0.28),
        "midground":  (0.45, 0.38, 0.42),
        "stage_wall": (0.55, 0.48, 0.52),
        "stage_floor":(0.50, 0.42, 0.48),
        "bloom_intensity": 0.5,
        "vignette_radius": 0.95,
        "depth_tint_far":  (0.90, 0.85, 0.95),
        "depth_tint_mid":  (0.95, 0.92, 0.97),
        "warmth":             0.06,
        "contrast":           0.95,
        "saturation":         0.85,
        "shadow_lift":        0.040,
        "highlight_compress": 0.96,
        "flicker_intensity":  0.08,
        "weathering":         0.4,
    },
}


def resolve_palette(register: str) -> dict:
    """Get the shadowbox palette for a register, defaulting to survival."""
    return SHADOWBOX_REGISTERS.get(register, SHADOWBOX_REGISTERS["survival"])


# -- Scene manager (pure logic, no Panda3D dependency) -------------------------

class ShadowboxScene:
    """
    Manages the shadow box layer stack.

    Pure logic layer -- no rendering. Tracks camera state, calculates
    parallax offsets, resolves palettes. The app (shadowbox_dungeon.py)
    reads from this to drive the Panda3D scene graph.
    """

    def __init__(self, config: ShadowboxConfig | None = None):
        self.config = config or ShadowboxConfig()
        self.camera_x = 0.0
        self.camera_y = 0.0
        self.camera_h = 0.0  # heading in degrees
        self._palette = resolve_palette(self.config.register)

    @property
    def palette(self) -> dict:
        return self._palette

    @property
    def layers(self) -> list[ShadowboxLayer]:
        return self.config.layers_back_to_front

    def set_register(self, register: str):
        """Switch visual register."""
        self.config.register = register
        self._palette = resolve_palette(register)

    def move_camera(self, x: float, y: float, heading: float = 0.0):
        """Update camera position."""
        self.camera_x = x
        self.camera_y = y
        self.camera_h = heading

    def get_layer_offset(self, layer: ShadowboxLayer) -> tuple[float, float]:
        """Get parallax offset for a layer at current camera position."""
        return parallax_offset(self.camera_x, self.camera_y, layer)

    def get_layer_offsets(self) -> dict[str, tuple[float, float]]:
        """Get all layer offsets as {name: (ox, oy)}."""
        return {
            layer.name: self.get_layer_offset(layer)
            for layer in self.config.layers
        }

    def get_fog_range(self, layer: ShadowboxLayer) -> tuple[float, float]:
        """Get fog range for a specific layer."""
        return layer_fog_range(layer)

    def layer_by_name(self, name: str) -> ShadowboxLayer | None:
        """Find a layer by name."""
        for layer in self.config.layers:
            if layer.name == name:
                return layer
        return None
