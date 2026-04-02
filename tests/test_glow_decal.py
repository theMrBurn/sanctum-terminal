"""
tests/test_glow_decal.py

Regression tests for glow decal textures and light casting.
Pure logic — no display, no GPU.
"""

import math
import pytest

from core.systems.glow_decal import (
    get_glow_texture, get_shaft_texture,
    get_mote_shaft_texture, get_ceiling_blob_texture,
)


# -- Circular falloff (no square edges) ----------------------------------------

class TestGlowTextureShape:
    """The glow texture must be circular, not square.
    Corners and edges beyond the inscribed circle must be fully transparent."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Each test gets a fresh texture — no cache hits."""
        from core.systems.glow_decal import _glow_tex_cache
        _glow_tex_cache.clear()
        yield
        _glow_tex_cache.clear()

    def _read_alpha(self, tex, x, y):
        """Read alpha from a Panda3D Texture at pixel (x, y)."""
        from panda3d.core import PNMImage
        img = PNMImage()
        tex.store(img)
        return img.getAlpha(x, y)

    def test_center_is_opaque(self):
        tex = get_glow_texture(64)
        alpha = self._read_alpha(tex, 32, 32)
        assert alpha > 0.8, f"Center alpha {alpha} should be nearly opaque"

    def test_corners_are_transparent(self):
        """Corners of the texture quad must be zero — no visible rectangle."""
        tex = get_glow_texture(64)
        corners = [(0, 0), (63, 0), (0, 63), (63, 63)]
        for cx, cy in corners:
            alpha = self._read_alpha(tex, cx, cy)
            assert alpha < 0.01, f"Corner ({cx},{cy}) alpha={alpha}, must be ~0"

    def test_edge_midpoints_are_transparent(self):
        """Edge midpoints are at distance 1.0 from center — must be zero."""
        tex = get_glow_texture(64)
        edges = [(0, 32), (63, 32), (32, 0), (32, 63)]
        for ex, ey in edges:
            alpha = self._read_alpha(tex, ex, ey)
            assert alpha < 0.05, f"Edge ({ex},{ey}) alpha={alpha}, must be ~0"

    def test_falloff_is_monotonic(self):
        """Alpha must decrease as distance from center increases."""
        tex = get_glow_texture(64)
        center = 32
        prev_alpha = self._read_alpha(tex, center, center)
        # Walk from center toward edge along X axis
        for x in range(center + 2, 60, 3):
            alpha = self._read_alpha(tex, x, center)
            assert alpha <= prev_alpha + 0.02, (
                f"Alpha at x={x} ({alpha}) > alpha at previous ({prev_alpha})"
            )
            prev_alpha = alpha

    def test_circular_symmetry(self):
        """Points at same distance from center should have similar alpha."""
        tex = get_glow_texture(64)
        center = 32
        # Sample at 45-degree increments, radius ~15 pixels
        r = 15
        alphas = []
        for angle_deg in range(0, 360, 45):
            rad = math.radians(angle_deg)
            x = int(center + r * math.cos(rad))
            y = int(center + r * math.sin(rad))
            alphas.append(self._read_alpha(tex, x, y))
        spread = max(alphas) - min(alphas)
        assert spread < 0.15, f"Circular symmetry broken: spread={spread}"

    def test_wet_stone_surface_has_pattern(self):
        """wet_stone texture should have brightness variation (caustics)."""
        tex = get_glow_texture(64, surface="wet_stone")
        from panda3d.core import PNMImage
        img = PNMImage()
        tex.store(img)
        # Sample brightness across the bright center region
        brightnesses = []
        for x in range(20, 44):
            r, g, b = img.getXel(x, 32)
            brightnesses.append(r)
        spread = max(brightnesses) - min(brightnesses)
        assert spread > 0.01, "wet_stone should have visible caustic variation"

    def test_smooth_surface_uniform_brightness(self):
        """smooth texture should have uniform RGB=1.0 in the bright zone."""
        tex = get_glow_texture(64, surface="smooth")
        from panda3d.core import PNMImage
        img = PNMImage()
        tex.store(img)
        r, g, b = img.getXel(32, 32)
        assert abs(r - 1.0) < 0.01
        assert abs(g - 1.0) < 0.01
        assert abs(b - 1.0) < 0.01


# -- Glow texture caching ------------------------------------------------------

class TestGlowTextureCache:

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        from core.systems.glow_decal import _glow_tex_cache
        _glow_tex_cache.clear()
        yield
        _glow_tex_cache.clear()

    def test_same_params_return_same_object(self):
        t1 = get_glow_texture(64)
        t2 = get_glow_texture(64)
        assert t1 is t2

    def test_different_size_returns_different(self):
        t1 = get_glow_texture(64)
        t2 = get_glow_texture(128)
        assert t1 is not t2

    def test_different_surface_returns_different(self):
        t1 = get_glow_texture(64, surface="smooth")
        t2 = get_glow_texture(64, surface="wet_stone")
        assert t1 is not t2


# -- Shaft texture -------------------------------------------------------------

class TestShaftTexture:

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        from core.systems.glow_decal import _shaft_tex_cache
        _shaft_tex_cache.clear()
        yield
        _shaft_tex_cache.clear()

    def test_bottom_brighter_than_top(self):
        """Shaft must be bright at bottom, dark at top."""
        tex = get_shaft_texture(32, 64)
        from panda3d.core import PNMImage
        img = PNMImage()
        tex.store(img)
        # PNMImage Y=0 is top of image, Y=63 is bottom.
        # Shaft texture: bright at bottom (high Y), dark at top (low Y).
        bottom_r, _, _ = img.getXel(16, 4)   # image top = shaft bottom (bright)
        top_r, _, _ = img.getXel(16, 60)     # image bottom = shaft top (dark)
        assert bottom_r > top_r * 2, "Bottom should be much brighter than top"

    def test_center_brighter_than_edges(self):
        """Shaft center column should be brighter than sides."""
        tex = get_shaft_texture(32, 64)
        from panda3d.core import PNMImage
        img = PNMImage()
        tex.store(img)
        mid_y = 48  # lower half where there's brightness
        center_r, _, _ = img.getXel(16, mid_y)
        edge_r, _, _ = img.getXel(2, mid_y)
        assert center_r > edge_r * 1.5


# -- Mote shaft texture (baked particles) --------------------------------------

class TestMoteShaftTexture:

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        from core.systems.glow_decal import _mote_shaft_cache
        _mote_shaft_cache.clear()
        yield
        _mote_shaft_cache.clear()

    def test_has_bright_specks(self):
        """Mote shaft should have pixels brighter than the base gradient."""
        tex = get_mote_shaft_texture(32, 128, seed=42)
        from panda3d.core import PNMImage
        img = PNMImage()
        tex.store(img)
        # Get the base shaft texture for comparison
        base = get_shaft_texture(32, 128)
        base_img = PNMImage()
        base.store(base_img)
        # Find pixels where mote version is brighter than base
        brighter_count = 0
        for y in range(128):
            for x in range(32):
                mr, _, _ = img.getXel(x, y)
                br, _, _ = base_img.getXel(x, y)
                if mr > br + 0.1:
                    brighter_count += 1
        assert brighter_count > 5, f"Only {brighter_count} mote pixels found"

    def test_base_gradient_intact(self):
        """Mote shaft should still be bright at bottom, dark at top."""
        tex = get_mote_shaft_texture(32, 128, seed=42)
        from panda3d.core import PNMImage
        img = PNMImage()
        tex.store(img)
        bottom_r, _, _ = img.getXel(16, 4)
        top_r, _, _ = img.getXel(16, 124)
        assert bottom_r > top_r

    def test_different_seeds_different_motes(self):
        t1 = get_mote_shaft_texture(32, 128, seed=1)
        t2 = get_mote_shaft_texture(32, 128, seed=99)
        assert t1 is not t2

    def test_cache_works(self):
        t1 = get_mote_shaft_texture(32, 128, seed=42)
        t2 = get_mote_shaft_texture(32, 128, seed=42)
        assert t1 is t2


# -- Ceiling blob billboard texture --------------------------------------------

class TestCeilingBlobTexture:

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        from core.systems.glow_decal import _blob_tex_cache
        _blob_tex_cache.clear()
        yield
        _blob_tex_cache.clear()

    def test_center_is_opaque(self):
        tex = get_ceiling_blob_texture(64)
        from panda3d.core import PNMImage
        img = PNMImage()
        tex.store(img)
        alpha = img.getAlpha(32, 32)
        assert alpha > 0.5, f"Center alpha {alpha} should be bright"

    def test_corners_are_transparent(self):
        tex = get_ceiling_blob_texture(64)
        from panda3d.core import PNMImage
        img = PNMImage()
        tex.store(img)
        for cx, cy in [(0, 0), (63, 0), (0, 63), (63, 63)]:
            alpha = img.getAlpha(cx, cy)
            assert alpha < 0.01, f"Corner ({cx},{cy}) alpha={alpha}"

    def test_warm_tint(self):
        """Blob should be warm-tinted: R > G > B."""
        tex = get_ceiling_blob_texture(64)
        from panda3d.core import PNMImage
        img = PNMImage()
        tex.store(img)
        r, g, b = img.getXel(32, 32)
        assert r > g > b, f"Expected warm tint, got r={r} g={g} b={b}"

    def test_cache_works(self):
        t1 = get_ceiling_blob_texture(64)
        t2 = get_ceiling_blob_texture(64)
        assert t1 is t2
