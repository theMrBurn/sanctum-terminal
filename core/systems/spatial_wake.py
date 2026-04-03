"""
core/systems/spatial_wake.py

Spatial hash + chain-priority wake system.

Replaces the O(n) entity scan with O(1) cell lookups.
Wake chain defines priority order per biome — skeleton first, detail last.
Budget-aware: if frame budget runs out, remaining chain links defer.

The rendering stays dumb (show/hide). All intelligence is here.

Usage:
    chain = WakeChain(WAKE_CHAINS["outdoor"])
    spatial = SpatialHash(cell_size=20.0)

    # At spawn time:
    idx = chain.chain_index(entity.kind)
    spatial.insert(entity.id, x, y, chain_index=idx)

    # Each tick:
    wake_set = chain.compute_wake_set(spatial, cam_x, cam_y)
    for entity_id, _ in wake_set:
        entity.show()
"""

import math


# -- Wake chain config per biome -----------------------------------------------
# Each link in the chain wakes as a group. Engine processes links in order.
# If frame budget runs out, remaining links defer to next tick.

WAKE_CHAINS = {
    "outdoor": [
        {
            "name": "skeleton",
            "kinds": {"mega_column", "column"},
            "radius": 40.0,
        },
        {
            "name": "landmarks",
            "kinds": {"boulder", "crystal_cluster", "stalagmite"},
            "radius": 35.0,
        },
        {
            "name": "ecosystem",
            "kinds": {"giant_fungus", "dead_log", "moss_patch"},
            "radius": 28.0,
        },
        {
            "name": "ground_cover",
            "kinds": {"grass_tuft", "leaf_pile", "rubble"},
            "radius": 20.0,
        },
        {
            "name": "life",
            "kinds": {"firefly", "leaf", "beetle", "rat"},
            "radius": 18.0,
        },
    ],
    "cavern": [
        {
            "name": "skeleton",
            "kinds": {"mega_column", "column", "crystal_cluster"},
            "radius": 30.0,
        },
        {
            "name": "landmarks",
            "kinds": {"boulder", "stalagmite", "giant_fungus"},
            "radius": 25.0,
        },
        {
            "name": "atmosphere",
            "kinds": {"ceiling_moss", "hanging_vine", "filament"},
            "radius": 22.0,
        },
        {
            "name": "ecosystem",
            "kinds": {"dead_log", "moss_patch", "bone_pile"},
            "radius": 20.0,
        },
        {
            "name": "ground_cover",
            "kinds": {"grass_tuft", "rubble", "leaf_pile", "twig_scatter", "cave_gravel"},
            "radius": 15.0,
        },
        {
            "name": "life",
            "kinds": {"firefly", "leaf", "beetle", "rat", "spider"},
            "radius": 12.0,
        },
    ],
}


class SpatialHash:
    """Grid-based spatial index. O(1) insert/remove/query by cell."""

    def __init__(self, cell_size=20.0):
        self._cell_size = cell_size
        self._inv_cell = 1.0 / cell_size
        self._cells = {}  # (cx, cy) -> list of (entity_id, chain_index)
        self._entity_cells = {}  # entity_id -> (cx, cy) for fast remove

    def _key(self, x, y):
        return (int(math.floor(x * self._inv_cell)),
                int(math.floor(y * self._inv_cell)))

    def insert(self, entity_id, x, y, chain_index=0):
        key = self._key(x, y)
        if key not in self._cells:
            self._cells[key] = []
        self._cells[key].append((entity_id, chain_index))
        self._entity_cells[entity_id] = key

    def remove(self, entity_id, x, y):
        key = self._key(x, y)
        cell = self._cells.get(key)
        if cell:
            self._cells[key] = [(eid, ci) for eid, ci in cell if eid != entity_id]
        self._entity_cells.pop(entity_id, None)

    def query(self, cx, cy, radius=40.0):
        """Return all entities within radius, sorted by chain_index (priority)."""
        r_cells = int(math.ceil(radius * self._inv_cell))
        center_key = self._key(cx, cy)
        r2 = radius * radius
        results = []

        for dx in range(-r_cells, r_cells + 1):
            for dy in range(-r_cells, r_cells + 1):
                key = (center_key[0] + dx, center_key[1] + dy)
                cell = self._cells.get(key)
                if not cell:
                    continue
                # Cell center distance check (coarse) — skip cells clearly out of range
                cell_cx = (key[0] + 0.5) * self._cell_size
                cell_cy = (key[1] + 0.5) * self._cell_size
                ddx = cell_cx - cx
                ddy = cell_cy - cy
                # Cell diagonal is cell_size * sqrt(2) ≈ cell_size * 1.42
                # If cell center is beyond radius + cell diagonal, skip
                cell_d2 = ddx * ddx + ddy * ddy
                margin = radius + self._cell_size * 1.42
                if cell_d2 > margin * margin:
                    continue
                results.extend(cell)

        results.sort(key=lambda r: r[1])
        return results

    def query_chain(self, cx, cy, chain_links):
        """Query with per-link radius. Returns list of (entity_id, chain_index).

        Only returns entities whose chain_index link radius reaches them.
        More precise than a single radius — skeleton wakes at 40m,
        detail only at 18m.
        """
        # Use the maximum radius for the cell scan
        max_radius = max(link["radius"] for link in chain_links)
        r_cells = int(math.ceil(max_radius * self._inv_cell))
        center_key = self._key(cx, cy)
        results = []

        # Build radius² lookup by chain_index
        link_r2 = {}
        for i, link in enumerate(chain_links):
            link_r2[i] = link["radius"] * link["radius"]

        for dx in range(-r_cells, r_cells + 1):
            for dy in range(-r_cells, r_cells + 1):
                key = (center_key[0] + dx, center_key[1] + dy)
                cell = self._cells.get(key)
                if not cell:
                    continue
                cell_cx = (key[0] + 0.5) * self._cell_size
                cell_cy = (key[1] + 0.5) * self._cell_size
                ddx = cell_cx - cx
                ddy = cell_cy - cy
                cell_d2 = ddx * ddx + ddy * ddy
                margin = max_radius + self._cell_size * 1.42
                if cell_d2 > margin * margin:
                    continue
                for entity_id, chain_idx in cell:
                    # Check against this link's specific radius
                    r2 = link_r2.get(chain_idx, 0)
                    if cell_d2 < (math.sqrt(r2) + self._cell_size * 1.42) ** 2:
                        results.append((entity_id, chain_idx))

        results.sort(key=lambda r: r[1])
        return results


class WakeChain:
    """Maps entity kinds to chain priority and processes wake decisions."""

    def __init__(self, chain_config):
        self._links = chain_config
        self._kind_to_index = {}
        self._kind_to_radius = {}
        for i, link in enumerate(chain_config):
            for kind in link["kinds"]:
                self._kind_to_index[kind] = i
                self._kind_to_radius[kind] = link["radius"]
        self._max_index = len(chain_config) - 1

    def chain_index(self, kind):
        """Return the chain link index for an entity kind."""
        return self._kind_to_index.get(kind, self._max_index)

    def wake_radius(self, kind):
        """Return the wake radius for an entity kind."""
        return self._kind_to_radius.get(kind, self._links[-1]["radius"])

    def should_wake(self, kind, distance):
        """Should this entity kind wake at this distance?"""
        return distance <= self.wake_radius(kind)

    def compute_wake_set(self, spatial_hash, cam_x, cam_y, max_links=None):
        """Compute which entities should be awake, in priority order.

        Returns list of (entity_id, chain_index).
        max_links limits how many chain links are processed (budget control).
        """
        if max_links is None:
            max_links = len(self._links)
        links_to_process = self._links[:max_links]
        return spatial_hash.query_chain(cam_x, cam_y, links_to_process)
