"""
bake_edge_color.py — Bake per-face edge darkening into mesh vertex colors.

Vertices on sharp edges between faces get darkened (mortar).
Vertices in face interiors stay bright (stone plate center).
This creates the "dark border → gradient → flat center" look per polygon
that the shader can't achieve without barycentric coordinates.

The effect is baked into vertex colors, so it works on any shader that
reads COLOR — zero GPU cost, works with MultiMesh instancing.

Usage:
    python tools/bake_edge_color.py
"""

import sys
from pathlib import Path
import numpy as np

try:
    import trimesh
except ImportError:
    print("ERROR: need trimesh. Run: .venv/bin/pip install trimesh")
    sys.exit(1)

MESH_DIR = Path(__file__).parent.parent / "godot" / "meshes"

# All kinds get edge baking — unified visual language
SKIP_KINDS = [
    "firefly", "leaf", "exit_lure",  # too tiny to matter
]


def bake_edges(mesh: trimesh.Trimesh, edge_dark: float = 0.55, angle_threshold: float = 8.0) -> trimesh.Trimesh:
    """Darken vertices that sit on edges between angled faces.

    edge_dark: brightness multiplier for edge vertices (0.55 = 45% darker)
    angle_threshold: minimum angle between faces to count as an edge (degrees)
    """
    verts = mesh.vertices
    faces = mesh.faces
    normals = mesh.face_normals
    n_verts = len(verts)

    # Start all vertices at full brightness
    brightness = np.ones(n_verts)

    # For each vertex, find all faces it belongs to
    vert_faces = [[] for _ in range(n_verts)]
    for fi, face in enumerate(faces):
        for vi in face:
            vert_faces[vi].append(fi)

    # A vertex is an "edge vertex" if the faces it belongs to have
    # significantly different normals (angle > threshold)
    angle_thresh_rad = np.radians(angle_threshold)
    cos_thresh = np.cos(angle_thresh_rad)

    for vi in range(n_verts):
        face_indices = vert_faces[vi]
        if len(face_indices) < 2:
            # Boundary vertex — treat as edge
            brightness[vi] = edge_dark
            continue

        # Check all pairs of faces sharing this vertex
        is_edge = False
        for i in range(len(face_indices)):
            for j in range(i + 1, len(face_indices)):
                dot = np.dot(normals[face_indices[i]], normals[face_indices[j]])
                if dot < cos_thresh:
                    is_edge = True
                    break
            if is_edge:
                break

        if is_edge:
            brightness[vi] = edge_dark

    # Create vertex colors: brightness as grayscale RGB
    # The shader multiplies these with palette_base via vertex_color_blend
    colors = np.column_stack([
        brightness, brightness, brightness,
        np.ones(n_verts)  # alpha = 1
    ])

    mesh.visual.vertex_colors = (colors * 255).astype(np.uint8)

    return mesh


def process_all():
    glb_files = sorted(MESH_DIR.glob("*.glb"))
    baked = 0
    skipped = 0

    for glb_path in glb_files:
        name = glb_path.stem
        base_kind = name.replace("_v0", "").replace("_v1", "").replace("_v2", "").replace("_v3", "")

        if base_kind in SKIP_KINDS:
            continue

        print(f"  {name}... ", end="", flush=True)
        try:
            scene = trimesh.load(str(glb_path))
            if isinstance(scene, trimesh.Scene):
                meshes = list(scene.geometry.values())
                if not meshes:
                    print("SKIP")
                    skipped += 1
                    continue
                mesh = meshes[0]
            elif isinstance(scene, trimesh.Trimesh):
                mesh = scene
            else:
                print(f"SKIP ({type(scene)})")
                skipped += 1
                continue

            n_faces = len(mesh.faces)
            mesh = bake_edges(mesh, edge_dark=0.50, angle_threshold=10.0)

            # Count edge vs interior verts
            colors = mesh.visual.vertex_colors
            edge_count = (colors[:, 0] < 200).sum()
            total = len(colors)

            mesh.export(str(glb_path), file_type="glb")
            print(f"OK  {n_faces} faces, {edge_count}/{total} edge verts ({edge_count*100//max(total,1)}%)")
            baked += 1

        except Exception as e:
            print(f"ERROR: {e}")
            skipped += 1

    print(f"\nDone: {baked} baked, {skipped} skipped")


if __name__ == "__main__":
    print("Baking edge colors into meshes...")
    process_all()
