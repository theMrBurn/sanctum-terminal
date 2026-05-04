"""Player-vs-entity collision pushout."""
from __future__ import annotations

import math

from clients.vector_terminal.collision import resolve_collisions


def _entity(x: float, y: float, radius: float) -> dict:
    return {"x": x, "y": y, "collision_radius": radius}


def test_no_entities_no_change():
    assert resolve_collisions(5.0, 5.0, [], 0.3, 8.0) == (5.0, 5.0)


def test_far_entity_does_not_push():
    out = resolve_collisions(0.0, 0.0, [_entity(100.0, 100.0, 1.0)], 0.3, 8.0)
    assert out == (0.0, 0.0)


def test_overlapping_entity_pushes_player_out():
    # Entity at (1, 0) with radius 1.0; player radius 0.3; player at origin.
    # Min separation = 1.3. Player should be pushed to (-0.3, 0).
    new_x, new_z = resolve_collisions(0.0, 0.0, [_entity(1.0, 0.0, 1.0)], 0.3, 8.0)
    assert math.isclose(new_x, -0.3, abs_tol=1e-6)
    assert math.isclose(new_z, 0.0, abs_tol=1e-6)


def test_zero_radius_entity_skipped():
    out = resolve_collisions(0.0, 0.0, [_entity(0.1, 0.0, 0.0)], 0.3, 8.0)
    assert out == (0.0, 0.0)


def test_player_exactly_on_center_pushes_along_x():
    # Degeneracy guard: player at entity center → push along +X by min_dist.
    new_x, new_z = resolve_collisions(0.0, 0.0, [_entity(0.0, 0.0, 1.0)], 0.3, 8.0)
    assert new_x > 0.0  # pushed somewhere
    assert math.isclose(new_z, 0.0, abs_tol=1e-6)


def test_cull_distance_skips_far_entities():
    # Entity is within radius+player but cull_dist excludes it
    out = resolve_collisions(
        0.0, 0.0,
        [_entity(10.0, 0.0, 1.0)],
        0.3, 8.0,  # cull_dist 8m, entity at 10m → skipped
    )
    assert out == (0.0, 0.0)


def test_multiple_overlaps_resolve_in_sequence():
    # Two entities overlapping the player; resolution is sequential, not
    # ideal-simultaneous. Just verify both effects kick in.
    new_x, new_z = resolve_collisions(
        0.0, 0.0,
        [_entity(1.0, 0.0, 1.0), _entity(0.0, 1.0, 1.0)],
        0.3, 8.0,
    )
    # Both pushed out — final position should be in the -x, -z quadrant
    assert new_x < 0.0
    assert new_z < 0.0


def test_negative_radius_skipped():
    out = resolve_collisions(0.0, 0.0, [_entity(0.5, 0.0, -1.0)], 0.3, 8.0)
    assert out == (0.0, 0.0)
