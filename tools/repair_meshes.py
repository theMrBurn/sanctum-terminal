"""
repair_meshes.py — Weld split vertices in GLB meshes to close polygon gaps.

The original mesh generator (geometry.py make_rock) writes 3 separate vertices
per triangle. Adjacent faces don't share edges, creating visible gaps. This
script welds vertices at the same position, producing manifold geometry where
faces connect seamlessly.

Usage:
    python tools/repair_meshes.py
    # or: make repair-meshes
"""

import struct
import json
import os
import sys
import base64
from pathlib import Path

# We'll use trimesh if available, otherwise fall back to manual GLB parsing
try:
    import trimesh
    HAS_TRIMESH = True
except ImportError:
    HAS_TRIMESH = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


MESH_DIR = Path(__file__).parent.parent / "godot" / "meshes"


def weld_mesh_trimesh(input_path: str, output_path: str, tolerance: float = 1e-4) -> dict:
    """Weld vertices using trimesh library. Returns stats."""
    scene = trimesh.load(input_path)

    if isinstance(scene, trimesh.Scene):
        meshes = list(scene.geometry.values())
        if not meshes:
            return {"skipped": True, "reason": "no geometry"}
        mesh = meshes[0]
    elif isinstance(scene, trimesh.Trimesh):
        mesh = scene
    else:
        return {"skipped": True, "reason": f"unknown type {type(scene)}"}

    verts_before = len(mesh.vertices)
    faces_before = len(mesh.faces)

    # Merge vertices that are within tolerance
    mesh.merge_vertices(merge_tex=True, merge_norm=True)

    # Fix face winding for consistent normals
    mesh.fix_normals()

    verts_after = len(mesh.vertices)

    # Export back to GLB
    mesh.export(output_path, file_type="glb")

    return {
        "verts_before": verts_before,
        "verts_after": verts_after,
        "faces": faces_before,
        "reduction": f"{(1 - verts_after / max(verts_before, 1)) * 100:.0f}%",
    }


def repair_all():
    """Find and repair all mesh GLBs."""
    if not HAS_TRIMESH:
        print("ERROR: trimesh not installed. Run: pip install trimesh")
        print("  .venv/bin/pip install trimesh")
        sys.exit(1)

    glb_files = sorted(MESH_DIR.glob("*.glb"))
    if not glb_files:
        print(f"No GLB files found in {MESH_DIR}")
        return

    # Back up originals
    backup_dir = MESH_DIR / "pre_repair_backup"
    backup_dir.mkdir(exist_ok=True)

    repaired = 0
    skipped = 0
    for glb_path in glb_files:
        # Skip .import files
        if glb_path.suffix != ".glb":
            continue

        name = glb_path.stem
        backup_path = backup_dir / glb_path.name

        # Back up if not already backed up
        if not backup_path.exists():
            import shutil
            shutil.copy2(glb_path, backup_path)

        print(f"  {name}... ", end="", flush=True)
        try:
            stats = weld_mesh_trimesh(str(glb_path), str(glb_path))
            if stats.get("skipped"):
                print(f"SKIP ({stats.get('reason', '?')})")
                skipped += 1
            else:
                print(f"OK  {stats['verts_before']}→{stats['verts_after']} verts ({stats['reduction']} reduction), {stats['faces']} faces")
                repaired += 1
        except Exception as e:
            print(f"ERROR: {e}")
            skipped += 1

    print(f"\nDone: {repaired} repaired, {skipped} skipped")
    print(f"Backups in: {backup_dir}")


if __name__ == "__main__":
    print("Repairing meshes — welding split vertices...")
    repair_all()
