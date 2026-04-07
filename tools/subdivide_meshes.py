"""
subdivide_meshes.py — Add geometry to low-poly meshes via subdivision.

Each triangle becomes 4 triangles (midpoint subdivision). Preserves shape,
increases face count so the edge-following texture system (fwidth Layer A)
has more edges to work with. Columns go from 70 → 280 faces, mega_columns
from 420 → 1680. Targeted at geological/structural kinds that need stone
plate texture density.

Usage:
    python tools/subdivide_meshes.py [--passes 1]
"""

import sys
from pathlib import Path

try:
    import trimesh
    import numpy as np
except ImportError:
    print("ERROR: need trimesh + numpy. Run: .venv/bin/pip install trimesh numpy")
    sys.exit(1)

MESH_DIR = Path(__file__).parent.parent / "godot" / "meshes"

# Kinds that need subdivision for texture density.
# Small objects (rubble, cave_gravel, bone_pile) already have enough faces
# relative to their screen size. Large structural objects need more.
SUBDIVIDE_KINDS = [
    "mega_column", "column", "stalagmite", "boulder", "buttress",
    "giant_fungus", "dead_log", "hanging_vine", "ceiling_moss",
    "horizon_form", "horizon_mid", "horizon_near",
]

# Kinds to skip — already dense enough or too small to matter
SKIP_KINDS = [
    "rubble", "cave_gravel", "bone_pile", "leaf_pile", "twig_scatter",
    "grass_tuft", "moss_patch", "leaf", "firefly", "beetle", "rat",
    "spider", "exit_lure", "filament", "crystal_cluster",
]


def subdivide_mesh(mesh: trimesh.Trimesh, passes: int = 1) -> trimesh.Trimesh:
    """Midpoint subdivision — each triangle becomes 4."""
    for _ in range(passes):
        vertices = mesh.vertices.copy()
        faces = mesh.faces.copy()

        # Build edge midpoints
        edges = {}
        new_verts = list(vertices)

        def get_midpoint(i0, i1):
            key = (min(i0, i1), max(i0, i1))
            if key in edges:
                return edges[key]
            mid = (vertices[i0] + vertices[i1]) / 2.0
            idx = len(new_verts)
            new_verts.append(mid)
            edges[key] = idx
            return idx

        new_faces = []
        for f in faces:
            a, b, c = f
            ab = get_midpoint(a, b)
            bc = get_midpoint(b, c)
            ca = get_midpoint(c, a)
            new_faces.append([a, ab, ca])
            new_faces.append([ab, b, bc])
            new_faces.append([ca, bc, c])
            new_faces.append([ab, bc, ca])

        mesh = trimesh.Trimesh(
            vertices=np.array(new_verts),
            faces=np.array(new_faces),
            process=True,
        )
        mesh.fix_normals()

    return mesh


def process_all(passes: int = 1):
    glb_files = sorted(MESH_DIR.glob("*.glb"))
    subdivided = 0
    skipped = 0

    for glb_path in glb_files:
        name = glb_path.stem
        # Check if this kind should be subdivided
        base_kind = name.replace("_v0", "").replace("_v1", "").replace("_v2", "").replace("_v3", "")

        if base_kind in SKIP_KINDS:
            continue
        if base_kind not in SUBDIVIDE_KINDS:
            # Unknown kind — skip to be safe
            continue

        print(f"  {name}... ", end="", flush=True)
        try:
            scene = trimesh.load(str(glb_path))
            if isinstance(scene, trimesh.Scene):
                meshes = list(scene.geometry.values())
                if not meshes:
                    print("SKIP (no geometry)")
                    skipped += 1
                    continue
                mesh = meshes[0]
            elif isinstance(scene, trimesh.Trimesh):
                mesh = scene
            else:
                print(f"SKIP (type {type(scene)})")
                skipped += 1
                continue

            faces_before = len(mesh.faces)
            verts_before = len(mesh.vertices)

            mesh = subdivide_mesh(mesh, passes=passes)

            faces_after = len(mesh.faces)
            verts_after = len(mesh.vertices)

            mesh.export(str(glb_path), file_type="glb")
            print(f"OK  {faces_before}→{faces_after} faces, {verts_before}→{verts_after} verts")
            subdivided += 1

        except Exception as e:
            print(f"ERROR: {e}")
            skipped += 1

    print(f"\nDone: {subdivided} subdivided ({passes} pass{'es' if passes > 1 else ''}), {skipped} skipped")


if __name__ == "__main__":
    passes = 1
    if "--passes" in sys.argv:
        idx = sys.argv.index("--passes")
        if idx + 1 < len(sys.argv):
            passes = int(sys.argv[idx + 1])

    print(f"Subdividing meshes ({passes} pass{'es' if passes > 1 else ''})...")
    process_all(passes=passes)
