import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Optional, Tuple
from panda3d.core import Geom, GeomNode, GeomTriangles, GeomVertexData, GeomVertexFormat, GeomVertexWriter


# -- Primitive definitions ------------------------------------------------

PRIMITIVES = {
    'PILLAR': {
        'default_scale': (1.0, 8.0, 1.0),
        'role_hints':    ['trunk', 'column', 'obelisk', 'stalactite', 'antenna'],
        'color_source':  'floor',
    },
    'SLAB': {
        'default_scale': (4.0, 0.5, 4.0),
        'role_hints':    ['canopy', 'table', 'shelf', 'roof', 'platform'],
        'color_source':  'accent',
    },
    'BLOCK': {
        'default_scale': (2.0, 2.0, 2.0),
        'role_hints':    ['rubble', 'crate', 'boulder', 'furniture', 'shrub'],
        'color_source':  'accent',
    },
    'WEDGE': {
        'default_scale': (2.0, 2.0, 1.0),
        'role_hints':    ['ramp', 'cliff', 'broken_wall', 'blade', 'prow'],
        'color_source':  'floor',
    },
    'ARCH': {
        'default_scale': (4.0, 0.5, 3.0),
        'role_hints':    ['doorway', 'bridge', 'cave_mouth', 'span'],
        'color_source':  'floor',
    },
    'SPIKE': {
        'default_scale': (0.5, 3.0, 0.5),
        'role_hints':    ['crystal', 'thorn', 'stalagmite', 'blade', 'handle'],
        'color_source':  'accent',
    },
    'PLANE': {
        'default_scale': (10.0, 0.1, 10.0),
        'role_hints':    ['floor', 'ceiling', 'wall', 'water'],
        'color_source':  'floor',
    },
}


# -- Archetype modifiers --------------------------------------------------

ARCHETYPE_MODIFIERS = {
    'SEEKER':   {'pillar_h': 1.3, 'slab_w': 0.8, 'rotation_range': 15, 'detail': 1},
    'KEEPER':   {'pillar_h': 0.9, 'slab_w': 1.3, 'rotation_range':  5, 'detail': 2},
    'BUILDER':  {'pillar_h': 1.0, 'slab_w': 1.1, 'rotation_range':  8, 'detail': 3},
    'WANDERER': {'pillar_h': 1.1, 'slab_w': 0.9, 'rotation_range': 25, 'detail': 1},
}


# -- Primitive dataclass --------------------------------------------------

@dataclass
class Primitive:
    primitive_type:  str
    role:            str
    scale:           Tuple[float, float, float]
    color:           Tuple[float, float, float]
    geom_node:       object
    offset_z:        float = 0.0
    rotation:        Tuple[float, float, float] = (0.0, 0.0, 0.0)
    detail_level:    int = 0
    vibe:            str = ''
    provenance_hash: str = ''
    relic:           dict = field(default_factory=dict)
    profile:         dict = field(default_factory=dict)


# -- Recipe placeholder ---------------------------------------------------

@dataclass
class Recipe:
    primitives: list
    blueprint:  dict
    palette:    dict


# -- PrimitiveFactory -----------------------------------------------------

class PrimitiveFactory:
    """
    Generates Primitive objects from type, scale, color,
    relic properties, and character profile.
    Everything in the game world is assembled from 7 primitives.
    Same inputs always produce same provenance hash.
    """

    def build(self, primitive_type, scale, color,
              role='', relic=None, profile=None):
        if primitive_type not in PRIMITIVES:
            raise ValueError(
                f'PrimitiveFactory: unknown primitive {primitive_type!r}. '
                f'Valid: {list(PRIMITIVES.keys())}'
            )

        relic   = relic   or {}
        profile = profile or {}

        # Apply relic influence
        scale = self._apply_relic(primitive_type, list(scale), relic)

        # Apply character profile
        scale, rotation, detail = self._apply_profile(primitive_type, scale, profile)

        # Build geometry
        geom_node = self._make_geom(primitive_type, scale, color)

        # Provenance hash
        ph = self._make_hash(primitive_type, scale, color, relic, profile)

        return Primitive(
            primitive_type  = primitive_type,
            role            = role or PRIMITIVES[primitive_type]['role_hints'][0],
            scale           = tuple(scale),
            color           = tuple(color),
            geom_node       = geom_node,
            rotation        = rotation,
            detail_level    = detail,
            vibe            = relic.get('vibe', ''),
            provenance_hash = ph,
            relic           = relic,
            profile         = profile,
        )

    def from_blueprint(self, blueprint, palette):
        """
        Build a list of Primitives from a blueprint grammar.
        Handles parent/child relationships (trunk -> canopy).
        """
        grammar  = blueprint.get('grammar', [])
        built    = []
        by_role  = {}

        for entry in grammar:
            ptype  = entry['primitive']
            role   = entry.get('role', '')
            scale  = list(entry.get('scale', PRIMITIVES[ptype]['default_scale']))
            c_key  = entry.get('color', 'floor')
            color  = palette.get(c_key, (0.5, 0.5, 0.5))
            parent = entry.get('parent')

            # Resolve parent offset
            offset_z = 0.0
            if parent and parent in by_role:
                offset_z = by_role[parent].scale[1]

            p = self.build(ptype, tuple(scale), color, role=role)
            p.offset_z = offset_z
            built.append(p)
            by_role[role] = p

        return built

    # -- Private ----------------------------------------------------------

    def _apply_relic(self, ptype, scale, relic):
        if not relic:
            return scale
        impact = relic.get('impact_rating', 1)
        factor = 1.0 + (impact - 1) / 9.0 * 0.4  # 1.0 - 1.4x
        # Height scale for verticals, width for horizontals
        if ptype in ('PILLAR', 'SPIKE'):
            scale[1] = scale[1] * factor
        elif ptype in ('SLAB', 'PLANE'):
            scale[0] = scale[0] * factor
            scale[2] = scale[2] * factor
        else:
            scale[0] = scale[0] * (1.0 + (factor - 1.0) * 0.5)
            scale[1] = scale[1] * (1.0 + (factor - 1.0) * 0.5)
            scale[2] = scale[2] * (1.0 + (factor - 1.0) * 0.5)
        return scale

    def _apply_profile(self, ptype, scale, profile):
        archetype = profile.get('archetype', 'WANDERER')
        mods      = ARCHETYPE_MODIFIERS.get(archetype, ARCHETYPE_MODIFIERS['WANDERER'])
        scale     = list(scale)

        if ptype == 'PILLAR':
            scale[1] = scale[1] * mods['pillar_h']
        elif ptype == 'SLAB':
            scale[0] = scale[0] * mods['slab_w']
            scale[2] = scale[2] * mods['slab_w']

        rng_range = mods['rotation_range']
        rng       = random.Random(str(scale) + archetype)
        rotation  = (
            rng.uniform(-rng_range, rng_range),
            rng.uniform(-rng_range, rng_range),
            rng.uniform(0, 360),
        )
        detail = mods['detail']
        return tuple(scale), rotation, detail

    def _make_geom(self, ptype, scale, color):
        from core.systems.biome_renderer import _make_box_geom
        w, h, d = scale[0], scale[1], scale[2]
        r, g, b = color[0], color[1], color[2]
        return _make_box_geom(w, h, d, (r, g, b))

    def _make_hash(self, ptype, scale, color, relic, profile):
        raw = json.dumps({
            'type':    ptype,
            'scale':   [round(s, 4) for s in scale],
            'color':   [round(c, 4) for c in color],
            'relic':   relic.get('archetypal_name', ''),
            'impact':  relic.get('impact_rating', 0),
            'arch':    profile.get('archetype', ''),
        }, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]