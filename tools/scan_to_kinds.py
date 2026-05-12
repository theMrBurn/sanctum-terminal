"""scan_to_kinds — turn an image-scan CSV into vector-renderable composite entities.

V2 — composite emit. Each scan row now produces 3 entities at the same
grid cell, stacked vertically:

    Z=top    secondary primitive   in color_accent
    Z=mid    primary primitive     in color_base
    Z=floor  ground_hug "shadow"   in color_shadow

The 3-primitive composition is what makes the kind-engine actually
*blend* an image — primary feature + secondary feature + grounded
shadow, each in its own derived color. V1 was a single primitive
in a single color (router-shape, not blender-shape).

CSV columns (V2):
    filename, primary_shape, secondary_shape,
    color_base, color_shadow, color_accent,
    register_hint

Output: ~/Desktop/reference_art/scan_2026-05-11/entities.json (or
the path passed as second arg).

Run:
    python3 tools/scan_to_kinds.py \\
        ~/Desktop/reference_art/scan_2026-05-11/scan_v2.csv

Bridge test for `design_render_reuse_mandate`: does the existing
primitive set, composed in 3-layer stacks, produce visibly-distinct
cells per source image?
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


DEFAULT_OUT = (
    Path.home() / "Desktop" / "reference_art" / "scan_2026-05-11" / "entities.json"
)

GRID_COLS = 5
SPACING   = 5.0
GRID_BASE = (0.0, 8.0, 0.0)         # in front of the player

# Per-shape scale hints — used by both primary and secondary slots. The
# secondary primitive scales slightly smaller so it reads as a cap/feature
# perched on the primary base.
_SCALE_HINT: dict[str, tuple[float, float, float]] = {
    "orb":              (2.0, 2.0, 2.0),
    "tapered_vertical": (1.2, 1.2, 4.0),
    "banner":           (4.0, 0.2, 2.8),
    "heptagonal_mote":  (2.0, 2.0, 2.0),
    "silhouette_void":  (2.8, 2.8, 4.4),
    "lattice_7":        (4.0, 4.0, 1.2),
    "scatter_7":        (4.4, 4.4, 1.0),
    "chain":            (0.6, 0.6, 5.0),
    "ground_hug":       (4.0, 4.0, 0.6),
    "vector_sprite":    (2.4, 0.2, 3.6),
}

# How much vertical headroom each primary shape needs before the
# secondary stacks above it. Roughly matches the shape's z-extent.
_PRIMARY_HEIGHT: dict[str, float] = {
    "orb":              2.5,
    "tapered_vertical": 4.5,
    "banner":           3.0,
    "heptagonal_mote":  2.0,
    "silhouette_void":  4.5,
    "lattice_7":        1.5,
    "scatter_7":        1.5,
    "chain":            5.0,
    "ground_hug":       1.0,
    "vector_sprite":    3.8,
}

# Secondary scales smaller by this factor so it reads as a cap/feature.
_SECONDARY_SCALE_FACTOR = 0.6

# Shadow disc at the base — always ground_hug, slightly larger than the
# primary footprint so it reads as a real shadow/footprint.
_SHADOW_SCALE = (4.5, 0.15, 4.5)

ENTITY_ID_BASE = 10_000


def hex_to_rgb01(h: str) -> tuple[float, float, float]:
    """#rrggbb → (r, g, b) ∈ [0, 1]^3."""
    s = h.strip().lstrip("#")
    if len(s) != 6:
        return (0.6, 0.6, 0.6)
    try:
        r = int(s[0:2], 16) / 255.0
        g = int(s[2:4], 16) / 255.0
        b = int(s[4:6], 16) / 255.0
        return (r, g, b)
    except ValueError:
        return (0.6, 0.6, 0.6)


def csv_to_entities(csv_path: Path) -> list[dict]:
    """Read a V2 scan CSV and return a list of composite entity dicts.

    Each scan row emits 3 entities (shadow / primary / secondary)
    sharing the same xy grid cell but stacked in z.
    """
    entities: list[dict] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            primary   = (row.get("primary_shape")   or "orb").strip()
            secondary = (row.get("secondary_shape") or primary).strip()
            c_base    = (row.get("color_base")      or "#888888").strip()
            c_shadow  = (row.get("color_shadow")    or "#1a1a1a").strip()
            c_accent  = (row.get("color_accent")    or c_base).strip()
            register  = (row.get("register_hint")   or "unknown").strip()
            filename  = (row.get("filename")        or f"row_{idx}").strip()

            col = idx % GRID_COLS
            row_idx = idx // GRID_COLS
            gx = GRID_BASE[0] + (col - (GRID_COLS - 1) / 2.0) * SPACING
            gy = GRID_BASE[1] + row_idx * SPACING

            # Primary at base — sits on the floor (its scale_z/2 lifts the
            # center off ground).
            prim_scale = _SCALE_HINT.get(primary, (1.0, 1.0, 1.0))
            prim_z = prim_scale[2] / 2.0
            r_b, g_b, b_b = hex_to_rgb01(c_base)

            # Secondary stacked on top — small cap. Height = primary's
            # top + half of secondary's scale_z.
            sec_scale_full = _SCALE_HINT.get(secondary, (1.0, 1.0, 1.0))
            sec_scale = tuple(s * _SECONDARY_SCALE_FACTOR for s in sec_scale_full)
            primary_top = _PRIMARY_HEIGHT.get(primary, prim_scale[2])
            sec_z = primary_top + sec_scale[2] / 2.0
            r_a, g_a, b_a = hex_to_rgb01(c_accent)

            # Shadow disc at the floor — always ground_hug, tinted with
            # color_shadow. Lifts ~0.1m so it doesn't z-fight with the grid.
            r_s, g_s, b_s = hex_to_rgb01(c_shadow)

            shared = {
                "_register": register,
                "_source":   filename,
                "_cell":     idx,
            }

            # 1) Shadow / footprint
            entities.append({
                "id":   ENTITY_ID_BASE + idx * 3 + 0,
                "kind": f"scan_ground_hug_{idx:02d}",
                "x": round(gx, 2), "y": round(gy, 2), "z": 0.10,
                "sx": _SHADOW_SCALE[0], "sy": _SHADOW_SCALE[1], "sz": _SHADOW_SCALE[2],
                "r": round(r_s, 3), "g": round(g_s, 3), "b": round(b_s, 3),
                "_slot": "shadow",
                **shared,
            })
            # 2) Primary
            entities.append({
                "id":   ENTITY_ID_BASE + idx * 3 + 1,
                "kind": f"scan_{primary}_{idx:02d}",
                "x": round(gx, 2), "y": round(gy, 2), "z": round(prim_z, 2),
                "sx": prim_scale[0], "sy": prim_scale[1], "sz": prim_scale[2],
                "r": round(r_b, 3), "g": round(g_b, 3), "b": round(b_b, 3),
                "_slot": "primary",
                **shared,
            })
            # 3) Secondary stacked
            entities.append({
                "id":   ENTITY_ID_BASE + idx * 3 + 2,
                "kind": f"scan_{secondary}_{idx:02d}",
                "x": round(gx, 2), "y": round(gy, 2), "z": round(sec_z, 2),
                "sx": sec_scale[0], "sy": sec_scale[1], "sz": sec_scale[2],
                "r": round(r_a, 3), "g": round(g_a, 3), "b": round(b_a, 3),
                "_slot": "secondary",
                **shared,
            })
    return entities


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: scan_to_kinds.py <csv_path> [<out_json>]")
        return 2
    csv_path = Path(argv[1]).expanduser()
    out_path = Path(argv[2]).expanduser() if len(argv) > 2 else DEFAULT_OUT
    if not csv_path.exists():
        print(f"error: csv not found: {csv_path}")
        return 1
    entities = csv_to_entities(csv_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(entities, indent=2))
    cells = len({e["_cell"] for e in entities})
    print(f"wrote {len(entities)} entities ({cells} composite cells) → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
