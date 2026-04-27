#!/usr/bin/env python3
"""sketch_to_sprite.py — Freeform / Procreate sketch → game-ready sprite.

Reads a raster export (PNG from Freeform on iPad, Procreate, Aseprite, etc.),
detects drawn content via brightness threshold (anything darker than near-white
counts as ink), color-keys the white background to transparent, auto-crops to
the bounding box of drawn content, pads with a transparent border, optionally
downscales, and saves a clean RGBA PNG.

The output drops onto a billboard subpart in Godot via the flame/sprite
primitive's `sprite` field — see kind_config_schema. No Aseprite or Asset
Forge authoring required: sketch on iPad, export to Desktop, run this.

Usage:
    python3 tools/sketch_to_sprite.py <input.png> <output.png>
        [--threshold 240]  # background brightness cutoff (0-255)
        [--pad 8]          # transparent border padding in px
        [--max-size 256]   # downscale longer edge to this if larger

Example:
    python3 tools/sketch_to_sprite.py \\
        ~/Desktop/flame_sketch.png \\
        godot/lib/sprites/flame/flame_user_01.png

Doctrine: design_render_reuse_mandate ('vector composite skin' over
primitives) + user_sprite_pipeline (sprites land in /lib).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def extract_sprite(
    input_path: Path,
    output_path: Path,
    threshold: int = 240,
    pad: int = 8,
    max_size: int = 256,
) -> None:
    img = Image.open(input_path).convert("RGBA")
    pixels = img.load()
    w, h = img.size

    # Bounding box of non-near-white, non-transparent pixels. A pixel counts
    # as "drawn" if any RGB channel is below threshold (i.e. it's been
    # marked, not just empty page color).
    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a > 0 and (r < threshold or g < threshold or b < threshold):
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y

    if max_x < 0:
        raise SystemExit(f"sketch_to_sprite: no drawn content in {input_path}")

    # Crop to drawn bounding box + transparent padding.
    x0 = max(0, min_x - pad)
    y0 = max(0, min_y - pad)
    x1 = min(w, max_x + 1 + pad)
    y1 = min(h, max_y + 1 + pad)
    img = img.crop((x0, y0, x1, y1))

    # Color-key near-white pixels to alpha 0. Drawn pixels keep their color
    # and full opacity; the page background becomes a clean transparent edge.
    pixels = img.load()
    cw, ch = img.size
    for y in range(ch):
        for x in range(cw):
            r, g, b, a = pixels[x, y]
            if r >= threshold and g >= threshold and b >= threshold:
                pixels[x, y] = (r, g, b, 0)

    # Downscale large sketches so a single Freeform full-page export
    # doesn't ship as a 4096px texture. Edge longer than max_size only.
    if max(cw, ch) > max_size:
        ratio = max_size / max(cw, ch)
        new_size = (max(1, int(cw * ratio)), max(1, int(ch * ratio)))
        img = img.resize(new_size, Image.LANCZOS)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    final_w, final_h = img.size
    print(f"sketch_to_sprite: wrote {final_w}x{final_h} -> {output_path}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", type=Path, help="Source PNG (Freeform / Procreate / etc.)")
    p.add_argument("output", type=Path, help="Destination PNG (alpha sprite)")
    p.add_argument(
        "--threshold",
        type=int,
        default=240,
        help="Background brightness cutoff 0-255 (default 240)",
    )
    p.add_argument("--pad", type=int, default=8, help="Transparent padding in px (default 8)")
    p.add_argument(
        "--max-size", type=int, default=256, help="Max edge size in px (default 256)"
    )
    args = p.parse_args()
    extract_sprite(args.input, args.output, args.threshold, args.pad, args.max_size)


if __name__ == "__main__":
    main()
