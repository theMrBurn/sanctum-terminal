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


def teardrop(radius: float, height: float, color: RGBA,
             sections: int = 8) -> trimesh.Trimesh:
    """Teardrop / pear-shaped pod via revolved profile.

    Bulbous base, tapering smoothly to a pointed apex. Used for spore
    pods and any organic kind that wants a discrete pointed-bulb shape
    instead of a sphere or cylinder. Each pod reads as its own form
    even when clustered with neighbors.
    """
    profile = np.array([
        [radius * 1.00, 0.00],
        [radius * 0.98, height * 0.18],
        [radius * 0.90, height * 0.36],
        [radius * 0.72, height * 0.54],
        [radius * 0.48, height * 0.72],
        [radius * 0.22, height * 0.88],
        [0.0,           height],
    ])
    profile = np.vstack([profile, [0.0, 0.0]])  # close base
    mesh = trimesh.creation.revolve(profile, sections=sections)
    return _solid_color(mesh, color)


def slab(width: float, depth: float, height: float,
         color: RGBA) -> trimesh.Trimesh:
    """Rectangular stone slab — wider than thick, the building block of
    standing stones, walls, and architectural fragments. Lower poly than
    a tapered cylinder and reads as flat-faced megalithic stone."""
    mesh = trimesh.creation.box(extents=[width, depth, height])
    return _solid_color(mesh, color)


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


def heptagon_billboard(center: np.ndarray, normal: np.ndarray,
                       size: float, color: RGBA) -> trimesh.Trimesh:
    """Single flat seven-sided polygon at a position, facing a normal.

    The atom of the meta-pixel mote system. Heptagonal because:
      - Seven is prime: no rotational sub-symmetry with environmental
        shapes (hex columns, square grids, triangular mesh facets).
      - Heptagons cannot tile the plane: negative space stays
        irreducible, the shape cannot dissolve into its surroundings.
      - Merkabah-coded (seven Hekhalot halls). Each atom is a tiny
        working model of the architecture.

    Pinned by design_heptagonal_mote.md and design_meta_pixel_mote.md.
    Use this instead of quad_billboard for any small bright marker on
    a surface that should read as part of the visual atom doctrine.

    7 vertices triangulated as a fan from vertex 0 → 5 triangles per
    heptagon. `size` is the inscribed circle radius.
    """
    n = normal / (np.linalg.norm(normal) + 1e-9)
    up = np.array([0.0, 0.0, 1.0]) if abs(n[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    tangent = np.cross(up, n)
    tangent /= np.linalg.norm(tangent) + 1e-9
    bitangent = np.cross(n, tangent)

    # 7 perimeter vertices around center, in the tangent-bitangent plane
    verts = []
    for i in range(7):
        angle = (2.0 * math.pi * i) / 7.0
        offset = tangent * (math.cos(angle) * size) + \
                 bitangent * (math.sin(angle) * size)
        verts.append(center + offset)

    # Fan triangulation from vertex 0: (0, 1, 2), (0, 2, 3), ..., (0, 5, 6)
    # 5 triangles total for a 7-vertex polygon.
    faces = [[0, i + 1, i + 2] for i in range(5)]

    verts_array = np.array(verts)
    faces_array = np.array(faces)
    mesh = trimesh.Trimesh(vertices=verts_array, faces=faces_array, process=False)
    return _solid_color(mesh, color)


def scattered_heptagons(surface_points: np.ndarray,
                        surface_normals: np.ndarray,
                        sizes: Sequence[float],
                        color: RGBA) -> trimesh.Trimesh:
    """Batch of heptagonal billboards placed on a surface.

    Same interface as scattered_quads but each marker is a 7-sided
    atom from the meta-pixel doctrine. Use for surface markers on
    any kind that should be visually consistent with the atom mote
    system (puffball warts, fungal spore points, designed surface
    speckles).
    """
    meshes = []
    for pt, nrm, sz in zip(surface_points, surface_normals, sizes):
        meshes.append(heptagon_billboard(pt, nrm, sz, color))
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

    # Spots — heptagonal atom-doctrine billboards, the toadstool's
    # signature recognition marker. Originally authored as
    # scattered_quads (square billboards) before the heptagon doctrine
    # landed; retrofitted to scattered_heptagons here to align with
    # design_heptagonal_mote.md / design_meta_pixel_mote.md. Same
    # placement logic, same color, same per-spot size variation —
    # only the underlying primitive geometry changes (4-vert squares
    # → 7-vert heptagons). Both fungal kinds (toadstool + spore_pod)
    # now share the same atomic surface marker primitive.
    spots = scattered_heptagons(
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
# Boulder-mimic partner to giant_fungus. NOT a mushroom — no cap, no stem.
# Each pod is a PUFFBALL: squashed hemisphere body + dark apex pore (the
# spore-release vent) + flat dark contact-shadow disc at the base + cream
# warts scattered on the upper surface. Three puffballs at distinctly
# different scales (~3x spread) cluster as a colony catching the giant
# fungus's airborne spore release. Carries the fungus partner-type design
# without conflating with the cap-bearing toadstool / giant_fungus forms.
#
# Composition follows the toadstool recipe applied to a non-mushroom fungal
# silhouette:
#   1. Composed primitives — 4 sub-shapes per puffball (body, pore, apron, warts)
#   2. Vertex color regions per sub-shape
#   3. Palette anchored to cream cavern floor with deliberate value contrast
#   4. ~3x scale spread across the three pods in a cluster
#   5. Hand-tuned variants — different cluster spreads + size scales
#   6. Recognition markers — apex pore + cream warts (the "puffball brand")
#   7. Ground-hugging proportions (squashed hemisphere, body_height < radius)
#   8. Base contact-shadow disc fakes ground anchoring without lighting


# Palette — dusty mauve body distinct from toadstool red and giant_fungus
# purple-pink. Source RGB intentionally moderate; the trimesh→glTF→Godot
# pipeline shifts brighter on display so these will read lighter than the
# raw bytes. Cream warts use the same trick as toadstool spots, slightly
# cooler so the species reads as different.
#
# Five-region structure (matches toadstool's region count, applied to a
# non-mushroom silhouette via vertex-graded body instead of separate parts):
#   BODY  — equator skin, the lightest mauve, base of the dome
#   CROWN — dark "spore halo" near the apex, baked into body vertices via
#           a Z-gradient. Same hue as BODY, deeper value. Lets the body
#           read as two distinct zones inside one continuous hemisphere.
#   PORE  — near-black disc at the very apex, sits inside the dark crown
#           for maximum value contrast. Primary recognition marker.
#   APRON — deepest mauve, flat ring on the ground around the body base,
#           fakes a contact shadow without lighting.
#   WART  — warm cream scattered quads on the upper surface, secondary
#           recognition marker (same trick as toadstool spots).
SPORE_POD_BODY: RGBA  = (95, 65, 80, 255)     # equator skin (lightest)
SPORE_POD_CROWN: RGBA = (55, 35, 50, 255)     # apex spore halo (darker)
SPORE_POD_PORE: RGBA  = (28, 18, 24, 255)     # near-black apex vent
SPORE_POD_APRON: RGBA = (48, 32, 40, 255)     # deep mauve ground shadow
SPORE_POD_WART: RGBA  = (215, 195, 178, 255)  # warm cream warts


def build_puffball(
    body_radius: float = 0.45,
    body_height: float = 0.30,
    pore_radius: float = 0.10,
    apron_outer_mult: float = 1.15,
    apron_inner_mult: float = 0.70,
    wart_count: int = 7,
    wart_size: float = 0.060,
    body_sections: int = 12,
    body_rings: int = 3,
    wart_seed: int = 0,
) -> trimesh.Trimesh:
    """Single puffball — squashed dome + apex pore + base shadow + warts.

    NOT a mushroom. Four composed sub-shapes give the brain enough
    distinct features to read 'puffball / spore body' instead of generic
    'lump.' Same compositional grammar as the toadstool (dome+stem+ring
    +spots) translated to a non-cap-bearing fungal silhouette.

    body_radius / body_height — squashed hemisphere main mass; height
        should be < radius to read as ground-hugging not balloon-like.
    pore_radius — small dark disc on top, the spore-release vent. The
        primary recognition marker that says "this is a puffball."
    apron_outer_mult / apron_inner_mult — flat ring around the base
        (radius range body_radius * inner..outer) faking a contact shadow.
    wart_count / wart_size — surface recognition marker, scattered cream
        quad billboards on the upper hemisphere (same trick as toadstool
        spots).
    """
    # Body — squashed hemisphere, ground-hugging
    body = hemisphere(
        radius=body_radius,
        height=body_height,
        color=SPORE_POD_BODY,
        meridian_sections=body_sections,
        parallel_rings=body_rings,
    )

    # Z-graded body recoloring — equator stays SPORE_POD_BODY, the apex
    # pulls toward SPORE_POD_CROWN. Quadratic falloff (t*t) gives a tight
    # dark halo near the pore and lets the lower 60% of the dome stay the
    # lighter base shade. This creates two distinct visual zones inside
    # one continuous hemisphere — the texture-region trick that makes
    # the body itself feel multi-part instead of a single uniform blob.
    # Same hue family for both zones, only the value changes, so the
    # surface still reads as one organism not two stacked shapes.
    verts = body.vertices  # (N, 3) — Z is up in author space
    t = np.clip(verts[:, 2] / max(body_height, 1e-6), 0.0, 1.0)
    t = t * t  # quadratic — tight halo near apex, broad lighter zone below
    base_rgb = np.array(SPORE_POD_BODY[:3], dtype=float)
    crown_rgb = np.array(SPORE_POD_CROWN[:3], dtype=float)
    graded = base_rgb * (1.0 - t)[:, None] + crown_rgb * t[:, None]
    graded_u8 = np.clip(graded, 0, 255).astype(np.uint8)
    alpha = np.full((len(graded_u8), 1), 255, dtype=np.uint8)
    body.visual.vertex_colors = np.hstack([graded_u8, alpha])

    # Apex pore — small dark disc at the apex, just above the dome top
    pore = trimesh.creation.annulus(
        r_min=0.0, r_max=pore_radius,
        height=0.020, sections=10,
    )
    _solid_color(pore, SPORE_POD_PORE)
    pore.apply_translation([0.0, 0.0, body_height + 0.005])

    # Base contact shadow — flat ring around the body's base, just above
    # ground. Hidden under the body where it overlaps; the visible part
    # is the outer rim that extends beyond body_radius. Section count
    # decoupled from body — 6 facets is plenty for a ground shadow and
    # frees up triangle budget for the heptagonal warts above.
    apron = trimesh.creation.annulus(
        r_min=body_radius * apron_inner_mult,
        r_max=body_radius * apron_outer_mult,
        height=0.015, sections=6,
    )
    _solid_color(apron, SPORE_POD_APRON)
    apron.apply_translation([0.0, 0.0, 0.005])

    # Warts — scattered HEPTAGONAL atoms on upper hemisphere surface.
    # Avoid the apex (where the pore sits) and the equator (where the
    # apron is). Heptagons follow the atom mote doctrine
    # (design_heptagonal_mote.md, design_meta_pixel_mote.md): 7-sided,
    # prime, non-tiling, no rotational sub-symmetry with environmental
    # shapes. Replaces the previous quad billboards which were a
    # one-off violation of the atom doctrine — the puffball wart cluster
    # is exactly the use case the meta-pixel system was built for.
    rng = np.random.default_rng(wart_seed)
    wart_positions = []
    wart_normals = []
    wart_sizes = []
    for _ in range(wart_count):
        theta = rng.uniform(0, 2 * math.pi)
        phi = rng.uniform(0.20, 1.15)  # 0=apex (avoid), pi/2=equator (avoid)
        x = body_radius * math.sin(phi) * math.cos(theta)
        y = body_radius * math.sin(phi) * math.sin(theta)
        z = body_height * math.cos(phi)
        wart_positions.append(np.array([x, y, z]))
        wart_normals.append(np.array([
            x / body_radius,
            y / body_radius,
            (body_height * math.cos(phi)) / body_radius,
        ]))
        wart_sizes.append(wart_size * (0.7 + rng.random() * 0.6))

    warts = scattered_heptagons(
        np.array(wart_positions),
        np.array(wart_normals),
        wart_sizes,
        SPORE_POD_WART,
    )

    return compose([body, pore, apron, warts])


def build_spore_pod(
    cluster_radius: float = 0.55,
    size_scale: float = 1.0,
    body_sections: int = 12,
    pod_seed: int = 0,
) -> trimesh.Trimesh:
    """Three-puffball cluster — large mother + medium + small satellites.

    Three puffballs at ~3x scale spread (recipe Ingredient 4: distinct
    feature scales). Mother sits at the cluster center, two satellites
    at hash-driven angles around it. Each pod gets a different wart seed
    so the surface marker patterns don't repeat. The size spread does
    the heavy lifting for visual variety so the brain doesn't read
    'three identical lumps.'

    cluster_radius — XY spread of satellites from the mother
    size_scale     — uniform scale across all three pods (per-variant tweak)
    body_sections  — meridian count for body + apron (per-variant variation
                     so face counts differ across the four canonical variants)
    pod_seed       — seed for satellite angles + per-pod wart placement
    """
    rng = np.random.default_rng(pod_seed)

    # Per-pod base sizes — large mother, medium, small (~3x spread)
    # (body_radius, body_height, pore_radius, wart_count, wart_size)
    pod_specs = [
        (0.55, 0.34, 0.13, 8, 0.062),
        (0.36, 0.24, 0.09, 6, 0.048),
        (0.22, 0.16, 0.06, 5, 0.036),
    ]

    pods = []

    # Mother at center
    br, bh, pr, wc, ws = pod_specs[0]
    mother = build_puffball(
        body_radius=br * size_scale,
        body_height=bh * size_scale,
        pore_radius=pr * size_scale,
        wart_count=wc,
        wart_size=ws * size_scale,
        body_sections=body_sections,
        wart_seed=pod_seed,
    )
    pods.append(mother)

    # Medium + small satellites at varied angles around mother
    for i, (br, bh, pr, wc, ws) in enumerate(pod_specs[1:], start=1):
        angle = rng.uniform(0, 2 * math.pi)
        radial = cluster_radius * (0.75 + rng.random() * 0.30)
        x = radial * math.cos(angle)
        y = radial * math.sin(angle)

        sat = build_puffball(
            body_radius=br * size_scale,
            body_height=bh * size_scale,
            pore_radius=pr * size_scale,
            wart_count=wc,
            wart_size=ws * size_scale,
            body_sections=body_sections,
            wart_seed=pod_seed + i * 13,
        )
        sat.apply_translation([x, y, 0.0])
        pods.append(sat)

    return compose(pods)


def spore_pod_variants() -> list[trimesh.Trimesh]:
    """Four puffball cluster arrangements. Same mother+medium+small
    composition; variants differ by cluster spread, overall scale,
    body section count, and seed for natural distribution when several
    instances spawn nearby."""
    return [
        # v0: tight intimate trio — slightly smaller overall
        build_spore_pod(
            cluster_radius=0.45, size_scale=0.90,
            body_sections=10, pod_seed=11,
        ),
        # v1: standard
        build_spore_pod(
            cluster_radius=0.55, size_scale=1.00,
            body_sections=12, pod_seed=22,
        ),
        # v2: wider spread, slightly larger mother
        build_spore_pod(
            cluster_radius=0.65, size_scale=1.00,
            body_sections=14, pod_seed=33,
        ),
        # v3: tight cluster, slightly larger overall
        build_spore_pod(
            cluster_radius=0.50, size_scale=1.05,
            body_sections=11, pod_seed=44,
        ),
    ]


# -----------------------------------------------------------------------------
# Kind: doorframe
# -----------------------------------------------------------------------------
#
# Architectural kind — two upright stone posts + horizontal lintel beam.
# The threshold of a passage. Larger than fungus, smaller than mega_column.
# Reads as "carved entrance" / "ancient doorway." Vertex-colored so the
# lintel can be slightly darker than the posts (gives the illusion of
# weathered stone with shadowed underside).
#
# This is the first ARCHITECTURAL output of the gen_kind_mesh pipeline,
# proving the same composition framework handles man-made forms not just
# organic kinds. Pattern is reusable for arches, lintels, walls, doors.


# Aggressive darkening — vertex colors gamma-shift brighter through the
# trimesh→glTF→Godot pipeline. Source bytes need to be much lower than
# the intended display value. ~40% of first-pass values lands these in
# dark stone range matching the existing facet-normal column kinds.
DOORFRAME_POST_COLOR: RGBA   = (32, 26, 21, 255)     # dark weathered stone
DOORFRAME_LINTEL_COLOR: RGBA = (22, 17, 13, 255)     # shadowed beam — even darker
DOORFRAME_RUNE_COLOR: RGBA   = (75, 62, 48, 255)     # carved rune highlights


def doorframe_runes(
    lintel_length: float,
    lintel_depth: float,
    lintel_height: float,
    lintel_z_center: float,
    rune_count_front: int = 4,
    rune_count_back: int = 2,
    rune_size: float = 0.13,
    rune_seed: int = 0,
    color: RGBA = DOORFRAME_RUNE_COLOR,
) -> trimesh.Trimesh:
    """Heptagonal carved runes scattered across the front and back
    faces of the doorframe lintel. Atom-doctrine compliant
    (design_heptagonal_mote.md / design_meta_pixel_mote.md).

    The lintel is the natural surface for an inscription on a
    doorway — the carved beam over the threshold that names what
    you're entering. Same scattered_heptagons mechanism the monolith
    uses for its body glyphs, just oriented along a horizontal beam
    instead of a vertical body slab.

    Front face gets more runes than back (player approaches from
    front). Position scatter via deterministic hash so each variant
    carries a unique inscription pattern.
    """
    rng = np.random.default_rng(rune_seed)
    positions: list[np.ndarray] = []
    normals: list[np.ndarray] = []
    sizes: list[float] = []

    # Front face (y = -lintel_depth/2, normal points -Y)
    for _ in range(rune_count_front):
        x = rng.uniform(-lintel_length * 0.40, lintel_length * 0.40)
        z = lintel_z_center + rng.uniform(-lintel_height * 0.30,
                                          lintel_height * 0.30)
        pos = np.array([x, -lintel_depth * 0.5 - 0.005, z])
        nrm = np.array([0.0, -1.0, 0.0])
        sz = rune_size * (0.7 + rng.random() * 0.6)
        positions.append(pos)
        normals.append(nrm)
        sizes.append(sz)

    # Back face (y = +lintel_depth/2, normal points +Y) — fewer runes
    for _ in range(rune_count_back):
        x = rng.uniform(-lintel_length * 0.40, lintel_length * 0.40)
        z = lintel_z_center + rng.uniform(-lintel_height * 0.30,
                                          lintel_height * 0.30)
        pos = np.array([x, lintel_depth * 0.5 + 0.005, z])
        nrm = np.array([0.0, 1.0, 0.0])
        sz = rune_size * (0.7 + rng.random() * 0.6)
        positions.append(pos)
        normals.append(nrm)
        sizes.append(sz)

    return scattered_heptagons(
        np.array(positions),
        np.array(normals),
        sizes,
        color,
    )


def build_doorframe(
    post_height: float = 3.2,
    post_width: float = 0.50,      # square cross-section
    post_spacing: float = 1.80,    # gap between post inner edges
    lintel_overhang: float = 0.55, # how far lintel extends past posts (heavier)
    lintel_height: float = 0.80,   # vertical thickness of the beam (chunkier)
    lintel_depth_mult: float = 2.0,# how much deeper than the posts
    post_sections: int = 6,        # hexagonal posts (low-poly faceted)
    left_post_lean: float = 0.0,   # radians of lean — non-zero for ruined variants
    right_post_lean: float = 0.0,
    # Carved runes — heptagonal recognition markers on the lintel
    rune_count_front: int = 4,
    rune_count_back: int = 2,
    rune_size: float = 0.13,
    rune_seed: int = 0,
) -> trimesh.Trimesh:
    """Compose a doorway: two posts + heavy lintel beam, all vertex-colored.

    Lintel is now significantly chunkier than first pass — taller, deeper,
    with more overhang. Reads as a weathered stone block, not a beam.
    Optional per-post lean lets ruined variants tilt the posts inward
    or outward (subtle, ~3-8 degrees) for collapsed-arch character.
    """
    # --- Left post ---
    left_post = capped_cylinder(
        radius_bottom=post_width,
        radius_top=post_width * 0.85,
        height=post_height,
        sections=post_sections,
        color=DOORFRAME_POST_COLOR,
    )
    left_post.apply_translation([0.0, 0.0, post_height * 0.5])
    if abs(left_post_lean) > 0.001:
        # Rotate around Y axis (lean toward/away from doorway center)
        rot = trimesh.transformations.rotation_matrix(
            angle=left_post_lean, direction=[0.0, 1.0, 0.0],
            point=[0.0, 0.0, 0.0],
        )
        left_post.apply_transform(rot)
    left_post.apply_translation([-post_spacing * 0.5 - post_width, 0.0, 0.0])

    # --- Right post ---
    right_post = capped_cylinder(
        radius_bottom=post_width,
        radius_top=post_width * 0.85,
        height=post_height,
        sections=post_sections,
        color=DOORFRAME_POST_COLOR,
    )
    right_post.apply_translation([0.0, 0.0, post_height * 0.5])
    if abs(right_post_lean) > 0.001:
        rot = trimesh.transformations.rotation_matrix(
            angle=right_post_lean, direction=[0.0, 1.0, 0.0],
            point=[0.0, 0.0, 0.0],
        )
        right_post.apply_transform(rot)
    right_post.apply_translation([post_spacing * 0.5 + post_width, 0.0, 0.0])

    # --- Lintel: chunky rectangular block across the top ---
    lintel_length = post_spacing + (post_width * 2) + (lintel_overhang * 2)
    lintel_depth = post_width * lintel_depth_mult
    lintel_z_center = post_height + lintel_height * 0.5
    lintel = trimesh.creation.box(
        extents=[lintel_length, lintel_depth, lintel_height]
    )
    _solid_color(lintel, DOORFRAME_LINTEL_COLOR)
    lintel.apply_translation([0.0, 0.0, lintel_z_center])

    parts = [left_post, right_post, lintel]

    # --- Carved heptagonal runes on the lintel face ---
    # Atom-doctrine recognition marker via the same scattered_heptagons
    # primitive the monolith uses for body glyphs. Closes the recipe
    # gap on the doorframe — every authored kind in the gen_kind_mesh
    # set now carries the doctrine-compliant marker.
    if rune_count_front + rune_count_back > 0:
        runes = doorframe_runes(
            lintel_length=lintel_length,
            lintel_depth=lintel_depth,
            lintel_height=lintel_height,
            lintel_z_center=lintel_z_center,
            rune_count_front=rune_count_front,
            rune_count_back=rune_count_back,
            rune_size=rune_size,
            rune_seed=rune_seed,
        )
        parts.append(runes)

    return compose(parts)


def doorframe_variants() -> list[trimesh.Trimesh]:
    """Four doorway variants with carved heptagonal runes on the
    lintel. Two are intact, two are weathered/ruined with subtle post
    lean for collapsed-arch character. Each variant carries a distinct
    rune_seed so the inscription patterns differ."""
    return [
        # v0: standard — solid intact doorway, dense runes
        build_doorframe(
            post_height=3.2, post_width=0.50,
            post_spacing=1.80, lintel_overhang=0.55,
            lintel_height=0.80, lintel_depth_mult=2.0,
            rune_count_front=5, rune_count_back=2,
            rune_size=0.13, rune_seed=171,
        ),
        # v1: tall passage — narrow vertical, fewer runes
        build_doorframe(
            post_height=4.2, post_width=0.45,
            post_spacing=1.40, lintel_overhang=0.50,
            lintel_height=0.70, lintel_depth_mult=1.9,
            rune_count_front=4, rune_count_back=2,
            rune_size=0.11, rune_seed=282,
        ),
        # v2: wide gateway — heavy stone, slight inward lean (ruined),
        # MORE runes (the wide lintel has room for an inscription)
        build_doorframe(
            post_height=3.0, post_width=0.65,
            post_spacing=2.40, lintel_overhang=0.75,
            lintel_height=1.00, lintel_depth_mult=2.2,
            left_post_lean=0.06, right_post_lean=-0.06,  # ~3.4° inward
            rune_count_front=7, rune_count_back=3,
            rune_size=0.15, rune_seed=393,
        ),
        # v3: ruined collapse — fewer worn runes (most have eroded away)
        build_doorframe(
            post_height=2.6, post_width=0.55,
            post_spacing=1.70, lintel_overhang=0.45,
            lintel_height=0.65, lintel_depth_mult=1.8,
            left_post_lean=-0.10, right_post_lean=0.04,  # asymmetric collapse
            rune_count_front=3, rune_count_back=1,
            rune_size=0.12, rune_seed=404,
        ),
    ]


# -----------------------------------------------------------------------------
# Kind: monolith
# -----------------------------------------------------------------------------
#
# Standing-stone landmark — single tall narrow stone with subtle vertical
# fluting. Adds a third landmark class beyond mega_column (huge fat) and
# column (rounded spire). Different silhouette = more visual variety in
# distance vistas. Reads as "menhir / standing stone / boundary marker."
# Single-color (no per-region painting needed) but uses use_vertex_colors
# so it integrates with the same shader path as toadstool/spore_pod.


# Slab palette — three vertical zones for the standing stone plus a
# glyph color for the carved heptagonal recognition markers:
#   base  = mossy/buried foot
#   body  = main stone
#   crown = weathered top
#   glyph = carved heptagonal markers on the body face (atom doctrine)
# Source bytes are aggressively gamma-compensated (dark) to land in
# stone-grey display range. Glyph is brighter than body for value
# contrast (so the marks read as carved-out / weathered-bright).
SLAB_BASE_COLOR: RGBA  = (28, 24, 21, 255)   # dark earth-bound foot
SLAB_BODY_COLOR: RGBA  = (40, 34, 28, 255)   # main stone body
SLAB_CROWN_COLOR: RGBA = (52, 44, 36, 255)   # lighter weathered crown
SLAB_GLYPH_COLOR: RGBA = (95, 82, 68, 255)   # brighter weathered carved marks
# Backwards-compat alias for any external import — maps to body color
MONOLITH_STONE_COLOR: RGBA = SLAB_BODY_COLOR


def monolith_glyphs(
    body_width: float,
    body_depth: float,
    body_height: float,
    body_z_offset: float,
    glyph_count_front: int = 5,
    glyph_count_back: int = 3,
    glyph_size: float = 0.12,
    glyph_seed: int = 0,
    color: RGBA = SLAB_GLYPH_COLOR,
) -> trimesh.Trimesh:
    """Heptagonal carved glyphs scattered across the front and back
    faces of a monolith body. Each glyph is an atom-doctrine-compliant
    heptagonal billboard (design_heptagonal_mote.md /
    design_meta_pixel_mote.md).

    Adds the recognition marker that distinguishes a monolith from a
    generic standing rock — the toadstool recipe says every kind needs
    a marker (Ingredient 6), and the atom doctrine says markers must
    be heptagonal. The glyphs read as worn / weathered carvings on the
    monolith face.

    Glyphs scatter via deterministic hash, so the same monolith
    variant always carries the same glyph pattern (no shimmer between
    frames). Front face gets more glyphs than back (player view bias).
    """
    rng = np.random.default_rng(glyph_seed)
    positions: list[np.ndarray] = []
    normals: list[np.ndarray] = []
    sizes: list[float] = []

    # Front face (y = -body_depth/2, normal points -Y)
    for _ in range(glyph_count_front):
        x = rng.uniform(-body_width * 0.35, body_width * 0.35)
        z = body_z_offset + rng.uniform(body_height * 0.20, body_height * 0.85)
        pos = np.array([x, -body_depth * 0.5 - 0.005, z])
        nrm = np.array([0.0, -1.0, 0.0])
        sz = glyph_size * (0.7 + rng.random() * 0.6)
        positions.append(pos)
        normals.append(nrm)
        sizes.append(sz)

    # Back face (y = +body_depth/2, normal points +Y) — fewer glyphs
    for _ in range(glyph_count_back):
        x = rng.uniform(-body_width * 0.35, body_width * 0.35)
        z = body_z_offset + rng.uniform(body_height * 0.20, body_height * 0.85)
        pos = np.array([x, body_depth * 0.5 + 0.005, z])
        nrm = np.array([0.0, 1.0, 0.0])
        sz = glyph_size * (0.7 + rng.random() * 0.6)
        positions.append(pos)
        normals.append(nrm)
        sizes.append(sz)

    return scattered_heptagons(
        np.array(positions),
        np.array(normals),
        sizes,
        color,
    )


def build_monolith(
    # Base — wider footing planted in ground (slightly buried)
    base_width: float = 1.40,
    base_depth: float = 0.70,
    base_height: float = 0.45,
    # Body — tall narrow main slab (this is the "stone" itself)
    body_width: float = 0.95,
    body_depth: float = 0.45,
    body_height: float = 3.20,
    # Capital — wider overhanging top (the architectural feature that
    # makes this read as a CARVED stone, not just a rock)
    capital_width: float = 1.30,
    capital_depth: float = 0.65,
    capital_height: float = 0.40,
    has_capital: bool = True,
    overall_lean: float = 0.0,
    # Carved glyphs — heptagonal recognition markers on the body face
    glyph_count_front: int = 5,
    glyph_count_back: int = 3,
    glyph_size: float = 0.12,
    glyph_seed: int = 0,
) -> trimesh.Trimesh:
    """Carved standing stone — base + body + capital stack.

    Three distinct architectural zones, each wider/narrower than the next,
    that together read as a carved monument fragment:
      - BASE  : wide footing, darker, partially buried (the foundation)
      - BODY  : narrow tall slab, mid-tone (the stone itself)
      - CAPITAL: wide flat overhang, lighter (the carved top — Greek/
                 Egyptian column capital, Mayan stele top, tombstone)

    The capital is the key feature. A rock without a capital is just a
    rock. A rock WITH a flat overhanging top reads as carved/monumental.
    The width steps in (wide-narrow-wide) create a recognizable carved
    silhouette that the eye reads as "stone monument" instantly.

    has_capital=False produces a "broken" variant — body alone with
    weathered top, the monument fragment after the capital fell.
    """
    sections = []

    # Base — wider, darker, planted into ground
    base = slab(width=base_width, depth=base_depth,
                height=base_height, color=SLAB_BASE_COLOR)
    base.apply_translation([0.0, 0.0, base_height * 0.5])
    sections.append(base)

    # Body — tall narrow main slab
    body = slab(width=body_width, depth=body_depth,
                height=body_height, color=SLAB_BODY_COLOR)
    body.apply_translation([0.0, 0.0, base_height + body_height * 0.5])
    sections.append(body)

    # Capital — wide overhanging top (the carved feature)
    if has_capital and capital_height > 0.001:
        capital = slab(width=capital_width, depth=capital_depth,
                       height=capital_height, color=SLAB_CROWN_COLOR)
        capital.apply_translation([
            0.0, 0.0,
            base_height + body_height + capital_height * 0.5,
        ])
        sections.append(capital)

    # Carved heptagonal glyphs on the body face — recognition marker
    # via the atom doctrine. Adds the "this is a monument" cue that
    # distinguishes a monolith from a generic stone slab.
    if glyph_count_front + glyph_count_back > 0:
        glyphs = monolith_glyphs(
            body_width=body_width,
            body_depth=body_depth,
            body_height=body_height,
            body_z_offset=base_height,
            glyph_count_front=glyph_count_front,
            glyph_count_back=glyph_count_back,
            glyph_size=glyph_size,
            glyph_seed=glyph_seed,
        )
        sections.append(glyphs)

    mesh = compose(sections)

    if abs(overall_lean) > 0.001:
        rot = trimesh.transformations.rotation_matrix(
            angle=overall_lean, direction=[0.0, 1.0, 0.0],
            point=[0.0, 0.0, 0.0],
        )
        mesh.apply_transform(rot)
        min_z = float(mesh.vertices[:, 2].min())
        mesh.apply_translation([0.0, 0.0, -min_z])

    return mesh


def monolith_variants() -> list[trimesh.Trimesh]:
    """Four carved standing stones — base+body+capital architecture
    with heptagonal carved glyphs on the body face. The wide-narrow-wide
    silhouette + glyph markers read as MONUMENT, not as ROCK. Each
    variant gets a distinct glyph_seed so the carving patterns differ."""
    return [
        # v0: standard carved stele — clean architectural form, dense glyphs
        build_monolith(
            base_width=1.40, base_depth=0.70, base_height=0.45,
            body_width=0.95, body_depth=0.45, body_height=3.20,
            capital_width=1.30, capital_depth=0.65, capital_height=0.40,
            glyph_count_front=6, glyph_count_back=4,
            glyph_size=0.13, glyph_seed=131,
        ),
        # v1: tall slim stele — narrower body, taller, slight lean,
        # slightly fewer glyphs (taller body needs spacing not clutter)
        build_monolith(
            base_width=1.20, base_depth=0.60, base_height=0.40,
            body_width=0.80, body_depth=0.38, body_height=4.00,
            capital_width=1.15, capital_depth=0.55, capital_height=0.35,
            overall_lean=0.07,  # ~4° lean
            glyph_count_front=5, glyph_count_back=3,
            glyph_size=0.11, glyph_seed=242,
        ),
        # v2: broken monument — capital fallen off, weathered body alone,
        # MORE glyphs (the body is the only feature so it carries more)
        build_monolith(
            base_width=1.50, base_depth=0.75, base_height=0.55,
            body_width=1.00, body_depth=0.50, body_height=2.50,
            capital_width=0.0, capital_depth=0.0, capital_height=0.0,
            has_capital=False,
            glyph_count_front=7, glyph_count_back=4,
            glyph_size=0.14, glyph_seed=353,
        ),
        # v3: heavy short pillar — wide squat stele, dramatic capital,
        # fewer larger glyphs (wide body, bigger marks read at distance)
        build_monolith(
            base_width=1.60, base_depth=0.80, base_height=0.55,
            body_width=1.05, body_depth=0.55, body_height=2.20,
            capital_width=1.55, capital_depth=0.80, capital_height=0.50,
            overall_lean=-0.05,  # slight opposite lean
            glyph_count_front=4, glyph_count_back=2,
            glyph_size=0.16, glyph_seed=464,
        ),
    ]


# -----------------------------------------------------------------------------
# Kind: boulder
# -----------------------------------------------------------------------------
#
# Geological mass — composed multi-lobe mound. NOT a single deformed
# sphere. Three icospheres (1 main + 2 secondary) at overlapping
# offset positions create a knobby asymmetric silhouette that the
# brain parses as "weathered stone mass" rather than "lump." The
# secondary lobes overlap the main lobe enough to read as bumps, not
# as separate balls — concatenate-based composition with deliberate
# overlap.
#
# Composition follows the toadstool recipe applied to a real-stone
# kind (no fungal mimic, no chromatic mismatch needed):
#   1. Composed primitives — 3 lobes per boulder (Ingredient 1)
#   2. Vertex color regions — Z-graded body + apron (Ingredient 2)
#   3. Palette anchored to env — warm grey-brown stone (Ingredient 3)
#   4. Scale spread across lobes — 0.50 / 0.30 / 0.22 (~2.3x spread)
#   5. Hand-tuned 4 variants — different lobe arrangements + moss
#      coverage stages (newer fall vs long-settled)
#   6. Mossy upper grading via Z-gradient — top vertices pull toward
#      moss color (the recognition marker — "this rock has been
#      sitting here long enough to grow a coat")
#   7. Roughly cubic bounds — keeps main.gd's per-instance scaling
#      working without breaking existing boulder placement logic
#   8. Base apron — flat ring at z=0 fakes contact shadow


# Boulder palette — warm grey-brown stone with mossy upper grading.
# Boulder is REAL stone, not a fungal mimic, so the mycelium camouflage
# doctrine does NOT apply. Stone color is in the cavern grey family.
# Moss is the recognition marker — value+hue contrast against the
# stone body, anchored to the cavern's existing moss palette so it
# reads as the same green family as moss_patch.
BOULDER_BASE: RGBA   = (38, 32, 26, 255)   # dark warm grey-brown body
BOULDER_CROWN: RGBA  = (62, 52, 40, 255)   # lighter weathered upper
BOULDER_MOSS: RGBA   = (45, 65, 30, 255)   # muted dark mossy green
BOULDER_APRON: RGBA  = (22, 18, 15, 255)   # deepest shadow under


def build_boulder(
    main_radius: float = 0.50,
    main_z_squash: float = 0.78,
    secondary_offset_a: tuple = (0.32, 0.18, 0.05),
    secondary_radius_a: float = 0.30,
    secondary_offset_b: tuple = (-0.25, -0.20, 0.10),
    secondary_radius_b: float = 0.22,
    moss_strength: float = 0.55,
    moss_threshold: float = 0.55,
    apron_outer_mult: float = 1.18,
    apron_inner_mult: float = 0.72,
) -> trimesh.Trimesh:
    """Multi-lobe boulder mass — main mound + 2 smaller bumps + base
    apron, with Z-graded vertex coloring (stone at the equator,
    lighter weathered crown above, mossy green at the very top).

    NOT a single deformed sphere. Three composed icospheres at
    overlapping offset positions break the "smooth round blob"
    reading. The secondary lobes are placed inside the main lobe's
    radius so they appear as bumps protruding from the surface, not
    as separate balls touching each other.

    moss_strength controls how aggressively the upper vertices pull
    toward MOSS color. moss_threshold is the Z fraction above which
    moss starts (0.0 = full body, 1.0 = only the very apex).
    """
    parts = []

    # Main lobe — squashed icosphere centered at origin
    main = sphere(
        radius=main_radius,
        color=BOULDER_BASE,
        subdivisions=1,
        squash=main_z_squash,
    )
    main.apply_translation([0.0, 0.0, main_radius * main_z_squash])
    parts.append(main)

    # Secondary lobe A — smaller, offset to one side, deliberately
    # placed inside the main lobe so it reads as a bump not a ball
    sec_a = sphere(
        radius=secondary_radius_a,
        color=BOULDER_BASE,
        subdivisions=1,
        squash=main_z_squash,
    )
    sec_a.apply_translation([
        secondary_offset_a[0],
        secondary_offset_a[1],
        secondary_radius_a * main_z_squash + secondary_offset_a[2],
    ])
    parts.append(sec_a)

    # Secondary lobe B — even smaller, opposite side
    sec_b = sphere(
        radius=secondary_radius_b,
        color=BOULDER_BASE,
        subdivisions=1,
        squash=main_z_squash,
    )
    sec_b.apply_translation([
        secondary_offset_b[0],
        secondary_offset_b[1],
        secondary_radius_b * main_z_squash + secondary_offset_b[2],
    ])
    parts.append(sec_b)

    # Combine the lobes into one body before grading
    body = compose(parts)

    # Z-gradient vertex recoloring on the combined body:
    #   t=0 (z_min) → BOULDER_BASE (dark stone)
    #   t=1 (z_max) → BOULDER_CROWN (lighter weathered)
    #   above moss_threshold → lerp toward BOULDER_MOSS
    # Same per-vertex grading pattern the puffball body uses.
    verts = body.vertices
    z_min = float(verts[:, 2].min())
    z_max = float(verts[:, 2].max())
    z_range = max(z_max - z_min, 1e-6)
    t = (verts[:, 2] - z_min) / z_range  # 0 at base, 1 at top

    base_rgb = np.array(BOULDER_BASE[:3], dtype=float)
    crown_rgb = np.array(BOULDER_CROWN[:3], dtype=float)
    moss_rgb = np.array(BOULDER_MOSS[:3], dtype=float)

    # Linear lerp base → crown across the whole body
    body_color = base_rgb * (1.0 - t)[:, None] + crown_rgb * t[:, None]

    # Moss overlay: above moss_threshold, lerp toward moss_rgb
    moss_t = np.clip(
        (t - moss_threshold) / max(1.0 - moss_threshold, 1e-6),
        0.0, 1.0,
    )
    moss_t = moss_t * moss_strength
    final_color = body_color * (1.0 - moss_t)[:, None] + moss_rgb * moss_t[:, None]

    final_u8 = np.clip(final_color, 0, 255).astype(np.uint8)
    alpha = np.full((len(final_u8), 1), 255, dtype=np.uint8)
    body.visual.vertex_colors = np.hstack([final_u8, alpha])

    # Base apron — flat shadow ring around the body's footprint
    apron = trimesh.creation.annulus(
        r_min=main_radius * apron_inner_mult,
        r_max=main_radius * apron_outer_mult,
        height=0.015, sections=8,
    )
    _solid_color(apron, BOULDER_APRON)
    apron.apply_translation([0.0, 0.0, 0.005])

    return compose([body, apron])


def boulder_variants() -> list[trimesh.Trimesh]:
    """Four boulder masses — different lobe arrangements and moss
    coverage stages. The multi-lobe composition + Z-graded mossy
    crown reads as 'weathered stone mass with a moss coat' instead
    of 'generic round blob.' Each variant is a different stage of
    weathering (newer fall → long-settled mossy)."""
    return [
        # v0: standard 3-lobe — main + medium + small to one side,
        # moderate moss coverage (typical settled boulder)
        build_boulder(
            main_radius=0.50,
            secondary_offset_a=(0.32, 0.18, 0.05),
            secondary_radius_a=0.30,
            secondary_offset_b=(-0.25, -0.20, 0.10),
            secondary_radius_b=0.22,
            moss_strength=0.55,
            moss_threshold=0.55,
        ),
        # v1: heavy 3-lobe — bigger main, sparse moss (newer fall)
        build_boulder(
            main_radius=0.55,
            secondary_offset_a=(0.30, -0.15, 0.08),
            secondary_radius_a=0.28,
            secondary_offset_b=(-0.30, 0.18, 0.06),
            secondary_radius_b=0.20,
            moss_strength=0.30,
            moss_threshold=0.65,
        ),
        # v2: weathered 3-lobe — long-settled, dominant moss coat
        build_boulder(
            main_radius=0.48,
            secondary_offset_a=(0.28, 0.22, 0.08),
            secondary_radius_a=0.32,
            secondary_offset_b=(-0.22, -0.15, 0.12),
            secondary_radius_b=0.25,
            moss_strength=0.75,
            moss_threshold=0.45,
        ),
        # v3: asymmetric 3-lobe — main offset, dramatic secondary
        build_boulder(
            main_radius=0.52,
            secondary_offset_a=(0.38, 0.10, 0.04),
            secondary_radius_a=0.32,
            secondary_offset_b=(-0.20, 0.25, 0.08),
            secondary_radius_b=0.18,
            moss_strength=0.45,
            moss_threshold=0.55,
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
    "doorframe": doorframe_variants,
    "monolith": monolith_variants,
    "boulder": boulder_variants,
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
