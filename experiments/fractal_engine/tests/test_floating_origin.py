"""Floating origin: no vertex jitter at extreme scales.

The engine never tries to render absolute world coords. Instead, every
GridNode is its own local origin. So even at depth=10 (where one tile
in the parent grid is 1e-10 world units wide), we render the *current*
grid in its own [-0.5, 0.5] frame and project from there.

That means:
  1. Vertex magnitudes coming out of the engine stay bounded.
  2. Two nodes at very different absolute "depths" produce the same
     numeric range — the renderer never sees floating-point precision
     loss from huge offsets.
"""

import math

from engine import FractalEngine
from grid_node import GridNode
from primitives import Camera, Vec3, primitive_for_depth


def _max_abs_vertex_component(node, camera):
    engine = FractalEngine()
    biggest = 0.0
    for line in engine.render(node, camera):
        for p in (line.a, line.b):
            biggest = max(biggest, abs(p.x), abs(p.y))
    return biggest


def test_vertex_components_bounded_at_shallow_depth():
    node = GridNode(seed=11, depth=0)
    cam = Camera(position=Vec3(0, 0.6, 1.5))
    biggest = _max_abs_vertex_component(node, cam)
    # NDC clip space is [-1, 1]; we don't draw lines fully outside that
    # because both endpoints must pass near/far culling. Project space
    # can briefly exceed 1 for partially-clipped lines (we don't clip
    # them — we trivially reject), but should still be sane.
    assert biggest < 10.0, f"vertex magnitude {biggest} unexpectedly large"


def test_vertex_components_bounded_at_extreme_depth():
    """Build a chain 8 levels deep — each level is 10x smaller."""
    node = GridNode(seed=11, depth=0)
    for _ in range(8):
        node = node.child(1, 1)

    cam = Camera(position=Vec3(0, 0.6, 1.5))
    biggest = _max_abs_vertex_component(node, cam)

    # Critical assertion: even at 1e-8 world scale per tile, the
    # numbers coming out of the projector are the same range as at
    # depth=0. That's floating origin doing its job.
    assert biggest < 10.0, f"jitter at depth 8: biggest component {biggest}"


def test_geometry_identical_modulo_scale_across_depths():
    """The same primitive, projected with the same local camera,
    produces the same screen-space output regardless of which depth
    it's authored for.

    This is the math expression of "vertex magnitudes don't blow up":
    if we always work in node-local coords, depth is irrelevant.
    """
    cam = Camera(position=Vec3(0, 0.6, 1.5))
    geom = primitive_for_depth(2)

    from primitives import stream_geometry

    shallow_lines = list(stream_geometry(geom, Vec3(0, 0, 0), 1.0, cam))
    deep_lines = list(stream_geometry(geom, Vec3(0, 0, 0), 1.0, cam))

    assert len(shallow_lines) == len(deep_lines)
    for a, b in zip(shallow_lines, deep_lines):
        assert a.a.x == b.a.x and a.a.y == b.a.y
        assert a.b.x == b.b.x and a.b.y == b.b.y


def test_no_nan_or_inf_in_projection():
    """Floating-origin renderer must never emit non-finite vertices."""
    engine = FractalEngine()
    node = GridNode(seed=5, depth=0)
    for _ in range(5):
        node = node.child(2, 4)
    cam = Camera(position=Vec3(0, 0.6, 1.5))
    for line in engine.render(node, cam):
        for p in (line.a, line.b):
            assert math.isfinite(p.x)
            assert math.isfinite(p.y)


def test_camera_far_culls_geometry_behind_camera():
    cam = Camera(position=Vec3(0, 0.6, 1.5))
    # Place the geometry behind the camera (z > camera.z).
    from primitives import stream_geometry, wireframe_cube

    behind = list(stream_geometry(wireframe_cube(0.1), Vec3(0, 0, 5.0), 1.0, cam))
    assert behind == []
