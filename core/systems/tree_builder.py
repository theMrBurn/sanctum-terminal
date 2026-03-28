import random
from core.systems.biome_renderer import _make_box_geom


class TreeBuilder:
    """
    Builds 7 VERDANT tree variations from blueprint grammar.
    Returns node dicts for placement in render root.
    Headless-safe -- no Panda3D render root required for building.
    """

    def pick_tree_type(self, blueprint, rng):
        trees  = blueprint['trees']
        types  = list(trees.keys())
        weights= [trees[t]['frequency'] for t in types]
        return rng.choices(types, weights=weights, k=1)[0]

    def get_trunk_height(self, tree_type, blueprint, rng):
        trunk = blueprint['trees'][tree_type]['trunk']
        h     = trunk['h']
        return rng.uniform(h[0], h[1]) if h[1] > 0 else 0.0

    def get_canopy_width(self, tree_type, blueprint, rng):
        canopy = blueprint['trees'][tree_type]['canopy']
        if not canopy:
            return 0.0
        w = canopy[0]['w']
        return rng.uniform(w[0], w[1])

    def _resolve_color(self, color_key, blueprint):
        palette = blueprint.get('palette', {})
        c = palette.get(color_key, [0.3, 0.5, 0.2])
        return tuple(c)

    def build_tree(self, tree_type, blueprint, rng, x, y):
        """
        Build one tree of the given type.
        Returns list of node dicts: {geom_node, x, y, z, role, tree_type}
        """
        tree  = blueprint['trees'][tree_type]
        nodes = []

        trunk_def = tree['trunk']
        th = rng.uniform(trunk_def['h'][0], trunk_def['h'][1]) if trunk_def['h'][1] > 0 else 0.0
        tw = rng.uniform(trunk_def['w'][0], trunk_def['w'][1]) if trunk_def['w'][1] > 0 else 0.0
        trunk_color = self._resolve_color(trunk_def['color'], blueprint)

        # Trunk flare for ANCIENT
        if 'trunk_flare' in tree and th > 0:
            flare = tree['trunk_flare']
            fw = rng.uniform(flare['w'][0], flare['w'][1])
            fh = rng.uniform(flare['h'][0], flare['h'][1])
            gn = _make_box_geom(fw, fh, fw, trunk_color)
            nodes.append({'geom_node': gn, 'x': x, 'y': y,
                          'z': fh/2, 'role': 'flare', 'tree_type': tree_type})

        # Trunk
        if th > 0 and tw > 0:
            gn = _make_box_geom(tw, th, tw, trunk_color)
            nodes.append({'geom_node': gn, 'x': x, 'y': y,
                          'z': th/2, 'role': 'trunk', 'tree_type': tree_type})

        # Dead branches
        if 'branches' in tree and th > 0:
            bd   = tree['branches']
            bc   = rng.randint(bd['count'][0], bd['count'][1])
            dark = tuple(c*0.6 for c in trunk_color)
            for i in range(bc):
                bw = rng.uniform(bd['w'][0], bd['w'][1])
                bh = rng.uniform(bd['h'][0], bd['h'][1])
                bz = th * rng.uniform(0.4, 0.9)
                ox = rng.uniform(-tw*2, tw*2)
                oy = rng.uniform(-tw*2, tw*2)
                gn = _make_box_geom(bw, bh, bw*0.3, dark)
                nodes.append({'geom_node': gn, 'x': x+ox, 'y': y+oy,
                              'z': bz, 'role': 'branch', 'tree_type': tree_type})

        # Canopy layers
        ground_offset = tree.get('ground_offset', 0.0)
        for layer in tree['canopy']:
            cw = rng.uniform(layer['w'][0], layer['w'][1])
            ch = rng.uniform(layer['h'][0], layer['h'][1])
            z_off = layer.get('z_offset', 0.0)
            cz = th + z_off + ch/2 + ground_offset
            ox = rng.uniform(-cw*0.1, cw*0.1)
            oy = rng.uniform(-cw*0.1, cw*0.1)
            cc = self._resolve_color(layer['color'], blueprint)
            # Slight color variation per layer
            cc = tuple(min(1.0, c * rng.uniform(0.85, 1.15)) for c in cc)
            gn = _make_box_geom(cw, ch, cw, cc)
            nodes.append({'geom_node': gn, 'x': x+ox, 'y': y+oy,
                          'z': cz, 'role': 'canopy', 'tree_type': tree_type})

        return nodes

    def build_forest(self, blueprint, rng, x1, x2, y1, y2, count=50):
        """
        Build a forest of count trees, distributed across the given bounds.
        Returns list of node dicts ready for render placement.
        """
        all_nodes = []
        placed    = 0
        attempts  = 0
        while placed < count and attempts < count * 5:
            attempts += 1
            x = rng.uniform(x1, x2)
            y = rng.uniform(y1, y2)
            tree_type = self.pick_tree_type(blueprint, rng)
            nodes     = self.build_tree(tree_type, blueprint, rng, x, y)
            all_nodes.extend(nodes)
            placed += 1
        return all_nodes