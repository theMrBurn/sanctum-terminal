"""Crosshair raycast — entity targeting for the F interact key."""
from __future__ import annotations

from clients.vector_terminal.targeting import entity_at_crosshair


def _entity(x: float, y: float, z: float = 0.0, radius: float = 1.0) -> dict:
    """Create a manifest-style entity (manifest x/y/z, raylib swaps y/z)."""
    return {"x": x, "y": y, "z": z, "collision_radius": radius, "kind": "test"}


def test_no_entities_returns_none():
    out = entity_at_crosshair(0, 1.7, 0, 0, 0, 1, [], 3.0, 0.5)
    assert out is None


def test_entity_directly_ahead_is_picked():
    # Entity at manifest (0, 2, 0) → raylib (0, 0, 2). Camera at raylib (0,1.7,0)
    # facing raylib +Z (forward=(0,0,1)). Ray hits entity at distance 2.
    ents = [_entity(0, 2, 0, 1.0)]
    out = entity_at_crosshair(0, 1.7, 0, 0, 0, 1, ents, 3.0, 0.5)
    assert out is not None
    assert out["kind"] == "test"


def test_entity_behind_camera_skipped():
    # Entity at manifest y=-2 → raylib z=-2. Camera looks +Z, so entity is behind.
    ents = [_entity(0, -2, 0, 1.0)]
    out = entity_at_crosshair(0, 1.7, 0, 0, 0, 1, ents, 3.0, 0.5)
    assert out is None


def test_entity_off_axis_outside_radius_skipped():
    # Entity at manifest (5, 2, 0) → raylib (5, 0, 2). Camera at origin facing +Z.
    # Closest point on ray to entity is at (0, 0, 2), perp dist = 5m. Radius 1m → miss.
    ents = [_entity(5, 2, 0, 1.0)]
    out = entity_at_crosshair(0, 1.7, 0, 0, 0, 1, ents, 3.0, 0.5)
    assert out is None


def test_entity_off_axis_inside_radius_hits():
    # XZ-only targeting: entity at manifest (0.5, 2, 0) → raylib (0.5, ?, 2).
    # XZ perp = 0.5; radius = 2.0 → hits regardless of cam height.
    ents = [_entity(0.5, 2, 0, 2.0)]
    out = entity_at_crosshair(0, 1.7, 0, 0, 0, 1, ents, 3.0, 0.5)
    assert out is not None


def test_closest_among_multiple_targets():
    # Two on-axis entities at distances 1.5 and 2.5; closer one wins.
    ents = [
        _entity(0, 2.5, 0, 1.0),  # raylib z=2.5
        _entity(0, 1.5, 0, 1.0),  # raylib z=1.5  ← closer
    ]
    out = entity_at_crosshair(0, 1.7, 0, 0, 0, 1, ents, 3.0, 0.5)
    assert out is not None
    assert out["y"] == 1.5


def test_max_range_excludes_far_entity():
    # Entity at distance 10m, max_range 3m → skipped.
    ents = [_entity(0, 10, 0, 1.0)]
    out = entity_at_crosshair(0, 1.7, 0, 0, 0, 1, ents, 3.0, 0.5)
    assert out is None


def test_zero_collision_radius_uses_default():
    # Entity has 0 radius → falls back to radius_default (0.5).
    # Entity at manifest (0.4, 2, 0) → off-axis 0.4 horiz. Below default 0.5 → hits.
    ents = [{"x": 0.4, "y": 2, "z": 0, "collision_radius": 0.0, "kind": "x"}]
    out = entity_at_crosshair(0, 0, 0, 0, 0, 1, ents, 3.0, 0.5)
    assert out is not None
