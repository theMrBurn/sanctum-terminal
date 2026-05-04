"""Edge skins — procedural skin profiles for wireframe meshes.

Sampled per edge during wireframe rendering: each skin is a function
that takes mesh-local edge endpoints + monotonic time + a seed and
returns one or more colored line segments to draw in place of the
plain edge. The renderer transforms returned segments back to world
space; skins themselves stay pure-math on local coords so the noise
pattern stays anchored to the mesh as the camera moves.

V1 ships five profiles per the slice plan in
`.claude/feature/feat_loop-completion.md`:
  rust       — Worley noise + warm brown/orange cosine palette
  ice        — value-noise FBM + slow time drift, white-blue palette
  metal      — cosine palette modulated by edge orientation
  decay      — value-noise threshold dashed segments (corrosion)
  prismatic  — time + position phase → full hue cycle

Helpers (`worley_noise`, `cosine_palette`, `value_noise`, `value_fbm`)
are intentionally minimal: pure math, no numpy. The helpers will be
the substrate for future membrane work — see `design_membrane_system`.
"""
from __future__ import annotations

import math
from typing import Callable

Point3 = tuple[float, float, float]
RGBA = tuple[int, int, int, int]
SkinSegment = tuple[Point3, Point3, RGBA]
SkinFn = Callable[[Point3, Point3, float, int], list[SkinSegment]]


# ── Hashing + noise primitives ───────────────────────────────────────


def _hash2(x: int, y: int, seed: int) -> float:
    """Deterministic 2D integer hash → float in [0, 1).

    Mixes three primes, two xorshift bounces. Fast, stable, no numpy.
    """
    h = (x * 374761393 + y * 668265263 + seed * 1274126177) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    return (h & 0xFFFFFFFF) / 4294967296.0


def worley_noise(x: float, y: float, seed: int = 0) -> float:
    """Cellular (Worley) noise — distance from (x,y) to nearest jittered
    grid feature point. Output is unbounded above but typically lies in
    [0, ~1.4] for unit-cell grids; callers should treat values >1 as
    "far from any cell center" and map through a palette accordingly.

    Single-cell algorithm: floor (x,y) into a unit grid, scan the 3×3
    neighborhood, jitter each cell's feature point by hash, return the
    minimum Euclidean distance.
    """
    gx = math.floor(x)
    gy = math.floor(y)
    fx = x - gx
    fy = y - gy
    min_d2 = math.inf
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            jx = _hash2(gx + dx, gy + dy, seed)
            jy = _hash2(gx + dx, gy + dy, seed * 31 + 1)
            px = dx + jx - fx
            py = dy + jy - fy
            d2 = px * px + py * py
            if d2 < min_d2:
                min_d2 = d2
    return math.sqrt(min_d2)


def value_noise(x: float, y: float, seed: int = 0) -> float:
    """Bilinear-interpolated value noise on a unit grid. Output in [0, 1].

    Smoother than raw hash, cheaper than Perlin gradients. Good enough
    for skin sampling at edge midpoints.
    """
    gx = math.floor(x)
    gy = math.floor(y)
    fx = x - gx
    fy = y - gy
    # Smoothstep the fractional coords for less grid-aligned banding.
    sx = fx * fx * (3.0 - 2.0 * fx)
    sy = fy * fy * (3.0 - 2.0 * fy)
    n00 = _hash2(gx, gy, seed)
    n10 = _hash2(gx + 1, gy, seed)
    n01 = _hash2(gx, gy + 1, seed)
    n11 = _hash2(gx + 1, gy + 1, seed)
    nx0 = n00 + (n10 - n00) * sx
    nx1 = n01 + (n11 - n01) * sx
    return nx0 + (nx1 - nx0) * sy


def value_fbm(x: float, y: float, seed: int = 0, octaves: int = 4) -> float:
    """Fractal Brownian motion stack — value_noise summed at doubling
    frequencies, halving amplitudes. Output normalized to [0, 1].
    """
    total = 0.0
    amp = 1.0
    freq = 1.0
    norm = 0.0
    for o in range(octaves):
        total += amp * value_noise(x * freq, y * freq, seed + o)
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return total / norm if norm > 0 else 0.0


# ── Cosine palette (Inigo Quilez) ────────────────────────────────────


Triple = tuple[float, float, float]


def cosine_palette(
    t: float,
    a: Triple,
    b: Triple,
    c: Triple,
    d: Triple,
) -> Triple:
    """`color = a + b * cos(2π * (c*t + d))` per iquilezles.org/articles/palettes.

    Five-float-per-channel parameterization → infinite color schemes from
    a single function. Output channels NOT clamped; callers that need
    bytes should clamp to [0, 1] first.
    """
    two_pi = 2.0 * math.pi
    r = a[0] + b[0] * math.cos(two_pi * (c[0] * t + d[0]))
    g = a[1] + b[1] * math.cos(two_pi * (c[1] * t + d[1]))
    bl = a[2] + b[2] * math.cos(two_pi * (c[2] * t + d[2]))
    return (r, g, bl)


def _to_rgba(rgb: Triple, alpha: float = 1.0) -> RGBA:
    """Clamp + quantize a 0..1 RGB triple plus alpha into raylib RGBA bytes."""
    def _b(v: float) -> int:
        if v < 0.0:
            v = 0.0
        elif v > 1.0:
            v = 1.0
        return int(round(v * 255.0))
    return (_b(rgb[0]), _b(rgb[1]), _b(rgb[2]), _b(alpha))


def _midpoint_xz(a: Point3, b: Point3) -> tuple[float, float]:
    return ((a[0] + b[0]) * 0.5, (a[2] + b[2]) * 0.5)


def _lerp3(a: Point3, b: Point3, t: float) -> Point3:
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


# ── Skin profiles ────────────────────────────────────────────────────


def rust(a: Point3, b: Point3, time: float, seed: int) -> list[SkinSegment]:
    """Worley patina sampled at edge midpoint → warm brown/orange cosine
    palette. Patches read as oxidation pitting clinging to corners.
    """
    mx, mz = _midpoint_xz(a, b)
    n = worley_noise(mx * 0.7, mz * 0.7, seed)
    # Brown→orange palette; pitched darker so wireframe still reads.
    rgb = cosine_palette(
        n,
        a=(0.45, 0.25, 0.10),
        b=(0.35, 0.20, 0.08),
        c=(1.0, 1.0, 0.5),
        d=(0.0, 0.10, 0.20),
    )
    return [(a, b, _to_rgba(rgb))]


def ice(a: Point3, b: Point3, time: float, seed: int) -> list[SkinSegment]:
    """Value-FBM with slow horizontal drift → white-blue palette. Edges
    breathe over ~30s as the noise field slides past sample points.
    """
    mx, mz = _midpoint_xz(a, b)
    drift = time * 0.05
    n = value_fbm(mx * 0.8 + drift, mz * 0.8, seed, octaves=3)
    rgb = cosine_palette(
        n,
        a=(0.75, 0.85, 0.95),
        b=(0.20, 0.15, 0.10),
        c=(1.0, 1.0, 1.0),
        d=(0.0, 0.10, 0.20),
    )
    return [(a, b, _to_rgba(rgb))]


def metal(a: Point3, b: Point3, time: float, seed: int) -> list[SkinSegment]:
    """Cosine palette modulated by edge verticality. Vertical struts
    read silver/cool, flatter spans warm toward gold — fakes specular
    sheen without needing a real shader.
    """
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    dz = b[2] - a[2]
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length <= 0.0:
        vert = 0.0
    else:
        vert = abs(dy) / length
    rgb = cosine_palette(
        vert,
        a=(0.60, 0.55, 0.50),
        b=(0.40, 0.35, 0.25),
        # c < 1 so vert=0 and vert=1 land on different phases (avoids
        # cosine periodicity collapsing the orientation signal).
        c=(0.50, 0.50, 0.50),
        d=(0.0, 0.05, 0.15),
    )
    return [(a, b, _to_rgba(rgb))]


_DECAY_SEGMENTS = 7  # factor of 7 (per `feedback_factor_of_7`)
_DECAY_THRESHOLD = 0.42  # below this → segment skipped (the corrosion gap)


def decay(a: Point3, b: Point3, time: float, seed: int) -> list[SkinSegment]:
    """Edge subdivided into 7 pieces; each piece kept or skipped by a
    value-noise threshold. Surviving pieces shaded by their noise sample.
    Reads as crumbling segments. Returned list may be empty for edges
    that fall entirely below threshold.
    """
    out: list[SkinSegment] = []
    for i in range(_DECAY_SEGMENTS):
        t0 = i / _DECAY_SEGMENTS
        t1 = (i + 1) / _DECAY_SEGMENTS
        s_a = _lerp3(a, b, t0)
        s_b = _lerp3(a, b, t1)
        mx = (s_a[0] + s_b[0]) * 0.5
        mz = (s_a[2] + s_b[2]) * 0.5
        n = value_noise(mx * 1.3, mz * 1.3, seed)
        if n < _DECAY_THRESHOLD:
            continue
        rgb = cosine_palette(
            n,
            a=(0.30, 0.25, 0.20),
            b=(0.30, 0.25, 0.18),
            c=(1.0, 1.0, 1.0),
            d=(0.0, 0.08, 0.15),
        )
        out.append((s_a, s_b, _to_rgba(rgb)))
    return out


def prismatic(a: Point3, b: Point3, time: float, seed: int) -> list[SkinSegment]:
    """Time + position phase drives a full-spectrum cosine palette. Each
    edge cycles through the rainbow with a position-dependent offset so
    adjacent edges desync — reads as iridescence.
    """
    mx = (a[0] + b[0]) * 0.5
    my = (a[1] + b[1]) * 0.5
    mz = (a[2] + b[2]) * 0.5
    pos_phase = (mx + my * 0.7 + mz) * 0.13
    seed_phase = (seed * 0.618033) % 1.0
    t = (pos_phase + time * 0.20 + seed_phase) % 1.0
    rgb = cosine_palette(
        t,
        a=(0.55, 0.50, 0.55),
        b=(0.45, 0.45, 0.45),
        c=(1.0, 1.0, 1.0),
        d=(0.0, 0.33, 0.67),
    )
    return [(a, b, _to_rgba(rgb))]


# ── Registry ─────────────────────────────────────────────────────────


_SKINS: dict[str, SkinFn] = {
    "rust": rust,
    "ice": ice,
    "metal": metal,
    "decay": decay,
    "prismatic": prismatic,
}


def get_skin(name: str) -> SkinFn | None:
    """Look up a skin profile by name. Returns None for unknown names."""
    return _SKINS.get(name)


def skin_names() -> tuple[str, ...]:
    return tuple(sorted(_SKINS.keys()))
