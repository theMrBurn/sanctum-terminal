"""
core/systems/fake_ground.py

WorldRunner ground — flat card, sediment texture, self-lit. Performance mode.

The geometric relief approach doesn't work with setLightOff() on Metal —
normals can't shade faces, so displaced vertices create stripe artifacts.
Instead: a high-quality sediment texture with baked brightness variation
that sells depth through contrast and parallax-free visual cues.

Usage:
    ground = FakeGround(render, palette, chunk_seed=42)
    ground.update(camera_x, camera_y)  # call each frame — repositions plane
    ground.hide() / ground.show()      # A/B toggle
"""

import math
import random
from panda3d.core import (
    CardMaker, Vec4, Texture, PNMImage, SamplerState, TextureStage,
    PerlinNoise2,
)


class FakeGround:
    """Flat ground plane with high-detail sediment texture. One draw call."""

    def __init__(self, render_node, palette, chunk_seed=42, tile_size=16.0):
        self._render = render_node
        self._tile_size = tile_size
        self._plane_size = 300.0  # must exceed camera far (45m) at any pitch angle
        half = self._plane_size / 2.0

        # Pre-bake cavern sediment texture ONCE
        tex = self._bake_tiling_texture(palette, chunk_seed)

        # Single CardMaker quad — proven texture path
        cm = CardMaker("fake_ground")
        cm.setFrame(-half, half, -half, half)
        cm.setHasUvs(True)
        self._node = render_node.attachNewNode(cm.generate())
        self._node.setP(-90)  # lay flat
        self._node.setPos(0, 0, 0)
        self._node.setTexture(tex)
        tiles = self._plane_size / self._tile_size
        self._node.setTexScale(TextureStage.getDefault(), tiles, tiles)
        # Self-lit, single-sided
        self._node.setLightOff()
        self._node.setColorScale(0.55, 0.50, 0.45, 1.0)
        self._node.setBin("background", 0)

        # Camera bob state
        self._bob_phase = 0.0

    def _bake_tiling_texture(self, palette, seed, size=256):
        """Cavern floor — Voronoi cells from WORLD_GRAIN, dark negative space.

        Same visual DNA as object textures: Voronoi cell grid defines
        sediment islands, gaps between cells are true dark negative space
        (erosion channels). The WORLD_GRAIN root value drives cell density
        so floor and objects share the same visual language.
        """
        floor = palette.get("stage_floor", (0.08, 0.06, 0.05))
        base_r = floor[0] * 1.2 + 0.03
        base_g = floor[1] * 1.3 + 0.04
        base_b = floor[2] * 1.5 + 0.05

        # Dark negative space — true black-ish, not just "dimmer"
        dark_r, dark_g, dark_b = 0.02, 0.018, 0.022

        tile = self._tile_size
        # Cell size from WORLD_GRAIN — same visual rhythm as object textures
        # Ground cells are larger (÷ 0.08 ratio) because we're looking straight down
        cell_size = 0.80  # meters per cell in world space

        rng = __import__("random").Random(seed)

        # Generate jittered Voronoi cell centers across the tile + overscan
        overscan = cell_size * 2
        cells = []
        cell_colors = []
        n_color = PerlinNoise2(0.4, 0.4, 256, seed)
        n_warm = PerlinNoise2(0.7, 0.7, 256, seed + 50)

        gx = -overscan
        while gx < tile + overscan:
            gy = -overscan
            while gy < tile + overscan:
                jx = rng.uniform(-0.4, 0.4) * cell_size
                jy = rng.uniform(-0.4, 0.4) * cell_size
                wx, wy = gx + jx, gy + jy
                cells.append((wx, wy))
                # Per-cell color variation
                n = (n_color(wx, wy) + 1.0) * 0.5
                v = (n - 0.5) * 0.08
                w = (n_warm(wx, wy) + 1.0) * 0.5
                warm = (w - 0.5) * 0.04
                cell_colors.append((
                    base_r + v + warm,
                    base_g + v,
                    base_b + v - warm * 0.3,
                ))
                gy += cell_size
            gx += cell_size

        # Spatial hash for fast lookup
        bucket_size = cell_size * 1.5
        buckets = {}
        for ci, (ccx, ccy) in enumerate(cells):
            bx = int(math.floor(ccx / bucket_size))
            by = int(math.floor(ccy / bucket_size))
            key = (bx, by)
            if key not in buckets:
                buckets[key] = []
            buckets[key].append(ci)

        n_grit = PerlinNoise2(4.0, 4.0, 256, seed + 700)
        mortar_width = cell_size * 0.18  # gap between cells = negative space

        img = PNMImage(size, size, 3)
        for y in range(size):
            for x in range(size):
                px = (x / size) * tile
                py = (y / size) * tile

                # Find nearest two Voronoi cells
                bx = int(math.floor(px / bucket_size))
                by = int(math.floor(py / bucket_size))
                min_d1, min_d2 = 999.0, 999.0
                min_ci = 0
                for dbx in range(-1, 2):
                    for dby in range(-1, 2):
                        for ci in buckets.get((bx + dbx, by + dby), ()):
                            ccx, ccy = cells[ci]
                            for ox in (-tile, 0, tile):
                                for oy in (-tile, 0, tile):
                                    ddx = px - (ccx + ox)
                                    ddy = py - (ccy + oy)
                                    d = ddx * ddx + ddy * ddy
                                    if d < min_d1:
                                        min_d2 = min_d1
                                        min_d1 = d
                                        min_ci = ci
                                    elif d < min_d2:
                                        min_d2 = d

                min_d1 = math.sqrt(min_d1)
                min_d2 = math.sqrt(min_d2)
                # Edge distance — how close to the cell boundary
                edge_dist = (min_d2 - min_d1) * 0.5

                cr, cg, cb = cell_colors[min_ci % len(cell_colors)]

                if edge_dist < mortar_width:
                    # Negative space — true dark, not just dimmer
                    t = edge_dist / mortar_width  # 0=deep, 1=edge
                    t = t * t  # ease-in
                    r = dark_r * (1 - t) + cr * t
                    g = dark_g * (1 - t) + cg * t
                    b = dark_b * (1 - t) + cb * t
                else:
                    # Cell surface — sediment island
                    grit = (n_grit(px, py) + 1.0) * 0.5
                    r = cr + (grit - 0.5) * 0.04
                    g = cg + (grit - 0.5) * 0.03
                    b = cb + (grit - 0.5) * 0.02

                img.setXel(x, y,
                           max(0.0, min(1.0, r)),
                           max(0.0, min(1.0, g)),
                           max(0.0, min(1.0, b)))

        tex = Texture("fake_ground_tile")
        tex.load(img)
        tex.setMagfilter(SamplerState.FT_nearest)
        tex.setMinfilter(SamplerState.FT_nearest)
        tex.setWrapU(SamplerState.WM_repeat)
        tex.setWrapV(SamplerState.WM_repeat)
        return tex

    def update(self, cam_x, cam_y, dt=0, moving=False):
        """Reposition plane centered on camera. Texture stays world-locked."""
        self._node.setPos(cam_x, cam_y, 0)
        half = self._plane_size / 2.0
        u_offset = (cam_x - half) / self._tile_size
        v_offset = (cam_y - half) / self._tile_size
        self._node.setTexOffset(TextureStage.getDefault(), u_offset, v_offset)

        # Camera bob
        if moving and dt > 0:
            self._bob_phase += dt * 6.0
            return math.sin(self._bob_phase) * 0.06
        else:
            self._bob_phase *= 0.9
            return math.sin(self._bob_phase) * 0.06 * 0.5

    def show(self):
        self._node.show()

    def hide(self):
        self._node.hide()

    @property
    def node(self):
        return self._node
