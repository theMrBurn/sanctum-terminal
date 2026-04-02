"""
core/systems/glow_decal.py

Ground glow decals + vertical light shafts — the ONLY visible lighting effects.

Panda3D's setShaderAuto() per-pixel lighting does not work on Apple Silicon
(Metal backend, basic shaders unsupported). Point lights are structurally
present but cast zero visible light. All visible illumination comes from:
  1. AmbientLight (flat fill — works without shaders)
  2. These additive decals (glow pools on ground)
  3. Self-illuminated entities (setLightOff + setColorScale)
  4. Light shafts (vertical billboard cards)

The decals ARE the lighting layer.
"""

import math
from panda3d.core import (
    CardMaker, ColorBlendAttrib, TransparencyAttrib,
    Texture, PNMImage, SamplerState,
)

_glow_tex_cache = {}


def get_glow_texture(size=64, surface="smooth"):
    """Radial gaussian glow texture with alpha falloff.

    The decal paints its OWN surface — the ground texture does not bleed through.
    Alpha channel controls where the decal is visible (gaussian falloff).
    RGB channel controls what the pool surface looks like.

    surface="smooth" — clean gradient, no pattern (default cavern)
    surface="wet_stone" — subtle caustic ripple (wet cave floor)
    """
    key = (size, surface)
    if key in _glow_tex_cache:
        return _glow_tex_cache[key]

    img = PNMImage(size, size, 4)  # RGBA
    center = size / 2.0
    for y in range(size):
        for x in range(size):
            dx = (x - center) / center
            dy = (y - center) / center
            d2 = dx * dx + dy * dy

            # Alpha: gaussian falloff — sharp center, soft edges
            alpha = math.exp(-d2 * 2.5)
            # Organic edge noise
            noise = math.sin(x * 0.7 + y * 1.3) * 0.03
            alpha = max(0.0, min(1.0, alpha + noise))

            # RGB: the pool surface — what the light looks like on the ground
            if surface == "wet_stone":
                # Caustic ripple — light on wet rock
                ripple = math.sin(x * 0.5 + y * 0.3) * 0.08
                ripple += math.cos(x * 0.3 - y * 0.7) * 0.06
                brightness = max(0.0, min(1.0, 0.9 + ripple))
            else:
                # Smooth — clean glow, no pattern
                brightness = 1.0

            img.setXelA(x, y, brightness, brightness, brightness, alpha)

    tex = Texture("glow_decal")
    tex.load(img)
    tex.setMagfilter(SamplerState.FT_linear)
    tex.setMinfilter(SamplerState.FT_linear)
    tex.setWrapU(SamplerState.WM_clamp)
    tex.setWrapV(SamplerState.WM_clamp)

    _glow_tex_cache[key] = tex
    return tex


def make_glow_decal(parent, color, radius, tex, height_offset=0.08):
    """
    Ground glow pool. Paints its own surface — no ground texture bleed.

    Uses alpha blend (not additive) so the decal's RGB replaces the ground
    within the gaussian falloff zone. The pool looks like colored light
    on a smooth surface, not a tinted view of cobblestone.
    """
    cm = CardMaker("glow_decal")
    cm.setFrame(-radius, radius, -radius, radius)
    cm.setHasUvs(True)

    decal = parent.attachNewNode(cm.generate())
    decal.setTexture(tex)
    decal.setP(-90)
    decal.setPos(0, 0, height_offset)
    # Alpha blend: decal color * alpha + ground * (1-alpha)
    # At center (alpha=1): pure glow color. At edges (alpha=0): ground shows.
    decal.setTransparency(TransparencyAttrib.MAlpha)
    r, g, b = color
    decal.setColorScale(r, g, b, 1.0)
    decal.setLightOff()
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
    """
    if tex is None:
        tex = get_shaft_texture()

    cm = CardMaker("light_shaft")
    cm.setFrame(-shaft_width / 2, shaft_width / 2, 0, shaft_height)
    cm.setHasUvs(True)

    shaft = parent.attachNewNode(cm.generate())
    shaft.setTexture(tex)
    shaft.setPos(0, 0, 0.05)
    shaft.setBillboardPointEye()
    # Additive blend for shafts — they ADD atmosphere to the scene
    shaft.setAttrib(ColorBlendAttrib.make(
        ColorBlendAttrib.MAdd,
        ColorBlendAttrib.OOne,
        ColorBlendAttrib.OOne,
    ))
    r, g, b = color
    shaft.setColorScale(r * 0.4, g * 0.4, b * 0.4, 1.0)
    shaft.setLightOff()
    shaft.setBin("transparent", 11)
    shaft.setDepthWrite(False)
    shaft.setDepthTest(True)
    shaft.setTwoSided(True)

    return shaft


def make_glow_halo(parent, color, halo_radius, halo_height, tex=None):
    """
    Low horizontal halo — radial emitter (crystals, embers, minerals).

    A billboard ring that sits at the entity's mid-height and radiates
    outward. Reads as light emanating from the object in all directions,
    not projecting up or down like a lamp.
    """
    if tex is None:
        tex = get_glow_texture(64)

    cm = CardMaker("glow_halo")
    cm.setFrame(-halo_radius, halo_radius, -halo_height / 2, halo_height / 2)
    cm.setHasUvs(True)

    halo = parent.attachNewNode(cm.generate())
    halo.setTexture(tex)
    halo.setBillboardPointEye()
    # Additive — adds glow atmosphere around the object
    halo.setAttrib(ColorBlendAttrib.make(
        ColorBlendAttrib.MAdd,
        ColorBlendAttrib.OOne,
        ColorBlendAttrib.OOne,
    ))
    r, g, b = color
    halo.setColorScale(r * 0.3, g * 0.3, b * 0.3, 1.0)
    halo.setLightOff()
    halo.setBin("transparent", 11)
    halo.setDepthWrite(False)
    halo.setDepthTest(True)
    halo.setTwoSided(True)

    return halo
