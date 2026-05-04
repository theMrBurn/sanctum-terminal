"""Wireframe edit ops + replay — T3 of feat/vector-workroom PR 3.

Pins each verb's behavior against a known base mesh, verifies replay
determinism, edge canonical-form preservation, and order-dependence
where order matters.
"""
from __future__ import annotations

import pytest

from core.systems.wireframe_edits import (
    add_edge,
    add_vertex,
    apply_op,
    move_vertex,
    op_names,
    remove_edge,
    replay,
    subdivide_edge,
)
from core.systems.wireframe_mesh import WireframeMesh, get_builtin


def _cube() -> WireframeMesh:
    """Convenience — known 8-vertex, 12-edge mesh for op testing."""
    return get_builtin("cube")


def _canonical(edges):
    """Canonical form for comparison: pairs sorted (low, high), list
    sorted. Mirrors what `wireframe_edits._normalize_edges` produces.
    Test helper because the built-in cube stores edges face-traversal-
    order, not canonical."""
    return tuple(sorted((min(a, b), max(a, b)) for (a, b) in edges))


def _is_canonical(mesh: WireframeMesh) -> bool:
    """Edges sorted (low, high), edge list globally sorted."""
    if any(a > b for (a, b) in mesh.edges):
        return False
    return list(mesh.edges) == sorted(mesh.edges)


# ── move_vertex ─────────────────────────────────────────────────────


def test_move_vertex_relocates_target():
    cube = _cube()
    out = move_vertex(cube, {"i": 0, "to": [9.0, 9.0, 9.0]})
    assert out.vertices[0] == (9.0, 9.0, 9.0)
    # Other vertices unchanged.
    for i in range(1, len(cube.vertices)):
        assert out.vertices[i] == cube.vertices[i]
    # Edge SET unchanged (op canonicalizes; built-in cube doesn't).
    assert out.edges == _canonical(cube.edges)


def test_move_vertex_does_not_mutate_input():
    cube = _cube()
    original_v0 = cube.vertices[0]
    move_vertex(cube, {"i": 0, "to": [1.0, 1.0, 1.0]})
    assert cube.vertices[0] == original_v0


def test_move_vertex_rejects_out_of_range_index():
    cube = _cube()
    with pytest.raises(ValueError):
        move_vertex(cube, {"i": 99, "to": [0.0, 0.0, 0.0]})


def test_move_vertex_rejects_missing_keys():
    cube = _cube()
    with pytest.raises(ValueError):
        move_vertex(cube, {"i": 0})
    with pytest.raises(ValueError):
        move_vertex(cube, {"to": [0.0, 0.0, 0.0]})


def test_move_vertex_rejects_bad_vertex_shape():
    cube = _cube()
    with pytest.raises(ValueError):
        move_vertex(cube, {"i": 0, "to": [1.0, 2.0]})  # 2 components
    with pytest.raises(ValueError):
        move_vertex(cube, {"i": 0, "to": "abc"})


# ── add_vertex ──────────────────────────────────────────────────────


def test_add_vertex_appends_at_index_n():
    cube = _cube()
    n = len(cube.vertices)
    out = add_vertex(cube, {"at": [5.0, 6.0, 7.0]})
    assert len(out.vertices) == n + 1
    assert out.vertices[n] == (5.0, 6.0, 7.0)
    # Original vertices preserved.
    for i in range(n):
        assert out.vertices[i] == cube.vertices[i]
    # No new edges; canonical comparison.
    assert out.edges == _canonical(cube.edges)


def test_add_vertex_rejects_missing_at():
    cube = _cube()
    with pytest.raises(ValueError):
        add_vertex(cube, {})


# ── add_edge ────────────────────────────────────────────────────────


def test_add_edge_inserts_canonical():
    cube = _cube()
    # Vertices 0 and 5 are not directly connected in cube — body diagonal.
    out = add_edge(cube, {"a": 5, "b": 0})
    assert (0, 5) in out.edges
    assert _is_canonical(out)


def test_add_edge_idempotent_on_existing():
    cube = _cube()
    # (0, 1) is an edge of the cube.
    assert (0, 1) in cube.edges
    out = add_edge(cube, {"a": 0, "b": 1})
    # Op canonicalizes; cube built-in doesn't — compare against canonical.
    assert out.edges == _canonical(cube.edges)


def test_add_edge_rejects_self_edge():
    cube = _cube()
    with pytest.raises(ValueError):
        add_edge(cube, {"a": 3, "b": 3})


def test_add_edge_rejects_oob_index():
    cube = _cube()
    with pytest.raises(ValueError):
        add_edge(cube, {"a": 0, "b": 99})


# ── remove_edge ─────────────────────────────────────────────────────


def test_remove_edge_drops_canonical():
    cube = _cube()
    assert (0, 1) in cube.edges
    out = remove_edge(cube, {"a": 1, "b": 0})  # reverse order should still find it
    assert (0, 1) not in out.edges
    assert len(out.edges) == len(cube.edges) - 1
    assert _is_canonical(out)


def test_remove_edge_rejects_absent():
    cube = _cube()
    # (0, 6) is not a cube edge.
    with pytest.raises(ValueError):
        remove_edge(cube, {"a": 0, "b": 6})


# ── subdivide_edge ──────────────────────────────────────────────────


def test_subdivide_edge_inserts_midpoint_and_two_edges():
    cube = _cube()
    n = len(cube.vertices)
    e = len(cube.edges)
    out = subdivide_edge(cube, {"a": 0, "b": 1, "t": 0.5})
    # New vertex at index n.
    assert len(out.vertices) == n + 1
    new_idx = n
    # Midpoint at lerp(v0, v1, 0.5).
    v0 = cube.vertices[0]
    v1 = cube.vertices[1]
    expected_mid = (
        (v0[0] + v1[0]) / 2,
        (v0[1] + v1[1]) / 2,
        (v0[2] + v1[2]) / 2,
    )
    assert out.vertices[new_idx] == expected_mid
    # Original (0, 1) gone, replaced by (0, new_idx) and (1, new_idx).
    assert (0, 1) not in out.edges
    assert (0, new_idx) in out.edges
    assert (1, new_idx) in out.edges
    # Net edge count: 12 - 1 + 2 = 13.
    assert len(out.edges) == e + 1
    assert _is_canonical(out)


def test_subdivide_edge_at_t_quarter():
    cube = _cube()
    out = subdivide_edge(cube, {"a": 0, "b": 1, "t": 0.25})
    new_idx = len(cube.vertices)
    v0 = cube.vertices[0]
    v1 = cube.vertices[1]
    expected = (
        v0[0] + (v1[0] - v0[0]) * 0.25,
        v0[1] + (v1[1] - v0[1]) * 0.25,
        v0[2] + (v1[2] - v0[2]) * 0.25,
    )
    assert out.vertices[new_idx] == pytest.approx(expected)


def test_subdivide_edge_rejects_t_at_endpoints():
    cube = _cube()
    with pytest.raises(ValueError):
        subdivide_edge(cube, {"a": 0, "b": 1, "t": 0.0})
    with pytest.raises(ValueError):
        subdivide_edge(cube, {"a": 0, "b": 1, "t": 1.0})
    with pytest.raises(ValueError):
        subdivide_edge(cube, {"a": 0, "b": 1, "t": -0.5})


def test_subdivide_edge_rejects_absent_edge():
    cube = _cube()
    with pytest.raises(ValueError):
        subdivide_edge(cube, {"a": 0, "b": 6, "t": 0.5})


# ── apply_op + replay ───────────────────────────────────────────────


def test_apply_op_dispatches_each_verb():
    cube = _cube()
    # One of each — sequenced because add_vertex changes index space.
    log = [
        {"op": "move_vertex", "i": 0, "to": [9.0, 9.0, 9.0]},
        {"op": "add_vertex", "at": [4.0, 4.0, 4.0]},
        {"op": "add_edge", "a": 0, "b": 8},
        {"op": "subdivide_edge", "a": 1, "b": 2, "t": 0.5},
        {"op": "remove_edge", "a": 2, "b": 3},
    ]
    mesh = cube
    for op in log:
        mesh = apply_op(mesh, op)
    assert _is_canonical(mesh)


def test_apply_op_rejects_unknown_verb():
    cube = _cube()
    with pytest.raises(ValueError):
        apply_op(cube, {"op": "twist_vertex", "i": 0})


def test_apply_op_rejects_missing_op_key():
    cube = _cube()
    with pytest.raises(ValueError):
        apply_op(cube, {"i": 0, "to": [0, 0, 0]})


def test_replay_empty_log_returns_base():
    cube = _cube()
    out = replay(cube, [])
    assert out is cube


def test_replay_determinism_same_log_same_mesh():
    cube = _cube()
    log = [
        {"op": "move_vertex", "i": 0, "to": [9.0, 9.0, 9.0]},
        {"op": "subdivide_edge", "a": 1, "b": 2, "t": 0.5},
        {"op": "add_vertex", "at": [4.0, 4.0, 4.0]},
        {"op": "add_edge", "a": 0, "b": 9},
    ]
    a = replay(cube, log)
    b = replay(cube, log)
    assert a.vertices == b.vertices
    assert a.edges == b.edges


def test_replay_order_matters_for_index_dependent_ops():
    """add_vertex appends an index that subsequent ops can reference;
    swapping order changes meaning. This pins that the system is
    intentionally order-sensitive."""
    cube = _cube()
    log_correct = [
        {"op": "add_vertex", "at": [4.0, 4.0, 4.0]},  # → index 8
        {"op": "add_edge", "a": 0, "b": 8},           # references the new vertex
    ]
    log_swapped = [
        {"op": "add_edge", "a": 0, "b": 8},           # index 8 doesn't exist yet
        {"op": "add_vertex", "at": [4.0, 4.0, 4.0]},
    ]
    out_correct = replay(cube, log_correct)
    assert (0, 8) in out_correct.edges
    with pytest.raises(ValueError):
        replay(cube, log_swapped)


def test_replay_preserves_canonical_form_at_each_step():
    cube = _cube()
    log = [
        {"op": "subdivide_edge", "a": 0, "b": 1, "t": 0.5},
        {"op": "subdivide_edge", "a": 0, "b": 8, "t": 0.5},
        {"op": "add_edge", "a": 4, "b": 9},
    ]
    out = replay(cube, log)
    assert _is_canonical(out)


def test_replay_long_sequence_of_subdivides():
    """Bend a cube edge into a sevenfold curve — repeated subdivides
    against the rolling new midpoint."""
    cube = _cube()
    log = []
    target_a = 0
    target_b = 1
    for i in range(7):
        log.append({"op": "subdivide_edge", "a": target_a, "b": target_b, "t": 0.5})
        # Subdivision inserts at index n (where n grows each step). Update
        # target to keep splitting toward `1` — the new midpoint becomes
        # the new "a" vertex on the next iteration.
        target_a = len(cube.vertices) + i
    out = replay(cube, log)
    assert _is_canonical(out)
    # Started with 8 vertices, added 7 midpoints.
    assert len(out.vertices) == 15


# ── Registry ─────────────────────────────────────────────────────────


def test_op_names_lists_all_five():
    names = op_names()
    assert set(names) == {
        "move_vertex", "add_vertex", "add_edge", "remove_edge", "subdivide_edge",
    }
