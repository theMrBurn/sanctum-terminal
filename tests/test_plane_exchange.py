"""
tests/test_plane_exchange.py

TDD verification of the node-based plane exchange math for Design Law #14
(Merkabah plane-attachment architecture, Phase 1.5).

These tests verify the math at each exchange node: that entities
migrate between plane layers correctly as their distance to the
observer crosses thresholds, that transitions are smooth (no pops),
and that the system is internally consistent (weights sum to 1,
symmetric, monotonic).

Run with: ./.venv/bin/python -m pytest tests/test_plane_exchange.py -v
"""

import math
import pytest

from core.systems.plane_exchange import (
    ExchangeNode,
    classify_entity_layer,
    classify_all_entities,
    CAVERN_EXCHANGE_NODES,
)


def default_nodes():
    """Standard 3-node cavern layer stack: near -> mid -> far -> void."""
    return [
        ExchangeNode(distance=25.0, band=3.0, inner_layer="near", outer_layer="mid"),
        ExchangeNode(distance=60.0, band=5.0, inner_layer="mid", outer_layer="far"),
        ExchangeNode(distance=150.0, band=10.0, inner_layer="far", outer_layer="void"),
    ]


# -- Basic membership at pure-layer distances ---------------------------------


def test_entity_at_origin_is_fully_near():
    """An entity at the same position as the observer is fully in the near layer."""
    result = classify_entity_layer(0, 0, 0, 0, default_nodes())
    assert result == {"near": 1.0}


def test_entity_well_inside_near_layer():
    """An entity at 10m (well inside near-layer band) is fully near."""
    result = classify_entity_layer(10, 0, 0, 0, default_nodes())
    assert result == {"near": 1.0}


def test_entity_in_pure_mid_layer():
    """An entity at 40m (between near's outer band and mid's inner band) is fully mid."""
    result = classify_entity_layer(40, 0, 0, 0, default_nodes())
    assert result == {"mid": 1.0}


def test_entity_in_pure_far_layer():
    """An entity at 100m (between mid's outer band and far's inner band) is fully far."""
    result = classify_entity_layer(100, 0, 0, 0, default_nodes())
    assert result == {"far": 1.0}


def test_entity_past_final_node_is_void():
    """An entity at 200m (past the far-to-void transition) is fully void."""
    result = classify_entity_layer(200, 0, 0, 0, default_nodes())
    assert result == {"void": 1.0}


# -- Transition band behavior — exchange node 1 (near↔mid at 25m) ------------


def test_near_mid_node_inner_edge():
    """At distance = center - band (22m), entity is still fully near."""
    result = classify_entity_layer(22, 0, 0, 0, default_nodes())
    assert result == {"near": 1.0}


def test_near_mid_node_outer_edge():
    """At distance = center + band (28m), entity is fully mid."""
    result = classify_entity_layer(28, 0, 0, 0, default_nodes())
    assert result == {"mid": 1.0}


def test_near_mid_node_exact_center():
    """At the exact node center (25m), weight is 50/50 between near and mid."""
    result = classify_entity_layer(25, 0, 0, 0, default_nodes())
    assert result["near"] == pytest.approx(0.5)
    assert result["mid"] == pytest.approx(0.5)


def test_near_mid_node_quarter_transition():
    """At 23.5m (1/4 through the band), weight is 75% near / 25% mid."""
    result = classify_entity_layer(23.5, 0, 0, 0, default_nodes())
    assert result["near"] == pytest.approx(0.75)
    assert result["mid"] == pytest.approx(0.25)


def test_near_mid_node_three_quarters_transition():
    """At 26.5m (3/4 through the band), weight is 25% near / 75% mid."""
    result = classify_entity_layer(26.5, 0, 0, 0, default_nodes())
    assert result["near"] == pytest.approx(0.25)
    assert result["mid"] == pytest.approx(0.75)


# -- Transition band behavior — exchange node 2 (mid↔far at 60m) -------------


def test_mid_far_node_exact_center():
    """At the exact mid-far node center (60m), weight is 50/50 between mid and far."""
    result = classify_entity_layer(60, 0, 0, 0, default_nodes())
    assert result["mid"] == pytest.approx(0.5)
    assert result["far"] == pytest.approx(0.5)


def test_mid_far_node_inner_edge():
    """At 55m (mid-far node inner edge), entity is fully mid."""
    result = classify_entity_layer(55, 0, 0, 0, default_nodes())
    assert result == {"mid": 1.0}


def test_mid_far_node_outer_edge():
    """At 65m (mid-far node outer edge), entity is fully far."""
    result = classify_entity_layer(65, 0, 0, 0, default_nodes())
    assert result == {"far": 1.0}


# -- Transition band behavior — exchange node 3 (far↔void at 150m) -----------


def test_far_void_node_exact_center():
    """At the exact far-void node center (150m), weight is 50/50."""
    result = classify_entity_layer(150, 0, 0, 0, default_nodes())
    assert result["far"] == pytest.approx(0.5)
    assert result["void"] == pytest.approx(0.5)


def test_far_void_node_inner_edge():
    """At 140m (far-void inner edge), entity is fully far."""
    result = classify_entity_layer(140, 0, 0, 0, default_nodes())
    assert result == {"far": 1.0}


def test_far_void_node_outer_edge():
    """At 160m (far-void outer edge), entity is fully void."""
    result = classify_entity_layer(160, 0, 0, 0, default_nodes())
    assert result == {"void": 1.0}


# -- System-level invariants --------------------------------------------------


def test_weights_always_sum_to_one():
    """For ANY distance from 0 to 300m, layer membership weights sum to 1.0."""
    nodes = default_nodes()
    for d in range(0, 300):
        result = classify_entity_layer(d, 0, 0, 0, nodes)
        total = sum(result.values())
        assert total == pytest.approx(1.0), f"Weights don't sum to 1.0 at distance {d}: {result}"


def test_symmetry_approach_equals_retreat():
    """Entity at distance D has same membership whether we approached or retreated to that distance."""
    nodes = default_nodes()
    for d in [5, 15, 25, 27, 40, 60, 65, 100, 150, 200]:
        # Entity at (d, 0), observer at (0, 0)
        approach = classify_entity_layer(d, 0, 0, 0, nodes)
        # Entity at (0, 0), observer at (-d, 0) — same relative distance
        retreat = classify_entity_layer(0, 0, -d, 0, nodes)
        assert approach == retreat, f"Asymmetric at distance {d}: approach={approach}, retreat={retreat}"


def test_2d_distance_euclidean():
    """Entity at (3, 4) from observer at (0, 0) has distance 5m (3-4-5 triangle)."""
    nodes = default_nodes()
    # 5m from observer — well inside near layer
    result = classify_entity_layer(3, 4, 0, 0, nodes)
    assert result == {"near": 1.0}


def test_monotonic_near_to_mid_transition():
    """As distance increases through the near-mid band, mid weight monotonically increases."""
    nodes = default_nodes()
    distances = [22, 23, 24, 25, 26, 27, 28]
    mid_weights = [classify_entity_layer(d, 0, 0, 0, nodes).get("mid", 0) for d in distances]
    for i in range(len(mid_weights) - 1):
        assert mid_weights[i] <= mid_weights[i + 1], (
            f"Non-monotonic at {distances[i]}→{distances[i+1]}: "
            f"{mid_weights[i]} → {mid_weights[i+1]}"
        )
    assert mid_weights[0] == 0.0
    assert mid_weights[-1] == 1.0


def test_monotonic_mid_to_far_transition():
    """As distance increases through the mid-far band, far weight monotonically increases."""
    nodes = default_nodes()
    distances = [55, 57, 58, 60, 62, 63, 65]
    far_weights = [classify_entity_layer(d, 0, 0, 0, nodes).get("far", 0) for d in distances]
    for i in range(len(far_weights) - 1):
        assert far_weights[i] <= far_weights[i + 1]
    assert far_weights[0] == 0.0
    assert far_weights[-1] == 1.0


def test_adjacent_pure_layers_dont_leak():
    """An entity in the pure mid layer (40m) has ZERO near and ZERO far weight."""
    result = classify_entity_layer(40, 0, 0, 0, default_nodes())
    assert "near" not in result or result["near"] == 0
    assert "far" not in result or result["far"] == 0
    assert result["mid"] == 1.0


def test_zero_weight_layers_omitted_from_result():
    """Layers with zero weight should not appear in the result dict (cleanliness)."""
    result = classify_entity_layer(10, 0, 0, 0, default_nodes())
    # At 10m, only near should be present
    assert "mid" not in result
    assert "far" not in result
    assert "void" not in result
    assert result == {"near": 1.0}


# -- Edge cases ---------------------------------------------------------------


def test_empty_nodes_list_returns_near():
    """If no nodes are configured, everything is in the default 'near' layer."""
    result = classify_entity_layer(10, 0, 0, 0, [])
    assert result == {"near": 1.0}


def test_single_node():
    """A single node creates a 2-layer system (near/outer)."""
    nodes = [ExchangeNode(distance=30, band=2, inner_layer="inside", outer_layer="outside")]
    assert classify_entity_layer(10, 0, 0, 0, nodes) == {"inside": 1.0}
    assert classify_entity_layer(30, 0, 0, 0, nodes)["inside"] == pytest.approx(0.5)
    assert classify_entity_layer(30, 0, 0, 0, nodes)["outside"] == pytest.approx(0.5)
    assert classify_entity_layer(50, 0, 0, 0, nodes) == {"outside": 1.0}


def test_degenerate_zero_band_hard_step():
    """A node with band=0 produces a hard step function (no transition)."""
    nodes = [ExchangeNode(distance=30, band=0, inner_layer="a", outer_layer="b")]
    assert classify_entity_layer(29, 0, 0, 0, nodes) == {"a": 1.0}
    assert classify_entity_layer(31, 0, 0, 0, nodes) == {"b": 1.0}


def test_negative_coordinates_work():
    """Negative coordinates work the same as positive (absolute distance)."""
    nodes = default_nodes()
    assert classify_entity_layer(-10, 0, 0, 0, nodes) == {"near": 1.0}
    assert classify_entity_layer(0, -40, 0, 0, nodes) == {"mid": 1.0}
    # Entity at (-30, -40) is sqrt(900+1600)=50m from origin → still in mid layer
    assert classify_entity_layer(-30, -40, 0, 0, nodes) == {"mid": 1.0}
    # Entity at (-60, -80) is sqrt(3600+6400)=100m from origin → in far layer
    assert classify_entity_layer(-60, -80, 0, 0, nodes) == {"far": 1.0}


# -- Integration test — classify_all_entities --------------------------------


def test_classify_all_entities_annotates_in_place():
    """classify_all_entities adds 'layer_membership' to each entity dict."""
    entities = [
        {"kind": "boulder", "x": 5, "y": 0},        # near
        {"kind": "column", "x": 40, "y": 0},        # mid
        {"kind": "horizon", "x": 100, "y": 0},      # far
        {"kind": "skybox", "x": 200, "y": 0},       # void
    ]
    result = classify_all_entities(entities, observer_x=0, observer_y=0)
    assert result is entities  # mutated in place
    assert entities[0]["layer_membership"] == {"near": 1.0}
    assert entities[1]["layer_membership"] == {"mid": 1.0}
    assert entities[2]["layer_membership"] == {"far": 1.0}
    assert entities[3]["layer_membership"] == {"void": 1.0}


def test_classify_all_entities_uses_default_nodes():
    """classify_all_entities defaults to CAVERN_EXCHANGE_NODES if no nodes given."""
    entities = [{"kind": "test", "x": 10, "y": 0}]
    classify_all_entities(entities, 0, 0)
    assert entities[0]["layer_membership"] == {"near": 1.0}


def test_cavern_nodes_constant_is_valid():
    """The default CAVERN_EXCHANGE_NODES constant passes all sanity checks."""
    assert len(CAVERN_EXCHANGE_NODES) == 3
    # Nodes should be in ascending distance order
    for i in range(len(CAVERN_EXCHANGE_NODES) - 1):
        assert CAVERN_EXCHANGE_NODES[i].distance < CAVERN_EXCHANGE_NODES[i + 1].distance
    # Layer chain should be coherent (outer of one = inner of next)
    for i in range(len(CAVERN_EXCHANGE_NODES) - 1):
        assert CAVERN_EXCHANGE_NODES[i].outer_layer == CAVERN_EXCHANGE_NODES[i + 1].inner_layer


# -- The physics principle test ----------------------------------------------


def test_asymptotic_smoothness_no_pops():
    """The physics principle: weights change continuously, no discontinuous jumps.

    This is the mathematical expression of 'entities never pop between layers' —
    at any two adjacent distances (0.1m apart), layer weights should differ by
    at most some small epsilon, proving smooth asymptotic transitions.
    """
    nodes = default_nodes()
    epsilon = 0.2  # max allowed weight change per 0.1m of distance change
    prev_result = classify_entity_layer(0, 0, 0, 0, nodes)

    for i in range(1, 2000):  # 0 to 200m in 0.1m steps
        d = i * 0.1
        current = classify_entity_layer(d, 0, 0, 0, nodes)

        # For every layer that appears in either result, check the delta
        all_layers = set(prev_result.keys()) | set(current.keys())
        for layer in all_layers:
            prev_weight = prev_result.get(layer, 0.0)
            curr_weight = current.get(layer, 0.0)
            delta = abs(curr_weight - prev_weight)
            assert delta <= epsilon, (
                f"Discontinuous jump at distance {d}: layer {layer} "
                f"went from {prev_weight} to {curr_weight} (delta {delta})"
            )

        prev_result = current
