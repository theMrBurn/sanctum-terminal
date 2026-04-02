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
        self._plane_size = 200.0
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
        """Cavern sediment floor — compacted dirt with embedded gravel.

        Natural cave floor: water-deposited sediment, loose gravel,
        worn pebbles half-buried in dirt. Cool blue-gray tone to match
        the real ground's palette interaction.
        """
        floor = palette.get("stage_floor", (0.08, 0.06, 0.05))
        # Cool-shifted to match real ground's blue-gray tone
        base_r = floor[0] * 1.2 + 0.03
        base_g = floor[1] * 1.3 + 0.04
        base_b = floor[2] * 1.5 + 0.05

        tile = self._tile_size

        n_sed1 = PerlinNoise2(0.6, 0.6, 256, seed)
        n_sed2 = PerlinNoise2(1.5, 1.5, 256, seed + 200)
        n_grit = PerlinNoise2(4.0, 4.0, 256, seed + 700)
        n_peb = PerlinNoise2(8.0, 8.0, 256, seed + 400)
        n_color = PerlinNoise2(0.4, 0.4, 256, seed)
        n_warm = PerlinNoise2(0.7, 0.7, 256, seed + 50)
        n_crack = PerlinNoise2(3.0, 3.0, 256, seed + 800)

        img = PNMImage(size, size, 3)
        for y in range(size):
            for x in range(size):
                wx = (x / size) * tile
                wy = (y / size) * tile

                sed = (n_sed1(wx, wy) + 1.0) * 0.5
                sed2 = (n_sed2(wx, wy) + 1.0) * 0.5
                cdrift = (n_color(wx, wy)) * 0.06
                wdrift = (n_warm(wx, wy)) * 0.04

                r = base_r + sed * 0.06 + sed2 * 0.03 + cdrift + wdrift
                g = base_g + sed * 0.05 + sed2 * 0.02 + cdrift
                b = base_b + sed * 0.04 + sed2 * 0.015 + cdrift - wdrift * 0.3

                # Hairline cracks
                crack = abs(n_crack(wx, wy))
                if crack < 0.06:
                    dark = 1.0 - (0.06 - crack) * 8.0
                    r *= max(0.4, dark)
                    g *= max(0.4, dark)
                    b *= max(0.4, dark)

                # Fine grit
                grit = (n_grit(wx, wy) + 1.0) * 0.5
                r += (grit - 0.5) * 0.05
                g += (grit - 0.5) * 0.04
                b += (grit - 0.5) * 0.03

                # Embedded pebbles
                peb = n_peb(wx, wy)
                if peb > 0.55:
                    peb_str = min(1.0, (peb - 0.55) * 3.0)
                    pv = (n_color(wx * 3, wy * 3)) * 0.04
                    pr = base_r * 1.6 + peb_str * 0.08 + pv
                    pg = base_g * 1.5 + peb_str * 0.06 + pv
                    pb = base_b * 1.4 + peb_str * 0.04 - pv * 0.3
                    t = peb_str * 0.7
                    r = r * (1 - t) + pr * t
                    g = g * (1 - t) + pg * t
                    b = b * (1 - t) + pb * t

                # Sediment depressions
                if sed < 0.3:
                    dark_t = (0.3 - sed) * 1.5
                    r *= (1.0 - dark_t * 0.4)
                    g *= (1.0 - dark_t * 0.4)
                    b *= (1.0 - dark_t * 0.35)

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
