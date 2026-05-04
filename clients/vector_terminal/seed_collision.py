"""Per-seed surface-height collision for the vector workroom.

Computes the world-Y "floor" the player should stand on at any (X, Z)
position, given the seeds in the active manifest. Lateral collision
(blocking movement into seed walls) is deferred V1 — the user can walk
through obstacles, but they STAND ON top of placed primitives when
their XZ is inside a seed's footprint and the seed's surface height at
that XZ is within step distance of their current Y.

Per-primitive surface height functions live in `_HEIGHT_FNS`. Each
takes (local_x, local_z) in the mesh's local coords (after un-scaling
the player's world position relative to the seed's origin) and returns
the Y of the surface at that XZ in mesh-local coords, or None if XZ
is outside the primitive's footprint.

The dispatch then scales + offsets to world-Y. Mesh-edited primitives
fall back to the AABB top of the resolved mesh.
"""
from __future__ import annotations

from typing import Callable, Optional

from core.systems.wireframe_mesh import WireframeMesh, get_builtin


# ── Tunables ────────────────────────────────────────────────────────

STEP_HEIGHT_MAX_M = 0.6      # max snap-up distance per movement frame
GROUND_Y = 1.7               # default raylib EYE_HEIGHT (cfg fallback)


# ── Per-primitive local-space height functions ─────────────────────


def _flat_top_at_y_one(local_x: float, local_z: float) -> Optional[float]:
    """Footprint XZ in [-0.5, 0.5]; surface at Y=1.0. Cube, octahedron
    (treated as flat for collision V1)."""
    if -0.5 <= local_x <= 0.5 and -0.5 <= local_z <= 0.5:
        return 1.0
    return None


def _flat_top_at_y_zero_one(local_x: float, local_z: float) -> Optional[float]:
    """Slab — thin tile, top at Y=0.1."""
    if -0.5 <= local_x <= 0.5 and -0.5 <= local_z <= 0.5:
        return 0.1
    return None


def _flat_top_at_y_two(local_x: float, local_z: float) -> Optional[float]:
    """Pyramid + spire — peaked, but for collision V1 we use the apex
    height as a flat plateau. User stands on top."""
    if -1.0 <= local_x <= 1.0 and -1.0 <= local_z <= 1.0:
        return 2.0
    return None


def _wedge_slope(local_x: float, local_z: float) -> Optional[float]:
    """Triangular ramp. Slope rises from Y=0 at z=-0.5 to Y=1 at z=+0.5,
    constant across X in [-0.5, 0.5]."""
    if not (-0.5 <= local_x <= 0.5 and -0.5 <= local_z <= 0.5):
        return None
    # Linear interpolation across the slope.
    t = (local_z + 0.5)  # [0, 1]
    return max(0.0, min(1.0, t))


def _stair_4_step(local_x: float, local_z: float) -> Optional[float]:
    """4-step staircase per `wireframe_mesh._stair_4`. Each step rises
    0.25 in Y and advances 0.25 in Z, both starting at -0.5.

    Step k (k in 0..3) covers Z in [-0.5 + 0.25*k, -0.5 + 0.25*(k+1)]
    and its tread surface Y = 0.25 * (k + 1).
    """
    if not (-0.5 <= local_x <= 0.5 and -0.5 <= local_z <= 0.5):
        return None
    # Bin by Z; clamp at the back for the top step.
    if local_z < -0.25:
        return 0.25
    if local_z < 0.0:
        return 0.5
    if local_z < 0.25:
        return 0.75
    return 1.0


def _tetrahedron_surface(local_x: float, local_z: float) -> Optional[float]:
    """Tetrahedron — collision V1 uses flat plateau at Y=1 across the
    full footprint. The actual mesh has tilted faces; refining is a
    future task once the V1 traversal feels right."""
    if -1.0 <= local_x <= 1.0 and -1.0 <= local_z <= 1.0:
        return 1.0
    return None


_HEIGHT_FNS: dict[str, Callable[[float, float], Optional[float]]] = {
    "cube":        _flat_top_at_y_one,
    "octahedron":  _flat_top_at_y_one,    # AABB top is 1; flat for V1
    "slab":        _flat_top_at_y_zero_one,
    "pyramid":     _flat_top_at_y_two,
    "spire":       _flat_top_at_y_two,
    "tetrahedron": _tetrahedron_surface,
    "wedge":       _wedge_slope,
    "stair":       _stair_4_step,
}


# ── Mesh-edited fallback: AABB top ─────────────────────────────────


def _aabb_top_at(mesh: WireframeMesh, local_x: float, local_z: float) -> Optional[float]:
    """For mesh-edited primitives where the V1 height table doesn't
    apply, fall back to the AABB: footprint = mesh's XZ extents,
    surface = max Y of any vertex."""
    if not mesh.vertices:
        return None
    xs = [v[0] for v in mesh.vertices]
    zs = [v[2] for v in mesh.vertices]
    if not (min(xs) <= local_x <= max(xs) and min(zs) <= local_z <= max(zs)):
        return None
    return max(v[1] for v in mesh.vertices)


# ── Public API ─────────────────────────────────────────────────────


def seed_floor_height(
    seed: dict,
    world_x: float,
    world_z: float,
) -> Optional[float]:
    """Return the world Y of the seed's top surface at (world_x, world_z),
    or None if the player's XZ is outside the seed's footprint.

    Coordinate convention reminder: brain pos_y maps to raylib Z
    (forward), brain pos_z maps to raylib Y (up). This function takes
    raylib X and raylib Z as inputs; the seed's stored pos_x maps to
    raylib X, pos_y maps to raylib Z, pos_z maps to raylib Y.
    """
    base_name = str(seed.get("base_mesh", ""))
    fn = _HEIGHT_FNS.get(base_name)
    if fn is None:
        return None  # mesh-edited fallback handled by caller w/ resolved mesh
    seed_rx = float(seed.get("pos_x", 0.0))
    seed_ry = float(seed.get("pos_z", 0.0))     # brain z = raylib y
    seed_rz = float(seed.get("pos_y", 0.0))     # brain y = raylib z
    scale = float(seed.get("scale", 1.0))
    if scale <= 0.0:
        return None
    local_x = (world_x - seed_rx) / scale
    local_z = (world_z - seed_rz) / scale
    local_y = fn(local_x, local_z)
    if local_y is None:
        return None
    return seed_ry + local_y * scale


def seed_floor_height_with_mesh(
    seed: dict,
    mesh: WireframeMesh,
    world_x: float,
    world_z: float,
) -> Optional[float]:
    """Same as `seed_floor_height` but with a pre-resolved mesh, so
    mesh-edited seeds use the AABB fallback. Caller passes the
    resolved mesh from `seed_mesh_cache`."""
    base_name = str(seed.get("base_mesh", ""))
    fn = _HEIGHT_FNS.get(base_name)
    seed_rx = float(seed.get("pos_x", 0.0))
    seed_ry = float(seed.get("pos_z", 0.0))
    seed_rz = float(seed.get("pos_y", 0.0))
    scale = float(seed.get("scale", 1.0))
    if scale <= 0.0:
        return None
    local_x = (world_x - seed_rx) / scale
    local_z = (world_z - seed_rz) / scale
    if fn is not None and not seed.get("mesh_edits"):
        # Built-in primitive with no edits — use the precise height fn.
        local_y = fn(local_x, local_z)
    else:
        # Mesh-edited or unknown primitive — use AABB top.
        local_y = _aabb_top_at(mesh, local_x, local_z)
    if local_y is None:
        return None
    return seed_ry + local_y * scale


def compute_floor_height(
    seeds: list[dict],
    world_x: float,
    world_z: float,
    current_y: float,
    ground_y: float = GROUND_Y,
    step_max: float = STEP_HEIGHT_MAX_M,
    cache=None,
) -> float:
    """Return the player's effective floor Y at (world_x, world_z).

    Picks the highest walkable surface among seeds the player is over
    — but only counts surfaces within `step_max` above current_y so the
    player can't teleport up onto a tall stack from below. Falls back
    to `ground_y` (the EYE_HEIGHT default floor) when nothing applies.

    `cache` is an optional `SeedMeshCache` — when provided, mesh-edited
    seeds resolve their AABB through it. When None, edited seeds are
    skipped (collision uses base-primitive shape only).
    """
    best = ground_y
    for s in seeds:
        if cache is not None:
            base_name = str(s.get("base_mesh", ""))
            base = get_builtin(base_name)
            if base is None:
                continue
            try:
                mesh = cache.resolve(
                    seed_id=int(s.get("id", 0)),
                    base_mesh_name=base_name,
                    base_mesh=base,
                    mesh_edits=s.get("mesh_edits") or [],
                )
            except (ValueError, TypeError):
                mesh = base
            top = seed_floor_height_with_mesh(s, mesh, world_x, world_z)
        else:
            top = seed_floor_height(s, world_x, world_z)
        if top is None:
            continue
        # The player's "feet" sit at current_y - eye_offset. We want the
        # foot height to be within step_max of the surface to consider
        # it walkable. Caller passes current_y as foot height already
        # (main.py computes eye Y == camera position Y; floor reaches
        # to camera_y - EYE_HEIGHT_OFFSET).  For V1 we use camera_y
        # directly — the snap simply replaces the camera Y with
        # surface_y + EYE_HEIGHT_OFFSET in main.py. Here we just bound
        # candidate surfaces by their world height.
        if top > current_y + step_max:
            continue
        if top > best:
            best = top
    return best
