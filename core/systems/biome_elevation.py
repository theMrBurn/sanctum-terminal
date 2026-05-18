"""Per-biome elevation field generation via WFC.

Per `feat/biome-greenhouse` elevation extension 2026-05-17. Each
biome declares an `ELEVATION_RULES` profile: integer level range +
allowed adjacent-tile diffs + tier weights. The solver returns
a deterministic per-tile elevation field cached for the biome's
lifetime.

Tier semantics (level_diff = abs(level_a - level_b)):
  0 = flat       (walk)
  1 = step       (~1m, auto-step-up by player)
  2 = ledge      (~2m, JUMP required)
  3 = cliff      (~3m, NOT jumpable from below; fall-only)
  4+ = wall      (impassable + dramatic silhouette)

`solve_elevation_field(biome, tile_range, seed)` returns
`{(tile_x, tile_y): level}` for a (2*tile_range+1)² grid centered
on origin.
"""
from __future__ import annotations

from typing import Any

from core.systems import wfc


# ── Per-biome rules ───────────────────────────────────────────────
#
# `levels`              : range (min, max) of integer elevation levels
# `max_adjacent_diff`   : largest allowed level_diff between neighbors
#                         (4 = cliffs OK, 1 = smooth, 0 = flat)
# `tier_weights`        : bias toward certain transitions when collapsing.
#                         Higher weight on diff=0 → more flat regions.
#                         Higher weight on diff=2 → more ledges.
#                         These are CELL weights (per-level), not pair
#                         weights — the WFC solver biases collapse picks.
# `policy`              : human-readable summary; not consumed by code.

ELEVATION_RULES: dict[str, dict[str, Any]] = {
    "cavern": {
        "levels":            (0, 4),
        "max_adjacent_diff": 4,                  # cliffs allowed
        "level_weights":     {0: 1.0, 1: 1.5, 2: 1.5, 3: 0.8, 4: 0.4},
        "policy":            "vertical_exploration",
    },
    "outdoor": {
        "levels":            (0, 2),
        "max_adjacent_diff": 1,                  # smooth only
        "level_weights":     {0: 2.0, 1: 1.0, 2: 0.5},
        "policy":            "gentle_hills",
    },
    "hub": {
        "levels":            (0, 0),             # flat
        "max_adjacent_diff": 0,
        "level_weights":     {0: 1.0},
        "policy":            "flat",
    },
    "workroom": {
        "levels":            (0, 0),             # flat
        "max_adjacent_diff": 0,
        "level_weights":     {0: 1.0},
        "policy":            "flat",
    },
}

# Fallback for unknown biomes — flat. Forces an explicit rule when
# adding new biomes instead of silently varying terrain.
ELEVATION_RULES_DEFAULT: dict[str, Any] = {
    "levels":            (0, 0),
    "max_adjacent_diff": 0,
    "level_weights":     {0: 1.0},
    "policy":            "flat",
}


# World height per integer level (meters). 1.0m matches the
# step-up height most FPS conventions use for "automatic step";
# 2.0m = "jump required"; 3.0m = "cliff." Per the tiered design
# 2026-05-17.
LEVEL_HEIGHT_M: float = 1.0

# World spacing per elevation tile (meters). Decoupled from biome
# stamp tile_size (288m) — elevation lives on its own finer grid so
# transitions appear within walking distance of spawn. Matches the
# client-side terrain.ElevationCache default. Per the 2026-05-17
# "decouple elevation from stamp" fix.
ELEV_TILE_M: float = 12.0

# Default per-biome-init grid extent: (2*ELEV_TILE_RANGE_DEFAULT+1)²
# tiles centered on origin. With 12m tiles + range 8 → 17×17 grid
# covering ±96m. Beyond this, things & terrain fall back to flat.
ELEV_TILE_RANGE_DEFAULT: int = 8


def world_xy_to_elev_tile(world_x: float, world_y: float) -> tuple[int, int]:
    """Snap a world-space (x, y) to its elevation tile coordinate."""
    return (
        int(round(world_x / ELEV_TILE_M)),
        int(round(world_y / ELEV_TILE_M)),
    )


# ── Tier classification ──────────────────────────────────────────


def classify_transition(level_diff: int) -> str:
    """Tier label for a level diff. Used by slope/wall rendering +
    player auto-step-up logic."""
    d = abs(int(level_diff))
    if d == 0:
        return "flat"
    if d == 1:
        return "step"
    if d == 2:
        return "ledge"
    if d == 3:
        return "cliff"
    return "wall"


# ── Solving ──────────────────────────────────────────────────────


def solve_elevation_field(
    biome: str,
    tile_range: int = 2,
    base_seed: int = 0,
) -> dict[tuple[int, int], int]:
    """Solve a (2*tile_range+1)² elevation grid for `biome`.

    Returns {(tile_x, tile_y): level} for tiles in
    [-tile_range, tile_range] × [-tile_range, tile_range].

    Deterministic given (biome, base_seed). Re-solving the same
    biome on next brain boot produces identical terrain — per
    `design_path_memory`.
    """
    rules = ELEVATION_RULES.get(biome, ELEVATION_RULES_DEFAULT)
    lo, hi = rules["levels"]
    if hi < lo:
        raise ValueError(f"biome {biome!r}: invalid level range ({lo}, {hi})")

    if lo == hi:
        # Flat biome — short-circuit; no WFC needed.
        width = height = 2 * tile_range + 1
        return {
            (x - tile_range, y - tile_range): lo
            for x in range(width) for y in range(height)
        }

    options = list(range(lo, hi + 1))
    max_diff = int(rules["max_adjacent_diff"])
    weights = rules.get("level_weights", {})

    def adjacency(a: int, b: int) -> bool:
        return abs(a - b) <= max_diff

    width = height = 2 * tile_range + 1
    # WFC uses 0..width-1 coords; translate after solving.
    seed = hash((biome, "elevation", int(base_seed))) & 0xffffffff
    raw = wfc.solve_grid(
        width=width, height=height,
        options=options,
        adjacency=adjacency,
        weights=weights,
        seed=seed,
    )
    return {
        (x - tile_range, y - tile_range): level
        for (x, y), level in raw.items()
    }


def field_to_floor_z(level: int) -> float:
    """Convert an elevation level (integer tier) to a world floor Z
    in meters. Per LEVEL_HEIGHT_M (default 1.0m per level)."""
    return float(level) * LEVEL_HEIGHT_M


# ── Inspection ───────────────────────────────────────────────────


def describe_field(field: dict[tuple[int, int], int]) -> dict[str, Any]:
    """Summary stats for a solved field. Useful for brain boot log
    + UAT visibility."""
    levels = list(field.values())
    transitions: dict[str, int] = {
        "flat": 0, "step": 0, "ledge": 0, "cliff": 0, "wall": 0,
    }
    for (x, y), v in field.items():
        for nx, ny in [(x + 1, y), (x, y + 1)]:
            if (nx, ny) in field:
                tier = classify_transition(field[(nx, ny)] - v)
                transitions[tier] += 1
    return {
        "level_min":   min(levels) if levels else 0,
        "level_max":   max(levels) if levels else 0,
        "tile_count":  len(field),
        "transitions": transitions,
    }
