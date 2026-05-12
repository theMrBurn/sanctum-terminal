"""scan_to_kinds — turn an image-scan CSV into a vector-renderable entity grid.

Reads a CSV with columns:
    filename, dominant_shape, palette_anchor, register_hint

Emits a JSON list of entity dicts that the brain can splat into a
manifest. Each row maps to:
    - kind: f"scan_{dominant_shape}_{idx:02d}"  (vector terminal recipes.py
            picks the right wireframe from the `scan_*` prefix)
    - position: row × col on a flat 5-wide grid in the workroom-like
                pattern, spaced 3m apart
    - color (r/g/b 0-1): decoded from palette_anchor hex
    - sx/sy/sz: 1.0 default; lattice_7/scatter_7 get sx≈sz≈2.0 to show
                their spread

Output: writes to ~/Desktop/reference_art/scan_2026-05-11/entities.json
(or a path passed as second arg).

Run:
    python3 tools/scan_to_kinds.py \
        ~/Desktop/reference_art/scan_2026-05-11/scan.csv

This is the bridge test for `design_render_reuse_mandate`: given a
diverse-but-classified image dataset, can the existing primitive set
compose something recognizable on the receiving side? Pass = "yes".
Fail = the primitive set is too narrow OR the classification is too
crude.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


DEFAULT_OUT = (
    Path.home() / "Desktop" / "reference_art" / "scan_2026-05-11" / "entities.json"
)

# Grid spacing in world meters
GRID_COLS = 5
SPACING   = 3.0
GRID_BASE = (0.0, 6.0, 0.0)         # in front of the player

# Per-shape extra-scale hint so spread-out shapes read at a glance.
_SCALE_HINT: dict[str, tuple[float, float, float]] = {
    "orb":              (1.0, 1.0, 1.0),
    "tapered_vertical": (0.6, 0.6, 2.0),
    "banner":           (2.0, 0.2, 1.4),
    "heptagonal_mote":  (1.0, 1.0, 1.0),
    "silhouette_void":  (1.4, 1.4, 2.2),
    "lattice_7":        (2.0, 2.0, 0.6),
    "scatter_7":        (2.2, 2.2, 0.5),
    "chain":            (0.3, 0.3, 2.5),
    "ground_hug":       (2.0, 2.0, 0.3),
    "vector_sprite":    (1.2, 0.2, 1.8),     # billboardish flat sprite-block
}


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
    """Read a scan CSV and return a list of entity dicts."""
    entities: list[dict] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            shape    = (row.get("dominant_shape") or "orb").strip()
            palette  = (row.get("palette_anchor") or "#888888").strip()
            register = (row.get("register_hint") or "unknown").strip()
            filename = (row.get("filename") or f"row_{idx}").strip()

            col = idx % GRID_COLS
            row_idx = idx // GRID_COLS
            x = GRID_BASE[0] + (col - (GRID_COLS - 1) / 2.0) * SPACING
            y = GRID_BASE[1] + row_idx * SPACING
            z = GRID_BASE[2] + 1.0       # waist height — readable from spawn

            r, g, b = hex_to_rgb01(palette)
            sx, sy, sz = _SCALE_HINT.get(shape, (1.0, 1.0, 1.0))

            entities.append({
                "id":       10_000 + idx,        # high range so we don't collide
                "kind":     f"scan_{shape}_{idx:02d}",
                "x":        round(x, 2),
                "y":        round(y, 2),
                "z":        round(z, 2),
                "sx":       sx,
                "sy":       sy,
                "sz":       sz,
                "r":        round(r, 3),
                "g":        round(g, 3),
                "b":        round(b, 3),
                "_register": register,           # underscore = brain-side hint, not rendered
                "_source":   filename,
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
    print(f"wrote {len(entities)} entities → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
