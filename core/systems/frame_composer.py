"""
core/systems/frame_composer.py

Directed wandering via composed spatial frames.

A 'frame' is: two flanking objects + a gap + an accent in the gap.
The player walks through a sequence of composed views — never an empty
field, never a random scatter. Metroid Prime principle: give options
to intuit, not plan.

Config-as-code: biome declares what objects frame, what objects accent,
how wide the gaps are, and how often paths nudge left/right.

Usage:
    composer = FrameComposer(seed=42)
    placements = composer.compose_along_path(
        node_a=(0, 0), node_b=(20, 0),
        config=FRAMING_CONFIG["outdoor"],
    )
    for p in placements:
        spawn(p["kind"], pos=p["pos"], heading=p["heading"])
"""

import math
import random


# -- Framing config per biome --------------------------------------------------

FRAMING_CONFIG = {
    "cavern": {
        "frame_kinds": ["mega_column", "column"],
        "accent_kinds": ["crystal_cluster", "giant_fungus", "moss_patch"],
        "pair_spacing": (8.0, 14.0),     # distance between framing pair along path
        "gap_width": (14.0, 22.0),       # center-to-center; collision radii eat into this
        "min_walkable": 4.0,             # minimum clear space after collision radii
        "nudge_bias": 0.3,               # 30% chance accent is off-center
        # Collision radii for gap calculation (must exceed HARD_OBJECTS + base_radius)
        "frame_collision": {"mega_column": 12.0, "column": 3.0},
    },
    "outdoor": {
        "frame_kinds": ["mega_column", "column"],
        "accent_kinds": ["boulder", "crystal_cluster", "dead_log"],
        "pair_spacing": (10.0, 18.0),    # wider for forest
        "gap_width": (16.0, 28.0),       # wider — Doug fir base radius 5-12m each side
        "min_walkable": 5.0,
        "nudge_bias": 0.25,
        "frame_collision": {"mega_column": 12.0, "column": 3.0},
    },
}


class FrameComposer:
    """Compose spatial frames from biome placement rules.

    Each frame is a minimal composition: two flanking objects bracket
    a walkable gap, with an accent object placed in or near the gap
    to draw the eye forward.
    """

    def __init__(self, seed=0):
        self._seed = seed

    def compose_along_path(self, node_a, node_b, config):
        """Given two hex nodes, compose framing pairs between them.

        Returns list of placement dicts:
            {"kind": str, "pos": (x, y), "heading": float, "role": str}

        role is one of: "frame_left", "frame_right", "accent"
        """
        ax, ay = node_a
        bx, by = node_b

        dx = bx - ax
        dy = by - ay
        path_len = math.sqrt(dx * dx + dy * dy)

        if path_len < 1.0:
            return []

        # Path direction (normalized) and perpendicular
        nx, ny = dx / path_len, dy / path_len
        px, py = -ny, nx  # perpendicular (left is negative, right is positive)

        rng = random.Random(self._seed + hash((ax, ay, bx, by)))

        frame_kinds = config["frame_kinds"]
        accent_kinds = config["accent_kinds"]
        pair_min, pair_max = config["pair_spacing"]
        gap_min, gap_max = config["gap_width"]
        nudge_bias = config.get("nudge_bias", 0.0)

        if not frame_kinds or not accent_kinds:
            return []

        placements = []

        # Walk along path, placing frame pairs at spacing intervals
        t = pair_min * 0.5  # start offset from node_a
        while t < path_len - pair_min * 0.3:
            # Position along path
            cx = ax + nx * t
            cy = ay + ny * t

            # Pick frame kinds first — collision radii depend on kind
            left_kind = rng.choice(frame_kinds)
            right_kind = rng.choice(frame_kinds)

            # Gap width — must account for collision radii of frame objects
            gap = rng.uniform(gap_min, gap_max)
            frame_coll = config.get("frame_collision", {})
            left_coll = frame_coll.get(left_kind, 3.0)
            right_coll = frame_coll.get(right_kind, 3.0)
            min_walkable = config.get("min_walkable", 4.0)
            min_gap = left_coll + right_coll + min_walkable
            gap = max(gap, min_gap)
            half_gap = gap * 0.5

            left_pos = (
                round(cx + px * half_gap, 2),
                round(cy + py * half_gap, 2),
            )
            right_pos = (
                round(cx - px * half_gap, 2),
                round(cy - py * half_gap, 2),
            )

            placements.append({
                "kind": left_kind,
                "pos": left_pos,
                "heading": rng.uniform(0, 360),
                "role": "frame_left",
            })
            placements.append({
                "kind": right_kind,
                "pos": right_pos,
                "heading": rng.uniform(0, 360),
                "role": "frame_right",
            })

            # Accent in the gap (slightly ahead of the frame pair midpoint)
            accent_advance = rng.uniform(0.5, 2.0)
            accent_cx = cx + nx * accent_advance
            accent_cy = cy + ny * accent_advance

            # Nudge: offset accent to suggest a turn
            if rng.random() < nudge_bias:
                nudge_dir = rng.choice([-1, 1])
                nudge_amount = rng.uniform(1.5, half_gap * 0.6)
                accent_cx += px * nudge_dir * nudge_amount
                accent_cy += py * nudge_dir * nudge_amount

            accent_kind = rng.choice(accent_kinds)
            placements.append({
                "kind": accent_kind,
                "pos": (round(accent_cx, 2), round(accent_cy, 2)),
                "heading": rng.uniform(0, 360),
                "role": "accent",
            })

            # Advance along path
            spacing = rng.uniform(pair_min, pair_max)
            t += spacing

        return placements
