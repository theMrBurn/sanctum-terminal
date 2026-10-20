"""
tests/test_kitbash_blender_backend.py

Persona D -- the Blender->glTF backend (spec_kitbash_greeble.md §4, §6). These
tests SHELL OUT to the Blender BINARY headless (they are slow/integration), so
they pytest.skip gracefully when Blender is not installed on the host.

The backend consumes an AssemblyResult -- but Persona D tests the backend
consuming a *given* result, so the fixture assembly JSON is hand-authored here
(it does NOT ride on KitbashEngine's selection determinism; that is Persona A's
test). The socket names in the bindings are the SKT_<type>_<n> empties the bpy
fixture builds -- detection matches an empty to a binding by identical name.

Coverage:
  (a) produces a non-empty .glb + the expected mesh-node count -- TEST.
  (b) DECIMATE actually ran (sidecar before/after triangle counts) -- TEST.
      A no-op decimate would still pass a count check; this catches it.
  (c) COORDINATE CROSS-REFERENCE (AGENTS.md line 27) -- TEST. Pins BOTH sides
      of the Blender Z-up -> glTF Y-up convention by reading the raw glTF node
      translations off disk and asserting them against the Blender-space socket
      transforms. Read off disk (not via a bpy re-import, which would convert
      Y-up back to Z-up and prove only round-trip consistency, not the on-disk
      convention). Agrees with the codebase's other glTF writer,
      tools/export_glb.py (Panda Y-forward -> glTF Y-up).
"""

import json
import struct

import pytest

from core.systems.kitbash_blender_backend import (
    assemble_to_glb,
    is_blender_available,
    report_path_for,
)

# NOTE: tools/kitbash_assemble.py is a bpy script (`import bpy` at module top) and
# is NOT importable outside Blender. So the test sources the fixture's declared
# Blender-space facts (socket transforms, base name, decimate ratio) from the
# sidecar REPORT the run writes -- and independently parses the .glb for the
# OUTPUT translations. LEFT side (Blender input) vs RIGHT side (glTF output on
# disk) => the axis convention is pinned across the boundary, not self-referenced.


# Slow: each test spawns a headless Blender process.
pytestmark = [pytest.mark.slow, pytest.mark.integration]

# Skip the whole module unless Blender is present.
if not is_blender_available():
    pytest.skip(
        "Blender binary not available (set KITBASH_BLENDER) -- "
        "skipping Persona D integration tests.",
        allow_module_level=True,
    )


# -- Fixture: a hand-authored AssemblyResult (dict), one binding per axis ------
# Socket names are the SKT_ empties the bpy fixture builds; one socket per axis
# so the coordinate cross-reference is unambiguous.

FIXTURE_ASSEMBLY = {
    "base_id": "hull_alpha",
    "bindings": [
        ["SKT_mount_0", "greeble_x"],     # Blender +X
        ["SKT_mount_1", "greeble_fwd"],   # Blender +Y (forward)
        ["SKT_spire_0", "greeble_up"],    # Blender +Z (up)
    ],
    "signal_snapshot": {"entropy": 0.2},
}
EXPECTED_MESH_NODES = 1 + len(FIXTURE_ASSEMBLY["bindings"])   # base + greebles


def _parse_glb(path):
    """Parse a .glb: return the embedded glTF JSON dict. glb layout is a
    12-byte header then chunks; the first chunk is the JSON (8-byte chunk header
    + payload). Read off disk -- the point is to inspect the on-disk numbers."""
    with open(path, "rb") as fh:
        data = fh.read()
    assert data[:4] == b"glTF", "not a glb (bad magic)"
    json_len = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + json_len])


@pytest.fixture
def built_glb(tmp_path):
    """Run the backend once; return (glb_path, gltf_dict, report_dict)."""
    out = tmp_path / "assembly.glb"
    path = assemble_to_glb(FIXTURE_ASSEMBLY, out)
    gltf = _parse_glb(path)
    with open(report_path_for(path), encoding="utf-8") as fh:
        report = json.load(fh)
    return path, gltf, report


# -- (a) a non-empty .glb with the expected mesh-node count -------------------

def test_produces_non_empty_glb(built_glb, tmp_path):
    path, gltf, report = built_glb
    assert path == str(tmp_path / "assembly.glb")
    import os
    assert os.path.getsize(path) > 0

    # One node per mesh object: base + each bound greeble. Empties were deleted
    # before export, so no stray nodes.
    mesh_nodes = [n for n in gltf.get("nodes", []) if "mesh" in n]
    assert len(mesh_nodes) == EXPECTED_MESH_NODES
    assert len(gltf.get("meshes", [])) == EXPECTED_MESH_NODES

    node_names = {n["name"] for n in mesh_nodes}
    assert report["base_name"] in node_names
    for _socket, part_id in FIXTURE_ASSEMBLY["bindings"]:
        assert part_id in node_names


# -- (b) DECIMATE actually reduced geometry -----------------------------------

def test_decimate_ran(built_glb):
    _, _, report = built_glb
    assert 0.0 < report["decimate_ratio"] < 1.0    # a real reduction, not a no-op
    # Every assembled mesh must show a real reduction -- a no-op decimate is a bug.
    for name, counts in report["decimate"].items():
        assert counts["tris_after"] < counts["tris_before"], (
            f"{name}: decimate was a no-op "
            f"({counts['tris_before']} -> {counts['tris_after']})"
        )


# -- (c) coordinate cross-reference: Blender Z-up -> glTF Y-up -----------------
# AGENTS.md line 27. The exporter maps a Blender point (x, y, z) to glTF
# (x, z, -y). Both sides are pinned: the LEFT side is the Blender-space socket
# transform the bpy fixture uses (ka.FIXTURE_SOCKETS); the RIGHT side is the
# node.translation read off the exported glb. Same convention as
# tools/export_glb.py (Panda Y-forward -> glTF Y-up).

def _blender_to_gltf(point):
    """The pinned convention: glTF (x, y, z) = Blender (x, z, -y)."""
    bx, by, bz = point
    return [bx, bz, -by]


def _node_translation(gltf, name):
    """A node's glTF translation (default origin when omitted)."""
    for n in gltf.get("nodes", []):
        if n.get("name") == name:
            assert "matrix" not in n, (
                f"node {name} exported a matrix, not a translation -- the axis "
                "pin below assumes a bare translation (verified for this exporter)"
            )
            return n.get("translation", [0.0, 0.0, 0.0])
    raise AssertionError(f"node {name} not found in {[n.get('name') for n in gltf['nodes']]}")

def test_axis_convention_pinned_both_sides(built_glb):
    _, gltf, report = built_glb

    # LEFT side (Blender input): the socket transforms the fixture declares it used.
    socket_transforms = report["axis"]["socket_transforms_blender"]
    socket_to_part = {s: p for s, p in FIXTURE_ASSEMBLY["bindings"]}

    # RIGHT side (glTF output on disk): assert each node translation equals the
    # converted Blender point.
    for socket_name, blender_pos in socket_transforms.items():
        part_id = socket_to_part[socket_name]
        got = _node_translation(gltf, part_id)
        expected = _blender_to_gltf(blender_pos)
        assert got == pytest.approx(expected, abs=1e-5), (
            f"{socket_name} greeble {part_id}: Blender {blender_pos} should map "
            f"to glTF {expected}, got {got}"
        )

    # Explicit, human-readable both-sides assertions on the load-bearing axes so
    # a silent flip is unmissable in the failure output:
    #   Blender +Z (UP)      must land at glTF +Y.
    #   Blender +Y (FORWARD) must land at glTF -Z.
    arm = socket_transforms["SKT_spire_0"][2]   # the +Z (up) arm distance
    up_t  = _node_translation(gltf, socket_to_part["SKT_spire_0"])   # fixture: +Z
    fwd_t = _node_translation(gltf, socket_to_part["SKT_mount_1"])   # fixture: +Y
    assert up_t[1] == pytest.approx(arm) and up_t[2] == pytest.approx(0.0), \
        f"Blender +Z (up) did not land at glTF +Y: {up_t}"
    assert fwd_t[2] == pytest.approx(-arm) and fwd_t[1] == pytest.approx(0.0), \
        f"Blender +Y (forward) did not land at glTF -Z: {fwd_t}"


# -- runner surface -----------------------------------------------------------

def test_is_blender_available_true_here():
    # This module is skipped otherwise, so within it this must hold.
    assert is_blender_available() is True


def test_failure_raises_with_captured_output(tmp_path, monkeypatch):
    """A 'Blender' that runs but writes no .glb must raise RuntimeError (the
    success signal is the artifact, not the return code). Point the runner at
    `true` (exits 0, produces nothing)."""
    import shutil
    true_bin = shutil.which("true")
    if true_bin is None:
        pytest.skip("no `true` binary to stand in for a no-output Blender")
    monkeypatch.setenv("KITBASH_BLENDER", true_bin)
    assert is_blender_available() is True          # `true` is exec-able
    with pytest.raises(RuntimeError, match="produced no .glb"):
        assemble_to_glb(FIXTURE_ASSEMBLY, tmp_path / "never.glb")
