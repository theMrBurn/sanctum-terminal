"""
core/systems/fake_ground.py

WorldRunner ground — one flat plane, one tiling texture, scrolls with camera.
Fog hides the edges. Height is an illusion (camera bob). Zero per-frame Perlin.

The plane is 96×96m centered on the player. Texture tiles at CHUNK_SIZE intervals
so it looks identical to the real chunked ground through the fog.

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
    """Single infinite-feeling ground plane. One draw call. Zero Perlin per frame."""

    def __init__(self, render_node, palette, chunk_seed=42, tile_size=16.0):
        self._render = render_node
        self._tile_size = tile_size
        # Plane covers 96×96m — fog eats at 42m, so edges are invisible
        self._plane_size = 96.0
        half = self._plane_size / 2.0

        # Pre-bake a tiling cobblestone texture ONCE
        tex = self._bake_tiling_texture(palette, chunk_seed)

        # Single CardMaker quad — one draw call
        cm = CardMaker("fake_ground")
        cm.setFrame(-half, half, -half, half)
        cm.setHasUvs(True)
        self._node = render_node.attachNewNode(cm.generate())
        self._node.setP(-90)  # lay flat
        self._node.setPos(0, 0, 0)
        self._node.setTexture(tex)
        # Tile the texture across the plane
        tiles = self._plane_size / self._tile_size
        self._node.setTexScale(TextureStage.getDefault(), tiles, tiles)
        self._node.setTwoSided(True)
        # Receive ambient light (the only light that works on Metal)
        # but don't interfere with decals
        self._node.setBin("background", 0)

        # Camera bob state — sells uneven ground without geometry
        self._bob_phase = 0.0
        self._bob_active = False

    def _bake_tiling_texture(self, palette, seed, size=256):
        """Pre-bake a cobblestone texture that tiles seamlessly.

        Uses the same Perlin noise as the real ground generator but
        renders once at startup, not per-chunk per-frame.
        """
        # Floor base color — brighter than palette suggests.
        # Dark enough to feel like a cave, bright enough that glow decals
        # reveal surface detail (cracks, dust, wet patches) underneath.
        # Oblivion trick: the floor has visible detail at ambient level.
        floor_color = palette.get("stage_floor", (0.08, 0.06, 0.05))
        dr = floor_color[0] * 1.8
        dg = floor_color[1] * 1.6
        db = floor_color[2] * 1.4

        # Noise generators (same seeds as cavern.py for visual match)
        n_stone = PerlinNoise2(5.0, 5.0, 256, seed)
        n_color = PerlinNoise2(0.4, 0.4, 256, seed)
        n_warm = PerlinNoise2(0.7, 0.7, 256, seed + 50)
        n_grit = PerlinNoise2(1.8, 1.8, 256, seed + 700)
        n_dirt1 = PerlinNoise2(0.8, 0.8, 256, seed)

        img = PNMImage(size, size, 3)
        scale = self._tile_size / size  # world units per pixel

        for py in range(size):
            for px in range(size):
                wx = px * scale
                wy = py * scale

                # Base dirt color with variation
                cv = n_color(wx, wy) * 0.10
                wv = n_warm(wx, wy) * 0.06
                r = dr + cv + wv
                g = dg + cv
                b = db + cv - wv * 0.5

                # Stone cell boundaries (Voronoi-like from Perlin)
                stone = abs(n_stone(wx, wy))
                if stone < 0.15:
                    # Mortar line — darker
                    r *= 0.6
                    g *= 0.6
                    b *= 0.6

                # Dirt patches
                dirt = n_dirt1(wx, wy)
                if dirt > 0.3:
                    boost = (dirt - 0.3) * 0.15
                    r += boost * 0.55
                    g += boost * 0.50
                    b += boost * 0.45

                # Grit
                grit = n_grit(wx, wy)
                if grit > 0.35:
                    r += 0.02
                    g += 0.015
                    b += 0.01

                # Baked bumps — brightness variation reads as surface relief
                bump = n_stone(wx * 3, wy * 3) * 0.06
                r += bump
                g += bump
                b += bump

                # Wet patches — slightly darker, slightly blue-shifted
                # These catch glow decals and read as damp reflections
                wet = n_dirt1(wx * 1.5, wy * 1.5)
                if wet > 0.4:
                    wet_amt = (wet - 0.4) * 0.3
                    r -= wet_amt * 0.02
                    g -= wet_amt * 0.01
                    b += wet_amt * 0.02  # blue shift = damp

                # Fine dust — high frequency brightness noise
                dust = n_grit(wx * 4, wy * 4) * 0.03
                r += dust
                g += dust
                b += dust * 0.8

                img.setXel(px, py,
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
        """Reposition plane to follow camera. Optionally bob for height illusion."""
        # Snap to tile grid so texture doesn't slide
        snap_x = math.floor(cam_x / self._tile_size) * self._tile_size
        snap_y = math.floor(cam_y / self._tile_size) * self._tile_size
        self._node.setPos(snap_x, snap_y, 0)

        # Camera bob — only when moving, subtle sine
        if moving and dt > 0:
            self._bob_phase += dt * 6.0  # ~6 Hz bob
            return math.sin(self._bob_phase) * 0.06  # ±6cm height variation
        else:
            # Decay bob to zero
            self._bob_phase *= 0.9
            return math.sin(self._bob_phase) * 0.06 * 0.5

    def show(self):
        self._node.show()

    def hide(self):
        self._node.hide()

    @property
    def node(self):
        return self._node
