"""Horizon objects — distance-only banner-rendered concepts.

Per `design_banner_layer_taxonomy` (2026-05-02): kinds without world
entity counterparts. Render purely on the banner cylinders at fixed
angular positions. Authored per-biome in `BIOME_REGISTRY[biome]
["horizon_objects"]`; brain ships in manifest; this module routes
each entry to the right renderer function.

Adding a new horizon concept = config row + renderer function. No
engine changes. Renderers are camera-anchored — translate with the
player so the moon stays in the same direction as you walk.

V1 renderers:
    moon            — small bright disc at azimuth/elevation
    mountain_ridge  — series of triangular silhouettes along bottom band
    stars           — scattered points across the upper cylinder

The cylinder distance for these objects is the OUTERMOST banner
layer (typically 49m). Brain ships banner_layers in same manifest,
we look up the outermost radius per call.
"""
from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any

import pyray as rl

from core.systems.wireframe_mesh import (
    WireframeMesh,
    get_builtin as get_builtin_mesh,
    load_obj,
)
from clients.vector_terminal.wireframe_renderer import draw_wireframe


def draw_horizon_objects(manifest: dict, camera, now: float = 0.0) -> None:
    """Render all horizon objects in the manifest. Call AFTER the
    banner cylinder is drawn (so objects sit visually on it) and
    BEFORE entity rendering (so world entities can occlude them
    when close).

    `now` is monotonic seconds — chrono-driven kinds (aurora drift,
    lightning flash, sun rise) read it. Static kinds (moon, mountain
    ridge, stars) ignore it.
    """
    objects: list[dict] = manifest.get("horizon_objects") or []
    if not objects:
        return

    radius = _outermost_layer_radius(manifest)
    if radius <= 0.0:
        return

    cam_x = camera.position.x
    cam_z = camera.position.z

    for obj in objects:
        kind = str(obj.get("kind", ""))
        renderer = _RENDERERS.get(kind)
        if renderer is None:
            continue
        renderer(obj, cam_x, cam_z, radius, now)


def _outermost_layer_radius(manifest: dict) -> float:
    """Find the outermost banner layer's distance from manifest."""
    layers: list[dict] = manifest.get("banner_layers") or []
    if not layers:
        return 0.0
    return max(float(L.get("distance", 0.0)) for L in layers)


# ── Per-kind renderers ────────────────────────────────────────────


def _draw_moon(
    obj: dict,
    cam_x: float,
    cam_z: float,
    radius: float,
    now: float,
) -> None:
    """Bright disc at the configured azimuth/elevation on the cylinder."""
    azimuth = math.radians(float(obj.get("azimuth", 0.0)))
    elevation = math.radians(float(obj.get("elevation", 30.0)))
    size = float(obj.get("size", 1.0))
    color = _color(obj.get("color", [0.9, 0.9, 0.9]))

    # Position on cylinder surface at given azimuth + elevation.
    # azimuth = 0° points +x (east); +90° points -z (north in raylib).
    # Raylib uses +y = up.
    horiz_radius = radius * math.cos(elevation)
    height = radius * math.sin(elevation)
    px = cam_x + horiz_radius * math.cos(azimuth)
    pz = cam_z - horiz_radius * math.sin(azimuth)  # raylib z is -north

    rl.draw_sphere(rl.Vector3(px, height, pz), size, color)


def _draw_sun(
    obj: dict,
    cam_x: float,
    cam_z: float,
    radius: float,
    now: float,
) -> None:
    """Warm-colored sphere on the cylinder. Optional `drift_hz` arg
    moves it across the sky over time (rises east, sets west). Default
    drift_hz=0 = static placement.

    Future: bind drift_hz to manifest's chrono state so the sun arc
    matches actual time-of-day. For now, drift is just visual demo.
    """
    base_azimuth = math.radians(float(obj.get("azimuth", 90.0)))
    elevation = math.radians(float(obj.get("elevation", 45.0)))
    size = float(obj.get("size", 3.0))
    color = _color(obj.get("color", [1.0, 0.85, 0.55]))
    drift_hz = float(obj.get("drift_hz", 0.0))

    azimuth = base_azimuth + 2.0 * math.pi * drift_hz * now

    horiz = radius * math.cos(elevation)
    height = radius * math.sin(elevation)
    px = cam_x + horiz * math.cos(azimuth)
    pz = cam_z - horiz * math.sin(azimuth)

    rl.draw_sphere(rl.Vector3(px, height, pz), size, color)


def _draw_aurora(
    obj: dict,
    cam_x: float,
    cam_z: float,
    radius: float,
    now: float,
) -> None:
    """Drifting color band across the upper cylinder. Hue cycles per
    angular position with a time-driven phase shift, giving the band
    a slow rolling shimmer.
    """
    azimuth_center = math.radians(float(obj.get("azimuth", 0.0)))
    spread = math.radians(float(obj.get("spread", 220.0)))
    elevation = math.radians(float(obj.get("elevation", 65.0)))
    point_count = int(obj.get("point_count", 28))
    drift_hz = float(obj.get("drift_hz", 0.05))
    base_color = obj.get("color", [0.18, 0.85, 0.55])
    size = float(obj.get("size", 0.5))

    if point_count <= 0 or spread <= 0:
        return

    horiz = radius * math.cos(elevation)
    height = radius * math.sin(elevation)
    half_spread = spread / 2.0
    drift_phase = 2.0 * math.pi * drift_hz * now

    for i in range(point_count):
        t = i / max(1, point_count - 1)
        angle = azimuth_center - half_spread + t * spread
        hue_phase = t * 2.0 * math.pi + drift_phase
        # Cycle channels around base_color with the phase so colors
        # roll across the band over time.
        r = base_color[0] + 0.35 * math.sin(hue_phase)
        g = base_color[1] + 0.30 * math.sin(hue_phase + 2.0)
        b = base_color[2] + 0.40 * math.sin(hue_phase + 4.0)
        c = _color([r, g, b])
        px = cam_x + horiz * math.cos(angle)
        pz = cam_z - horiz * math.sin(angle)
        rl.draw_sphere(rl.Vector3(px, height, pz), size, c)


def _draw_lightning_flash(
    obj: dict,
    cam_x: float,
    cam_z: float,
    radius: float,
    now: float,
) -> None:
    """Periodic bright pulse at fixed azimuth. Brightness ramps from 1
    to 0 over `flash_duration` seconds within each `flash_hz` cycle.
    Outside the flash window the renderer no-ops.
    """
    azimuth = math.radians(float(obj.get("azimuth", 60.0)))
    elevation = math.radians(float(obj.get("elevation", 50.0)))
    size = float(obj.get("size", 5.0))
    color_base = obj.get("color", [0.85, 0.92, 1.0])
    # Default ~7s between flashes (factor of 7).
    flash_hz = float(obj.get("flash_hz", 1.0 / 7.0))
    flash_duration = float(obj.get("flash_duration", 0.25))

    if flash_hz <= 0 or flash_duration <= 0:
        return

    cycle_position = (now * flash_hz) % 1.0
    flash_window = flash_duration * flash_hz  # fraction of cycle
    if cycle_position > flash_window:
        return  # quiet between flashes

    # Brightness ramps 1 → 0 across the flash window.
    intensity = 1.0 - (cycle_position / flash_window)

    horiz = radius * math.cos(elevation)
    height = radius * math.sin(elevation)
    px = cam_x + horiz * math.cos(azimuth)
    pz = cam_z - horiz * math.sin(azimuth)

    # Size pulses with brightness — short bright stab.
    pulse_size = size * (0.4 + 0.6 * intensity)
    color = _color(color_base, intensity)
    rl.draw_sphere(rl.Vector3(px, height, pz), pulse_size, color)


def _draw_mountain_ridge(
    obj: dict,
    cam_x: float,
    cam_z: float,
    radius: float,
    now: float,
) -> None:
    """Series of triangular silhouettes along the bottom band of the
    cylinder. Determinstic per `seed` so the ridge is stable."""
    azimuth_center = math.radians(float(obj.get("azimuth", 180.0)))
    spread = math.radians(float(obj.get("spread", 180.0)))
    count = int(obj.get("ridge_count", 12))
    max_h = float(obj.get("max_height", 15.0))
    min_h = float(obj.get("min_height", 5.0))
    color = _color(obj.get("color", [0.2, 0.2, 0.2]))
    seed = int(obj.get("seed", 0))

    if count <= 0 or spread <= 0:
        return

    rng = random.Random(seed)

    # Place peaks across the spread, each with a randomized height.
    half_spread = spread / 2.0
    peak_positions = []
    for i in range(count):
        # Even-spaced base position with small jitter.
        t = i / max(1, count - 1)  # 0..1
        angle = azimuth_center - half_spread + t * spread
        height = min_h + rng.random() * (max_h - min_h)
        peak_positions.append((angle, height))

    # Draw triangles between each adjacent pair, base at y=0, peaks at the
    # configured heights, projected onto the cylinder.
    def _peak_world_pos(angle: float, height: float):
        px = cam_x + radius * math.cos(angle)
        pz = cam_z - radius * math.sin(angle)
        return rl.Vector3(px, height, pz)

    for i in range(len(peak_positions) - 1):
        a_angle, a_h = peak_positions[i]
        b_angle, b_h = peak_positions[i + 1]
        a_top = _peak_world_pos(a_angle, a_h)
        b_top = _peak_world_pos(b_angle, b_h)
        a_base = _peak_world_pos(a_angle, 0.0)
        b_base = _peak_world_pos(b_angle, 0.0)
        # Triangle 1: a_base, a_top, b_top
        # Triangle 2: a_base, b_top, b_base
        # raylib's draw_triangle takes 2D screen coords — we want 3D so
        # use draw_line_3d for the silhouette outline (wireframe style).
        rl.draw_line_3d(a_base, a_top, color)
        rl.draw_line_3d(a_top, b_top, color)
        rl.draw_line_3d(b_top, b_base, color)


def _draw_stars(
    obj: dict,
    cam_x: float,
    cam_z: float,
    radius: float,
    now: float,
) -> None:
    """Scattered points across the upper cylinder. Deterministic."""
    count = int(obj.get("count", 49))
    min_el = math.radians(float(obj.get("min_elevation", 20.0)))
    max_el = math.radians(float(obj.get("max_elevation", 75.0)))
    size = float(obj.get("size", 0.5))
    color = _color(obj.get("color", [0.9, 0.9, 0.9]))
    seed = int(obj.get("seed", 0))

    if count <= 0:
        return

    rng = random.Random(seed)
    for _ in range(count):
        azimuth = rng.uniform(0.0, 2.0 * math.pi)
        elevation = rng.uniform(min_el, max_el)
        horiz_radius = radius * math.cos(elevation)
        height = radius * math.sin(elevation)
        px = cam_x + horiz_radius * math.cos(azimuth)
        pz = cam_z - horiz_radius * math.sin(azimuth)
        rl.draw_sphere(rl.Vector3(px, height, pz), size, color)


def _draw_wireframe_mesh(
    obj: dict,
    cam_x: float,
    cam_z: float,
    radius: float,
    now: float,
) -> None:
    """Render an arbitrary wireframe mesh on the cylinder. The mesh is
    sourced from either a built-in primitive (`mesh: "cube"`) or an
    OBJ file (`obj_path: "path/to/mesh.obj"` relative to repo root).

    Loaded OBJ meshes are cached (module-global) so the file isn't
    re-parsed each frame.

    Optional `spin_hz` rotates the mesh around its vertical axis over
    time — V1 only supports this conceptually; actual rotation
    requires a matrix transform of the vertices, deferred to V1.1.
    For now, mesh is rendered static at its world position.
    """
    mesh = _resolve_mesh(obj)
    if mesh is None:
        return

    azimuth = math.radians(float(obj.get("azimuth", 0.0)))
    elevation = math.radians(float(obj.get("elevation", 30.0)))
    scale = float(obj.get("size", 1.0))
    color = _color(obj.get("color", [0.7, 0.7, 0.7]))

    # Position on cylinder surface.
    horiz = radius * math.cos(elevation)
    height = radius * math.sin(elevation)
    px = cam_x + horiz * math.cos(azimuth)
    pz = cam_z - horiz * math.sin(azimuth)

    draw_wireframe(mesh, (px, height, pz), scale, color)


# Module-global OBJ cache so we don't re-parse a file every frame.
_OBJ_CACHE: dict[str, WireframeMesh] = {}


def _resolve_mesh(obj: dict) -> WireframeMesh | None:
    """Pick the right WireframeMesh from the object's config.
    Priority: built-in `mesh` name first, then `obj_path` file."""
    builtin_name = obj.get("mesh")
    if builtin_name is not None:
        return get_builtin_mesh(str(builtin_name))

    obj_path = obj.get("obj_path")
    if obj_path is not None:
        path_str = str(obj_path)
        cached = _OBJ_CACHE.get(path_str)
        if cached is not None:
            return cached
        try:
            # Repo-root-relative path resolution.
            full_path = Path(__file__).resolve().parents[2] / path_str
            mesh = load_obj(full_path)
        except (FileNotFoundError, ValueError):
            return None
        _OBJ_CACHE[path_str] = mesh
        return mesh

    return None


def _color(rgb: Any, alpha: float = 1.0) -> tuple[int, int, int, int]:
    """Convert RGB 0-1 list to raylib RGBA bytes. Defensive on shape."""
    if not isinstance(rgb, (list, tuple)) or len(rgb) < 3:
        rgb = (0.5, 0.5, 0.5)

    def _byte(v: float) -> int:
        return max(0, min(255, int(round(float(v) * 255))))

    return (_byte(rgb[0]), _byte(rgb[1]), _byte(rgb[2]), _byte(alpha))


_RENDERERS: dict[str, Any] = {
    "moon": _draw_moon,
    "sun": _draw_sun,
    "aurora": _draw_aurora,
    "lightning_flash": _draw_lightning_flash,
    "mountain_ridge": _draw_mountain_ridge,
    "stars": _draw_stars,
    "wireframe_mesh": _draw_wireframe_mesh,
}
