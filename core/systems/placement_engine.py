"""
core/systems/placement_engine.py

Nature uses phyllotaxis. So do we.

Every object in the world is placed by the same math
that governs sunflower seeds, pine cones, nautilus shells.
The golden angle is irrational -- it never repeats.
Two seeds produce two worlds that will never converge.
"""
import math
import json
from pathlib import Path


# The golden angle -- irrational, aperiodic, inevitable
PHI = (1 + math.sqrt(5)) / 2

# Category density gates from signal_map
CATEGORY_DENSITY = {
    'flora':   0.80,
    'geology': 0.30,
    'fauna':   0.20,
    'remnant': 0.10,
    'relic':   0.05,
}


class PlacementEngine:
    """
    Places objects in the world by three-stage pipeline:

    1. GOLDEN SPIRAL   -- phyllotaxis candidate positions
                          seeded by interview, never periodic
    2. PERLIN FIELD    -- fractal noise modulation
                          filters candidates by local density
    3. GAUSSIAN GATE   -- ecological attunement check
                          only what belongs here manifests

    The result: a world that feels inevitable, not random.
    Your seed vault is genuinely yours.
    """

    GOLDEN_ANGLE = 137.5077640500378

    def __init__(self, seed=42):
        self.seed = seed
        self._rng_state = seed
        # Load signal map config if available
        sm = Path("config/signal_map.json")
        if sm.exists():
            data = json.load(open(sm))
            cat = data.get("placement_engine", {}).get("object_categories", {})
            self._density = {k: v["density"] for k, v in cat.items()} if cat else CATEGORY_DENSITY
        else:
            self._density = CATEGORY_DENSITY

    def golden_spiral(self, count, radius, cx=0.0, cy=0.0, phase=0.0):
        """
        Generate candidate positions via golden angle phyllotaxis.
        Phase offset is seeded from the interview -- shifts the spiral
        so every seed produces a unique arrangement.
        Returns list of (x, y) tuples.
        """
        angle_rad = math.radians(self.GOLDEN_ANGLE)
        phase_rad = math.radians(self.GOLDEN_ANGLE * (self.seed + phase))
        points = []
        for i in range(count):
            # Sunflower formula: r scales with sqrt for even density
            r = radius * math.sqrt((i + 0.5) / count)
            theta = i * angle_rad + phase_rad
            x = cx + r * math.cos(theta)
            y = cy + r * math.sin(theta)
            points.append((round(x, 4), round(y, 4)))
        return points

    def perlin(self, x, y, octaves=4, persistence=0.5, lacunarity=2.0):
        """
        Fractional Brownian Motion -- layered Perlin-style noise.
        Deterministic from seed. Returns 0.0-1.0.
        The fractal layer that makes each world unique at every scale.
        """
        value = 0.0
        amplitude = 1.0
        frequency = 1.0
        max_val = 0.0
        for _ in range(octaves):
            value   += self._smooth_noise(x * frequency, y * frequency) * amplitude
            max_val += amplitude
            amplitude *= persistence
            frequency *= lacunarity
        return max(0.0, min(1.0, (value / max_val + 1.0) / 2.0))

    def _smooth_noise(self, x, y):
        """Smooth interpolated noise cell. Seeded from instance seed."""
        ix, iy = int(math.floor(x)), int(math.floor(y))
        fx, fy = x - ix, y - iy
        # Smoothstep
        ux = fx * fx * (3 - 2 * fx)
        uy = fy * fy * (3 - 2 * fy)
        # Four corners -- hash from seed
        def h(a, b):
            n = self.seed ^ (a * 1619 + b * 31337)
            n = (n ^ (n >> 8)) * 0x45d9f3b
            n = (n ^ (n >> 8)) * 0x45d9f3b
            n = n ^ (n >> 8)
            return (n & 0xFFFFFF) / 0xFFFFFF * 2.0 - 1.0
        n00 = h(ix,   iy)
        n10 = h(ix+1, iy)
        n01 = h(ix,   iy+1)
        n11 = h(ix+1, iy+1)
        return (n00*(1-ux)*(1-uy) + n10*ux*(1-uy)
                + n01*(1-ux)*uy   + n11*ux*uy)

    def candidates(self, cx, cy, radius, count, category):
        """
        Generate placement candidates for a category.
        Spiral positions filtered by Perlin density field.
        Denser categories pass more candidates through.
        """
        density = self._density.get(category, 0.5)
        # Generate more spiral points than needed -- filter down
        oversample = int(count / max(density, 0.05))
        spiral = self.golden_spiral(oversample, radius, cx, cy)
        result = []
        for x, y in spiral:
            field = self.perlin(x * 0.05, y * 0.05)
            if field >= (1.0 - density):
                result.append((x, y))
        return result

    def place(self, cx, cy, radius, category, count, terrain,
              moisture=0.5, heat=0.4):
        """
        Full three-stage placement pipeline.
        Returns list of dicts with x, y, z, weight, category.

        Stage 1: Golden spiral candidates
        Stage 2: Perlin field filter
        Stage 3: Gaussian attunement gate (via terrain)
        """
        from core.systems.entropy_engine import EntropyEngine
        entropy = EntropyEngine()
        spiral_pts = self.golden_spiral(count * 8, radius, cx, cy)
        results = []
        for x, y in spiral_pts:
            if len(results) >= count:
                break
            # Stage 2 -- Perlin field
            field = self.perlin(x * 0.05, y * 0.05)
            density = self._density.get(category, 0.5)
            if field < (1.0 - density):
                continue
            # Stage 3 -- terrain + ecological gate
            gz = terrain.height_at(x, y)
            dx, dy = terrain.slope_direction(x, y)
            slope = min(1.0, math.sqrt(
                ((terrain.height_at(x+5, y) - gz)/5)**2 +
                ((terrain.height_at(x, y+5) - gz)/5)**2
            ))
            # Weight from local conditions
            elev_score  = max(0.0, 1.0 - abs(gz) / 20.0)
            moist_score = moisture
            slope_score = max(0.0, 1.0 - slope)
            weight = (elev_score * 0.4 + moist_score * 0.3
                      + slope_score * 0.3) * field
            if weight < 0.1:
                continue
            results.append({
                'x':        round(x, 2),
                'y':        round(y, 2),
                'z':        round(gz, 2),
                'weight':   round(weight, 4),
                'category': category,
            })
        return results