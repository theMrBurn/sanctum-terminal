"""
tools/extract_meshes.py

Extract vertex data from Panda3D builders into a binary mesh library.

For each entity kind, builds one instance, flattens, and extracts
raw vertex positions + colors + face normals. Saves to data/mesh_library.bin.

The wgpu renderer loads this file instead of hardcoded cubes.

Usage:
    PYTHONPATH=. ./.venv/bin/python tools/extract_meshes.py

Mesh library format:
    Header: "MESH" (4 bytes) + version u32 + num_kinds u32
    Per kind:
        kind_name: 32 bytes (null-padded ASCII)
        num_vertices: u32
        vertex data: num_vertices × (px, py, pz, nx, ny, nz, r, g, b) = 9 floats
    All floats are f32, little-endian.
"""

import sys
import os
import struct
import math

# Panda3D headless init — must happen before any panda3d imports
os.environ["PANDA_PRC_DIR"] = ""
os.environ["PANDA_PRC_PATH"] = ""

from panda3d.core import (
    NodePath, Geom, GeomNode, GeomVertexReader, loadPrcFileData,
)
loadPrcFileData("", "window-type none")
loadPrcFileData("", "audio-library-name null")

from direct.showbase.ShowBase import ShowBase
base = ShowBase()

# Monkey-patch glow functions to no-ops BEFORE importing builders.
# Builders embed glow decals/halos/shafts into the geometry — we only want
# the solid object mesh, not the flat rendering cards.
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

# Use outdoor biome for color scales
set_active_biome("outdoor")


# -- Builder registry ----------------------------------------------------------

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
    """Compute face normal from 3 vertices."""
    ax, ay, az = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    bx, by, bz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
    nx = ay * bz - az * by
    ny = az * bx - ax * bz
    nz = ax * by - ay * bx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-8:
        return (0.0, 0.0, 1.0)
    return (nx / length, ny / length, nz / length)


def extract_geom_data(node_path):
    """Extract all vertex positions and colors from a NodePath's geometry.

    Returns list of (px, py, pz, nx, ny, nz, r, g, b) tuples — one per vertex.
    Normals are computed per-face (flat shading).
    """
    vertices = []

    # Walk all GeomNodes in the hierarchy
    for np in node_path.findAllMatches("**/+GeomNode"):
        geom_node = np.node()
        # Get the net transform from this node to the root
        mat = np.getMat(node_path)

        for gi in range(geom_node.getNumGeoms()):
            geom = geom_node.getGeom(gi)
            vdata = geom.getVertexData()

            vreader = GeomVertexReader(vdata, "vertex")
            has_color = vdata.hasColumn("color")
            if has_color:
                creader = GeomVertexReader(vdata, "color")

            # Read all vertex positions + colors
            positions = []
            colors = []
            while not vreader.isAtEnd():
                v = vreader.getData3()
                # Apply transform
                tv = mat.xformPoint(v)
                positions.append((tv.getX(), tv.getY(), tv.getZ()))
                if has_color:
                    c = creader.getData4()
                    colors.append((c.getX(), c.getY(), c.getZ()))
                else:
                    colors.append((0.5, 0.5, 0.5))

            # Extract triangle indices and compute face normals
            for pi in range(geom.getNumPrimitives()):
                prim = geom.getPrimitive(pi)
                prim = prim.decompose()  # ensure triangles
                for ti in range(prim.getNumPrimitives()):
                    start = prim.getPrimitiveStart(ti)
                    i0 = prim.getVertex(start)
                    i1 = prim.getVertex(start + 1)
                    i2 = prim.getVertex(start + 2)

                    if i0 >= len(positions) or i1 >= len(positions) or i2 >= len(positions):
                        continue

                    p0, p1, p2 = positions[i0], positions[i1], positions[i2]
                    nx, ny, nz = compute_face_normal(p0, p1, p2)

                    for idx in (i0, i1, i2):
                        px, py, pz = positions[idx]
                        r, g, b = colors[idx]
                        vertices.append((px, py, pz, nx, ny, nz, r, g, b))

    # Also check the root node itself if it's a GeomNode
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
                prim = geom.getPrimitive(pi)
                prim = prim.decompose()
                for ti in range(prim.getNumPrimitives()):
                    start = prim.getPrimitiveStart(ti)
                    i0 = prim.getVertex(start)
                    i1 = prim.getVertex(start + 1)
                    i2 = prim.getVertex(start + 2)
                    if i0 >= len(positions) or i1 >= len(positions) or i2 >= len(positions):
                        continue
                    p0, p1, p2 = positions[i0], positions[i1], positions[i2]
                    nx, ny, nz = compute_face_normal(p0, p1, p2)
                    for idx in (i0, i1, i2):
                        px, py, pz = positions[idx]
                        r, g, b = colors[idx]
                        vertices.append((px, py, pz, nx, ny, nz, r, g, b))

    return vertices


def normalize_mesh(vertices):
    """Center mesh at origin and normalize to unit scale.

    The renderer applies per-instance position and scale,
    so the mesh library stores normalized geometry.
    Returns (normalized_vertices, bounds_info).
    """
    if not vertices:
        return vertices, {}

    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]

    cx = (min(xs) + max(xs)) * 0.5
    cy = (min(ys) + max(ys)) * 0.5
    # Don't center Z — keep base at 0 so objects sit on the ground
    z_min = min(zs)

    w = max(xs) - min(xs)
    d = max(ys) - min(ys)
    h = max(zs) - min(zs)

    # Normalize so max dimension = 1.0
    max_dim = max(w, d, h, 0.001)
    inv_scale = 1.0 / max_dim

    normalized = []
    for px, py, pz, nx, ny, nz, r, g, b in vertices:
        normalized.append((
            (px - cx) * inv_scale,
            (py - cy) * inv_scale,
            (pz - z_min) * inv_scale,
            nx, ny, nz,
            r, g, b,
        ))

    return normalized, {"width": w, "depth": d, "height": h, "scale": max_dim}


def main():
    os.makedirs("data", exist_ok=True)
    output_path = "data/mesh_library.bin"

    print(f"Extracting meshes from {len(BUILDERS)} entity kinds...", flush=True)

    mesh_data = {}  # kind -> (normalized_vertices, bounds)
    root = NodePath("extract_root")

    for kind, builder_fn in BUILDERS.items():
        try:
            parent = root.attachNewNode(f"parent_{kind}")
            result = builder_fn(parent, seed=42)

            # Glow decals/halos/shafts stripped via monkey-patch above.
            # Flatten like the real pipeline does
            if hasattr(result, 'flattenStrong'):
                result.flattenStrong()

            verts = extract_geom_data(result)
            if not verts:
                # Try parent if builder attached to parent
                verts = extract_geom_data(parent)

            if verts:
                normalized, bounds = normalize_mesh(verts)
                mesh_data[kind] = (normalized, bounds)
                print(f"  {kind}: {len(verts)} verts → {len(normalized)} normalized "
                      f"({bounds.get('width', 0):.1f}×{bounds.get('depth', 0):.1f}×{bounds.get('height', 0):.1f})",
                      flush=True)
            else:
                print(f"  {kind}: NO VERTICES (builder produced no geometry)", flush=True)

            parent.removeNode()

        except Exception as e:
            print(f"  {kind}: ERROR — {e}", flush=True)

    # Write binary mesh library
    with open(output_path, "wb") as f:
        # Header
        f.write(b"MESH")
        f.write(struct.pack("<II", 1, len(mesh_data)))  # version, num_kinds

        for kind, (vertices, bounds) in mesh_data.items():
            # Kind name (32 bytes, null-padded)
            name_bytes = kind.encode("ascii")[:31]
            f.write(name_bytes + b"\x00" * (32 - len(name_bytes)))

            # Num vertices
            f.write(struct.pack("<I", len(vertices)))

            # Original scale (for the renderer to apply)
            f.write(struct.pack("<fff",
                                bounds.get("width", 1.0),
                                bounds.get("depth", 1.0),
                                bounds.get("height", 1.0)))

            # Vertex data: 9 floats per vertex
            for v in vertices:
                f.write(struct.pack("<9f", *v))

    file_size = os.path.getsize(output_path)
    total_verts = sum(len(v) for v, _ in mesh_data.values())
    print(f"\nWrote {output_path}: {file_size / 1024:.0f} KB, "
          f"{len(mesh_data)} kinds, {total_verts} total vertices", flush=True)

    base.destroy()


if __name__ == "__main__":
    main()
