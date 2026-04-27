"""Tests for tools/sketch_to_sprite.py — Freeform/Procreate → game sprite.

Synthesizes test images via PIL, runs extraction, verifies cropping +
alpha-keying + downscaling. Protects the authoring tool that turns user
sketches into game-ready sprites without manual editing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from sketch_to_sprite import extract_sprite  # noqa: E402


def _make_sketch(
    path: Path, w: int, h: int, drawn_box: tuple, fill=(120, 50, 30),
    bg="white",
) -> None:
    """Write an image to `path`: bg color, with `drawn_box` painted in `fill`."""
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    d.rectangle(drawn_box, fill=fill)
    img.save(path)


def test_extract_crops_to_drawn_content_with_padding(tmp_path):
    src = tmp_path / "sketch.png"
    out = tmp_path / "sprite.png"
    # 200x200 white canvas, 30x50 drawn rect at (100,100)-(130,150).
    _make_sketch(src, 200, 200, (100, 100, 130, 150))
    extract_sprite(src, out, threshold=240, pad=8, max_size=256)

    result = Image.open(out)
    # Drawn region 31x51 (rectangle inclusive) + 8px pad each side.
    assert 40 <= result.size[0] <= 50  # ~31 + 16 padding
    assert 60 <= result.size[1] <= 70  # ~51 + 16 padding
    assert result.mode == "RGBA"


def test_extract_color_keys_white_to_alpha_zero(tmp_path):
    src = tmp_path / "sketch.png"
    out = tmp_path / "sprite.png"
    _make_sketch(src, 100, 100, (40, 40, 60, 60), fill=(120, 50, 30))
    extract_sprite(src, out)

    result = Image.open(out).convert("RGBA")
    # Center of drawn region should be fully opaque.
    cx, cy = result.size[0] // 2, result.size[1] // 2
    px = result.getpixel((cx, cy))
    assert px[3] == 255, f"expected opaque center pixel, got {px}"
    # Corner is in the padded transparent region.
    corner = result.getpixel((0, 0))
    assert corner[3] == 0, f"expected transparent corner pixel, got {corner}"


def test_extract_preserves_drawn_color(tmp_path):
    src = tmp_path / "sketch.png"
    out = tmp_path / "sprite.png"
    drawn_color = (200, 100, 30)
    _make_sketch(src, 100, 100, (40, 40, 60, 60), fill=drawn_color)
    extract_sprite(src, out)

    result = Image.open(out).convert("RGBA")
    cx, cy = result.size[0] // 2, result.size[1] // 2
    r, g, b, _a = result.getpixel((cx, cy))
    assert (r, g, b) == drawn_color


def test_extract_downscales_large_input(tmp_path):
    src = tmp_path / "sketch.png"
    out = tmp_path / "sprite.png"
    _make_sketch(src, 1000, 1000, (100, 100, 800, 800))
    extract_sprite(src, out, max_size=256)

    result = Image.open(out)
    assert max(result.size) <= 256, f"expected ≤256 max edge, got {result.size}"


def test_extract_does_not_upscale_small_input(tmp_path):
    src = tmp_path / "sketch.png"
    out = tmp_path / "sprite.png"
    _make_sketch(src, 50, 60, (10, 15, 30, 40))
    extract_sprite(src, out, max_size=256)

    result = Image.open(out)
    assert max(result.size) < 256


def test_extract_raises_on_blank_input(tmp_path):
    src = tmp_path / "blank.png"
    out = tmp_path / "sprite.png"
    Image.new("RGB", (100, 100), "white").save(src)

    with pytest.raises(SystemExit, match="no drawn content"):
        extract_sprite(src, out)


def test_threshold_lowering_handles_off_white_background(tmp_path):
    """Freeform exports may have light grid tints — adjustable threshold
    lets the user dial in the cutoff per source."""
    src = tmp_path / "sketch.png"
    out_strict = tmp_path / "strict.png"
    out_loose = tmp_path / "loose.png"

    img = Image.new("RGB", (100, 100), (230, 230, 230))  # off-white grid
    d = ImageDraw.Draw(img)
    d.rectangle((40, 40, 60, 60), fill=(50, 50, 50))  # dark draw
    img.save(src)

    # Threshold 240: 230 background counts as "drawn" — broad bbox.
    extract_sprite(src, out_strict, threshold=240)
    broad = Image.open(out_strict).size

    # Threshold 220: 230 background is "blank" — tight bbox.
    extract_sprite(src, out_loose, threshold=220)
    tight = Image.open(out_loose).size

    assert tight[0] * tight[1] < broad[0] * broad[1], \
        f"tight threshold should yield smaller crop ({tight} vs {broad})"


def test_padding_affects_output_size(tmp_path):
    src = tmp_path / "sketch.png"
    out_pad8 = tmp_path / "pad8.png"
    out_pad0 = tmp_path / "pad0.png"
    _make_sketch(src, 100, 100, (40, 40, 60, 60))

    extract_sprite(src, out_pad8, pad=8)
    extract_sprite(src, out_pad0, pad=0)

    s8 = Image.open(out_pad8).size
    s0 = Image.open(out_pad0).size
    # Larger padding → larger output by ~2*pad on each axis.
    assert s8[0] > s0[0] and s8[1] > s0[1]
