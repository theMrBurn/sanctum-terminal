"""Player-vs-entity collision — horizontal pushout using each entity's
`collision_radius` from the manifest.

Brain doesn't enforce collision; client checks every frame after movement
and before the envelope clamp. Cheap O(N) scan with a squared-distance
early reject, culled to entities within COLLISION_CULL_DIST of the player.
"""
from __future__ import annotations

import math


def resolve_collisions(
    x: float,
    z: float,
    entities: list[dict],
    player_radius: float,
    cull_dist: float,
) -> tuple[float, float]:
    """Push the player out of any entity whose collision cylinder overlaps.

    Operates on the horizontal plane (manifest x, manifest y → raylib z).
    Returns the new (x, z). Vertical y is the caller's concern.
    """
    cull_sq = cull_dist * cull_dist
    for ent in entities:
        rad = float(ent.get("collision_radius", 0.0))
        if rad <= 0.0:
            continue
        ex = float(ent.get("x", 0.0))
        ez = float(ent.get("y", 0.0))  # manifest y → raylib z
        dx = x - ex
        dz = z - ez
        sq = dx * dx + dz * dz
        if sq > cull_sq:
            continue
        min_dist = rad + player_radius
        if sq >= min_dist * min_dist:
            continue
        # Overlap — radial pushout. Guard against exactly-on-center degeneracy.
        dist = math.sqrt(sq)
        if dist <= 1e-6:
            x += min_dist
            continue
        push = (min_dist - dist) / dist
        x += dx * push
        z += dz * push
    return x, z
