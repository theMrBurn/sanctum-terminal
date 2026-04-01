"""
core/systems/membrane.py

Fake-everything visual overlay system. PS2-era philosophy:
paint the result, don't compute it.

- Ground decals instead of point lights (colored circle texture on floor)
- Motes on Panda3D intervals (C++ movement, Python never touches after spawn)
- Self-lit objects only (setLightOff + colorScale)

Usage:
    membrane = Membrane(render_node)
    # Instead of a point light:
    membrane.add_glow(pos=(10, 20, 0), color=(0.4, 0.1, 0.5), radius=8.0)
    # Instead of Python-ticked motes:
    membrane.add_motes(pos=(10, 20, 3), color=(0.4, 0.1, 0.5), count=40, cfg={...})
    # On wake/sleep:
    membrane.wake(entity_id)
    membrane.sleep(entity_id)
"""

import math
import random

from panda3d.core import (
    Vec4, NodePath, CardMaker, Texture, PNMImage,
    TransparencyAttrib, SamplerState, TextNode,
)
from direct.interval.LerpInterval import LerpPosInterval, LerpColorScaleInterval
from direct.interval.IntervalGlobal import Sequence, Func, Wait


# -- Ground decal textures (pre-baked, shared) --------------------------------

_DECAL_CACHE = {}  # radius_bucket -> Texture


def _get_decal_texture(size=64):
    """Gas-like radial glow — gaussian falloff with noise throughout. Cached."""
    if size in _DECAL_CACHE:
        return _DECAL_CACHE[size]

    import random as _rng
    noise = _rng.Random(42)  # deterministic noise
    img = PNMImage(size, size, 4)  # RGBA
    center = size / 2
    max_r = center * 0.95

    for y in range(size):
        for x in range(size):
            dx = x - center
            dy = y - center
            dist = math.sqrt(dx * dx + dy * dy)
            if dist > max_r:
                alpha = 0.0
            else:
                t = dist / max_r
                # Gaussian falloff — wide soft tail, no hard edge
                base = math.exp(-3.0 * t * t) * 0.40
                # Noise throughout — breaks up the circle, reads as gas not liquid
                base *= 0.6 + noise.random() * 0.4
                # Progressive dissolve: more holes further out
                if noise.random() < t * t * 0.5:
                    base = 0.0
                alpha = base
            img.setXelA(x, y, 1.0, 1.0, 1.0, alpha)

    tex = Texture("glow_decal")
    tex.load(img)
    tex.setMagfilter(SamplerState.FT_linear)
    tex.setMinfilter(SamplerState.FT_linear)
    tex.setWrapU(SamplerState.WM_clamp)
    tex.setWrapV(SamplerState.WM_clamp)
    _DECAL_CACHE[size] = tex
    return tex


# -- Membrane system ----------------------------------------------------------

class Membrane:
    """Fake-everything visual overlay. Zero point lights, zero per-frame Python."""

    def __init__(self, render_node):
        self._render = render_node
        self._decal_tex = _get_decal_texture(64)
        self._entries = {}  # entity_id -> {"decal": NodePath, "motes": [...], "active": bool}
        self._torch_decal = None  # player's warm ground light

    def update_torch(self, cam_pos, height_fn=None):
        """Move the player's warm ground decal to follow the camera."""
        if self._torch_decal is None:
            cm = CardMaker("torch_decal")
            r = 12.0  # warm pool radius
            cm.setFrame(-r, r, -r, r)
            self._torch_decal = self._render.attachNewNode(cm.generate())
            self._torch_decal.setTexture(self._decal_tex)
            self._torch_decal.setTransparency(TransparencyAttrib.MAlpha)
            self._torch_decal.setLightOff()
            self._torch_decal.setColorScale(1.2, 0.85, 0.4, 0.35)  # warm amber, subtle
            self._torch_decal.setP(-90)
            self._torch_decal.setBin("transparent", 11)  # on top of other decals
            self._torch_decal.setDepthWrite(False)
            self._torch_decal.setDepthOffset(2)
        cx, cy = cam_pos.getX(), cam_pos.getY()
        gz = height_fn(cx, cy) if height_fn else 0
        self._torch_decal.setPos(cx, cy, gz + 0.3)

    def register(self, entity_id, pos, glow_color, glow_radius,
                 mote_color=None, mote_count=0, mote_cfg=None):
        """Register a light source. Nothing renders until wake()."""
        self._entries[entity_id] = {
            "pos": pos,
            "glow_color": glow_color,
            "glow_radius": glow_radius,
            "mote_color": mote_color or glow_color,
            "mote_count": mote_count,
            "mote_cfg": mote_cfg or {},
            "decal": None,
            "motes": [],
            "intervals": [],
            "active": False,
        }

    def wake(self, entity_id):
        """Activate — create decal + start mote intervals."""
        entry = self._entries.get(entity_id)
        if not entry or entry["active"]:
            return
        entry["active"] = True

        pos = entry["pos"]
        r = entry["glow_radius"]
        color = entry["glow_color"]

        # Ground decal — colored circle on the floor
        cm = CardMaker(f"decal_{entity_id}")
        cm.setFrame(-r, r, -r, r)
        decal = self._render.attachNewNode(cm.generate())
        decal.setTexture(self._decal_tex)
        decal.setTransparency(TransparencyAttrib.MAlpha)
        decal.setLightOff()
        # Scale alpha by color intensity — bright colors (fungus purple) get more transparent
        # so they read as diffused light, not liquid puddles
        intensity = max(color[0], color[1], color[2])
        target_alpha = max(0.12, 0.35 - intensity * 0.25)  # bright=0.12, dim=0.35
        entry["_target_alpha"] = target_alpha
        decal.setColorScale(color[0], color[1], color[2], 0.0)  # start invisible
        # Lay flat on ground — high enough to clear chunk seams
        decal.setPos(pos[0], pos[1], pos[2] + 0.25)
        decal.setP(-90)  # face up
        decal.setBin("transparent", 10)  # render after ground, blend on top
        decal.setDepthWrite(False)  # don't cut into terrain z-buffer
        decal.setDepthOffset(1)  # bias toward camera to prevent z-fight
        entry["decal"] = decal

        # Fade in — C++ interval, zero Python per frame
        fade = LerpColorScaleInterval(
            decal, 3.0,
            Vec4(color[0], color[1], color[2], target_alpha),
            Vec4(color[0], color[1], color[2], 0.0),
        )
        fade.start()
        entry["intervals"].append(fade)

        # Motes — Panda3D intervals, zero Python per frame
        if entry["mote_count"] > 0:
            self._spawn_interval_motes(entry, pos)

    def sleep(self, entity_id):
        """Deactivate — remove decal, stop intervals, hide motes."""
        entry = self._entries.get(entity_id)
        if not entry or not entry["active"]:
            return
        entry["active"] = False

        if entry["decal"] and not entry["decal"].isEmpty():
            entry["decal"].removeNode()
        entry["decal"] = None

        for iv in entry["intervals"]:
            iv.pause()
        entry["intervals"] = []

        for m in entry["motes"]:
            if m and not m.isEmpty():
                m.removeNode()
        entry["motes"] = []

    def remove(self, entity_id):
        """Fully remove — cleanup everything."""
        self.sleep(entity_id)
        self._entries.pop(entity_id, None)

    def _spawn_interval_motes(self, entry, pos):
        """Spawn motes that move via Panda3D intervals — zero Python tick cost."""
        cfg = entry["mote_cfg"]
        rng = random.Random(hash(pos) & 0xFFFF)
        color = entry["mote_color"]
        count = entry["mote_count"]
        radius = cfg.get("radius", 3.0)
        height = cfg.get("height", 3.0)
        compress = cfg.get("float_compression", 1.0)
        downward = cfg.get("downward", False)
        ground_bias = cfg.get("ground_bias", False)

        from core.systems.geometry import make_box

        for i in range(count):
            size = rng.uniform(0.006, 0.02)
            mote = self._render.attachNewNode(
                make_box(size, size, size, color))

            # Start position
            mx = pos[0] + rng.uniform(-radius, radius)
            my = pos[1] + rng.uniform(-radius, radius)
            if ground_bias:
                mz = pos[2] + rng.uniform(0.05, height) ** 2 / height
            else:
                mz = pos[2] + rng.uniform(0.3, height)

            mote.setPos(mx, my, mz)
            mote.setLightOff()
            mote.setColorScale(color[0] * 15, color[1] * 15, color[2] * 15, 0.85)
            mote.setTwoSided(True)
            mote.setBillboardPointEye()

            # Target position — slow drift
            duration = rng.uniform(8.0, 25.0) / compress  # very slow
            if downward:
                # Fall slowly, then reset
                end_z = pos[2] - radius * 2
                seq = Sequence(
                    LerpPosInterval(mote, duration,
                                    (mx + rng.uniform(-0.5, 0.5),
                                     my + rng.uniform(-0.5, 0.5),
                                     end_z)),
                    Func(mote.setPos, mx, my, mz),  # reset to top
                )
            else:
                # Gentle drift loop
                tx = mx + rng.uniform(-radius * 0.4, radius * 0.4)
                ty = my + rng.uniform(-radius * 0.4, radius * 0.4)
                tz = mz + rng.uniform(-0.3, 0.3)
                seq = Sequence(
                    LerpPosInterval(mote, duration, (tx, ty, tz)),
                    LerpPosInterval(mote, duration, (mx, my, mz)),
                )
            seq.loop()
            entry["motes"].append(mote)
            entry["intervals"].append(seq)
