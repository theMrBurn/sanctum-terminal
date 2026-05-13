"""library_to_entities — image_scan library → brain entity manifest.

Reads every geometry kind from the library, expands each into N
positioned subpart entities, and writes them out as a JSON list the
brain reads via SANCTUM_SCAN_GALLERY. Each kind lands as a column
in a grid; subparts stack at their symbolic positions.

Standalone test path:
    python3 tools/library_to_entities.py
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


# ── Position vocabulary — mirrors image_scan.config.REGION_BBOX ─
# Symbolic position → (x, y, z) offset in unit-cube local space.
# (Matches the [positions] block in image_scan.toml.)
_POSITIONS: dict[str, tuple[float, float, float]] = {
    "center":             (0.0,  0.0,  0.0),
    "center_vertical":    (0.0,  0.0,  0.0),
    "center_horizontal":  (0.0,  0.0,  0.0),
    "upper_third":        (0.0,  0.0,  0.33),
    "lower_third":        (0.0,  0.0, -0.33),
    "on_top":             (0.0,  0.0,  0.55),
    "radiating_lower":    (0.0,  0.0, -0.25),
    "flanking_left":      (-0.30, 0.0, 0.0),
    "flanking_right":     (0.30,  0.0, 0.0),
    "flanking_upper":     (0.0,  0.0,  0.30),
    "flanking_lower":     (0.0,  0.0, -0.30),
    "upper_center":       (0.0,  0.0,  0.40),
    "lower_center":       (0.0,  0.0, -0.40),
}


# Per-primitive default scale (matches scan_to_kinds.py shape hints).
_PRIMITIVE_SCALE: dict[str, tuple[float, float, float]] = {
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
    "cube":             (1.5, 1.5, 1.5),
    "octahedron":       (1.5, 1.5, 1.5),
}


# Grid placement
GRID_COLS = 5
COL_SPACING = 8.0          # m between adjacent kind columns
ROW_SPACING = 8.0          # m between rows in the grid
GRID_BASE_FORWARD = 10.0   # m from spawn

# Composition local-space → world scale multiplier. The library
# positions are in unit-cube space (-0.5..0.5); we multiply by this
# to spread the composition over a reasonable area.
COMPOSITION_RADIUS = 3.0

ENTITY_ID_BASE = 30_000    # avoid collision with hand-authored scan_gallery ids


def _library_root() -> Path:
    import os
    raw = os.environ.get("SANCTUM_OS_HOME", "").strip()
    if raw:
        return Path(raw).expanduser() / "image_scan" / "library"
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg else (Path.home() / ".local" / "share")
    return base / "sanctum-os" / "image_scan" / "library"


def kind_to_entities(
    kind_idx: int,
    geometry: dict,
    palette: list[str] | None = None,
) -> list[dict]:
    """Expand one library geometry kind into N positioned entities."""
    col = kind_idx % GRID_COLS
    row = kind_idx // GRID_COLS
    gx = (col - (GRID_COLS - 1) / 2.0) * COL_SPACING
    gy = GRID_BASE_FORWARD + row * ROW_SPACING

    # Color cycle from palette, or fall back to amber.
    colors = palette or ["#dca54a", "#a8702c", "#5e4220"]

    entities: list[dict] = []
    subparts = geometry.get("subparts", [])
    kind_name = geometry.get("name", f"kind_{kind_idx}")

    for sp_idx, sp in enumerate(subparts):
        primitive = sp.get("primitive", "cube")
        position  = sp.get("position", "center")
        scale     = float(sp.get("scale", 1.0))

        offset = _POSITIONS.get(position, (0.0, 0.0, 0.0))
        ox = offset[0] * COMPOSITION_RADIUS
        oy = offset[1] * COMPOSITION_RADIUS
        oz = offset[2] * COMPOSITION_RADIUS

        base_scale = _PRIMITIVE_SCALE.get(primitive, (1.0, 1.0, 1.0))
        sx = base_scale[0] * scale
        sy = base_scale[1] * scale
        sz = base_scale[2] * scale

        # z = composition_z + half of vertical scale (sit on floor)
        sub_z = oz + sz / 2.0 + 0.5

        color_hex = colors[sp_idx % len(colors)]
        r, g, b = _hex_to_rgb01(color_hex)

        entities.append({
            "id":   ENTITY_ID_BASE + kind_idx * 100 + sp_idx,
            # Use the existing scan_<primitive>_<idx> naming so vector
            # terminal's recipes.py routes correctly.
            "kind": f"scan_{primitive}_{kind_idx:02d}",
            "x":    round(gx + ox, 2),
            "y":    round(gy + oy, 2),
            "z":    round(sub_z, 2),
            "sx":   sx, "sy": sy, "sz": sz,
            "r":    round(r, 3), "g": round(g, 3), "b": round(b, 3),
            "_kind_name":  kind_name,
            "_role":       sp.get("role"),
            "_tier":       sp.get("tier"),
            "_cell":       kind_idx,
        })

    return entities


def _hex_to_rgb01(h: str) -> tuple[float, float, float]:
    s = h.strip().lstrip("#")
    if len(s) != 6:
        return (0.6, 0.6, 0.6)
    try:
        return (
            int(s[0:2], 16) / 255.0,
            int(s[2:4], 16) / 255.0,
            int(s[4:6], 16) / 255.0,
        )
    except ValueError:
        return (0.6, 0.6, 0.6)


def build_entities() -> list[dict]:
    """Walk library/geometry/, return all entities for every kind."""
    root = _library_root()
    geo_dir = root / "geometry"
    ramps_dir = root / "ramps"
    if not geo_dir.exists():
        return []

    entities: list[dict] = []
    for kind_idx, geo_file in enumerate(sorted(geo_dir.iterdir())):
        if geo_file.suffix != ".json":
            continue
        geo = json.loads(geo_file.read_text())
        # Optional: load the first available ramp for color palette
        palette = None
        kind_name = geo.get("name", "")
        ramp_candidates = list(ramps_dir.glob(f"{kind_name}*.json")) if ramps_dir.exists() else []
        if ramp_candidates:
            try:
                rd = json.loads(ramp_candidates[0].read_text())
                palette = rd.get("colors")
            except Exception:                                # noqa: BLE001
                palette = None
        entities.extend(kind_to_entities(kind_idx, geo, palette=palette))

    return entities


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="library_to_entities")
    parser.add_argument(
        "--out",
        default=str(Path.home() / "Desktop" / "reference_art" /
                    "scan_2026-05-13" / "library_entities.json"),
        help="Output path for the entities.json")
    args = parser.parse_args(argv)
    entities = build_entities()
    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(entities, indent=2))
    cells = len({e.get("_cell") for e in entities})
    print(f"wrote {len(entities)} entities ({cells} composed kinds) → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
