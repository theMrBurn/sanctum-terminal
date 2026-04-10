"""
tools/gen_kind_mesh.py

Clean-room mesh authoring pipeline for Sanctum Terminal.

Composes designed kinds from primitives (hemispheres, cylinders, tori, quads)
with per-vertex colors baked in, exports to GLB for Godot. Same pipeline
is reusable for shrubs, trees, fish, insects, architectural elements, and
any future "designed" kind — not just fungi.

Usage:
    PYTHONPATH=. ./.venv/bin/python tools/gen_kind_mesh.py toadstool
    PYTHONPATH=. ./.venv/bin/python tools/gen_kind_mesh.py --all

Generates godot/meshes/<kind>_v{0..3}.glb plus bounds entries.

The flat-shaded kind_shader in Godot reads baked vertex colors when a
kind has `use_vertex_colors: true` in kind_config.json, bypassing the
facet-normal palette path. This keeps the low-poly flat-shaded aesthetic
while enabling designed color regions (e.g. red cap + white spots +
dark base ring on a toadstool).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Sequence

import numpy as np
import trimesh


# -----------------------------------------------------------------------------
# Primitives
# -----------------------------------------------------------------------------
#
# Each primitive returns a trimesh.Trimesh with vertex_colors already set
# to the provided RGBA. Downstream composition concatenates these into
# kind assemblies.


RGBA = tuple[int, int, int, int]  # 0-255 per channel


def _solid_color(mesh: trimesh.Trimesh, color: RGBA) -> trimesh.Trimesh:
    """Apply a solid vertex color to every vertex."""
    colors = np.tile(np.array(color, dtype=np.uint8),
                     (len(mesh.vertices), 1))
    mesh.visual.vertex_colors = colors
    return mesh


def hemisphere(radius: float, height: float, color: RGBA,
               meridian_sections: int = 12,
               parallel_rings: int = 4) -> trimesh.Trimesh:
    """Low-poly dome via revolved profile — no mesh slicing required.

    Builds a half-circle profile in the X-Z plane and revolves around
    the Z axis. `meridian_sections` controls the rotational facet count
    (longitude); `parallel_rings` controls the profile segment count
    (latitude). 12 x 4 → ~96 triangles, right in the low-poly zone.

    radius = dome horizontal radius
    height = dome vertical extent (height / radius = flatness ratio)
    """
    # Profile: quarter-ellipse from (radius, 0) at equator to (0, height) at pole
    # Extra point at (0, 0) to close the base. Must begin and end on the
    # Z axis for revolve() to produce a clean solid.
    angles = np.linspace(0.0, math.pi / 2.0, parallel_rings + 1)
    profile = np.column_stack([
        radius * np.cos(angles),   # X: radius at equator, 0 at pole
        height * np.sin(angles),   # Z: 0 at equator, height at pole
    ])
    # Close the bottom: add base center so we get an opaque cap
    profile = np.vstack([profile, [0.0, 0.0]])
    mesh = trimesh.creation.revolve(profile, sections=meridian_sections)
    return _solid_color(mesh, color)


def capped_cylinder(radius_bottom: float, radius_top: float,
                    height: float, sections: int, color: RGBA,
                    ) -> trimesh.Trimesh:
    """Tapered cylinder for mushroom stems, tree trunks, pillars.

    Uses the trimesh cylinder primitive and deforms the top ring for
    taper. `sections` controls facet count (6-12 recommended for
    low-poly readout).
    """
    cyl = trimesh.creation.cylinder(radius=radius_bottom, height=height,
                                    sections=sections)
    # Scale top vertices inward for taper (bottom = z<0, top = z>0)
    if not math.isclose(radius_bottom, radius_top, rel_tol=1e-6):
        top_mask = cyl.vertices[:, 2] > 0.0
        scale = radius_top / radius_bottom
        cyl.vertices[top_mask, 0] *= scale
        cyl.vertices[top_mask, 1] *= scale
    return _solid_color(cyl, color)


def torus_ring(major_radius: float, minor_radius: float,
               major_sections: int, minor_sections: int,
               color: RGBA) -> trimesh.Trimesh:
    """Ring for mushroom base sockets, tree roots, architectural collars."""
    # trimesh has no native torus; construct from revolved polygon
    theta = np.linspace(0, 2 * math.pi, minor_sections, endpoint=False)
    ring2d = np.column_stack([
        major_radius + minor_radius * np.cos(theta),
        minor_radius * np.sin(theta),
    ])
    mesh = trimesh.creation.revolve(ring2d, sections=major_sections)
    return _solid_color(mesh, color)


def sphere(radius: float, color: RGBA, subdivisions: int = 1,
           squash: float = 1.0) -> trimesh.Trimesh:
    """Low-poly sphere for spore pods, fruit, eyes, particles.

    `subdivisions=1` → 80 triangles (icosphere). `squash` < 1.0 flattens
    the Z axis for ground-hugging pods that look like growths, not balls.
    """
    s = trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)
    if squash != 1.0:
        s.vertices[:, 2] *= squash
    return _solid_color(s, color)


def quad_billboard(center: np.ndarray, normal: np.ndarray,
                   size: float, color: RGBA) -> trimesh.Trimesh:
    """Single flat quad at a position, facing a normal direction.

    Used for spots on mushroom caps, leaves on branches, scales on fish,
    panels on artifacts.
    """
    # Build a tangent frame from the normal
    n = normal / (np.linalg.norm(normal) + 1e-9)
    up = np.array([0.0, 0.0, 1.0]) if abs(n[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    tangent = np.cross(up, n)
    tangent /= np.linalg.norm(tangent) + 1e-9
    bitangent = np.cross(n, tangent)
    half = size * 0.5
    v0 = center - tangent * half - bitangent * half
    v1 = center + tangent * half - bitangent * half
    v2 = center + tangent * half + bitangent * half
    v3 = center - tangent * half + bitangent * half
    verts = np.array([v0, v1, v2, v3])
    faces = np.array([[0, 1, 2], [0, 2, 3]])
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    return _solid_color(mesh, color)


def scattered_quads(surface_points: np.ndarray,
                    surface_normals: np.ndarray,
                    sizes: Sequence[float],
                    color: RGBA) -> trimesh.Trimesh:
    """Batch of quad billboards placed on a surface.

    Concatenates per-spot quads into one mesh for efficient GLB output.
    """
    meshes = []
    for pt, nrm, sz in zip(surface_points, surface_normals, sizes):
        meshes.append(quad_billboard(pt, nrm, sz, color))
    combined = trimesh.util.concatenate(meshes)
    return combined


def compose(parts: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    """Concatenate multiple colored meshes into one assembly.

    Vertex colors from each part are preserved because concatenate merges
    visual attributes. The returned mesh has one COLOR_0 stream covering
    every vertex in the composed kind.
    """
    # trimesh.util.concatenate preserves vertex colors when all parts have them
    return trimesh.util.concatenate(parts)


# -----------------------------------------------------------------------------
# Kind: toadstool
# -----------------------------------------------------------------------------
#
# Classic Fly Agaric — red dome cap, white chunky spots, faceted white
# stem with slight taper, dark red base ring. Reference: Fly Agaric GIF
# on user Desktop. Our first output kind — pipeline dogfood.


# Palette — intentionally muted to fit the stone palette register.
# Not pure red/white; earthy cinnabar and warm cream. Stem is intentionally
# darker than the cream cavern ground so the silhouette reads cleanly in
# clean room mode where ambient washes light surfaces.
TOADSTOOL_CAP_RED: RGBA       = (165, 60, 50, 255)     # deep cinnabar
TOADSTOOL_CAP_UNDER: RGBA     = (120, 40, 30, 255)     # darker gill shadow
TOADSTOOL_SPOT_CREAM: RGBA    = (225, 215, 195, 255)   # warm off-white spots
TOADSTOOL_STEM_BROWN: RGBA    = (95, 80, 68, 255)      # dark warm beige — grounds against cream floor
TOADSTOOL_BASE_RING: RGBA     = (55, 30, 22, 255)      # near-black brown


def build_toadstool(
    cap_radius: float = 1.08,
    cap_height: float = 0.66,
    stem_radius_base: float = 0.39,
    stem_radius_top: float = 0.33,
    stem_height: float = 1.44,
    base_ring_radius: float = 0.48,
    base_ring_thickness: float = 0.13,
    spot_count: int = 10,
    spot_size: float = 0.22,
    spot_seed: int = 0,
    cap_sections: int = 2,   # icosphere subdivisions → 80 faces hemi
    stem_sections: int = 8,  # octagonal stem
    ring_major_sections: int = 12,
    ring_minor_sections: int = 5,
) -> trimesh.Trimesh:
    """Compose a single toadstool mesh with per-region vertex colors.

    Scale is in meters. Output mesh has +Z up; Godot remapping happens at
    load time via the bounds.json scale entry.
    """
    # --- Stem: faceted tapered cylinder ---
    stem = capped_cylinder(
        radius_bottom=stem_radius_base,
        radius_top=stem_radius_top,
        height=stem_height,
        sections=stem_sections,
        color=TOADSTOOL_STEM_BROWN,
    )
    # Move stem so base sits at z=0
    stem.apply_translation([0, 0, stem_height * 0.5])

    # --- Base ring: torus at bottom of stem ---
    base = torus_ring(
        major_radius=base_ring_radius,
        minor_radius=base_ring_thickness,
        major_sections=ring_major_sections,
        minor_sections=ring_minor_sections,
        color=TOADSTOOL_BASE_RING,
    )
    base.apply_translation([0, 0, base_ring_thickness])

    # --- Cap: low-poly dome via revolved profile ---
    cap = hemisphere(
        radius=cap_radius,
        height=cap_height,
        color=TOADSTOOL_CAP_RED,
        meridian_sections=12,
        parallel_rings=4,
    )
    # Translate cap to sit on top of stem
    cap.apply_translation([0, 0, stem_height])

    # --- Cap underside (gill): dark disc facing down ---
    # Simple n-gon disc below the cap sphere
    under = trimesh.creation.annulus(
        r_min=0.0, r_max=cap_radius * 0.95,
        height=0.05, sections=12,
    )
    _solid_color(under, TOADSTOOL_CAP_UNDER)
    under.apply_translation([0, 0, stem_height - 0.02])

    # --- Spots: small quad billboards on cap surface ---
    rng = np.random.default_rng(spot_seed)
    spot_positions = []
    spot_normals = []
    spot_sizes = []
    for _ in range(spot_count):
        # Uniformly distribute points on upper hemisphere surface of cap
        theta = rng.uniform(0, 2 * math.pi)
        phi = rng.uniform(0.05, 1.30)  # 0.05 rad from pole, 1.30 from bottom
        x = cap_radius * math.sin(phi) * math.cos(theta)
        y = cap_radius * math.sin(phi) * math.sin(theta)
        z = cap_height * math.cos(phi) + stem_height
        pos = np.array([x, y, z])
        nrm = np.array([x / cap_radius, y / cap_radius,
                        (cap_height * math.cos(phi)) / cap_radius])
        spot_positions.append(pos)
        spot_normals.append(nrm)
        # Vary spot size 0.75-1.25x
        spot_sizes.append(spot_size * (0.75 + rng.random() * 0.50))

    spots = scattered_quads(
        np.array(spot_positions),
        np.array(spot_normals),
        spot_sizes,
        TOADSTOOL_SPOT_CREAM,
    )

    # --- Compose ---
    assembly = compose([stem, base, cap, under, spots])
    return assembly


def toadstool_variants() -> list[trimesh.Trimesh]:
    """Hand-tuned production variants, sub-boulder scale.

    40% smaller than first pass. Target: ~1.5-2.7m tall × 1.8-2.7m wide.
    Reads as a waist-to-head-height fungus — playable foreground detail,
    not a landmark. Stem height ~2/3 of total so the cap sits naturally.
    """
    return [
        # v0: standard
        build_toadstool(
            cap_radius=1.08, cap_height=0.66,
            stem_height=1.44, stem_radius_base=0.39, stem_radius_top=0.33,
            base_ring_radius=0.48, base_ring_thickness=0.13,
            spot_count=10, spot_size=0.22, spot_seed=101,
        ),
        # v1: squat — shorter stem, wider cap
        build_toadstool(
            cap_radius=1.32, cap_height=0.57,
            stem_height=1.08, stem_radius_base=0.48, stem_radius_top=0.42,
            base_ring_radius=0.57, base_ring_thickness=0.14,
            spot_count=8, spot_size=0.24, spot_seed=202,
        ),
        # v2: tall lean — narrow cap, long stem
        build_toadstool(
            cap_radius=0.90, cap_height=0.78,
            stem_height=1.92, stem_radius_base=0.33, stem_radius_top=0.27,
            base_ring_radius=0.45, base_ring_thickness=0.12,
            spot_count=6, spot_size=0.25, spot_seed=303,
        ),
        # v3: mature — heavy base ring, lots of small spots
        build_toadstool(
            cap_radius=1.20, cap_height=0.66,
            stem_height=1.56, stem_radius_base=0.51, stem_radius_top=0.39,
            base_ring_radius=0.60, base_ring_thickness=0.18,
            spot_count=12, spot_size=0.18, spot_seed=404,
        ),
    ]


# -----------------------------------------------------------------------------
# Kind: spore_pod
# -----------------------------------------------------------------------------
#
# Boulder-mimic partner to giant_fungus. Cluster of rounded spore sacs at
# ground level. Receives spores from skyward fungus releases (lore). No cap,
# no stem — silhouette is "knobby growth" not "mushroom shape." Carries the
# fungus partner-type design without conflating with the cap-bearing form.


# Palette — partner to giant_fungus purple-pink, but earthier and darker so
# it reads as ground-hugging mass against the cream cavern floor.
SPORE_POD_BODY: RGBA      = (95, 70, 88, 255)     # dusty mauve-brown
SPORE_POD_HIGHLIGHT: RGBA = (115, 90, 105, 255)   # lighter mauve cap
SPORE_POD_DEEP: RGBA      = (60, 42, 55, 255)     # darker fold/shadow


def build_spore_pod(
    pod_count: int = 4,
    pod_radius: float = 0.42,
    radius_jitter: float = 0.18,
    cluster_radius: float = 0.55,
    height_squash: float = 0.78,
    pod_seed: int = 0,
    subdivisions: int = 1,
) -> trimesh.Trimesh:
    """Compose a spore_pod cluster from N small squashed spheres.

    Each pod is a low-poly icosphere placed at a hash-jittered offset from
    the cluster center, with slight per-pod radius and color variation.
    The cluster sits flat on the ground (Z=0 base after normalization).

    pod_count       — number of sub-pods in the cluster
    pod_radius      — base radius before jitter
    radius_jitter   — ±range applied per pod
    cluster_radius  — XY spread of pod centers from cluster center
    height_squash   — Z scale on each pod (< 1.0 = flatter, more growth-like)
    """
    rng = np.random.default_rng(pod_seed)
    pods = []
    # First pod sits at center, slightly larger
    center_r = pod_radius * 1.15
    center_pod = sphere(
        radius=center_r,
        color=SPORE_POD_BODY,
        subdivisions=subdivisions,
        squash=height_squash,
    )
    center_pod.apply_translation([0, 0, center_r * height_squash])
    pods.append(center_pod)

    # Surrounding pods at golden-angle distribution
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(1, pod_count):
        angle = i * golden_angle
        # Inner pods cluster tighter than outer
        radial = cluster_radius * (0.4 + (i / max(1, pod_count - 1)) * 0.6)
        x = radial * math.cos(angle)
        y = radial * math.sin(angle)
        # Per-pod radius variation
        r = pod_radius + rng.uniform(-radius_jitter, radius_jitter)
        r = max(r, 0.15)
        # Per-pod color: 70% body, 25% highlight, 5% deep
        roll = rng.random()
        if roll < 0.25:
            color = SPORE_POD_HIGHLIGHT
        elif roll < 0.30:
            color = SPORE_POD_DEEP
        else:
            color = SPORE_POD_BODY
        pod = sphere(
            radius=r,
            color=color,
            subdivisions=subdivisions,
            squash=height_squash,
        )
        # Z position: pod center sits at its squashed radius so it touches
        # the ground plane (Z=0 at base, max at 2*r*squash).
        pod.apply_translation([x, y, r * height_squash])
        pods.append(pod)

    return compose(pods)


def spore_pod_variants() -> list[trimesh.Trimesh]:
    """Four cluster arrangements — different pod counts and spreads."""
    return [
        # v0: tight 3-pod
        build_spore_pod(
            pod_count=3, pod_radius=0.45, cluster_radius=0.45,
            height_squash=0.80, pod_seed=11,
        ),
        # v1: loose 4-pod
        build_spore_pod(
            pod_count=4, pod_radius=0.40, cluster_radius=0.65,
            height_squash=0.78, pod_seed=22,
        ),
        # v2: linear 3-pod (more spread on one axis via custom seed)
        build_spore_pod(
            pod_count=3, pod_radius=0.48, cluster_radius=0.70,
            height_squash=0.85, radius_jitter=0.10, pod_seed=33,
        ),
        # v3: mound 5-pod
        build_spore_pod(
            pod_count=5, pod_radius=0.36, cluster_radius=0.55,
            height_squash=0.75, pod_seed=44,
        ),
    ]


# -----------------------------------------------------------------------------
# Export + bounds
# -----------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[1]
MESH_DIR = REPO_ROOT / "godot" / "meshes"
BOUNDS_PATH = MESH_DIR / "bounds.json"


def mesh_bounds(mesh: trimesh.Trimesh) -> dict:
    """Compute bounds entry matching the schema in bounds.json.

    Sanctum uses +Z up in blueprint space but Godot is +Y up. bounds.json
    stores raw dimensions (width=X, depth=Y, height=Z) and a `scale` field
    that is the max dimension — the GLB is imported and uniformly scaled
    so that max_dim = 1.0, then the original max is restored via this
    scale value at spawn time.
    """
    extents = mesh.extents  # (w, d, h) in world units
    width, depth, height = float(extents[0]), float(extents[1]), float(extents[2])
    scale = max(width, depth, height)
    return {
        "width": width,
        "depth": depth,
        "height": height,
        "scale": scale,
    }


def normalize_for_godot(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Rescale to max_dim=1.0 (Godot import convention) and convert from
    Z-up author space to Y-up glTF standard.

    trimesh's GLB export does NOT apply a Z-up→Y-up rotation by default —
    verified by raw accessor inspection of a generated file showing
    min/max with the tall axis on Z. glTF spec requires Y-up, and Godot
    imports per spec, so without this explicit rotation the mesh renders
    lying on its side in Godot (cap hidden behind the camera, stem
    collapsed into the ground plane).

    Rotation: -90° around X axis. Maps author (x, y, z) → file (x, z, -y).
    After rotation the original Z (author's up) becomes Y (glTF's up).
    """
    scale = float(max(mesh.extents))
    if scale > 0:
        mesh.apply_scale(1.0 / scale)
    rot = trimesh.transformations.rotation_matrix(
        angle=-math.pi / 2.0,
        direction=[1.0, 0.0, 0.0],
        point=[0.0, 0.0, 0.0],
    )
    mesh.apply_transform(rot)
    return mesh


def export_kind(kind_name: str,
                variants: list[trimesh.Trimesh]) -> dict:
    """Write v0..vN GLBs to godot/meshes/ and return bounds dict for
    the first variant (used as the kind's canonical bounds).
    """
    MESH_DIR.mkdir(parents=True, exist_ok=True)
    canonical_bounds = None
    for i, mesh in enumerate(variants):
        bounds = mesh_bounds(mesh)
        if canonical_bounds is None:
            canonical_bounds = bounds
        normalized = normalize_for_godot(mesh.copy())
        out_path = MESH_DIR / f"{kind_name}_v{i}.glb"
        glb_bytes = normalized.export(file_type="glb")
        out_path.write_bytes(glb_bytes)
        print(f"  {kind_name}_v{i}.glb  "
              f"({len(glb_bytes)} bytes, "
              f"{len(normalized.faces)} tris, "
              f"bounds {bounds['width']:.2f} x {bounds['depth']:.2f} x {bounds['height']:.2f})")
    return canonical_bounds


def update_bounds_file(kind_name: str, bounds: dict) -> None:
    data = {}
    if BOUNDS_PATH.exists():
        data = json.loads(BOUNDS_PATH.read_text())
    data[kind_name] = bounds
    BOUNDS_PATH.write_text(json.dumps(data, indent=2) + "\n")
    print(f"  bounds.json updated: {kind_name} -> "
          f"scale {bounds['scale']:.2f}")


# -----------------------------------------------------------------------------
# Registry + CLI
# -----------------------------------------------------------------------------


KIND_BUILDERS = {
    "toadstool": toadstool_variants,
    "spore_pod": spore_pod_variants,
    # Add future kinds here: "shrub", "fish", "tree", etc.
}


def generate_kind(kind_name: str) -> None:
    if kind_name not in KIND_BUILDERS:
        raise SystemExit(
            f"Unknown kind '{kind_name}'. Known: {list(KIND_BUILDERS)}")
    print(f"Generating {kind_name}...")
    variants = KIND_BUILDERS[kind_name]()
    bounds = export_kind(kind_name, variants)
    update_bounds_file(kind_name, bounds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kinds", nargs="*",
                        help="Kind names to generate (default: all)")
    parser.add_argument("--all", action="store_true",
                        help="Generate every registered kind")
    args = parser.parse_args()

    if args.all or not args.kinds:
        targets = list(KIND_BUILDERS)
    else:
        targets = args.kinds

    for kind in targets:
        generate_kind(kind)


if __name__ == "__main__":
    main()
