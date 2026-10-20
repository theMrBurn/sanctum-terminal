"""
tools/kitbash_assemble.py

Persona D -- the Blender->glTF backend of the kitbash / greeble subsystem
(spec_kitbash_greeble.md §4, Persona D in §5). The CAPABILITY path that feeds
the currently-paused Godot client.

This is a **bpy script run by the Blender BINARY headless** -- NOT `pip bpy`,
NOT importable as a normal module (it does `import bpy`). Drive it as:

    <BLENDER> --background --factory-startup --python tools/kitbash_assemble.py \
        -- <assembly_json_path> <out_glb_path>

The Python-side runner that shells this out is
core/systems/kitbash_blender_backend.py.

What it does
------------
1. Parse argv after "--": an input assembly-JSON path + an output .glb path.
   The JSON is a serialized AssemblyResult (core/systems/kitbash_engine.py):
       { "base_id": str, "bindings": [[socket_name, part_id], ...] }
   (signal_snapshot is carried in the JSON but not needed for meshing.)
2. Build a FIXTURE programmatically in bpy -- a base mesh + named socket
   EMPTIES (convention SKT_<type>_<n>) at known transforms + simple greeble
   meshes named by part_id. No curated assets exist yet; this makes the whole
   pipeline provable end-to-end without external assets. The three build_* /
   collect_sockets seams below are where a real base/greeble asset path drops
   in later (load a .blend / .obj instead of making cubes).
3. Socket detection: collect EMPTIES named SKT_* and match them to the
   AssemblyResult bindings by name.
4. For each binding, instance the greeble mesh at the matching empty's transform.
5. Apply a DECIMATE modifier to each assembled mesh (baked at export via
   export_apply). A simple-subsurf pass first gives the plain cubes coplanar
   geometry for the collapse to actually remove -- a no-op decimate is a bug.
6. Delete the socket empties (anchors have done their job) so the export is a
   clean `1 base + N greebles` set of mesh nodes.
7. Export glTF via bpy.ops.export_scene.gltf. The exporter's Z-up (Blender) ->
   Y-up (glTF) conversion is the axis convention the cross-reference test pins
   (see AXIS section below and tests/test_kitbash_blender_backend.py).
8. Write a sidecar <out>.report.json with the decimate before/after triangle
   counts and the node manifest, so the test can prove the decimate actually
   ran (a metric the exported .glb alone cannot reveal).

Air-gap / no-LLM: pure bpy + json + struct. Deterministic. No network, no model.

Axis convention (pinned)
-------------------------
Blender is Z-up; the glTF exporter (export_yup=True, the default) rewrites the
scene to glTF's Y-up. Empirically and by spec the point map is:

    glTF (x, y, z)  =  Blender (x, z, -y)

So a socket placed UP in Blender (+Z) lands at glTF +Y; a socket placed FORWARD
in Blender (+Y) lands at glTF -Z. This agrees with the codebase's other glTF
writer, tools/export_glb.py (Panda Y-forward -> glTF Y-up). AGENTS.md line 27
requires this be pinned from both sides -- the test asserts the on-disk glTF
node translations against the Blender-space socket transforms below.
"""

import json
import struct
import sys

import bpy


# -- Constants (no hardcoded tunables -- AGENTS.md line 18) --------------------

# Socket-empty naming convention. Empties whose name starts with this prefix are
# the base's attach points; everything after is <type>_<n>.
SKT_PREFIX = "SKT_"

# The programmatic FIXTURE. socket_name -> Blender-space location (x, y, z).
# These names ARE the socket names carried in the AssemblyResult bindings (the
# engine's Base declares sockets with exactly these names), so detection matches
# an empty to a binding by identical name -- no separate normalization table.
# The three axes are deliberately separated (one socket per axis) so the axis
# cross-reference test is unambiguous:
#   SKT_mount_0  -> +X  (stays +X in glTF)
#   SKT_mount_1  -> +Y forward (becomes -Z in glTF)
#   SKT_spire_0  -> +Z up      (becomes +Y in glTF)
SOCKET_ARM = 3.0                       # distance of each socket from the origin
FIXTURE_SOCKETS = {
    "SKT_mount_0": (SOCKET_ARM, 0.0, 0.0),
    "SKT_mount_1": (0.0, SOCKET_ARM, 0.0),
    "SKT_spire_0": (0.0, 0.0, SOCKET_ARM),
}

# Fixture mesh sizing. Greebles are small relative to SOCKET_ARM so their node
# translation is unambiguous against the arm distance.
FIXTURE_BASE_NAME = "kitbash_base"
BASE_CUBE_SIZE    = 2.0                # base cube edge length
GREEBLE_CUBE_SIZE = 0.6               # greeble cube edge length

# Simple-subsurf level applied before decimate: gives the cubes coplanar faces
# for the collapse modifier to remove. Simple (not Catmull-Clark) keeps shape.
SUBSURF_LEVELS = 2

# DECIMATE collapse ratio: fraction of edges to keep. < 1.0 so the modifier is a
# real reduction, not a silent no-op.
DECIMATE_RATIO = 0.5
DECIMATE_TYPE  = "COLLAPSE"

# glTF export parameters. export_yup=True is the Z-up->Y-up convention the axis
# test pins; export_apply=True bakes the modifier stack (incl. DECIMATE) into
# the exported mesh.
GLTF_FORMAT      = "GLB"
GLTF_EXPORT_YUP  = True
GLTF_EXPORT_APPLY = True

REPORT_SUFFIX = ".report.json"


# -- Scene helpers ------------------------------------------------------------

def _clear_scene():
    """Remove every object -- start from an empty scene regardless of the
    Blender startup file (we also pass --factory-startup from the runner)."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def _triangle_count(obj) -> int:
    """Evaluated triangle count of `obj` WITH its current modifier stack applied
    (via the dependency graph). Used to prove DECIMATE reduced geometry."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    mesh.calc_loop_triangles()
    n = len(mesh.loop_triangles)
    eval_obj.to_mesh_clear()
    return n


# -- Fixture build seams (replace with real asset loading later) --------------

def build_fixture_base():
    """SEAM: construct the fixture base mesh. A real path would load a curated
    base asset (which carries its own SKT_* empties) instead. Returns the base
    object."""
    bpy.ops.mesh.primitive_cube_add(size=BASE_CUBE_SIZE, location=(0.0, 0.0, 0.0))
    base = bpy.context.active_object
    base.name = FIXTURE_BASE_NAME
    return base


def build_fixture_sockets():
    """SEAM: create the SKT_* socket empties at the fixture transforms. A real
    base already carries these; this exists only because no curated asset does
    yet. collect_sockets() below reads them back the same way for either path."""
    for name, loc in FIXTURE_SOCKETS.items():
        empty = bpy.data.objects.new(name, None)      # None data == EMPTY
        empty.empty_display_type = "PLAIN_AXES"
        empty.location = loc
        bpy.context.scene.collection.objects.link(empty)


def build_greeble(part_id: str, socket_empty):
    """SEAM: instance the greeble for `part_id` at `socket_empty`'s FULL
    transform. A real path resolves part_id -> a curated mesh asset; here it is
    a small named cube. The greeble inherits the socket's location, ROTATION and
    SCALE (matrix_world) -- a socket's job is to say which way the greeble points
    and how big it is, so a real rotated/scaled SKT_* empty orients its greeble.
    The transform is LEFT on the object (not baked into vertices) so it survives
    export as node.translation/rotation/scale -- which the axis test reads.
    Returns the greeble object."""
    bpy.ops.mesh.primitive_cube_add(size=GREEBLE_CUBE_SIZE, location=(0.0, 0.0, 0.0))
    greeble = bpy.context.active_object
    greeble.name = part_id
    greeble.matrix_world = socket_empty.matrix_world.copy()
    return greeble


# -- Assembly -----------------------------------------------------------------

def collect_sockets() -> dict:
    """Detect socket attach points: EMPTIES whose name starts with SKT_PREFIX.
    Works for the fixture AND for a real base that carries its own empties.
    Returns {socket_name: object}."""
    return {
        obj.name: obj
        for obj in bpy.data.objects
        if obj.type == "EMPTY" and obj.name.startswith(SKT_PREFIX)
    }


def _add_decimate_stack(obj):
    """Give `obj` coplanar geometry (simple subsurf) then a DECIMATE collapse
    modifier. Both bake at export (export_apply). Returns (tris_before, tris_after)
    measured across just the decimate stage."""
    subsurf = obj.modifiers.new(name="kitbash_subsurf", type="SUBSURF")
    subsurf.subdivision_type = "SIMPLE"          # keep cube shape, add geometry
    subsurf.levels = SUBSURF_LEVELS
    subsurf.render_levels = SUBSURF_LEVELS

    tris_before = _triangle_count(obj)           # subsurf only

    decimate = obj.modifiers.new(name="kitbash_decimate", type="DECIMATE")
    decimate.decimate_type = DECIMATE_TYPE
    decimate.ratio = DECIMATE_RATIO

    tris_after = _triangle_count(obj)            # subsurf + decimate
    return tris_before, tris_after


def assemble(assembly: dict, out_glb_path: str) -> dict:
    """Build the fixture, bind greebles to sockets per the AssemblyResult,
    decimate, export glTF, and return the report dict (also written to the
    sidecar). Raises on a binding whose socket empty is absent."""
    bindings = [tuple(b) for b in assembly.get("bindings", [])]

    _clear_scene()
    base = build_fixture_base()
    build_fixture_sockets()
    sockets = collect_sockets()

    greebles = []
    for socket_name, part_id in bindings:
        empty = sockets.get(socket_name)
        if empty is None:
            raise ValueError(
                f"binding references socket {socket_name!r} but no SKT_ empty "
                f"with that name exists (have: {sorted(sockets)})"
            )
        greebles.append(build_greeble(part_id, empty))

    # DECIMATE the whole assembled result (base + every greeble).
    decimate_report = {}
    for obj in [base] + greebles:
        before, after = _add_decimate_stack(obj)
        decimate_report[obj.name] = {"tris_before": before, "tris_after": after}

    # Empties have served as anchors; drop them so the export is a clean
    # 1-base + N-greeble mesh-node set (empties would otherwise export as nodes).
    for empty in list(sockets.values()):
        bpy.data.objects.remove(empty, do_unlink=True)

    bpy.ops.export_scene.gltf(
        filepath=out_glb_path,
        export_format=GLTF_FORMAT,
        export_yup=GLTF_EXPORT_YUP,
        export_apply=GLTF_EXPORT_APPLY,
        use_selection=False,
    )

    report = {
        "base_id": assembly.get("base_id"),
        "base_name": base.name,
        "greeble_names": [g.name for g in greebles],
        "expected_mesh_nodes": 1 + len(greebles),
        "decimate": decimate_report,
        "decimate_ratio": DECIMATE_RATIO,
        "axis": {
            # The pinned Blender->glTF map, echoed for the test's reference.
            "convention": "gltf(x,y,z) = blender(x, z, -y)  [export_yup]",
            "socket_transforms_blender": FIXTURE_SOCKETS,
        },
    }
    with open(out_glb_path + REPORT_SUFFIX, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    return report


def _parse_argv():
    """argv after the '--' separator: <assembly_json_path> <out_glb_path>."""
    if "--" not in sys.argv:
        raise SystemExit("expected: ... -- <assembly_json_path> <out_glb_path>")
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 2:
        raise SystemExit(
            f"expected 2 args after --, got {len(args)}: {args}"
        )
    return args[0], args[1]


def main():
    assembly_json_path, out_glb_path = _parse_argv()
    with open(assembly_json_path, "r", encoding="utf-8") as fh:
        assembly = json.load(fh)
    report = assemble(assembly, out_glb_path)
    # Distinctive marker line: lets the runner confirm the script ran to the end
    # even amid Blender's own stdout noise.
    print("KITBASH_ASSEMBLE_OK", json.dumps({
        "out": out_glb_path,
        "mesh_nodes": report["expected_mesh_nodes"],
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:                      # noqa: BLE001 -- surface to stderr
        import traceback
        traceback.print_exc()
        print(f"KITBASH_ASSEMBLE_FAIL {exc}", file=sys.stderr)
        sys.exit(1)
