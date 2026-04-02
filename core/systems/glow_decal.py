"""
core/systems/glow_decal.py

Ground glow decals + vertical light shafts — the ONLY visible lighting effects.

Panda3D's setShaderAuto() per-pixel lighting does not work on Apple Silicon
(Metal backend, basic shaders unsupported). Point lights are structurally
present but cast zero visible light. All visible illumination comes from:
  1. AmbientLight (flat fill — works without shaders)
  2. These additive decals (glow pools on ground)
  3. Self-illuminated entities (setLightOff + setColorScale)

The decals ARE the lighting layer.
"""

import math
from panda3d.core import (
    CardMaker, ColorBlendAttrib,
    Texture, PNMImage, SamplerState,
)

_glow_tex_cache = {}


def get_glow_texture(size=64):
    """Radial gaussian — white center fades to black edges. RGB only."""
    if size in _glow_tex_cache:
        return _glow_tex_cache[size]

    img = PNMImage(size, size, 3)
    img.fill(0, 0, 0)
    center = size / 2.0
    for y in range(size):
        for x in range(size):
            dx = (x - center) / center
            dy = (y - center) / center
            d2 = dx * dx + dy * dy
            # Tight gaussian — visible bright pool, fades cleanly
            brightness = math.exp(-d2 * 2.5)
            # Subtle noise for organic edge
            noise = math.sin(x * 0.7 + y * 1.3) * 0.03
            brightness = max(0.0, min(1.0, brightness + noise))
            img.setXel(x, y, brightness, brightness, brightness)

    tex = Texture("glow_decal")
    tex.load(img)
    tex.setMagfilter(SamplerState.FT_linear)
    tex.setMinfilter(SamplerState.FT_linear)
    tex.setWrapU(SamplerState.WM_clamp)
    tex.setWrapV(SamplerState.WM_clamp)

    _glow_tex_cache[size] = tex
    return tex


def make_glow_decal(parent, color, radius, tex, height_offset=0.08):
    """
    Additive ground glow. This IS the light — not supplemental.

    Color values > 1.0 are expected. The gaussian texture modulates
    brightness spatially (bright center, zero at edges). The color
    scale sets hue and intensity. Additive blend adds to whatever
    is below — on dark ground, it paints the glow color directly.
    """
    cm = CardMaker("glow_decal")
    cm.setFrame(-radius, radius, -radius, radius)
    cm.setHasUvs(True)

    decal = parent.attachNewNode(cm.generate())
    decal.setTexture(tex)
    # Lay flat on ground
    decal.setP(-90)
    decal.setPos(0, 0, height_offset)
    # Additive: src*ONE + dst*ONE — black adds nothing, color adds glow
    decal.setAttrib(ColorBlendAttrib.make(
        ColorBlendAttrib.MAdd,
        ColorBlendAttrib.OOne,
        ColorBlendAttrib.OOne,
    ))
    r, g, b = color
    decal.setColorScale(r, g, b, 1.0)
    # No scene lighting — self-illuminated
    decal.setLightOff()
    # Render after ground geometry
    decal.setBin("transparent", 10)
    decal.setDepthWrite(False)
    decal.setDepthTest(True)

    return decal


_shaft_tex_cache = {}


def get_shaft_texture(width=32, height=64):
    """Vertical gradient — bright at bottom, fades to zero at top.

    Horizontal: gaussian falloff from center (thin beam, soft edges).
    Vertical: linear fade from bright bottom to transparent top.
    The combo reads as light dissipating upward from the ground pool.
    """
    key = (width, height)
    if key in _shaft_tex_cache:
        return _shaft_tex_cache[key]

    img = PNMImage(width, height, 3)
    img.fill(0, 0, 0)
    cx = width / 2.0
    for y in range(height):
        # Vertical: bottom=1.0, top=0.0
        v_fade = 1.0 - (y / float(height))
        # Soften the top with a curve — more light stays near ground
        v_fade = v_fade * v_fade
        for x in range(width):
            # Horizontal: gaussian from center
            dx = (x - cx) / cx
            h_fade = math.exp(-dx * dx * 3.0)
            brightness = v_fade * h_fade
            img.setXel(x, y, brightness, brightness, brightness)

    tex = Texture("light_shaft")
    tex.load(img)
    tex.setMagfilter(SamplerState.FT_linear)
    tex.setMinfilter(SamplerState.FT_linear)
    tex.setWrapU(SamplerState.WM_clamp)
    tex.setWrapV(SamplerState.WM_clamp)

    _shaft_tex_cache[key] = tex
    return tex


def make_light_shaft(parent, color, shaft_height, shaft_width=1.5, tex=None):
    """
    Vertical billboard card — connects glowing entity to ground pool.

    Fills the negative space between source and floor with a soft
    colored gradient. Billboard faces camera so it always reads as
    a volumetric column of light regardless of viewing angle.

    Args:
        parent: entity root NodePath
        color: (r, g, b) — same color as the entity's glow
        shaft_height: how tall the shaft is (entity height)
        shaft_width: width of the beam
        tex: shaft texture from get_shaft_texture()
    """
    if tex is None:
        tex = get_shaft_texture()

    cm = CardMaker("light_shaft")
    cm.setFrame(-shaft_width / 2, shaft_width / 2, 0, shaft_height)
    cm.setHasUvs(True)

    shaft = parent.attachNewNode(cm.generate())
    shaft.setTexture(tex)
    shaft.setPos(0, 0, 0.05)  # just above ground
    # Billboard — always faces camera
    shaft.setBillboardPointEye()
    # Additive blend — same as ground decals
    shaft.setAttrib(ColorBlendAttrib.make(
        ColorBlendAttrib.MAdd,
        ColorBlendAttrib.OOne,
        ColorBlendAttrib.OOne,
    ))
    r, g, b = color
    # Dimmer than the ground pool — atmosphere, not spotlight
    shaft.setColorScale(r * 0.4, g * 0.4, b * 0.4, 1.0)
    shaft.setLightOff()
    shaft.setBin("transparent", 11)  # render after ground decals
    shaft.setDepthWrite(False)
    shaft.setDepthTest(True)
    shaft.setTwoSided(True)

    return shaft
