"""
tests/test_config_engine.py

ConfigEngine + ConfigNode — watchers, dot-access, TOML round-trip.
Tests the live config pipeline that drives all engine parameters.
"""

import os
import tempfile

import pytest

from core.systems.config_engine import ConfigEngine, ConfigNode


# -- ConfigNode basics --------------------------------------------------------

class TestConfigNodeAccess:
    """Dot-access, nested sections, error on missing keys."""

    def test_scalar_access(self):
        node = ConfigNode({"fov": 65.0, "near": 0.5})
        assert node.fov == 65.0

    def test_nested_access(self):
        node = ConfigNode({"fog": {"near": 25.0, "far": 55.0}})
        assert node.fog.near == 25.0

    def test_deep_nested_access(self):
        node = ConfigNode({"lighting": {"torch": {"fov": 55, "flicker": {"intensity": 0.15}}}})
        assert node.lighting.torch.flicker.intensity == 0.15

    def test_missing_key_raises(self):
        node = ConfigNode({"fov": 65.0})
        with pytest.raises(AttributeError):
            _ = node.nonexistent

    def test_list_access(self):
        node = ConfigNode({"color": [0.1, 0.2, 0.3]})
        assert node.color[1] == 0.2

    def test_set_scalar(self):
        node = ConfigNode({"fov": 65.0})
        node.fov = 75.0
        assert node.fov == 75.0

    def test_set_nested(self):
        node = ConfigNode({"fog": {"near": 25.0}})
        node.fog.near = 30.0
        assert node.fog.near == 30.0


# -- ConfigNode watchers -----------------------------------------------------

class TestConfigNodeWatchers:
    """Watchers fire on matching config changes."""

    def test_watcher_fires_on_exact_match(self):
        fired = []
        node = ConfigNode({"fog": {"near": 25.0}})
        node.watch("fog", lambda p, v: fired.append((p, v)))
        node.fog.near = 30.0
        assert len(fired) == 1
        assert fired[0] == ("fog.near", 30.0)

    def test_watcher_fires_on_prefix_match(self):
        fired = []
        node = ConfigNode({"lighting": {"torch": {"fov": 55}}})
        node.watch("lighting", lambda p, v: fired.append(p))
        node.lighting.torch.fov = 65
        assert "lighting.torch.fov" in fired

    def test_watcher_star_matches_all(self):
        fired = []
        node = ConfigNode({"fog": {"near": 25.0}, "camera": {"fov": 65.0}})
        node.watch("*", lambda p, v: fired.append(p))
        node.fog.near = 30.0
        node.camera.fov = 75.0
        assert len(fired) == 2

    def test_watcher_does_not_fire_on_mismatch(self):
        fired = []
        node = ConfigNode({"fog": {"near": 25.0}, "camera": {"fov": 65.0}})
        node.watch("camera", lambda p, v: fired.append(p))
        node.fog.near = 30.0
        assert len(fired) == 0

    def test_multiple_watchers(self):
        fog_fired = []
        cam_fired = []
        node = ConfigNode({"fog": {"near": 25.0}, "camera": {"fov": 65.0}})
        node.watch("fog", lambda p, v: fog_fired.append(p))
        node.watch("camera", lambda p, v: cam_fired.append(p))
        node.fog.near = 30.0
        node.camera.fov = 75.0
        assert len(fog_fired) == 1
        assert len(cam_fired) == 1

    def test_watcher_receives_new_value(self):
        values = []
        node = ConfigNode({"postprocess": {"bloom_intensity": 0.3}})
        node.watch("postprocess", lambda p, v: values.append(v))
        node.postprocess.bloom_intensity = 0.7
        assert values[0] == 0.7


# -- ConfigNode dot-path helpers ----------------------------------------------

class TestConfigNodeDotPath:
    """_get_nested / _set_nested for REPL string-based access."""

    def test_get_nested(self):
        node = ConfigNode({"lighting": {"torch": {"fov": 55}}})
        assert node._get_nested("lighting.torch.fov") == 55

    def test_set_nested(self):
        node = ConfigNode({"lighting": {"torch": {"fov": 55}}})
        node._set_nested("lighting.torch.fov", 65)
        assert node.lighting.torch.fov == 65

    def test_set_nested_fires_watcher(self):
        fired = []
        node = ConfigNode({"lighting": {"torch": {"fov": 55}}})
        node.watch("lighting.torch", lambda p, v: fired.append(v))
        node._set_nested("lighting.torch.fov", 65)
        assert 65 in fired


# -- ConfigEngine TOML loading ------------------------------------------------

class TestConfigEngineLoad:
    """Load sanctum.toml, verify structure matches what cavern2 expects."""

    @pytest.fixture
    def cfg(self):
        return ConfigEngine("config/sanctum.toml")

    def test_fog_section_exists(self, cfg):
        assert cfg.fog.near > 0
        assert cfg.fog.far > cfg.fog.near

    def test_fog_night_deltas(self, cfg):
        assert cfg.fog.night_near_delta < 0
        assert cfg.fog.night_far_delta < 0

    def test_camera_section(self, cfg):
        assert cfg.camera.fov > 0
        assert cfg.camera.near_clip > 0
        assert cfg.camera.far_clip > cfg.camera.near_clip
        assert len(cfg.camera.background) == 3

    def test_torch_section(self, cfg):
        t = cfg.lighting.torch
        assert t.fov > 0
        assert len(t.color_mult) == 3
        assert len(t.attenuation) == 3
        assert t.shadow_size > 0
        assert len(t.position) == 3
        assert len(t.look_at) == 3

    def test_torch_flicker(self, cfg):
        fl = cfg.lighting.torch.flicker
        assert fl.intensity > 0
        assert fl.amplitude > 0
        assert fl.freq1 > 0
        assert fl.freq2 > 0
        assert len(fl.color_mult) == 3

    def test_torch_bob(self, cfg):
        bob = cfg.lighting.torch.bob
        for axis in ["x", "y", "z"]:
            a = getattr(bob, axis)
            assert "freq" in a
            assert "amp" in a

    def test_fill_light(self, cfg):
        f = cfg.lighting.fill
        assert len(f.color_mult) == 3
        assert len(f.attenuation) == 3

    def test_orb_marker(self, cfg):
        om = cfg.lighting.orb_marker
        assert om.size > 0
        assert len(om.color) == 3
        assert len(om.glow) == 3

    def test_postprocess_section(self, cfg):
        pp = cfg.postprocess
        assert 0 <= pp.bloom_intensity <= 2.0
        assert len(pp.bloom_blend) == 4
        assert len(pp.bloom_trigger) == 2
        assert 0 <= pp.bloom_desat <= 1.0

    def test_lod_section(self, cfg):
        l = cfg.lod
        assert l.wake_radius > 0
        assert l.sleep_radius > l.wake_radius
        assert 0 < l.band_mid_ratio < 1
        assert 0 < l.band_near_ratio < l.band_mid_ratio

    def test_ambient_section(self, cfg):
        a = cfg.lighting.ambient
        assert len(a.color) == 3
        assert 0 < a.night_dim < 1

    def test_daylight_section(self, cfg):
        dl = cfg.daylight
        assert len(dl.ambient) == 3
        assert len(dl.fog_color) == 3
        assert dl.fog_far > dl.fog_near
        assert dl.far_clip > dl.fog_far

    def test_ground_section(self, cfg):
        g = cfg.ground
        assert g.subdivisions > 0
        assert g.normal_perturb > 0


# -- ConfigEngine save/load round-trip ----------------------------------------

class TestConfigEngineRoundTrip:
    """Save to temp file, reload, values survive."""

    def test_round_trip(self):
        cfg = ConfigEngine("config/sanctum.toml")
        original_fov = cfg.camera.fov
        cfg.camera.fov = 90.0

        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            tmp = f.name
        try:
            cfg.save(tmp)
            cfg2 = ConfigEngine(tmp)
            assert cfg2.camera.fov == 90.0
            # Other values survived
            assert cfg2.fog.near == cfg.fog.near
        finally:
            os.unlink(tmp)

    def test_watchers_survive_reload(self):
        cfg = ConfigEngine("config/sanctum.toml")
        fired = []
        cfg.root.watch("fog", lambda p, v: fired.append(v))

        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            tmp = f.name
        try:
            cfg.save(tmp)
            cfg.load(tmp)
            cfg.fog.near = 99.0
            assert 99.0 in fired
        finally:
            os.unlink(tmp)


# -- Glow card texture isolation (the magenta fix) ----------------------------

panda3d = pytest.importorskip("panda3d.core", reason="panda3d not installed")


class TestGlowCardTextureIsolation:
    """Glow card must block parent texture inheritance to avoid magenta."""

    def test_set_texture_off_blocks_parent(self):
        from panda3d.core import (
            NodePath, CardMaker, TextureStage, TexGenAttrib,
            Texture, PNMImage, SamplerState,
        )
        from core.systems.membrane import _get_decal_texture

        # Simulate entity parent with MModulate + TexGen (like ambient_life builders)
        parent = NodePath("entity")
        ts = TextureStage("mat")
        ts.setMode(TextureStage.MModulate)

        # Create a small dummy texture for the parent
        img = PNMImage(4, 4, 3)
        parent_tex = Texture("parent_mat")
        parent_tex.load(img)
        parent.setTexture(ts, parent_tex)
        parent.setTexGen(ts, TexGenAttrib.MWorldPosition)

        # Create glow card as child — WITH the fix
        cm = CardMaker("glow")
        cm.setFrame(-1, 1, -1, 1)
        card = parent.attachNewNode(cm.generate())
        card.setTextureOff()  # THE FIX — blocks parent's MModulate stage
        card.setTexture(_get_decal_texture(64))

        # Card should have exactly one texture (the decal), not the parent's
        state = card.getNetState()
        tex_attrib = state.getAttrib(24)  # TextureAttrib type index
        # The card's own texture should be the decal, not the parent's
        own_tex = card.getTexture()
        assert own_tex is not None
        assert own_tex.getName() == "glow_decal"

    def test_without_fix_inherits_parent_stage(self):
        from panda3d.core import (
            NodePath, CardMaker, TextureStage, TexGenAttrib,
            Texture, PNMImage,
        )

        # Same parent setup
        parent = NodePath("entity")
        ts = TextureStage("mat")
        ts.setMode(TextureStage.MModulate)
        img = PNMImage(4, 4, 3)
        parent_tex = Texture("parent_mat")
        parent_tex.load(img)
        parent.setTexture(ts, parent_tex)
        parent.setTexGen(ts, TexGenAttrib.MWorldPosition)

        # Child WITHOUT setTextureOff — inherits parent's stage
        cm = CardMaker("glow_broken")
        cm.setFrame(-1, 1, -1, 1)
        card = parent.attachNewNode(cm.generate())
        # No setTextureOff() — this is the bug
        card.setTexture(Texture("decal"))

        # The card's net state includes the parent's "mat" stage
        net_state = card.getNetState()
        # Parent's texture stage leaks through
        assert parent.getTexture(ts) is not None
