"""Thing renderer — expand a Thing into N manifest entities.

Pure math; no I/O. Given a Thing schema + world origin + world yaw,
emits one entity dict per part with correct world coordinates and
sizes derived from the bounding-box math:

    world_pos = thing_origin + rotated(rel_position * real_size_m, world_yaw)
    world_size = rel_size * real_size_m

Default color cascade per part:
  1. part.color_base / color_shadow / color_accent  (explicit)
  2. amber fallback (cfg.AMBER_RGB equivalent — keeps rendering even
     when the LLM author didn't specify a palette)

Each emitted entity uses `scan_<primitive>_<thing>_<part_idx>` as its
kind name so vector_terminal's `recipes.py` scan_ prefix routing
picks the right wireframe atom.
"""
from __future__ import annotations

import math
from typing import Any

from core.systems.thing_schema import Thing, ThingPart


# Amber fallback when a part has no explicit color
_DEFAULT_COLOR = (0.85, 0.66, 0.20)
_DEFAULT_SHADOW = (0.20, 0.16, 0.08)
_DEFAULT_ACCENT = (1.00, 0.85, 0.40)


def expand_thing(
    thing: Thing,
    origin: tuple[float, float, float],
    yaw_deg: float = 0.0,
    *,
    id_base: int = 0,
    instance_id: int = 0,
) -> list[dict[str, Any]]:
    """Convert one Thing + world placement → list of manifest entities.

    `origin` is the thing's CENTER in brain coords (x=lateral, y=forward,
    z=up). `yaw_deg` rotates the composition around the up axis (z).
    `id_base` + `instance_id` produce unique entity IDs:
        id = id_base + instance_id * 100 + part_idx
    Caller chooses ranges that don't collide with other entity sources.
    """
    entities: list[dict[str, Any]] = []
    cos_y = math.cos(math.radians(yaw_deg))
    sin_y = math.sin(math.radians(yaw_deg))

    # Thing-level collision footprint: cylindrical radius = half of
    # the larger horizontal dimension of the bounding box. Stamped on
    # the anchor part so the vector terminal's resolve_collisions sees
    # one collision shape per thing, not per subpart.
    collision_r = max(thing.real_size_m[0], thing.real_size_m[1]) / 2.0

    for part_idx, part in enumerate(thing.parts):
        # Local offset in meters
        lx = part.rel_position[0] * thing.real_size_m[0]
        ly = part.rel_position[1] * thing.real_size_m[1]
        lz = part.rel_position[2] * thing.real_size_m[2]

        # Yaw around z-axis (up)
        wx = origin[0] + (lx * cos_y - ly * sin_y)
        wy = origin[1] + (lx * sin_y + ly * cos_y)
        wz = origin[2] + lz

        # Size in meters
        sx = part.rel_size[0] * thing.real_size_m[0]
        sy = part.rel_size[1] * thing.real_size_m[1]
        sz = part.rel_size[2] * thing.real_size_m[2]

        # Color — base wins if specified; else amber default.
        r, g, b = part.color_base or _DEFAULT_COLOR

        entity: dict[str, Any] = {
            "id":         id_base + instance_id * 100 + part_idx,
            "kind":       f"scan_{part.primitive}_{thing.name}_{part_idx:02d}",
            "x":          round(wx, 3),
            "y":          round(wy, 3),
            "z":          round(wz, 3),
            "sx":         round(sx, 3),
            "sy":         round(sy, 3),
            "sz":         round(sz, 3),
            "r":          round(r, 3),
            "g":          round(g, 3),
            "b":          round(b, 3),
            "heading":    round((yaw_deg + part.rotation_deg) % 360.0, 1),
            # Provenance hints, ignored by renderer but useful for inspection
            "_thing":     thing.name,
            "_role":      part.role,
            "_tier":      part.tier,
            "_negate":    part.negate,
        }
        # Anchor part carries the thing's collision footprint. Other
        # parts have no collision_radius and the client treats them
        # as walk-through decoration.
        if part.role == thing.anchor:
            entity["collision_radius"] = round(collision_r, 3)
        entities.append(entity)

    return entities


def expand_thing_to_world_z(
    thing: Thing,
    origin_xy: tuple[float, float],
    floor_z: float = 0.0,
    yaw_deg: float = 0.0,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Convenience: place a thing on a floor.

    Thing's bottom rests at `floor_z`. Useful default for "drop this in
    the workroom" — caller specifies XY and floor height; we lift the
    thing's center to floor_z + (real_size_z / 2).
    """
    center_z = floor_z + thing.real_size_m[2] / 2.0
    origin = (origin_xy[0], origin_xy[1], center_z)
    return expand_thing(thing, origin=origin, yaw_deg=yaw_deg, **kwargs)
