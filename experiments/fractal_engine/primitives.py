"""Vector primitives for the Unified Fractal Engine.

Everything emitted by the engine is a stream of DrawLine commands.
The engine is responsible for projecting (x, y, z) world coords into
2D screen coords; consumers (Godot, terminal, debug) only need to
draw 2D line segments.

Primitives are scale-agnostic: a wireframe cube at depth=0 (galaxy)
and depth=3 (dungeon room) both emit the same DrawLine stream — only
their world-space scale differs. That is the whole point of the
"everything is a grid" topology.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Iterator


# ---------------------------------------------------------------------------
# Core math types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    def __add__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, k: float) -> "Vec3":
        return Vec3(self.x * k, self.y * k, self.z * k)

    __rmul__ = __mul__

    def length(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)


@dataclass(frozen=True)
class Vec2:
    x: float
    y: float


@dataclass(frozen=True)
class Color:
    r: float
    g: float
    b: float
    a: float = 1.0

    @staticmethod
    def hex(value: str) -> "Color":
        v = value.lstrip("#")
        return Color(
            int(v[0:2], 16) / 255.0,
            int(v[2:4], 16) / 255.0,
            int(v[4:6], 16) / 255.0,
        )


# A few well-known palette entries used by the depth resolver.
WHITE = Color(1.0, 1.0, 1.0)
GREEN = Color(0.2, 1.0, 0.4)
CYAN = Color(0.4, 0.9, 1.0)
AMBER = Color(1.0, 0.7, 0.2)
VIOLET = Color(0.7, 0.4, 1.0)
DIM = Color(0.4, 0.4, 0.4)


# ---------------------------------------------------------------------------
# Output commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DrawLine:
    """A single 2D line segment for the consumer to render.

    a/b are post-projection screen-space coordinates in normalized device
    coords ([-1, 1] x [-1, 1]). The consumer maps that to its viewport.
    """

    a: Vec2
    b: Vec2
    color: Color


# ---------------------------------------------------------------------------
# Geometry: world-space wireframe primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VectorGeometry:
    """A bag of world-space line segments + a tint color.

    Geometry is authored unit-sized (extents roughly within [-0.5, 0.5]^3
    or [-1, 1]^3 for orbital primitives) and then transformed by the
    renderer via translate/scale before projection.
    """

    edges: tuple[tuple[Vec3, Vec3], ...]
    color: Color = WHITE

    def transformed(self, origin: Vec3, scale: float) -> Iterator[tuple[Vec3, Vec3]]:
        for a, b in self.edges:
            yield (a * scale + origin, b * scale + origin)


def wireframe_cube(size: float = 1.0) -> VectorGeometry:
    s = size * 0.5
    corners = [
        Vec3(-s, -s, -s),
        Vec3(s, -s, -s),
        Vec3(s, s, -s),
        Vec3(-s, s, -s),
        Vec3(-s, -s, s),
        Vec3(s, -s, s),
        Vec3(s, s, s),
        Vec3(-s, s, s),
    ]
    edge_idx = [
        (0, 1), (1, 2), (2, 3), (3, 0),  # bottom
        (4, 5), (5, 6), (6, 7), (7, 4),  # top
        (0, 4), (1, 5), (2, 6), (3, 7),  # verticals
    ]
    return VectorGeometry(
        edges=tuple((corners[i], corners[j]) for i, j in edge_idx),
        color=GREEN,
    )


def wireframe_grid(cells: int = 10, size: float = 1.0, color: Color = DIM) -> VectorGeometry:
    """Flat 2D grid (10x10 by default) on the y=0 plane.

    This is the canonical "this depth is a 10x10 board" visual. The
    grid is the substrate every depth level shares.
    """
    half = size * 0.5
    step = size / cells
    edges: list[tuple[Vec3, Vec3]] = []
    for i in range(cells + 1):
        t = -half + i * step
        edges.append((Vec3(t, 0.0, -half), Vec3(t, 0.0, half)))
        edges.append((Vec3(-half, 0.0, t), Vec3(half, 0.0, t)))
    return VectorGeometry(edges=tuple(edges), color=color)


def faceted_sphere(radius: float = 0.5, rings: int = 4, segments: int = 6) -> VectorGeometry:
    """Cheap icosphere-ish wireframe — for stars, planets, bosses."""
    edges: list[tuple[Vec3, Vec3]] = []
    pts: list[list[Vec3]] = []
    for i in range(rings + 1):
        phi = math.pi * i / rings
        ring: list[Vec3] = []
        for j in range(segments):
            theta = 2 * math.pi * j / segments
            ring.append(Vec3(
                radius * math.sin(phi) * math.cos(theta),
                radius * math.cos(phi),
                radius * math.sin(phi) * math.sin(theta),
            ))
        pts.append(ring)
    for i, ring in enumerate(pts):
        for j in range(segments):
            edges.append((ring[j], ring[(j + 1) % segments]))
            if i < rings:
                edges.append((ring[j], pts[i + 1][j]))
    return VectorGeometry(edges=tuple(edges), color=AMBER)


def orbital_path(radius: float = 1.0, segments: int = 32) -> VectorGeometry:
    """Closed circle on the y=0 plane — orbits, range rings, gravity wells."""
    edges: list[tuple[Vec3, Vec3]] = []
    for i in range(segments):
        a = 2 * math.pi * i / segments
        b = 2 * math.pi * (i + 1) / segments
        edges.append((
            Vec3(radius * math.cos(a), 0.0, radius * math.sin(a)),
            Vec3(radius * math.cos(b), 0.0, radius * math.sin(b)),
        ))
    return VectorGeometry(edges=tuple(edges), color=VIOLET)


def wireframe_walls(size: float = 1.0, height: float = 0.6) -> VectorGeometry:
    """Dungeon room: 4 walls + floor outline. No ceiling — top-open."""
    s = size * 0.5
    floor = [
        Vec3(-s, 0, -s), Vec3(s, 0, -s),
        Vec3(s, 0, -s), Vec3(s, 0, s),
        Vec3(s, 0, s), Vec3(-s, 0, s),
        Vec3(-s, 0, s), Vec3(-s, 0, -s),
    ]
    top = [(Vec3(p.x, height, p.z), Vec3(q.x, height, q.z)) for p, q in zip(floor[::2], floor[1::2])]
    verts = [
        (Vec3(-s, 0, -s), Vec3(-s, height, -s)),
        (Vec3(s, 0, -s), Vec3(s, height, -s)),
        (Vec3(s, 0, s), Vec3(s, height, s)),
        (Vec3(-s, 0, s), Vec3(-s, height, s)),
    ]
    edges: list[tuple[Vec3, Vec3]] = []
    edges.extend((floor[i], floor[i + 1]) for i in range(0, len(floor), 2))
    edges.extend(top)
    edges.extend(verts)
    return VectorGeometry(edges=tuple(edges), color=CYAN)


# ---------------------------------------------------------------------------
# Depth → primitive resolver
# ---------------------------------------------------------------------------

DEPTH_NAMES = {
    0: "GALAXY",
    1: "SOLAR_SYSTEM",
    2: "OVERWORLD",
    3: "DUNGEON",
}


def primitive_for_depth(depth: int) -> VectorGeometry:
    """Pick the canonical wireframe primitive for a depth slice.

    Galaxy = orbital ring (the spiral hint).
    Solar System = orbital path + faceted sun glyph (returned as the path;
        the system also draws a sphere via render code).
    Overworld = grid (the literal map).
    Dungeon = walls.
    """
    if depth <= 0:
        return orbital_path(radius=0.95, segments=48)
    if depth == 1:
        return orbital_path(radius=0.7, segments=32)
    if depth == 2:
        return wireframe_grid(cells=10, size=1.0)
    return wireframe_walls(size=1.0, height=0.45)


# ---------------------------------------------------------------------------
# FOV projection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Camera:
    """Pinhole camera, looking down -Z by default.

    Position is in world space relative to the *floating origin* (see
    grid_node.center_view) — never absolute world coords. That keeps
    vertex jitter bounded regardless of depth scale.
    """

    position: Vec3 = field(default_factory=lambda: Vec3(0.0, 0.6, 1.5))
    fov_y_deg: float = 60.0
    aspect: float = 1.0  # square viewport by default
    near: float = 0.05
    far: float = 100.0

    def project(self, p: Vec3) -> Vec2 | None:
        """Project a *camera-space* point into NDC. Returns None if culled.

        We deliberately don't apply a view matrix here; the engine
        translates points into camera-relative space *before* calling
        project(), which is what makes floating-origin work cleanly.
        """
        rel = p - self.position
        # Camera looks toward -Z; depth is -rel.z.
        d = -rel.z
        if d < self.near or d > self.far:
            return None
        f = 1.0 / math.tan(math.radians(self.fov_y_deg) * 0.5)
        return Vec2(
            (rel.x * f / self.aspect) / d,
            (rel.y * f) / d,
        )


def stream_geometry(
    geometry: VectorGeometry,
    origin: Vec3,
    scale: float,
    camera: Camera,
) -> Iterator[DrawLine]:
    """Project a geometry instance to a DrawLine stream, culling/clipping."""
    for a3, b3 in geometry.transformed(origin, scale):
        a2 = camera.project(a3)
        b2 = camera.project(b3)
        if a2 is None or b2 is None:
            # Trivial reject — full clipping (Liang-Barsky on the near
            # plane) is intentionally out of scope for the PoC; both
            # endpoints must be in-frustum to draw.
            continue
        yield DrawLine(a2, b2, geometry.color)


def stream_many(
    items: Iterable[tuple[VectorGeometry, Vec3, float]],
    camera: Camera,
) -> Iterator[DrawLine]:
    for geom, origin, scale in items:
        yield from stream_geometry(geom, origin, scale, camera)
