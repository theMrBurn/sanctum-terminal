"""
tools/export_glb.py

Export Panda3D builder meshes to .glb (glTF binary) for Godot.

Builds each entity kind headless, strips glow decals, and exports
via panda3d-gltf. Output goes to godot/meshes/<kind>.glb.

Usage:
    PYTHONPATH=. ./.venv/bin/python tools/export_glb.py
"""

import os
import sys
import struct
import json
import math

# Panda3D headless init
os.environ["PANDA_PRC_DIR"] = ""
os.environ["PANDA_PRC_PATH"] = ""

from panda3d.core import (
    NodePath, GeomNode, GeomVertexReader, GeomVertexWriter,
    GeomVertexFormat, GeomVertexData, Geom, GeomTriangles,
    loadPrcFileData, LVector3, LVector4, Filename,
)
loadPrcFileData("", "window-type none")
loadPrcFileData("", "audio-library-name null")

from direct.showbase.ShowBase import ShowBase
base = ShowBase()

# Strip glow decals (same as extract_meshes.py)
import core.systems.glow_decal as _glow_mod

def _noop_decal(parent, color, radius, tex=None, height_offset=0.08):
    return parent.attachNewNode("stripped_decal")
def _noop_shaft(parent, color, shaft_height, shaft_width=1.5, tex=None):
    return parent.attachNewNode("stripped_shaft")
def _noop_halo(parent, color, halo_radius, halo_height, tex=None):
    return parent.attachNewNode("stripped_halo")

_glow_mod.make_glow_decal = _noop_decal
_glow_mod.make_light_shaft = _noop_shaft
_glow_mod.make_glow_halo = _noop_halo

from core.systems.ambient_life import (
    build_boulder, build_grass_tuft, build_rubble, build_leaf_pile,
    build_dead_log, build_twig_scatter, build_stalagmite,
    build_column, build_mega_column, build_giant_fungus,
    build_moss_patch, build_crystal_cluster, build_bone_pile,
    build_rat, build_leaf, build_spider, build_beetle, build_firefly,
    build_cave_gravel, build_ceiling_moss, build_hanging_vine,
    build_filament,
    build_horizon_form, build_horizon_mid, build_horizon_near,
    build_exit_lure,
    set_active_biome,
)

set_active_biome("outdoor")

BUILDERS = {
    "mega_column":     build_mega_column,
    "column":          build_column,
    "boulder":         build_boulder,
    "stalagmite":      build_stalagmite,
    "crystal_cluster": build_crystal_cluster,
    "giant_fungus":    build_giant_fungus,
    "dead_log":        build_dead_log,
    "moss_patch":      build_moss_patch,
    "bone_pile":       build_bone_pile,
    "grass_tuft":      build_grass_tuft,
    "rubble":          build_rubble,
    "leaf_pile":       build_leaf_pile,
    "twig_scatter":    build_twig_scatter,
    "cave_gravel":     build_cave_gravel,
    "firefly":         build_firefly,
    "leaf":            build_leaf,
    "beetle":          build_beetle,
    "rat":             build_rat,
    "spider":          build_spider,
    "ceiling_moss":    build_ceiling_moss,
    "hanging_vine":    build_hanging_vine,
    "filament":        build_filament,
    "horizon_form":    build_horizon_form,
    "horizon_mid":     build_horizon_mid,
    "horizon_near":    build_horizon_near,
    "exit_lure":       build_exit_lure,
}


def compute_face_normal(p0, p1, p2):
    ax, ay, az = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    bx, by, bz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
    nx = ay * bz - az * by
    ny = az * bx - ax * bz
    nz = ax * by - ay * bx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-8:
        return (0.0, 0.0, 1.0)
    return (nx / length, ny / length, nz / length)


def extract_triangles(node_path):
    """Extract all triangles as (pos, normal, color) per vertex."""
    tris = []

    for np in node_path.findAllMatches("**/+GeomNode"):
        geom_node = np.node()
        mat = np.getMat(node_path)

        for gi in range(geom_node.getNumGeoms()):
            geom = geom_node.getGeom(gi)
            vdata = geom.getVertexData()
            vreader = GeomVertexReader(vdata, "vertex")
            has_color = vdata.hasColumn("color")
            if has_color:
                creader = GeomVertexReader(vdata, "color")

            positions = []
            colors = []
            while not vreader.isAtEnd():
                v = vreader.getData3()
                tv = mat.xformPoint(v)
                positions.append((tv.getX(), tv.getY(), tv.getZ()))
                if has_color:
                    c = creader.getData4()
                    colors.append((c.getX(), c.getY(), c.getZ()))
                else:
                    colors.append((0.5, 0.5, 0.5))

            for pi in range(geom.getNumPrimitives()):
                prim = geom.getPrimitive(pi).decompose()
                for ti in range(prim.getNumPrimitives()):
                    start = prim.getPrimitiveStart(ti)
                    i0 = prim.getVertex(start)
                    i1 = prim.getVertex(start + 1)
                    i2 = prim.getVertex(start + 2)
                    if max(i0, i1, i2) >= len(positions):
                        continue
                    p0, p1, p2 = positions[i0], positions[i1], positions[i2]
                    fn = compute_face_normal(p0, p1, p2)
                    for idx in (i0, i1, i2):
                        tris.append((positions[idx], fn, colors[idx]))

    # Check root node too
    if node_path.node().isOfType(GeomNode.getClassType()):
        geom_node = node_path.node()
        for gi in range(geom_node.getNumGeoms()):
            geom = geom_node.getGeom(gi)
            vdata = geom.getVertexData()
            vreader = GeomVertexReader(vdata, "vertex")
            has_color = vdata.hasColumn("color")
            if has_color:
                creader = GeomVertexReader(vdata, "color")
            positions = []
            colors = []
            while not vreader.isAtEnd():
                v = vreader.getData3()
                positions.append((v.getX(), v.getY(), v.getZ()))
                if has_color:
                    c = creader.getData4()
                    colors.append((c.getX(), c.getY(), c.getZ()))
                else:
                    colors.append((0.5, 0.5, 0.5))
            for pi in range(geom.getNumPrimitives()):
                prim = geom.getPrimitive(pi).decompose()
                for ti in range(prim.getNumPrimitives()):
                    start = prim.getPrimitiveStart(ti)
                    i0 = prim.getVertex(start)
                    i1 = prim.getVertex(start + 1)
                    i2 = prim.getVertex(start + 2)
                    if max(i0, i1, i2) >= len(positions):
                        continue
                    p0, p1, p2 = positions[i0], positions[i1], positions[i2]
                    fn = compute_face_normal(p0, p1, p2)
                    for idx in (i0, i1, i2):
                        tris.append((positions[idx], fn, colors[idx]))

    return tris


def normalize_and_rebase(tris):
    """Center XY at origin, base Z at 0, normalize to unit scale.

    Returns (normalized_tris, bounds).
    Panda3D Y-forward → glTF Y-up conversion:
      Panda (X, Y, Z) → glTF (X, Z, Y)
    """
    if not tris:
        return tris, {}

    xs = [t[0][0] for t in tris]
    ys = [t[0][1] for t in tris]
    zs = [t[0][2] for t in tris]

    cx = (min(xs) + max(xs)) * 0.5
    cy = (min(ys) + max(ys)) * 0.5
    z_min = min(zs)

    w = max(xs) - min(xs)
    d = max(ys) - min(ys)
    h = max(zs) - min(zs)
    max_dim = max(w, d, h, 0.001)
    inv = 1.0 / max_dim

    # Convert positions to glTF space first, then recompute normals
    converted = []
    for pos, _norm, col in tris:
        px = (pos[0] - cx) * inv
        py = (pos[2] - z_min) * inv    # Panda Z → glTF Y
        pz = -(pos[1] - cy) * inv      # Panda Y → glTF -Z
        converted.append(((px, py, pz), col))

    # The Z-negate mirrors geometry, flipping triangle winding.
    # Swap verts 1 and 2 to restore CCW for glTF, then recompute normals.
    # First pass: build triangles with face normals and fix winding.
    fixed = []
    for i in range(0, len(converted), 3):
        if i + 2 >= len(converted):
            break
        v0 = converted[i]
        v1 = converted[i+1]
        v2 = converted[i+2]
        fn = compute_face_normal(v0[0], v2[0], v1[0])
        fixed.append((v0[0], fn, v0[1]))
        fixed.append((v2[0], fn, v2[1]))
        fixed.append((v1[0], fn, v1[1]))

    return fixed, {"width": w, "depth": d, "height": h, "scale": max_dim}


def smooth_normals(tris):
    """Average normals at shared vertex positions. Makes low-poly look smooth.

    Vertices within 0.001 distance are considered the same point.
    Their normals are averaged, giving soft shading on curved surfaces.
    """
    import collections

    # Quantize positions to find shared vertices
    def key(p):
        return (round(p[0], 3), round(p[1], 3), round(p[2], 3))

    # Accumulate normals per position
    normal_accum = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
    for pos, norm, col in tris:
        k = key(pos)
        normal_accum[k][0] += norm[0]
        normal_accum[k][1] += norm[1]
        normal_accum[k][2] += norm[2]

    # Normalize accumulated normals
    smooth = {}
    for k, n in normal_accum.items():
        length = math.sqrt(n[0]**2 + n[1]**2 + n[2]**2)
        if length < 1e-8:
            smooth[k] = (0.0, 1.0, 0.0)
        else:
            smooth[k] = (n[0]/length, n[1]/length, n[2]/length)

    # Replace normals
    out = []
    for pos, norm, col in tris:
        k = key(pos)
        out.append((pos, smooth[k], col))
    return out


def write_glb(tris, filepath):
    """Write triangle list to a .glb file (glTF 2.0 binary).

    Embeds vertex positions, normals, and colors (COLOR_0) so Godot
    can render with vertex_color_use_as_albedo.
    """
    num_verts = len(tris)
    if num_verts == 0:
        return False

    # Build buffer: position (3f) + normal (3f) + color (4f) per vertex
    # COLOR_0 in glTF is vec4 float
    stride = (3 + 3 + 4) * 4  # 40 bytes per vertex
    buf = bytearray()

    pos_min = [1e9, 1e9, 1e9]
    pos_max = [-1e9, -1e9, -1e9]

    for pos, norm, col in tris:
        buf += struct.pack("<3f", pos[0], pos[1], pos[2])
        buf += struct.pack("<3f", norm[0], norm[1], norm[2])
        buf += struct.pack("<4f", col[0], col[1], col[2], 1.0)
        for i in range(3):
            pos_min[i] = min(pos_min[i], pos[i])
            pos_max[i] = max(pos_max[i], pos[i])

    # Pad buffer to 4-byte alignment
    while len(buf) % 4 != 0:
        buf += b"\x00"

    pos_offset = 0
    norm_offset = 12
    color_offset = 24

    # glTF JSON
    gltf = {
        "asset": {"version": "2.0", "generator": "sanctum-terminal"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{
            "primitives": [{
                "attributes": {
                    "POSITION": 0,
                    "NORMAL": 1,
                    "COLOR_0": 2,
                },
                "mode": 4,  # TRIANGLES
            }],
        }],
        "accessors": [
            {   # POSITION
                "bufferView": 0,
                "byteOffset": pos_offset,
                "componentType": 5126,  # FLOAT
                "count": num_verts,
                "type": "VEC3",
                "min": pos_min,
                "max": pos_max,
            },
            {   # NORMAL
                "bufferView": 0,
                "byteOffset": norm_offset,
                "componentType": 5126,
                "count": num_verts,
                "type": "VEC3",
            },
            {   # COLOR_0
                "bufferView": 0,
                "byteOffset": color_offset,
                "componentType": 5126,
                "count": num_verts,
                "type": "VEC4",
            },
        ],
        "bufferViews": [{
            "buffer": 0,
            "byteOffset": 0,
            "byteLength": len(buf),
            "byteStride": stride,
        }],
        "buffers": [{
            "byteLength": len(buf),
        }],
    }

    gltf_json = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    # Pad JSON to 4-byte alignment
    while len(gltf_json) % 4 != 0:
        gltf_json += b" "

    # GLB structure: header (12) + JSON chunk (8 + json) + BIN chunk (8 + buf)
    total_length = 12 + 8 + len(gltf_json) + 8 + len(buf)

    with open(filepath, "wb") as f:
        # GLB header
        f.write(b"glTF")
        f.write(struct.pack("<II", 2, total_length))
        # JSON chunk
        f.write(struct.pack("<II", len(gltf_json), 0x4E4F534A))  # JSON
        f.write(gltf_json)
        # BIN chunk
        f.write(struct.pack("<II", len(buf), 0x004E4942))  # BIN
        f.write(buf)

    return True


def main():
    out_dir = os.path.join("godot", "meshes")
    os.makedirs(out_dir, exist_ok=True)

    print(f"Exporting {len(BUILDERS)} kinds to .glb...", flush=True)

    root = NodePath("export_root")
    bounds_map = {}

    VARIANTS = 4  # export 4 variants per kind with different seeds
    VARIANT_SEEDS = [42, 137, 293, 571]

    SMOOTH_KINDS = {
        "mega_column", "column", "boulder", "giant_fungus",
        "moss_patch", "dead_log", "bone_pile", "grass_tuft",
        "rubble", "leaf_pile", "hanging_vine", "ceiling_moss",
        "horizon_form", "horizon_mid", "horizon_near",
        "rat", "beetle", "spider", "firefly", "leaf",
    }

    for kind, builder_fn in BUILDERS.items():
        for vi, vseed in enumerate(VARIANT_SEEDS[:VARIANTS]):
            try:
                parent = root.attachNewNode(f"parent_{kind}_{vi}")
                result = builder_fn(parent, seed=vseed)

                if hasattr(result, "flattenStrong"):
                    result.flattenStrong()

                tris = extract_triangles(result)
                if not tris:
                    tris = extract_triangles(parent)

                if not tris:
                    print(f"  {kind}: SKIP (no geometry)", flush=True)
                    parent.removeNode()
                    continue

                normalized, bounds = normalize_and_rebase(tris)

                if kind in SMOOTH_KINDS:
                    normalized = smooth_normals(normalized)
                    shading = "smooth"
                else:
                    shading = "flat"

                filepath = os.path.join(out_dir, f"{kind}_v{vi}.glb")
                if write_glb(normalized, filepath):
                    size_kb = os.path.getsize(filepath) / 1024
                    if vi == 0:
                        bounds_map[kind] = bounds
                    print(f"  {kind}_v{vi}: {len(tris)} verts, "
                          f"{bounds['width']:.1f}x{bounds['depth']:.1f}x{bounds['height']:.1f}, "
                          f"{size_kb:.0f}KB [{shading}]", flush=True)

                parent.removeNode()

            except Exception as e:
                print(f"  {kind}_v{vi}: ERROR — {e}", flush=True)
                import traceback
                traceback.print_exc()

    # Write bounds metadata for the Godot loader
    meta_path = os.path.join(out_dir, "bounds.json")
    with open(meta_path, "w") as f:
        json.dump(bounds_map, f, indent=2)
    print(f"\nWrote {len(bounds_map)} .glb files + bounds.json to {out_dir}/", flush=True)

    base.destroy()


if __name__ == "__main__":
    main()
