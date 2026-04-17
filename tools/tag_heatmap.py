"""
tools/tag_heatmap.py

Post-hoc analysis of player-dropped telemetry tags. Buckets tag positions
by 16m slot, counts tag reasons per slot, prints a density × difficulty
grid. Feeds procedural tuning decisions — which slots run "hot" (repeat
dangerous tags) vs cold (repeat neutral/interesting).

Tag reasons from godot/main.gd:3762-3771:
  - neutral      (T)           — baseline observation
  - interesting  (Shift+T)     — composition worked, possibly capture
  - beautiful    (Alt+T)       — aesthetic reference
  - dangerous    (Ctrl+T)      — collision / traversal bug (or gameplay hazard)
  - weird        (Cmd+T)       — anomaly / "I don't know what's happening"

Usage:
    PYTHONPATH=. ./.venv/bin/python tools/tag_heatmap.py [tag_dir]

Default tag_dir: godot/tags/
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

SLOT_SIZE = 16.0  # matches stamp_world.SLOT_SIZE


def _slot_for(x: float, y: float) -> tuple[int, int]:
    """Convert world position to slot coords (matches stamp_world math)."""
    import math
    return int(math.floor(x / SLOT_SIZE)), int(math.floor(y / SLOT_SIZE))


def load_tags(tag_dir: Path) -> list[dict]:
    """Load every tag JSON in tag_dir. Returns list of parsed dicts."""
    tags = []
    for f in sorted(tag_dir.glob("sanctum_tag_*.json")):
        try:
            with f.open() as fh:
                tags.append(json.load(fh))
        except (json.JSONDecodeError, OSError):
            continue
    return tags


def bucket_by_slot(tags: list[dict]) -> dict[tuple[int, int], Counter]:
    """Bucket tags by 16m slot. Returns {(gx, gy): Counter(reason -> count)}."""
    buckets: dict[tuple[int, int], Counter] = defaultdict(Counter)
    for t in tags:
        cam = t.get("camera", {})
        x = cam.get("x")
        y = cam.get("y")
        if x is None or y is None:
            continue
        slot = _slot_for(float(x), float(y))
        reason = t.get("tag_reason", "neutral")
        buckets[slot][reason] += 1
    return buckets


def print_overview(tags: list[dict]) -> None:
    print(f"=== {len(tags)} tags scanned ===")
    reason_counts = Counter(t.get("tag_reason", "neutral") for t in tags)
    for reason, count in reason_counts.most_common():
        print(f"  {reason:15s} {count:4d}")


def print_hot_slots(buckets: dict[tuple[int, int], Counter],
                    min_tags: int = 2) -> None:
    """Print slots with multiple tags, sorted by dangerous-ratio then count."""
    print()
    print(f"=== Slots with >={min_tags} tags (sorted by danger) ===")
    print(f"{'slot':>12s}  {'tags':>5s}  {'dang':>5s}  {'weird':>5s}  {'int':>5s}  {'neut':>5s}  ratio")
    rows = []
    for slot, counter in buckets.items():
        total = sum(counter.values())
        if total < min_tags:
            continue
        danger_like = counter.get("dangerous", 0) + counter.get("weird", 0)
        ratio = danger_like / total if total else 0
        rows.append((slot, total, counter, ratio))
    rows.sort(key=lambda r: (-r[3], -r[1]))
    for slot, total, counter, ratio in rows:
        print(f"{str(slot):>12s}  {total:5d}  "
              f"{counter.get('dangerous', 0):5d}  "
              f"{counter.get('weird', 0):5d}  "
              f"{counter.get('interesting', 0):5d}  "
              f"{counter.get('neutral', 0):5d}  "
              f"{ratio:.2f}")


def print_radial_bands(tags: list[dict]) -> None:
    """Group tags by radial distance band from origin (matches stamp_world
    bands: spawn <32m, near <80m, mid <144m, frontier >=144m). Shows
    whether dangerous tags correlate with band distance."""
    bands = {"spawn": Counter(), "near": Counter(), "mid": Counter(), "frontier": Counter()}
    for t in tags:
        cam = t.get("camera", {})
        x = float(cam.get("x", 0.0))
        y = float(cam.get("y", 0.0))
        d = (x * x + y * y) ** 0.5
        if d < 32:
            band = "spawn"
        elif d < 80:
            band = "near"
        elif d < 144:
            band = "mid"
        else:
            band = "frontier"
        bands[band][t.get("tag_reason", "neutral")] += 1

    print()
    print("=== Tags per radial band (distance from origin) ===")
    print(f"{'band':>10s}  {'total':>5s}  {'dang':>5s}  {'weird':>5s}  {'int':>5s}  {'neut':>5s}  ratio")
    for band in ("spawn", "near", "mid", "frontier"):
        c = bands[band]
        total = sum(c.values())
        danger = c.get("dangerous", 0) + c.get("weird", 0)
        ratio = danger / total if total else 0
        print(f"{band:>10s}  {total:5d}  "
              f"{c.get('dangerous', 0):5d}  "
              f"{c.get('weird', 0):5d}  "
              f"{c.get('interesting', 0):5d}  "
              f"{c.get('neutral', 0):5d}  "
              f"{ratio:.2f}")


def main() -> int:
    tag_dir = Path(sys.argv[1]) if len(sys.argv) > 1 \
        else Path(__file__).resolve().parents[1] / "godot" / "tags"
    if not tag_dir.is_dir():
        print(f"error: tag dir not found: {tag_dir}")
        return 1

    tags = load_tags(tag_dir)
    if not tags:
        print(f"no tags in {tag_dir}")
        return 1

    print_overview(tags)
    print_radial_bands(tags)
    print_hot_slots(bucket_by_slot(tags), min_tags=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
