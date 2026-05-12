"""scan_events_to_entities — image_scan JSONL → workroom entities.

Reads a stream of `image.scanned` events (one JSON line each) and
emits the 3-primitive composite entity list that brain_server reads
from SANCTUM_SCAN_GALLERY.

Same wire-format as the hand-classified bridge so the consumer side
(brain manifest + recipes.py) needs no changes — only the source
of classification has shifted from "me reading images" to "code
reading pixels."
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path


# Grid placement
GRID_COLS = 16                  # 422 imgs / 16 cols ≈ 27 rows
SPACING   = 5.0
GRID_BASE = (0.0, 8.0, 0.0)

_SCALE_HINT = {
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

_PRIMARY_HEIGHT = {
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

_SECONDARY_SCALE_FACTOR = 0.6
_SHADOW_SCALE = (4.5, 0.15, 4.5)
ENTITY_ID_BASE = 10_000


def hex_to_rgb01(h: str) -> tuple[float, float, float]:
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


def event_to_entities(idx: int, payload: dict) -> list[dict]:
    primary   = payload.get("primary_shape", "orb")
    secondary = payload.get("secondary_shape", "orb")
    colors    = payload.get("colors", ["#888888", "#1a1a1a", "#888888"])
    c_base    = colors[0] if len(colors) > 0 else "#888888"
    c_shadow  = colors[1] if len(colors) > 1 else "#1a1a1a"
    c_accent  = colors[2] if len(colors) > 2 else c_base
    register  = payload.get("register", "unknown")
    filename  = payload.get("path", "").split("/")[-1] or f"row_{idx}"

    col     = idx % GRID_COLS
    row_idx = idx // GRID_COLS
    gx = GRID_BASE[0] + (col - (GRID_COLS - 1) / 2.0) * SPACING
    gy = GRID_BASE[1] + row_idx * SPACING

    prim_scale = _SCALE_HINT.get(primary, (1.0, 1.0, 1.0))
    prim_z = prim_scale[2] / 2.0
    sec_scale_full = _SCALE_HINT.get(secondary, (1.0, 1.0, 1.0))
    sec_scale = tuple(s * _SECONDARY_SCALE_FACTOR for s in sec_scale_full)
    primary_top = _PRIMARY_HEIGHT.get(primary, prim_scale[2])
    sec_z = primary_top + sec_scale[2] / 2.0

    r_b, g_b, b_b = hex_to_rgb01(c_base)
    r_s, g_s, b_s = hex_to_rgb01(c_shadow)
    r_a, g_a, b_a = hex_to_rgb01(c_accent)

    shared = {
        "_register": register,
        "_source":   filename,
        "_cell":     idx,
    }

    return [
        {
            "id":   ENTITY_ID_BASE + idx * 3 + 0,
            "kind": f"scan_ground_hug_{idx:02d}",
            "x": round(gx, 2), "y": round(gy, 2), "z": 0.10,
            "sx": _SHADOW_SCALE[0], "sy": _SHADOW_SCALE[1], "sz": _SHADOW_SCALE[2],
            "r": round(r_s, 3), "g": round(g_s, 3), "b": round(b_s, 3),
            "_slot": "shadow",
            **shared,
        },
        {
            "id":   ENTITY_ID_BASE + idx * 3 + 1,
            "kind": f"scan_{primary}_{idx:02d}",
            "x": round(gx, 2), "y": round(gy, 2), "z": round(prim_z, 2),
            "sx": prim_scale[0], "sy": prim_scale[1], "sz": prim_scale[2],
            "r": round(r_b, 3), "g": round(g_b, 3), "b": round(b_b, 3),
            "_slot": "primary",
            **shared,
        },
        {
            "id":   ENTITY_ID_BASE + idx * 3 + 2,
            "kind": f"scan_{secondary}_{idx:02d}",
            "x": round(gx, 2), "y": round(gy, 2), "z": round(sec_z, 2),
            "sx": sec_scale[0], "sy": sec_scale[1], "sz": sec_scale[2],
            "r": round(r_a, 3), "g": round(g_a, 3), "b": round(b_a, 3),
            "_slot": "secondary",
            **shared,
        },
    ]


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: scan_events_to_entities.py <events.jsonl> <out.json>")
        return 2
    in_path  = Path(argv[1]).expanduser()
    out_path = Path(argv[2]).expanduser()
    entities: list[dict] = []
    with in_path.open() as f:
        for line in f:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("kind") != "image.scanned":
                continue
            payload = ev.get("payload", {})
            entities.extend(event_to_entities(len(entities) // 3, payload))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(entities, indent=2))
    print(f"wrote {len(entities)} entities ({len(entities) // 3} cells) → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
