"""Wireframe ingestion registry + edit primitives + ingest CLI.

Persona E of `docs/spec_open_source_primitive_pipeline.md` (D1–D6). Proves
the seam the kitbash parts provider assumed exists: a name→mesh registry,
`resolve_mesh`, the D4 edit primitives, and `tools/import_obj.py`.

All ingest tests run in a SANDBOXED repo root (tmp) so nothing is written
into the committed tree. `imported_at` is always passed a fixed timestamp
so the (unhashed) sidecar is deterministic too.
"""
from __future__ import annotations

import json

import pytest

from core.systems import wireframe_ingest_edits as ie
from core.systems import wireframe_mesh as wm
from core.systems.wireframe_mesh import (
    WireframeMesh,
    parse_obj,
    parse_wireframe_obj,
    resolve_mesh,
    to_obj_text,
)
from tools import import_obj

FIXED_TS = "2026-05-02T17:42:00-07:00"

# A tetrahedron, y-up, lifted so min-y = 5 (recenter has a visible effect).
_FIXTURE_OBJ = """# synthetic test tetra
v 0 7 0
v -1 5 -1
v 1 5 -1
v 0 5 1
f 1 2 3
f 1 3 4
f 1 4 2
f 2 4 3
"""


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point both modules' repo-root at a tmp dir + reset the mesh cache."""
    monkeypatch.setattr(wm, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(import_obj, "_REPO_ROOT", tmp_path)
    wm.clear_registry_cache()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "wireframe_meshes.json").write_text("{}\n")
    yield tmp_path
    wm.clear_registry_cache()


def _write_source(root, *, with_license=True):
    pack = root / "assets" / "kenney" / "nature-kit"
    (pack / "Models").mkdir(parents=True)
    src = pack / "Models" / "tetra.obj"
    src.write_text(_FIXTURE_OBJ)
    if with_license:
        (pack / "License.txt").write_text("Kenney — CC0 Public Domain")
    return src


# ── OBJ writer / l-aware reader (parse_obj left untouched) ───────────────


def test_writer_reader_round_trip():
    base = wm.get_builtin("cube")
    text = to_obj_text(base)
    assert "\nl " in text and "\nv " in text
    back = parse_wireframe_obj(text)
    assert back.vertex_count() == base.vertex_count()
    assert set(back.edges) == {
        (min(a, b), max(a, b)) for (a, b) in base.edges
    }


def test_parse_obj_still_ignores_l_lines():
    """Regression guard: parse_obj must NOT read `l` (kitbash/live path
    depends on this)."""
    text = "v 0 0 0\nv 1 0 0\nl 1 2\n"
    assert parse_obj(text).edge_count() == 0
    assert parse_wireframe_obj(text).edge_count() == 1


# ── resolve_mesh / get_registered ────────────────────────────────────────


def test_resolve_mesh_builtin_first():
    assert resolve_mesh("cube") is wm.get_builtin("cube")


def test_resolve_mesh_unknown_raises(sandbox):
    with pytest.raises(KeyError):
        resolve_mesh("does_not_exist_anywhere")


def test_get_registered_missing_returns_none(sandbox):
    assert wm.get_registered("nope") is None


# ── Edit primitives (D4) ─────────────────────────────────────────────────


def test_recenter_bottom_center_grounds_min_y(sandbox):
    """COORD CROSS-REF (AGENTS 'coord math pairs'): the engine convention
    is y-up, matching how the built-in primitives are authored
    (wedge/slab/stair have min-y = 0). bottom_center must leave min-y at 0."""
    mesh = parse_obj(_FIXTURE_OBJ)
    out = ie.recenter(mesh, mode="bottom_center")
    (lo, hi) = ie._bounds(out.vertices)
    assert lo[1] == pytest.approx(0.0)          # grounded
    assert lo[0] == pytest.approx(-hi[0])       # centered in X
    assert lo[2] == pytest.approx(-hi[2])       # centered in Z
    # Pin the OTHER side of the convention too: the built-in primitives are
    # authored ground-anchored y-up (slab's min-y is 0). If either side's
    # convention flips, this cross-reference test fails. (AGENTS coord rule.)
    assert ie._bounds(wm.get_builtin("slab").vertices)[0][1] == pytest.approx(0.0)


def test_recenter_centroid_zeros_mean(sandbox):
    mesh = parse_obj(_FIXTURE_OBJ)
    out = ie.recenter(mesh, mode="centroid")
    n = len(out.vertices)
    assert sum(v[1] for v in out.vertices) / n == pytest.approx(0.0)


def test_rescale_target_height(sandbox):
    mesh = ie.recenter(parse_obj(_FIXTURE_OBJ), mode="bottom_center")
    out = ie.rescale(mesh, target_height=4.0)
    (lo, hi) = ie._bounds(out.vertices)
    assert (hi[1] - lo[1]) == pytest.approx(4.0)


def test_rescale_requires_exactly_one_metric(sandbox):
    with pytest.raises(ValueError):
        ie.rescale(wm.get_builtin("cube"))  # none given
    with pytest.raises(ValueError):
        ie.rescale(wm.get_builtin("cube"), target_height=1.0, factor=2.0)


def test_axis_swap_z_up_to_y_up():
    mesh = WireframeMesh(vertices=((0.0, 0.0, 1.0),), edges=())
    out = ie.axis_swap(mesh, from_up="z_up", to_up="y_up")
    assert out.vertices[0] == pytest.approx((0.0, 1.0, 0.0))


def test_axis_swap_same_axis_is_identity():
    mesh = wm.get_builtin("spire")
    out = ie.axis_swap(mesh, from_up="y_up", to_up="y_up")
    assert out.vertices == mesh.vertices


def test_merge_vertices_collapses_near_dupes():
    v = ((0.0, 0.0, 0.0), (0.0, 0.0, 1e-9), (1.0, 0.0, 0.0))
    mesh = WireframeMesh(vertices=v, edges=((0, 1), (1, 2)))
    out = ie.merge_vertices(mesh, epsilon=1e-6)
    assert out.vertex_count() == 2          # first two collapse
    assert out.edge_count() == 1            # (0,1) self-edge dropped


def test_decimate_edges_keeps_longest():
    # Varied edge lengths so the SHORTEST-first policy is actually exercised
    # (not just the count): edge (0,1) has length 1, (1,2) has length 9.
    mesh = WireframeMesh(
        vertices=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
        edges=((0, 1), (1, 2)),
    )
    out = ie.decimate_edges(mesh, target_count=1)
    assert out.edges == ((1, 2),)          # short edge dropped, long kept
    # count honored + no-op when already under
    assert ie.decimate_edges(wm.get_builtin("cube"), target_count=4).edge_count() == 4
    assert ie.decimate_edges(wm.get_builtin("cube"), target_count=99).edge_count() == 12


def test_bounds_clip_drops_outside():
    v = ((0.0, 0.0, 0.0), (5.0, 5.0, 5.0), (1.0, 1.0, 1.0))
    mesh = WireframeMesh(vertices=v, edges=((0, 1), (0, 2)))
    out = ie.bounds_clip(mesh, min=(-2.0, -2.0, -2.0), max=(2.0, 2.0, 2.0))
    assert out.vertex_count() == 2          # (5,5,5) dropped
    assert out.edge_count() == 1            # (0,1) dropped, (0,2) reindexed


def test_composition_determinism():
    """Same base + same edit log → identical geometry, twice."""
    base = parse_obj(_FIXTURE_OBJ)
    edits = [
        {"op": "recenter", "mode": "bottom_center"},
        {"op": "rescale", "target_height": 4.0},
        {"op": "merge_vertices", "epsilon": 1e-6},
    ]
    a = import_obj.apply_edits(base, edits)
    b = import_obj.apply_edits(base, edits)
    assert a.vertices == b.vertices
    assert a.edges == b.edges


# ── Ingest CLI (D5) end-to-end ───────────────────────────────────────────


def test_ingest_end_to_end(sandbox):
    src = _write_source(sandbox)
    result = import_obj.run_ingest(
        source=src,
        name="spire_test",
        imported_at=FIXED_TS,
        recenter="bottom_center",
        rescale_height=4.0,
        axis_swap_from="y_up",
        merge_epsilon=1e-6,
        max_edges=200,
        credit="Kenney (www.kenney.nl)",
        vendor="kenney",
        pack="nature-kit",
    )

    # derived OBJ written
    mesh_path = sandbox / "assets" / "derived" / "spire_test" / "mesh.obj"
    assert mesh_path.exists()
    assert result["mesh_path"] == mesh_path

    # provenance valid + license present
    prov = json.loads(
        (sandbox / "assets" / "derived" / "spire_test" / "provenance.json").read_text()
    )
    assert prov["name"] == "spire_test"
    assert prov["source"]["license"] == "CC0"
    assert prov["source"]["license_url"]
    assert prov["source"]["credit"] == "Kenney (www.kenney.nl)"
    assert prov["imported_at"] == FIXED_TS
    assert [e["op"] for e in prov["edits"]] == [
        "recenter", "rescale", "axis_swap", "merge_vertices",
    ]
    assert "sha256" in prov["stats"]

    # registry updated (sorted keys, correct path)
    registry = json.loads((sandbox / "config" / "wireframe_meshes.json").read_text())
    assert registry["spire_test"]["path"] == "assets/derived/spire_test/mesh.obj"

    # resolve_mesh loads it back with matching stats
    wm.clear_registry_cache()
    mesh = resolve_mesh("spire_test")
    assert mesh.vertex_count() == prov["stats"]["vertex_count"]
    assert mesh.edge_count() == prov["stats"]["edge_count"]
    (lo, hi) = ie._bounds(mesh.vertices)
    assert [list(lo), list(hi)] == prov["stats"]["bounds"]
    # rescale worked: height == 4
    assert (hi[1] - lo[1]) == pytest.approx(4.0)


def test_ingest_idempotent_mesh_bytes(sandbox):
    src = _write_source(sandbox)
    kw = dict(source=src, name="idem", imported_at=FIXED_TS,
              recenter="bottom_center", rescale_height=4.0)
    import_obj.run_ingest(**kw)
    mesh_path = sandbox / "assets" / "derived" / "idem" / "mesh.obj"
    first = mesh_path.read_bytes()
    first_prov = json.loads(
        (mesh_path.parent / "provenance.json").read_text()
    )["stats"]["sha256"]
    import_obj.run_ingest(**kw)
    assert mesh_path.read_bytes() == first          # byte-identical
    second_prov = json.loads(
        (mesh_path.parent / "provenance.json").read_text()
    )["stats"]["sha256"]
    assert first_prov == second_prov


def test_ingest_license_hard_fail(sandbox):
    """No --license and no License.txt anywhere → hard fail (D6)."""
    nolic = sandbox / "loose"
    nolic.mkdir()
    src = nolic / "tetra.obj"
    src.write_text(_FIXTURE_OBJ)
    with pytest.raises(import_obj.IngestError, match="license"):
        import_obj.run_ingest(source=src, name="nolic", imported_at=FIXED_TS)
    # aborted before writing artifacts
    assert not (sandbox / "assets" / "derived" / "nolic").exists()


def test_ingest_max_edges_hard_fail(sandbox):
    src = _write_source(sandbox)
    with pytest.raises(import_obj.IngestError, match="edge count"):
        import_obj.run_ingest(
            source=src, name="toomany", imported_at=FIXED_TS,
            license="CC0", max_edges=2,
        )


def test_ingest_missing_source_hard_fail(sandbox):
    with pytest.raises(import_obj.IngestError, match="not found"):
        import_obj.run_ingest(
            source=sandbox / "ghost.obj", name="ghost",
            imported_at=FIXED_TS, license="CC0",
        )


def test_ingest_degenerate_bounds_hard_fail(sandbox):
    """All-coincident verts → zero bounds on every axis → hard fail (D6)."""
    src = sandbox / "degenerate.obj"
    src.write_text("v 1 1 1\nv 1 1 1\nv 1 1 1\nf 1 2 3\n")
    with pytest.raises(import_obj.IngestError, match="degenerate"):
        import_obj.run_ingest(source=src, name="degen",
                              imported_at=FIXED_TS, license="CC0")
    assert not (sandbox / "assets" / "derived" / "degen").exists()


def test_ingest_malformed_source_hard_fail(sandbox):
    """Unparseable vertex line → hard fail (D6)."""
    src = sandbox / "malformed.obj"
    src.write_text("v not a number here\nf 1 1 1\n")
    with pytest.raises(import_obj.IngestError, match="malformed"):
        import_obj.run_ingest(source=src, name="bad",
                              imported_at=FIXED_TS, license="CC0")


def test_get_registered_hash_drift(sandbox):
    src = _write_source(sandbox)
    import_obj.run_ingest(source=src, name="drift", imported_at=FIXED_TS,
                          license="CC0")
    mesh_path = sandbox / "assets" / "derived" / "drift" / "mesh.obj"
    # hand-edit the mesh AFTER ingest → hash no longer matches provenance
    mesh_path.write_text(mesh_path.read_text() + "v 9 9 9\n")
    wm.clear_registry_cache()
    with pytest.raises(ValueError, match="hash drift"):
        wm.get_registered("drift")


def test_cache_hit_survives_file_delete(sandbox):
    src = _write_source(sandbox)
    import_obj.run_ingest(source=src, name="cached", imported_at=FIXED_TS,
                          license="CC0")
    wm.clear_registry_cache()
    first = wm.get_registered("cached")
    assert first is not None
    # delete the file; cached mesh must still resolve (cache hit)
    (sandbox / "assets" / "derived" / "cached" / "mesh.obj").unlink()
    assert wm.get_registered("cached") is first
