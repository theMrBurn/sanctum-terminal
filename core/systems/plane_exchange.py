"""
core/systems/plane_exchange.py

Node-based plane exchange math for the Merkabah plane-attachment
architecture (Design Law #14).

An entity's layer membership is determined by its distance to the
observer. As the player moves, entities migrate between plane layers
(near → mid → far → void) via ExchangeNodes — threshold points with
hysteresis transition bands that produce smooth handoffs instead of
hard pops.

The exchange nodes are the radial spokes between the wheels of the
Merkabah. Entities drift between halls as the throne moves.

Pure math. No rendering. Brain-side. Unit-tested.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class ExchangeNode:
    """A threshold point where entities transition between two adjacent layers.

    Attributes:
        distance: Center distance of the transition (meters from observer).
        band: Half-width of the hysteresis zone. Entities within
              [distance - band, distance + band] are in active transition
              between inner_layer and outer_layer with smoothly interpolated
              weights.
        inner_layer: Name of the layer on the "near" (closer to observer) side.
        outer_layer: Name of the layer on the "far" (further from observer) side.
    """

    distance: float
    band: float
    inner_layer: str
    outer_layer: str

    def compute_membership(self, entity_distance: float) -> Tuple[float, float]:
        """Return (inner_weight, outer_weight) for an entity at the given distance.

        Weights sum to 1.0 always.
        - If entity_distance <= distance - band: fully inner (1.0, 0.0)
        - If entity_distance >= distance + band: fully outer (0.0, 1.0)
        - Otherwise: linear interpolation across the band
        """
        if self.band <= 0:
            # Degenerate band — treat as hard step
            return (1.0, 0.0) if entity_distance < self.distance else (0.0, 1.0)

        lower = self.distance - self.band
        upper = self.distance + self.band

        if entity_distance <= lower:
            return (1.0, 0.0)
        if entity_distance >= upper:
            return (0.0, 1.0)

        # Linear interpolation across the transition band
        t = (entity_distance - lower) / (upper - lower)
        return (1.0 - t, t)


def classify_entity_layer(
    entity_x: float,
    entity_y: float,
    observer_x: float,
    observer_y: float,
    nodes: List[ExchangeNode],
) -> Dict[str, float]:
    """Compute layer membership weights for an entity relative to an observer.

    Uses horizontal (XY in brain manifest coords, which is the ground plane)
    distance — vertical offset does NOT affect layer membership. A stalactite
    15m above the player at the same XY position is in the same layer as a
    stalagmite directly below them.

    Args:
        entity_x, entity_y: Entity position in brain manifest coords (ground plane).
        observer_x, observer_y: Observer (camera) position in same coords.
        nodes: List of ExchangeNode instances, sorted by distance ascending.
               Each node's outer_layer should match the next node's inner_layer
               for coherent layer chain. First node's inner_layer is the
               "closest" layer; last node's outer_layer is the "furthest."

    Returns:
        Dict of layer_name -> weight. Weights sum to 1.0. Zero-weight layers
        are omitted from the result for cleanliness.
    """
    dx = entity_x - observer_x
    dy = entity_y - observer_y
    dist = math.sqrt(dx * dx + dy * dy)

    if not nodes:
        return {"near": 1.0}

    # Pass 1: check if we're inside any node's transition band
    for node in nodes:
        lower = node.distance - node.band
        upper = node.distance + node.band
        if lower <= dist <= upper:
            inner, outer = node.compute_membership(dist)
            result = {}
            if inner > 0:
                result[node.inner_layer] = inner
            if outer > 0:
                result[node.outer_layer] = outer
            return result

    # Pass 2: not in any band, determine the pure layer we're in
    # Before the first node's band — fully in the innermost layer
    if dist < nodes[0].distance - nodes[0].band:
        return {nodes[0].inner_layer: 1.0}

    # Between two adjacent nodes' bands — in the intermediate layer
    for i in range(len(nodes) - 1):
        upper_of_current = nodes[i].distance + nodes[i].band
        lower_of_next = nodes[i + 1].distance - nodes[i + 1].band
        if upper_of_current < dist < lower_of_next:
            # The layer between node i and node i+1 is nodes[i].outer_layer
            # (which should equal nodes[i+1].inner_layer for coherent config)
            return {nodes[i].outer_layer: 1.0}

    # Past the last node's band — fully in the outermost layer
    return {nodes[-1].outer_layer: 1.0}


# -- Default layer configurations for the canonical cavern Merkabah stack ----
#
# Seven layers mapped to the seven Hekhalot palaces:
#   1. near_floor / 2. near_ceiling  — player's immediate space (0-25m)
#   3. mid_floor  / 4. mid_ceiling   — mid-depth silhouettes (25-60m)
#   5. far_floor  / 6. far_ceiling   — far-depth plate (60-150m)
#   7. horizon_dome                  — outermost atmospheric shell (150m+ / void)
#
# The exchange nodes handle the three transitions along the distance axis
# (ceiling/floor pairs share the same distance thresholds since they're
# the same horizontal range, just at different Y offsets).

CAVERN_EXCHANGE_NODES: List[ExchangeNode] = [
    ExchangeNode(distance=25.0, band=3.0, inner_layer="near", outer_layer="mid"),
    ExchangeNode(distance=60.0, band=5.0, inner_layer="mid", outer_layer="far"),
    ExchangeNode(distance=150.0, band=10.0, inner_layer="far", outer_layer="void"),
]


def classify_all_entities(
    entities: List[Dict],
    observer_x: float,
    observer_y: float,
    nodes: List[ExchangeNode] = None,
) -> List[Dict]:
    """Annotate each entity with its layer membership dict.

    Takes a list of entity dicts (as produced by brain_server.py's wake chain)
    and adds a "layer_membership" field to each, computed via
    classify_entity_layer using the entity's x/y position and the observer's.

    Returns the same list (mutated in place) for convenience.
    """
    if nodes is None:
        nodes = CAVERN_EXCHANGE_NODES

    for ent in entities:
        ex = ent.get("x", 0.0)
        ey = ent.get("y", 0.0)
        ent["layer_membership"] = classify_entity_layer(ex, ey, observer_x, observer_y, nodes)

    return entities
