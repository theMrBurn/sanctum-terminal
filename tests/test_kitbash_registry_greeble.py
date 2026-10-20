"""End-to-end proof: a REAL ingested mesh (via the wireframe registry) is used
as a kitbash greeble — the full chain ingest -> registry -> resolve -> part ->
assemble -> compose -> terminal-ready op-log. Self-contained: ingests under a
throwaway name and restores the registry + derived dir on teardown, so it never
pollutes the committed repo.
"""
import json
import shutil
from pathlib import Path

from core.systems import kitbash_engine as ke
from core.systems import kitbash_wireframe_backend as kb
from core.systems.wireframe_mesh import resolve_mesh, clear_registry_cache
from core.systems.wireframe_edits import replay
from tools.import_obj import run_ingest

REPO = Path(__file__).resolve().parents[1]
NAME = "greeble_probe_e2e"


def _write_tetra(path: Path) -> None:
    # a small non-degenerate tetrahedron (4 verts, 4 faces) — a valid ingest source
    path.write_text(
        "v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\n"
        "f 1 2 3\nf 1 2 4\nf 1 3 4\nf 2 3 4\n"
    )


def test_registered_mesh_greebled_end_to_end(tmp_path):
    src = tmp_path / "probe.obj"
    _write_tetra(src)
    registry = REPO / "config" / "wireframe_meshes.json"
    derived = REPO / "assets" / "derived" / NAME
    before = registry.read_text() if registry.is_file() else None
    try:
        # 1) INGEST a real mesh through the registry pipeline
        run_ingest(
            source=src, name=NAME, imported_at="2026-07-28T00:00:00-07:00",
            recenter="bottom_center", rescale_height=1.0,
            license="CC0", credit="test-fixture", vendor="test", pack="probe",
        )
        clear_registry_cache()

        # 2) it RESOLVES from the registry
        mesh = resolve_mesh(NAME)
        assert len(mesh.vertices) == 4, "ingested tetra should round-trip 4 verts"

        # 3) it appears as a kitbash PART (default panel/medium, so it binds the hull)
        regparts = {p.part_id: p for p in kb.registered_parts()}
        assert NAME in regparts, "registered mesh must surface as a greeble Part"
        assert "panel" in regparts[NAME].socket_types

        # 4) ASSEMBLE with only this part -> binds to the hull's panel 'port' socket
        parts = [regparts[NAME]]
        result = ke.KitbashEngine().assemble(kb.base_hull(), parts, {"entropy": 0.0}, seed=1)
        assert ("port", NAME) in result.bindings, "registered greeble should bind the panel socket"

        # 5) COMPOSE merges the real mesh's geometry at the socket
        meshes = kb.meshes_for(parts)
        scales = kb.scale_map(parts)
        composed = kb.compose(kb.hull_base_mesh(), kb.hull_socket_positions(), result, meshes, scales=scales)
        expected = len(kb.hull_base_mesh().vertices) + 4
        assert len(composed.vertices) == expected, "composed = hull + the ingested greeble"

        # 6) TERMINAL-READY: the op-log replays (the live vector-terminal path) to the same mesh
        edits = kb.to_mesh_edits(kb.hull_base_mesh(), kb.hull_socket_positions(), result, meshes, scales=scales)
        replayed = replay(kb.hull_base_mesh(), edits)
        assert len(replayed.vertices) == len(composed.vertices), "replay(op-log) == compose"
    finally:
        clear_registry_cache()
        if before is not None:
            registry.write_text(before)
        elif registry.is_file():
            registry.unlink()
        if derived.exists():
            shutil.rmtree(derived)
        clear_registry_cache()
