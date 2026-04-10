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
import zlib
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


# =============================================================================
# Family builders — parameterized primitives ported from ambient_life.py
# =============================================================================
#
# Each family builder has the signature:
#     (kind_name: str, kind_cfg: dict) -> list[trimesh.Trimesh]
#
# `kind_cfg` is the per-kind dict from godot/kind_config.json["kinds"][name].
# The family builder reads:
#   - kind_cfg["recipe"]  (tier, variant_count, bounds, variant_spread,
#                          apron, atoms, family_params)
#   - kind_cfg["color_base"], ["color_shadow"], ["color_accent"]  (palette)
#
# Determinism: seeds derive from hash((kind_name, variant_idx)) so
# regenerating the same kind produces byte-identical variants.


# Shared constants used across family builders
_CREAM_ATOM: RGBA = (225, 215, 195, 255)  # heptagonal recognition markers


def _rgb01_to_rgba_u8(rgb01: Sequence[float], alpha: int = 255) -> RGBA:
    """Convert [0..1] float RGB from kind_config into a (0..255) RGBA tuple."""
    return (
        int(round(rgb01[0] * 255)),
        int(round(rgb01[1] * 255)),
        int(round(rgb01[2] * 255)),
        alpha,
    )


def _apply_z_gradient_three_stop(mesh: trimesh.Trimesh,
                                 base: RGBA,
                                 mid: RGBA,
                                 top: RGBA) -> trimesh.Trimesh:
    """Paint a 3-stop Z-gradient onto a mesh in place.

    t=0   → base color   (bottom of mesh)
    t=0.5 → mid color    (middle)
    t=1.0 → top color    (crown)

    Used by every family builder whose kind wants "dark base, mid-value
    body, lighter crown" — the default stone/flora reading. Same pattern
    as build_boulder's Z-gradient but extracted for reuse.
    """
    verts = mesh.vertices
    z_min = float(verts[:, 2].min())
    z_max = float(verts[:, 2].max())
    z_range = max(z_max - z_min, 1e-6)
    t = (verts[:, 2] - z_min) / z_range

    base_rgb = np.array(base[:3], dtype=float)
    mid_rgb = np.array(mid[:3], dtype=float)
    top_rgb = np.array(top[:3], dtype=float)

    lower_mask = t < 0.5
    upper_mask = ~lower_mask

    colors = np.zeros((len(verts), 3), dtype=float)
    lt = (t[lower_mask] * 2.0)[:, None]               # 0..1 across lower half
    colors[lower_mask] = base_rgb * (1 - lt) + mid_rgb * lt
    ut = ((t[upper_mask] - 0.5) * 2.0)[:, None]       # 0..1 across upper half
    colors[upper_mask] = mid_rgb * (1 - ut) + top_rgb * ut

    colors_u8 = np.clip(colors, 0, 255).astype(np.uint8)
    alpha = np.full((len(colors_u8), 1), 255, dtype=np.uint8)
    mesh.visual.vertex_colors = np.hstack([colors_u8, alpha])
    return mesh


def _build_tapered_vertical_instance(
    base_radius: float,
    height: float,
    taper_strength: float,
    flare_ratio: float,
    flare_frac: float,
    noise_strength: float,
    facet_count: int,
    ring_count: int,
    base_color: RGBA,
    shadow_color: RGBA,
    accent_color: RGBA,
    atoms_cfg: dict | None,
    rng: np.random.Generator,
) -> trimesh.Trimesh:
    """Single variant of a tapered-vertical body: revolved noisy profile
    + optional base flare + 3-stop Z-gradient + optional heptagonal atom
    markers on the surface."""
    # Build the 2D profile: ring_count+1 points from base (z=0) to tip (z=height).
    # Each point has a per-ring radius that incorporates taper, flare, and noise.
    z_values = np.linspace(0.0, height, ring_count + 1)
    profile_radii = []
    for i, z in enumerate(z_values):
        t = z / height if height > 0 else 0.0   # 0 at base, 1 at tip

        # Taper: 1.0 at base, (1 - taper_strength) at tip
        r = base_radius * (1.0 - t * taper_strength)

        # Base flare: widen the bottom `flare_frac` of the height
        if t < flare_frac and flare_frac > 0:
            flare_t = 1.0 - (t / flare_frac)  # 1 at z=0, 0 at top of flare zone
            r *= 1.0 + (flare_ratio - 1.0) * flare_t

        # Radial noise (deterministic via rng): ±noise_strength of current radius
        noise = 1.0 + (rng.random() - 0.5) * 2.0 * noise_strength
        r *= noise
        profile_radii.append(max(r, 0.005))

    # trimesh.creation.revolve expects a profile starting AND ending on the Z axis
    # for a closed solid. Add a closing point at the origin below the base.
    profile_2d = np.column_stack([profile_radii, z_values])
    profile_2d = np.vstack([profile_2d, [0.0, 0.0]])   # close base

    body = trimesh.creation.revolve(profile_2d, sections=facet_count)
    _apply_z_gradient_three_stop(body, base_color, shadow_color, accent_color)

    # Atom markers — scatter heptagons along the vertical at chain_5 positions
    if atoms_cfg:
        atom_count = int(atoms_cfg.get("count", 5))
        atom_size = float(atoms_cfg.get("size", 0.08))

        atom_points = []
        atom_normals = []
        # Stagger vertically between 15% and 85% of height (avoid base & tip)
        for i in range(atom_count):
            y_frac = 0.15 + 0.7 * (i / max(atom_count - 1, 1))
            z_pos = y_frac * height
            # Interpolate the profile radius at this height
            ring_pos = y_frac * ring_count
            lower_idx = int(np.floor(ring_pos))
            upper_idx = min(lower_idx + 1, ring_count)
            frac = ring_pos - lower_idx
            r_here = profile_radii[lower_idx] * (1 - frac) + profile_radii[upper_idx] * frac
            # Distinct angle per atom (staggered so they don't line up)
            angle = (i * (2.0 * math.pi / atom_count)
                     + (i % 2) * (math.pi / atom_count))
            # Place slightly outside the surface so the heptagon's flat plane
            # doesn't co-plane with the body and cause z-fighting
            outward_offset = 1.03
            px = math.cos(angle) * r_here * outward_offset
            py = math.sin(angle) * r_here * outward_offset
            atom_points.append([px, py, z_pos])
            atom_normals.append([math.cos(angle), math.sin(angle), 0.0])

        atoms_mesh = scattered_heptagons(
            np.array(atom_points),
            np.array(atom_normals),
            [atom_size] * atom_count,
            _CREAM_ATOM,
        )
        body = compose([body, atoms_mesh])

    return body


def _build_rock_lobed_instance(
    v_width: float,
    v_depth: float,
    v_height: float,
    lobe_count: int,
    spread_radius_frac: float,
    flatness: float,
    noise_strength: float,
    elongation: float,
    base_color: RGBA,
    shadow_color: RGBA,
    accent_color: RGBA,
    rng: np.random.Generator,
) -> trimesh.Trimesh:
    """Single variant of a rock-lobed cluster: N squashed icospheres
    scattered within a footprint, radially noise-displaced, Z-gradient
    colored. Used by Tier 2 geological tissue (rubble, cave_gravel,
    bone_pile) — not a recipe-faithful anchor, just enough shape to
    unify the render path with vertex colors."""
    parts = []
    cluster_radius = v_width * 0.5 * spread_radius_frac
    lobe_base_r = v_width * 0.25  # each lobe is about a quarter of the cluster width

    for li in range(lobe_count):
        # First lobe is the biggest; subsequent lobes decay in size
        decay = 1.0 - 0.3 * (li / max(lobe_count - 1, 1))
        lobe_r = lobe_base_r * decay * (0.85 + rng.random() * 0.3)

        # Position within the cluster footprint
        if li == 0:
            offset_x, offset_y = 0.0, 0.0
        else:
            angle = rng.random() * 2.0 * math.pi
            dist = cluster_radius * (0.3 + rng.random() * 0.7)
            offset_x = math.cos(angle) * dist * elongation
            offset_y = math.sin(angle) * dist

        lobe = sphere(
            radius=lobe_r,
            color=base_color,
            subdivisions=1,
            squash=flatness,
        )
        # Rest on ground — center at (x, y, lobe_r*flatness*0.7) so the
        # bottom is at ~0.3 × squashed_radius below ground (concave sink)
        z_offset = lobe_r * flatness * 0.7
        lobe.apply_translation([offset_x, offset_y, z_offset])

        # Radial noise: push each vertex outward or inward by ±noise_strength
        if noise_strength > 0:
            verts = lobe.vertices
            center = np.array([offset_x, offset_y, z_offset])
            directions = verts - center
            norms = np.linalg.norm(directions, axis=1, keepdims=True)
            directions_norm = directions / np.maximum(norms, 1e-6)
            noise_amt = (rng.random(len(verts)) - 0.5) * 2.0 * noise_strength * lobe_r
            lobe.vertices = verts + directions_norm * noise_amt[:, None]

        parts.append(lobe)

    body = compose(parts)
    _apply_z_gradient_three_stop(body, base_color, shadow_color, accent_color)

    # Fit the cluster's natural footprint to canonical bounds. Elongation
    # is preserved by using a non-uniform target: X = v_width, Y = v_depth
    # (where v_depth can be shrunk by elongation at the caller level).
    natural_ext = body.extents
    sx = v_width  / natural_ext[0] if natural_ext[0] > 1e-6 else 1.0
    sy = v_depth  / natural_ext[1] if natural_ext[1] > 1e-6 else 1.0
    sz = v_height / natural_ext[2] if natural_ext[2] > 1e-6 else 1.0
    body.vertices[:, 0] *= sx
    body.vertices[:, 1] *= sy
    body.vertices[:, 2] *= sz

    return body


def _family_rock_lobed(kind_name: str, kind_cfg: dict) -> list[trimesh.Trimesh]:
    """Rock lobed cluster family — Tier 2 geological tissue. Used for
    rubble, cave_gravel, bone_pile: multi-lobe scatter of squashed
    icospheres merged into one mesh per variant, Z-gradient colored,
    no atoms, no composed primitives. Cheap, consistent, unifies the
    shader path for all ground-rock scatter.

    NOT a generalization of build_boulder. Boulder stays on its
    hand-authored legacy path; this family is authored fresh for the
    non-landmark rocks.

    Recipe fields (kind_cfg["recipe"]):
      bounds           [w, d, h]   cluster footprint
      variant_count    int          typically 2 for Tier 2
      variant_spread   float        per-variant size drift
      family_params    dict:
        lobe_count        int       1 (single rock) to 5 (debris field)
        spread_radius     float     0..1 fraction of width for scatter
        flatness          float     icosphere squash (0.3-1.0)
        noise_strength    float     radial vertex displacement 0..0.5
        elongation        float     1=round cluster, >1=elongated along X

    Palette from kind_cfg["color_base"/"color_shadow"/"color_accent"].
    """
    recipe = kind_cfg["recipe"]
    fp = recipe.get("family_params", {})
    bounds = recipe["bounds"]
    variant_count = int(recipe["variant_count"])
    variant_spread = float(recipe.get("variant_spread", 0.30))

    canonical_width  = float(bounds[0])
    canonical_depth  = float(bounds[1])
    canonical_height = float(bounds[2])

    lobe_count         = int(fp.get("lobe_count", 3))
    spread_radius_frac = float(fp.get("spread_radius", 0.8))
    flatness           = float(fp.get("flatness", 0.7))
    noise_strength     = float(fp.get("noise_strength", 0.15))
    elongation         = float(fp.get("elongation", 1.0))
    # Elongation shrinks Y (depth) relative to X (width). Bone_pile with
    # elongation 1.8 → depth = 0.55 × width. Uniform clusters use 1.0.
    effective_depth = canonical_depth / elongation

    base_color   = _rgb01_to_rgba_u8(kind_cfg.get("color_base",   [0.30, 0.27, 0.23]))
    shadow_color = _rgb01_to_rgba_u8(kind_cfg.get("color_shadow", [0.26, 0.23, 0.19]))
    accent_color = _rgb01_to_rgba_u8(kind_cfg.get("color_accent", [0.34, 0.30, 0.25]))

    variants = []
    for v_idx in range(variant_count):
        seed = zlib.crc32(f"{kind_name}-{v_idx}".encode()) & 0xFFFFFFFF
        rng = np.random.default_rng(seed)

        size_drift = 1.0 + variant_spread * (rng.random() * 2.0 - 1.0)
        v_width  = canonical_width  * size_drift
        v_depth  = effective_depth  * size_drift
        v_height = canonical_height * size_drift

        variants.append(_build_rock_lobed_instance(
            v_width=v_width,
            v_depth=v_depth,
            v_height=v_height,
            lobe_count=lobe_count,
            spread_radius_frac=spread_radius_frac,
            flatness=flatness,
            noise_strength=noise_strength,
            elongation=elongation,
            base_color=base_color,
            shadow_color=shadow_color,
            accent_color=accent_color,
            rng=rng,
        ))

    return variants


def _family_scatter_tissue(kind_name: str, kind_cfg: dict) -> list[trimesh.Trimesh]:
    """Scatter tissue family — crossed-quad dome scatter for low-cost
    plant tissue. Used by grass_tuft, leaf_pile, twig_scatter, moss_patch.

    Each instance is a dome-profile scatter of N crossed-quad billboards,
    where each "cross" is 2-3 flat quads rotated around a shared vertical
    axis. Cheap (~40-120 tris per instance) and the crossing angles
    provide parallax when the player walks past.

    No atoms, no composed primitives. Tier 2 tissue path only.

    Recipe fields (kind_cfg["recipe"]):
      bounds           [w, d, h]   dome footprint and typical height
      variant_count    int          4 for consistency with pipeline
      variant_spread   float        size drift
      family_params    dict:
        cross_count        int     number of cross-stacks in the dome (4-14)
        cross_planes       int     quads per cross (2 or 3)
        cross_width_frac   float   quad width / bounds width
        dome_flatness      float   0..1, how much edges are shorter
        lean_jitter_deg    float   random per-cross Z-rotation
    """
    recipe = kind_cfg["recipe"]
    fp = recipe.get("family_params", {})
    bounds = recipe["bounds"]
    variant_count = int(recipe["variant_count"])
    variant_spread = float(recipe.get("variant_spread", 0.30))

    canonical_width  = float(bounds[0])
    canonical_height = float(bounds[2])

    cross_count      = int(fp.get("cross_count", 9))
    cross_planes     = int(fp.get("cross_planes", 3))
    cross_width_frac = float(fp.get("cross_width_frac", 0.08))
    dome_flatness    = float(fp.get("dome_flatness", 0.5))
    lean_jitter_deg  = float(fp.get("lean_jitter_deg", 0.0))

    base_color   = _rgb01_to_rgba_u8(kind_cfg.get("color_base",   [0.24, 0.26, 0.20]))
    shadow_color = _rgb01_to_rgba_u8(kind_cfg.get("color_shadow", [0.20, 0.22, 0.17]))
    accent_color = _rgb01_to_rgba_u8(kind_cfg.get("color_accent", [0.28, 0.30, 0.24]))

    variants = []
    for v_idx in range(variant_count):
        seed = zlib.crc32(f"{kind_name}-{v_idx}".encode()) & 0xFFFFFFFF
        rng = np.random.default_rng(seed)

        size_drift = 1.0 + variant_spread * (rng.random() * 2.0 - 1.0)
        v_width  = canonical_width  * size_drift
        v_height = canonical_height * size_drift
        footprint_r = v_width * 0.5

        parts = []
        for ci in range(cross_count):
            angle = rng.random() * 2.0 * math.pi
            dist = rng.random() * footprint_r
            cx = math.cos(angle) * dist
            cy = math.sin(angle) * dist

            # Dome profile — edges of the dome are shorter than center
            edge_t = dist / max(footprint_r, 1e-6)
            dome_scale = 1.0 - edge_t * dome_flatness
            h_local = v_height * dome_scale * (0.7 + rng.random() * 0.6)
            w_local = canonical_width * cross_width_frac * (0.8 + rng.random() * 0.4)

            rot_base = rng.random() * 2.0 * math.pi
            lean = math.radians(lean_jitter_deg) * (rng.random() - 0.5) * 2.0

            for pi in range(cross_planes):
                plane_angle = rot_base + pi * (math.pi / cross_planes)
                cos_a = math.cos(plane_angle)
                sin_a = math.sin(plane_angle)
                half_w = w_local * 0.5
                # Build a vertical quad in the plane defined by (cos_a, sin_a)
                # rotated around Z. Optionally lean the top forward by `lean`.
                lean_offset = math.sin(lean) * h_local * 0.4
                v0 = [-half_w * cos_a, -half_w * sin_a, 0.0]
                v1 = [ half_w * cos_a,  half_w * sin_a, 0.0]
                v2 = [ half_w * cos_a + lean_offset * -sin_a,
                       half_w * sin_a + lean_offset * cos_a,
                       h_local]
                v3 = [-half_w * cos_a + lean_offset * -sin_a,
                      -half_w * sin_a + lean_offset * cos_a,
                      h_local]
                verts = np.array([v0, v1, v2, v3])
                verts[:, 0] += cx
                verts[:, 1] += cy
                faces = np.array([[0, 1, 2], [0, 2, 3]])
                quad = trimesh.Trimesh(
                    vertices=verts, faces=faces, process=False
                )
                _solid_color(quad, base_color)
                parts.append(quad)

        if not parts:
            # Degenerate safety: empty tuft becomes a single 1mm dot
            tiny = trimesh.Trimesh(
                vertices=np.array([[0.0, 0.0, 0.0],
                                   [0.001, 0.0, 0.0],
                                   [0.0, 0.001, 0.0]]),
                faces=np.array([[0, 1, 2]]),
                process=False,
            )
            _solid_color(tiny, base_color)
            parts = [tiny]

        cluster = compose(parts)
        _apply_z_gradient_three_stop(cluster, shadow_color, base_color, accent_color)
        variants.append(cluster)

    return variants


def _family_flora_composed(kind_name: str, kind_cfg: dict) -> list[trimesh.Trimesh]:
    """Composed flora family — stem + cap construction for giant_fungus
    and any future organic kind that needs "body + cap" silhouette.

    Reuses _build_tapered_vertical_instance for the stem (with bulbous
    params — strong base flare, mild taper, thick mid-body) and a
    hemisphere for the cap. Atoms scatter on the cap surface for
    recognition markers.

    Recipe fields (kind_cfg["recipe"]):
      bounds           [w, d, h]   overall kind bbox
      variant_count    int
      variant_spread   float
      atoms            dict|null   cap marker spec
      family_params    dict:
        stem_height_frac   float  0..1, stem_height / total_height
        stem_radius_frac   float  0..1, stem_base_diameter / v_width
        cap_radius_frac    float  0..1, cap_diameter / v_width
        cap_height_frac    float  0..1, cap_height / stem_height
        stem_taper         float  0..1, taper of the stem body
        stem_flare         float  >1, flare ratio at stem base
        noise_strength     float  stem radial noise

    Palette: color_base/shadow/accent used for stem. cap color derived
    from color_accent brightened, unless color_cap override given.
    """
    recipe = kind_cfg["recipe"]
    fp = recipe.get("family_params", {})
    bounds = recipe["bounds"]
    variant_count = int(recipe["variant_count"])
    variant_spread = float(recipe.get("variant_spread", 0.20))

    canonical_width  = float(bounds[0])
    canonical_height = float(bounds[2])

    stem_height_frac = float(fp.get("stem_height_frac", 0.60))
    stem_radius_frac = float(fp.get("stem_radius_frac", 0.30))
    cap_radius_frac  = float(fp.get("cap_radius_frac",  0.50))
    cap_height_frac  = float(fp.get("cap_height_frac",  0.35))
    stem_taper       = float(fp.get("stem_taper",       0.20))
    stem_flare       = float(fp.get("stem_flare",       1.30))
    noise_strength   = float(fp.get("noise_strength",   0.05))

    stem_base   = _rgb01_to_rgba_u8(kind_cfg.get("color_base",   [0.22, 0.20, 0.22]))
    stem_shadow = _rgb01_to_rgba_u8(kind_cfg.get("color_shadow", [0.17, 0.16, 0.18]))
    stem_accent = _rgb01_to_rgba_u8(kind_cfg.get("color_accent", [0.26, 0.24, 0.27]))

    # Cap color: explicit override or derive from stem_accent (brighter)
    cap_override = kind_cfg.get("color_cap")
    if cap_override is not None:
        cap_color = _rgb01_to_rgba_u8(cap_override)
    else:
        r, g, b, _ = stem_accent
        cap_color = (
            min(int(round(r * 1.35)), 255),
            min(int(round(g * 1.35)), 255),
            min(int(round(b * 1.35)), 255),
            255,
        )

    atoms_cfg = recipe.get("atoms")

    variants = []
    for v_idx in range(variant_count):
        seed = zlib.crc32(f"{kind_name}-{v_idx}".encode()) & 0xFFFFFFFF
        rng = np.random.default_rng(seed)

        size_drift = 1.0 + variant_spread * (rng.random() * 2.0 - 1.0)
        v_width  = canonical_width  * size_drift
        v_height = canonical_height * size_drift

        stem_height = v_height * stem_height_frac
        stem_radius = v_width * 0.5 * stem_radius_frac
        cap_radius  = v_width * 0.5 * cap_radius_frac
        cap_h       = stem_height * cap_height_frac

        stem_rng = np.random.default_rng(seed + 1)
        stem = _build_tapered_vertical_instance(
            base_radius=stem_radius,
            height=stem_height,
            taper_strength=stem_taper,
            flare_ratio=stem_flare,
            flare_frac=0.30,
            noise_strength=noise_strength,
            facet_count=8,
            ring_count=6,
            base_color=stem_base,
            shadow_color=stem_shadow,
            accent_color=stem_accent,
            atoms_cfg=None,
            rng=stem_rng,
        )

        cap = hemisphere(
            radius=cap_radius, height=cap_h, color=cap_color,
            meridian_sections=10, parallel_rings=3,
        )
        cap.apply_translation([0.0, 0.0, stem_height])

        parts = [stem, cap]

        # Atoms on the cap surface — ring of heptagons around the dome
        if atoms_cfg:
            atom_count = int(atoms_cfg.get("count", 7))
            atom_size = float(atoms_cfg.get("size", 0.15))
            atom_pts = []
            atom_nrms = []
            for i in range(atom_count):
                theta = 2.0 * math.pi * i / atom_count
                # Place atoms on the upper dome — phi from ~30° to ~75°
                phi = math.pi * (0.18 + 0.22 * ((i % 3) / 2.0))
                nx = math.cos(theta) * math.sin(phi)
                ny = math.sin(theta) * math.sin(phi)
                nz = math.cos(phi)
                atom_pts.append([
                    nx * cap_radius * 1.02,
                    ny * cap_radius * 1.02,
                    stem_height + nz * cap_h * 1.02,
                ])
                atom_nrms.append([nx, ny, nz])
            atoms_mesh = scattered_heptagons(
                np.array(atom_pts),
                np.array(atom_nrms),
                [atom_size] * atom_count,
                _CREAM_ATOM,
            )
            parts.append(atoms_mesh)

        variants.append(compose(parts))

    return variants


def _family_crystal_spike(kind_name: str, kind_cfg: dict) -> list[trimesh.Trimesh]:
    """Crystal spike cluster family — crystal_cluster (Tier 1 anchor).

    Reuses _build_tapered_vertical_instance as the spire primitive with
    crystalline-specific parameters: sharp taper (no natural body
    tapering toward a point), no flare (crystals grow straight), low
    noise (crystalline facets are smooth), fewer facets (6 → harder
    silhouette reading). Composes a trunk-based cluster of N leaning
    main spires + M shorter satellite spires.

    Recipe fields (kind_cfg["recipe"]):
      bounds           [w, d, h]   cluster footprint
      variant_count    int
      variant_spread   float
      atoms            dict|null   atom markers per spire
      family_params    dict:
        main_spires       int     tall main spires (3 default)
        satellite_spires  int     short perimeter spires (4 default)
        spire_facets      int     6 for crystalline, 8 for smoother
        spire_rings       int     4-6 for crystals (sharp profile)
        noise_strength    float   <0.05 for crystalline smoothness
        lean_angle_deg    float   outward lean per main spire

    Palette from kind_cfg["color_base"/"color_shadow"/"color_accent"].
    """
    recipe = kind_cfg["recipe"]
    fp = recipe.get("family_params", {})
    bounds = recipe["bounds"]
    variant_count = int(recipe["variant_count"])
    variant_spread = float(recipe.get("variant_spread", 0.25))

    canonical_width  = float(bounds[0])
    canonical_height = float(bounds[2])

    main_spires     = int(fp.get("main_spires", 3))
    satellite_spires = int(fp.get("satellite_spires", 4))
    spire_facets    = int(fp.get("spire_facets", 6))
    spire_rings     = int(fp.get("spire_rings", 5))
    noise_strength  = float(fp.get("noise_strength", 0.03))
    lean_angle_deg  = float(fp.get("lean_angle_deg", 15.0))

    atoms_cfg = recipe.get("atoms")

    base_color   = _rgb01_to_rgba_u8(kind_cfg.get("color_base",   [0.30, 0.32, 0.42]))
    shadow_color = _rgb01_to_rgba_u8(kind_cfg.get("color_shadow", [0.24, 0.26, 0.34]))
    accent_color = _rgb01_to_rgba_u8(kind_cfg.get("color_accent", [0.36, 0.38, 0.48]))

    variants = []
    for v_idx in range(variant_count):
        seed = zlib.crc32(f"{kind_name}-{v_idx}".encode()) & 0xFFFFFFFF
        rng = np.random.default_rng(seed)

        size_drift = 1.0 + variant_spread * (rng.random() * 2.0 - 1.0)
        cluster_width  = canonical_width  * size_drift
        cluster_height = canonical_height * size_drift
        footprint_r    = cluster_width * 0.3   # how spread out spire bases are

        parts = []

        # Main spires — distributed ~evenly in a ring, each leaning outward
        for si in range(main_spires):
            angle = (si * (2.0 * math.pi / main_spires)
                     + (rng.random() - 0.5) * 0.5)
            spire_h = cluster_height * (0.7 + rng.random() * 0.3)
            spire_r = cluster_width * 0.12 * (0.8 + rng.random() * 0.4)
            offset_x = math.cos(angle) * footprint_r * 0.3
            offset_y = math.sin(angle) * footprint_r * 0.3

            spire_rng = np.random.default_rng(seed + 1 + si * 1000)
            spire = _build_tapered_vertical_instance(
                base_radius=spire_r,
                height=spire_h,
                taper_strength=0.92,      # very sharp tip
                flare_ratio=1.0,          # no flare
                flare_frac=0.0,
                noise_strength=noise_strength,
                facet_count=spire_facets,
                ring_count=spire_rings,
                base_color=base_color,
                shadow_color=shadow_color,
                accent_color=accent_color,
                atoms_cfg=atoms_cfg,      # cream atoms on each main spire
                rng=spire_rng,
            )

            # Lean outward: rotate around an axis perpendicular to the outward
            # direction, tilted by lean_angle_deg toward that direction.
            lean_rad = math.radians(lean_angle_deg)
            lean_axis = np.array([-math.sin(angle), math.cos(angle), 0.0])
            lean_mat = trimesh.transformations.rotation_matrix(lean_rad, lean_axis)
            spire.apply_transform(lean_mat)
            spire.apply_translation([offset_x, offset_y, 0.0])
            parts.append(spire)

        # Satellite spires — shorter, at a wider radius, no lean, no atoms
        for sati in range(satellite_spires):
            sat_angle = rng.random() * 2.0 * math.pi
            sat_dist = footprint_r * (0.8 + rng.random() * 0.5)
            sat_h = cluster_height * (0.2 + rng.random() * 0.25)
            sat_r = cluster_width * 0.06 * (0.7 + rng.random() * 0.5)

            sat_rng = np.random.default_rng(seed + 5000 + sati * 100)
            sat = _build_tapered_vertical_instance(
                base_radius=sat_r,
                height=sat_h,
                taper_strength=0.92,
                flare_ratio=1.0,
                flare_frac=0.0,
                noise_strength=noise_strength,
                facet_count=spire_facets,
                ring_count=4,
                base_color=base_color,
                shadow_color=shadow_color,
                accent_color=accent_color,
                atoms_cfg=None,        # satellites stay clean
                rng=sat_rng,
            )
            sat.apply_translation([
                math.cos(sat_angle) * sat_dist,
                math.sin(sat_angle) * sat_dist,
                0.0,
            ])
            parts.append(sat)

        variants.append(compose(parts))

    return variants


def _family_tapered_vertical(kind_name: str, kind_cfg: dict) -> list[trimesh.Trimesh]:
    """Tapered vertical family — stalagmites, columns, mega_columns,
    buttresses. A single noisy revolved profile with optional base flare,
    3-stop Z-gradient coloring, and heptagonal atom markers scattered
    along the spine.

    Recipe fields (kind_cfg["recipe"]):
      bounds           [w, d, h]   canonical bounding box before variation
      variant_count    int          how many v0..vN to emit
      variant_spread   float        ± size variation across variants
      atoms            dict|null    marker spec {pattern, count, size, palette}
      family_params    dict         kind-specific tuning:
        taper_strength  (0..1)      0 = cylinder, 1 = sharp point
        flare_ratio     (>1)        how much wider the base is vs body
        flare_frac      (0..1)      vertical fraction affected by flare
        noise_strength  (0..)       radial noise per ring
        facet_count     int         revolved side count (6-12 recommended)
        ring_count      int         profile segment count (4-10 recommended)

    Palette read from kind_cfg["color_base"/"color_shadow"/"color_accent"].
    """
    recipe = kind_cfg["recipe"]
    fp = recipe.get("family_params", {})
    bounds = recipe["bounds"]
    variant_count = int(recipe["variant_count"])
    variant_spread = float(recipe.get("variant_spread", 0.25))

    canonical_width = float(bounds[0])
    canonical_height = float(bounds[2])

    taper_strength = float(fp.get("taper_strength", 0.75))
    flare_ratio    = float(fp.get("flare_ratio", 1.4))
    flare_frac     = float(fp.get("flare_frac", 0.25))
    noise_strength = float(fp.get("noise_strength", 0.08))
    facet_count    = int(fp.get("facet_count", 8))
    ring_count     = int(fp.get("ring_count", 6))

    base_rgb01   = kind_cfg.get("color_base",   [0.30, 0.27, 0.23])
    shadow_rgb01 = kind_cfg.get("color_shadow", [0.26, 0.23, 0.19])
    accent_rgb01 = kind_cfg.get("color_accent", [0.34, 0.30, 0.25])
    base_color   = _rgb01_to_rgba_u8(base_rgb01)
    shadow_color = _rgb01_to_rgba_u8(shadow_rgb01)
    accent_color = _rgb01_to_rgba_u8(accent_rgb01)

    atoms_cfg = recipe.get("atoms")

    variants = []
    for v_idx in range(variant_count):
        # Deterministic per-variant rng — crc32 is stable across processes,
        # Python's built-in hash() is randomized per-run and would produce
        # different GLBs each make meshes.
        seed = (zlib.crc32(f"{kind_name}-{v_idx}".encode()) & 0xFFFFFFFF)
        rng = np.random.default_rng(seed)

        # Per-variant size drift
        size_drift = 1.0 + variant_spread * (rng.random() * 2.0 - 1.0)
        v_radius = (canonical_width * 0.5) * size_drift
        v_height = canonical_height * size_drift

        # Slight per-variant family param jitter for silhouette variety
        v_taper = np.clip(taper_strength * (0.9 + rng.random() * 0.2), 0.0, 1.0)
        v_flare = flare_ratio * (0.9 + rng.random() * 0.2)

        variants.append(_build_tapered_vertical_instance(
            base_radius=v_radius,
            height=v_height,
            taper_strength=v_taper,
            flare_ratio=v_flare,
            flare_frac=flare_frac,
            noise_strength=noise_strength,
            facet_count=facet_count,
            ring_count=ring_count,
            base_color=base_color,
            shadow_color=shadow_color,
            accent_color=accent_color,
            atoms_cfg=atoms_cfg,
            rng=rng,
        ))

    return variants


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
# Registry + Dispatcher + CLI
# -----------------------------------------------------------------------------
#
# Two authoring paths, resolved at dispatch time:
#
#   1. LEGACY_BUILDERS — hand-authored, per-kind functions. The 5 compliant
#      kinds (toadstool, spore_pod, doorframe, monolith, boulder) live here.
#      They take NO arguments; their params are baked into the function body.
#      Byte-identical GLB output across sessions as long as this file and
#      the primitive helpers above are unchanged.
#
#   2. FAMILY_BUILDERS — parameterized family primitives added by the
#      clean-room normalization sweep. Each family builder takes
#      `(kind_name, recipe)` where `recipe` is the per-kind recipe block
#      from godot/kind_config.json. Family builders read bounds, variants,
#      palette, atoms, and family_params from the recipe and produce
#      variants deterministically.
#
# Dispatch rule: if a kind name is in LEGACY_BUILDERS, it routes there
# regardless of what kind_config says. Otherwise the dispatcher reads
# kind_config.kinds[name].recipe.family and calls the matching family
# builder. This is the "backwards-compatible" half of the Option 3 refined
# sweep: proven kinds never touch the new codepath.


LEGACY_BUILDERS = {
    "toadstool": toadstool_variants,
    "spore_pod": spore_pod_variants,
    "doorframe": doorframe_variants,
    "monolith":  monolith_variants,
    "boulder":   boulder_variants,
}

# Populated in Steps 4–8 of the clean-room normalization sweep.
# Each family builder has signature: (kind_name: str, kind_cfg: dict) -> list[trimesh.Trimesh]
# where kind_cfg is the per-kind dict from kind_config.json (palette + recipe block).
FAMILY_BUILDERS: dict[str, callable] = {
    "tapered_vertical": _family_tapered_vertical,
    "rock_lobed":       _family_rock_lobed,
    "crystal_spike":    _family_crystal_spike,
    "flora_composed":   _family_flora_composed,
    "scatter_tissue":   _family_scatter_tissue,
}


# Lightweight cached loader — kind_config.json is the master table the
# dispatcher reads from. Godot also reads this file, so it remains the
# single source of truth.
_KIND_CONFIG_CACHE: dict | None = None
_KIND_CONFIG_PATH = Path(__file__).resolve().parent.parent / "godot" / "kind_config.json"


def _load_kind_config() -> dict:
    global _KIND_CONFIG_CACHE
    if _KIND_CONFIG_CACHE is None:
        _KIND_CONFIG_CACHE = json.loads(_KIND_CONFIG_PATH.read_text())
    return _KIND_CONFIG_CACHE


def build_kind(kind_name: str) -> list[trimesh.Trimesh]:
    """Resolve a kind name to its variant mesh list.

    Legacy kinds take precedence — they route through LEGACY_BUILDERS
    unchanged and produce byte-identical output to the pre-sweep baseline.
    Non-legacy kinds are dispatched via their recipe.family field in
    kind_config.json.
    """
    if kind_name in LEGACY_BUILDERS:
        return LEGACY_BUILDERS[kind_name]()

    config = _load_kind_config()
    kind_cfg = config.get("kinds", {}).get(kind_name)
    if kind_cfg is None:
        raise SystemExit(
            f"Unknown kind '{kind_name}' — not in LEGACY_BUILDERS and "
            f"no entry in kind_config.json")
    recipe = kind_cfg.get("recipe")
    if recipe is None:
        raise SystemExit(
            f"Kind '{kind_name}' has no recipe block in kind_config.json "
            f"— cannot dispatch via family builder")
    family = recipe.get("family")
    if family not in FAMILY_BUILDERS:
        raise SystemExit(
            f"Kind '{kind_name}' has family '{family}' but no builder is "
            f"registered. Known families: {sorted(FAMILY_BUILDERS)}")
    return FAMILY_BUILDERS[family](kind_name, kind_cfg)


def _all_known_kinds() -> list[str]:
    """Every kind the dispatcher can build: LEGACY_BUILDERS ∪ config-declared
    kinds whose family is in FAMILY_BUILDERS."""
    known = set(LEGACY_BUILDERS.keys())
    config = _load_kind_config()
    for name, cfg in config.get("kinds", {}).items():
        recipe = cfg.get("recipe")
        if recipe is None:
            continue
        family = recipe.get("family")
        if family in FAMILY_BUILDERS:
            known.add(name)
    return sorted(known)


def generate_kind(kind_name: str) -> None:
    print(f"Generating {kind_name}...")
    variants = build_kind(kind_name)
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
        targets = _all_known_kinds()
    else:
        targets = args.kinds

    for kind in targets:
        generate_kind(kind)


if __name__ == "__main__":
    main()
