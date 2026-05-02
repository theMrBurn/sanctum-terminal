"""
core/systems/tile_exchange.py

TileExchange — the endocrine system of the render pipeline.

Scores, gates, and delivers entities from cached tile rosters based on
camera state and biome config. Tiles generate once, cache by (tx, ty),
and serve entities in priority order gated to a per-frame budget.

The exchange unifies four subsystems into one delivery schedule:
  - Wake chain priorities (skeleton before scatter)
  - Plane exchange bands (near before far)
  - FOV relevance (in-view before behind)
  - Velocity bias (ahead-of-movement before behind)

Pure Python. No rendering. Brain-side. Unit-tested.
"""

from __future__ import annotations

import math
import random
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from core.systems.biome_data import BIOME_REGISTRY, RENDER_SHELLS, KIND_RENDER_CLASS
from core.systems.spatial_wake import WakeChain, WAKE_CHAINS
from core.systems.world_gen import generate_tile
from core.systems.macro_stamp import terrain_height, set_active_stamp
from core.systems.spectrum import set_active_biome
from core.systems import kind_config as _kc


# VISUAL_RADII — nominal hull at sv=1.0; per-instance = × ent.sv. Mirror of
# brain_server's same constant. Kinds without visual_radius default to 0
# (walk-through / atmospheric).
PLAYER_STOP_THRESHOLD = 0.5
VISUAL_RADII = {k: float(v.get("visual_radius", 0.0))
                for k, v in _kc.all_kinds().items()}


def _player_collision_radius(kind: str, sv: float) -> float:
    r = VISUAL_RADII.get(kind, 0.0) * sv
    return r if r >= PLAYER_STOP_THRESHOLD else 0.0


# Derived sets from kind_config.spatial_class — single source of truth.
# spike: tapered primitive, inversion-capable per-instance (stalactites).
# companion: small organic/scatter, inherits attachment_plane from nearby
# spike host — NEVER independently inverts. This is the rule that kills
# "upside-down fungus beside upright fungus" incoherence.
_SPIKE_KINDS = {k for k, v in _kc.all_kinds().items()
                if v.get("spatial_class") == "spike"}
_COMPANION_KINDS = {k for k, v in _kc.all_kinds().items()
                    if v.get("spatial_class") == "companion"}

# Radius within which a companion adopts a spike host's attachment. Tuned
# to the typical stamp cluster diameter — tight enough that two nearby
# spikes with different attachments don't cross-contaminate companions.
_HOST_INHERIT_RADIUS_SQ = 8.0 * 8.0

# Same hash Godot used for stalactite roll — now brain-authoritative.
# 40% of spikes go ceiling, 60% floor. Deterministic per (x, y).
_STALACTITE_HASH_THRESHOLD = 0.40


def _roll_spike_ceiling(x: float, y: float) -> bool:
    """Deterministic stalactite roll for spike kinds. Same hash as Godot
    previously used, now authoritative on brain side so companions can
    inherit the decision."""
    return abs(math.sin(x * 2.71 + y * 5.43)) < _STALACTITE_HASH_THRESHOLD


# -- Kind properties (shared with brain_server.py) ----------------------------
# TODO: unify to biome_data.py (pinned in memory)

KIND_PROPS = {
    "mega_column":     {"scale": [3.0, 3.0, 12.0], "color": [0.28, 0.22, 0.16], "emissive": 0.0},
    "column":          {"scale": [2.25, 2.25, 10.0], "color": [0.30, 0.25, 0.18], "emissive": 0.0},
    "buttress":        {"scale": [2.5, 2.5, 6.0],  "color": [0.26, 0.21, 0.16], "emissive": 0.0},
    "boulder":         {"scale": [5.0, 4.4, 3.1],  "color": [0.25, 0.42, 0.16], "emissive": 0.0},
    "stalagmite":      {"scale": [1.0, 1.0, 3.75], "color": [0.28, 0.24, 0.18], "emissive": 0.0},
    "crystal_cluster": {"scale": [2.8, 2.2, 3.5],  "color": [0.50, 0.55, 0.80], "emissive": 1.0},
    "giant_fungus":    {"scale": [2.5, 2.5, 4.4],  "color": [0.30, 0.50, 0.25], "emissive": 0.8},
    "dead_log":        {"scale": [3.75, 1.0, 0.75],"color": [0.19, 0.27, 0.12], "emissive": 0.0},
    "moss_patch":      {"scale": [1.5, 1.5, 0.15], "color": [0.22, 0.45, 0.15], "emissive": 0.9},
    "bone_pile":       {"scale": [0.6, 0.6, 0.3],  "color": [0.14, 0.13, 0.11], "emissive": 0.0},
    "grass_tuft":      {"scale": [0.3, 0.3, 0.25], "color": [0.18, 0.33, 0.11], "emissive": 0.0},
    "rubble":          {"scale": [1.0, 1.0, 0.5],  "color": [0.28, 0.24, 0.19], "emissive": 0.0},
    "leaf_pile":       {"scale": [0.5, 0.5, 0.1],  "color": [0.30, 0.23, 0.12], "emissive": 0.0},
    "twig_scatter":    {"scale": [0.6, 0.4, 0.05], "color": [0.25, 0.21, 0.14], "emissive": 0.0},
    "cave_gravel":     {"scale": [0.2, 0.2, 0.05], "color": [0.24, 0.22, 0.16], "emissive": 0.0},
    "firefly":         {"scale": [0.06, 0.06, 0.06],"color": [0.95, 0.75, 0.30], "emissive": 1.0},
    "leaf":            {"scale": [0.08, 0.06, 0.01],"color": [0.22, 0.30, 0.10], "emissive": 0.0},
    "beetle":          {"scale": [0.04, 0.03, 0.02],"color": [0.10, 0.08, 0.06], "emissive": 0.0},
    "rat":             {"scale": [0.12, 0.06, 0.06],"color": [0.14, 0.11, 0.08], "emissive": 0.0},
    "spider":          {"scale": [0.05, 0.05, 0.03],"color": [0.08, 0.07, 0.06], "emissive": 0.0},
    "ceiling_moss":    {"scale": [3.0, 3.0, 2.5],  "color": [0.35, 0.45, 0.18], "emissive": 0.9},
    "hanging_vine":    {"scale": [0.8, 0.8, 4.0],  "color": [0.10, 0.16, 0.07], "emissive": 0.0},
    "filament":        {"scale": [0.25, 0.25, 3.5], "color": [0.30, 0.40, 0.55], "emissive": 1.0},
    "horizon_form":    {"scale": [6.0, 4.0, 10.0], "color": [0.08, 0.10, 0.05], "emissive": 0.0},
    "horizon_mid":     {"scale": [4.0, 3.0, 7.0],  "color": [0.10, 0.12, 0.06], "emissive": 0.0},
    "horizon_near":    {"scale": [3.0, 2.0, 5.0],  "color": [0.12, 0.14, 0.08], "emissive": 0.0},
    "exit_lure":       {"scale": [1.0, 1.0, 2.0],  "color": [0.60, 0.45, 0.20], "emissive": 1.0},
}

KIND_BEHAVIOR = {
    "beetle": "scurry", "rat": "scurry", "spider": "crawl",
    "firefly": "drift", "leaf": "drift",
}
KIND_DECAY = {
    "dead_log": 0.3, "leaf_pile": 0.5, "bone_pile": 0.6,
}

COLLISION_RADII = {
    "mega_column": 3.0, "column": 2.0, "buttress": 1.5,
    "boulder": 2.0, "stalagmite": 1.0, "crystal_cluster": 1.5,
    "giant_fungus": 1.5, "dead_log": 1.0,
}

_STRUCTURAL_KINDS = {"column", "mega_column", "buttress"}

# Ground-level scatter — below-knee objects the eye notices last.
_GROUND_KINDS = {"grass_tuft", "rubble", "leaf_pile", "twig_scatter", "cave_gravel"}

# Shell radii cache — extracted once from RENDER_SHELLS for fast lookup.
_SHELL_RADII = [s["radius"] for s in RENDER_SHELLS]
_SHELL_CLASSES = [set(s["kind_classes"]) for s in RENDER_SHELLS]


def _assign_shell(ent: dict, cam_x: float, cam_y: float,
                  shells: list = RENDER_SHELLS) -> int:
    """Return the shell index (0-6) for an entity based on distance from camera.

    Returns -1 if the entity is beyond all shells (should be culled).
    """
    dx = ent["x"] - cam_x
    dy = ent["y"] - cam_y
    dist = math.sqrt(dx * dx + dy * dy)
    for i, shell in enumerate(shells):
        if dist <= shell["radius"]:
            return i
    return -1


class TileExchange:
    """The endocrine system. Generates, caches, scores, and gates entity delivery."""

    def __init__(self, biome_name: str, base_seed: int = 42, tile_size: float = 288.0):
        self.biome_name = biome_name
        self.base_seed = base_seed
        self.tile_size = tile_size

        # Config from biome registry
        biome_reg = BIOME_REGISTRY.get(biome_name, {})
        self.config = biome_reg.get("exchange", {
            "delivery_budget": 350,
            "compression_threshold": 500,
            "mandatory_kinds": {"mega_column", "column"},
            "scoring_weights": {
                "wake_priority": 1.0,
                "distance_band": 0.8,
                "fov_relevance": 0.6,
                "velocity_bias": 0.4,
            },
            "speculative_radius": 1,
            "cache_size": 64,
        })
        self.prefetch_radius = biome_reg.get("tile_prefetch_radius", 2)

        # Wake chain for priority indexing
        chain_key = biome_name if biome_name in WAKE_CHAINS else "outdoor"
        self.wake_chain = WakeChain(WAKE_CHAINS[chain_key])
        self._max_chain = len(WAKE_CHAINS[chain_key]) - 1

        # Macro stamp setup
        set_active_biome(biome_name)
        macro_stamps = biome_reg.get("macro_stamps", [])
        if macro_stamps:
            set_active_stamp(macro_stamps[0], tile_size)
        self._macro_stamps = macro_stamps

        # Ceiling height from planes config
        self._ceiling_y = 15.0
        for plane in biome_reg.get("planes", []):
            if plane.get("kind") == "ceiling":
                self._ceiling_y = plane.get("offset", 15.0)
                break

        # LRU tile cache: (tx, ty) → entity list
        self._tile_cache: OrderedDict[Tuple[int, int], List[Dict]] = OrderedDict()

        # Roster tracking — who was "at bat" last frame.
        # Set of (kind, x, y) tuples for O(1) incumbent lookup.
        self._prev_roster: set = set()

        # Structural positions across all tiles (for boulder proximity)
        self._structural_positions: List[Tuple[str, float, float]] = []

        # Tile variant tracking
        self._tile_variants: Dict[Tuple[int, int], str] = {}

        # Max new tiles to generate per frame — prevents TCP disconnect
        # by capping how long the brain blocks on tile generation.
        # Config: exchange.tiles_per_frame (default 1)
        self.tiles_per_frame = self.config.get("tiles_per_frame", 1)

        # Generate spawn tile
        self.get_tile_roster(0, 0)

    # -- Tile key ---------------------------------------------------------------

    def _tile_key(self, cam_x: float, cam_y: float) -> Tuple[int, int]:
        """Return the tile whose CENTER is closest to (cam_x, cam_y).

        Entity placement convention: tile (tx, ty) entities are
        generated with `x = lx - half + tx * tile_size` (see
        `_generate_tile`), so tile (0, 0) entities live in world
        coords x ∈ [-half, half), centered on the origin. This lookup
        must match — picking tile by `floor(cam / tile_size)` produces
        a half-tile offset where the cam ends up "in" tile (0, 0)
        even though its actual entities are in tile (0, 1).

        Pre-2026-05-01 this returned `floor(cam/tile_size)` which mis-
        matched entity placement and produced the "blank world past
        the origin stamp" regression — tile coverage windows skipped
        the tile the player was actually in.
        """
        half = self.tile_size / 2.0
        return (int(math.floor((cam_x + half) / self.tile_size)),
                int(math.floor((cam_y + half) / self.tile_size)))

    # -- Prefetch ordering ------------------------------------------------------

    def _spiral_order(self, r: int, heading: float,
                      vel_x: float, vel_y: float) -> List[Tuple[int, int]]:
        """Tile offsets in spiral order: center out, front-of-movement first.

        Chebyshev rings peel outward (ring 0 = camera tile, ring 1 = 8
        neighbors, ring 2 = 16 tiles...). Within each ring, tiles sort by
        angle relative to the movement direction so the tiles you're
        walking toward generate before tiles behind you.
        """
        # Movement direction — fall back to heading if stationary
        speed = math.sqrt(vel_x * vel_x + vel_y * vel_y)
        if speed > 0.5:
            front_angle = math.atan2(vel_y, vel_x)
        else:
            heading_rad = math.radians(heading)
            front_angle = math.atan2(-math.cos(heading_rad), math.sin(heading_rad))

        offsets = []
        for dtx in range(-r, r + 1):
            for dty in range(-r, r + 1):
                ring = max(abs(dtx), abs(dty))
                # Angle from center to this offset, relative to front
                angle = math.atan2(dty, dtx) - front_angle
                # Normalize to [0, 2π] — tiles near 0 are directly ahead
                angle = angle % (2.0 * math.pi)
                offsets.append((ring, angle, dtx, dty))
        offsets.sort()
        return [(dtx, dty) for _, _, dtx, dty in offsets]

    # -- Tile generation & cache ------------------------------------------------

    def get_tile_roster(self, tx: int, ty: int) -> List[Dict]:
        """Get the entity roster for a tile. Generates on miss, caches on hit."""
        key = (tx, ty)
        if key in self._tile_cache:
            self._tile_cache.move_to_end(key)
            return self._tile_cache[key]

        roster = self._generate_tile(tx, ty)
        self._tile_cache[key] = roster

        # Evict oldest if over cache limit
        cache_size = self.config.get("cache_size", 64)
        while len(self._tile_cache) > cache_size:
            self._tile_cache.popitem(last=False)

        return roster

    def _generate_tile(self, tx: int, ty: int) -> List[Dict]:
        """Generate a full entity roster for one tile."""
        seed = self.base_seed + tx * 7919 + ty * 6271
        rng = random.Random(seed)

        # Pick macro stamp
        ms = None
        if self._macro_stamps:
            ms = self._macro_stamps[0] if (tx == 0 and ty == 0) else \
                 self._macro_stamps[seed % len(self._macro_stamps)]

        variant_name, tile_spawns = generate_tile(
            seed=seed, biome_name=self.biome_name, tile_size=self.tile_size,
            is_spawn_tile=(tx == 0 and ty == 0), macro_stamp=ms)
        self._tile_variants[(tx, ty)] = variant_name

        offset_x = tx * self.tile_size
        offset_y = ty * self.tile_size
        half = self.tile_size / 2.0

        # Pre-pass: structural positions for this tile + spike ceiling status
        # so companions can deterministically inherit attachment from nearby
        # spike anchors (stalactite host → hanging companions, upright host →
        # ground companions, no mixed orientation within a cluster).
        for spawn in tile_spawns:
            sk, (slx, sly), _, _, _ = spawn
            if sk in _STRUCTURAL_KINDS or sk in _SPIKE_KINDS:
                sx_pos = slx - half + offset_x
                sy_pos = sly - half + offset_y
                is_ceiling = sk in _SPIKE_KINDS and _roll_spike_ceiling(sx_pos, sy_pos)
                self._structural_positions.append((sk, sx_pos, sy_pos, is_ceiling))

        roster = []
        for spawn in tile_spawns:
            kind, (lx, ly), heading, kseed, meta = spawn
            props = KIND_PROPS.get(kind)
            if not props:
                continue

            x = lx - half + offset_x
            y = ly - half + offset_y
            z = terrain_height(x, y)

            # Kind-specific z attachment
            if kind == "leaf":
                z = 3.0
            elif kind == "ceiling_moss":
                z = self._ceiling_y - rng.uniform(0.5, 2.0)
            elif kind == "hanging_vine":
                z = self._ceiling_y - rng.uniform(3.0, 8.0)
            elif kind == "filament":
                z = rng.uniform(1.0, 4.0)
            elif kind == "firefly":
                z = rng.uniform(0.5, 2.5)

            srng = random.Random(kseed)
            sv = srng.uniform(0.75, 1.25) * 1.30

            # Boulder 75/25 proximity split
            if kind == "boulder":
                near_anchor = False
                for ak, ax, ay, *_ in self._structural_positions:
                    dx, dy = x - ax, y - ay
                    if dx * dx + dy * dy < 64.0:
                        near_anchor = True
                        break
                if near_anchor and srng.random() < 0.75:
                    sv *= 0.64

            # Crystal size variation
            if kind == "crystal_cluster" and srng.random() < 0.10:
                sv *= 0.5

            # Vine/moss snap to nearest structural anchor
            if kind in ("hanging_vine", "ceiling_moss"):
                best_dist2 = 900.0
                snap_x, snap_y = x, y
                for ak, ax, ay, _ac in self._structural_positions:
                    dx, dy = x - ax, y - ay
                    d2 = dx * dx + dy * dy
                    if d2 < best_dist2 and d2 > 1.0:
                        best_dist2 = d2
                        dist = math.sqrt(d2)
                        frac = min(1.0, 2.5 / dist)
                        snap_x = x + (ax - x) * frac
                        snap_y = y + (ay - y) * frac
                x, y = snap_x, snap_y

            sx, sy_s, sz = props["scale"]
            r, g, b = props["color"]
            light_hue_idx = srng.randint(0, 3)

            ent = {
                "kind": kind,
                "x": round(x, 2),
                "y": round(y, 2),
                "z": round(z, 2),
                "heading": round(heading, 1),
                "sv": round(sv, 3),
                "light_hue": light_hue_idx,
                "sx": round(sx * sv, 3),
                "sy": round(sy_s * sv, 3),
                "sz": round(sz * srng.uniform(0.80, 1.20), 3),
                "r": round(r * srng.uniform(0.85, 1.15), 3),
                "g": round(g * srng.uniform(0.85, 1.15), 3),
                "b": round(b * srng.uniform(0.85, 1.15), 3),
                "emissive": props["emissive"],
                "collision_radius": _player_collision_radius(kind, sv),
                "tile_variant": self._tile_variants.get((tx, ty), "standard"),
                "behavior_type": KIND_BEHAVIOR.get(kind, ""),
                "decay_stage": KIND_DECAY.get(kind, 0.0),
                "_chain_index": self.wake_chain.chain_index(kind),
            }

            # Ceiling-bound kinds — always overhead regardless of host.
            if kind in ("ceiling_moss", "hanging_vine"):
                ent["attachment_plane"] = "ceiling"

            # Spike inversion — spikes (stalagmite/column/mega_column) roll
            # independently per-instance via deterministic hash. The decision
            # is recorded in _structural_positions so companions can inherit.
            elif kind in _SPIKE_KINDS:
                ent["attachment_plane"] = "ceiling" if _roll_spike_ceiling(x, y) else "floor"

            # Companion host-inheritance — companions (fungus, grass, moss,
            # rubble, etc) never flip independently. They look up the nearest
            # spike anchor within _HOST_INHERIT_RADIUS_SQ; if that host rolled
            # ceiling, the companion inherits ceiling and gets re-positioned
            # at a random Y below the ceiling plane. This kills the old
            # "upside-down fungus beside upright fungus" incoherence AND
            # gives hanging grass/fungus on stalactite clusters.
            elif kind in _COMPANION_KINDS:
                host_ceiling = False
                best_d2 = _HOST_INHERIT_RADIUS_SQ
                for ak, ax, ay, ac in self._structural_positions:
                    dx, dy = x - ax, y - ay
                    d2 = dx * dx + dy * dy
                    if d2 < best_d2:
                        best_d2 = d2
                        host_ceiling = ac
                if host_ceiling:
                    ent["attachment_plane"] = "ceiling"
                    ent["z"] = round(self._ceiling_y - rng.uniform(0.5, 2.0), 2)

            # Metadata passthrough
            if meta:
                if kind == "buttress":
                    ent["lean_angle"] = round(meta.get("lean_angle", 0), 1)
                    ent["scale_x"] = round(meta.get("scale_x", 1), 3)
                    ent["scale_y"] = round(meta.get("scale_y", 1), 3)
                    ent["scale_z"] = round(meta.get("scale_z", 1), 3)
                    ent["formation"] = meta.get("formation", "")
                if kind == "mega_column" and "formation_scale_mult" in meta:
                    mult = meta["formation_scale_mult"]
                    ent["sx"] = round(ent["sx"] * mult, 3)
                    ent["sy"] = round(ent["sy"] * mult, 3)
                    ent["sz"] = round(ent["sz"] * mult, 3)
                    ent["formation"] = meta.get("formation", "")
                if "cluster_z_offset" in meta:
                    ent["z"] = round(ent["z"] + meta["cluster_z_offset"], 2)
                if "scale_mult" in meta and kind != "mega_column":
                    mult = meta["scale_mult"]
                    ent["sx"] = round(ent["sx"] * mult, 3)
                    ent["sy"] = round(ent["sy"] * mult, 3)
                    ent["sz"] = round(ent["sz"] * mult, 3)
                if meta.get("colony_center"):
                    ent["colony_center"] = True
                if "stamp_scale_mult" in meta:
                    mult = meta["stamp_scale_mult"]
                    ent["sx"] = round(ent["sx"] * mult, 3)
                    ent["sy"] = round(ent["sy"] * mult, 3)
                    ent["sz"] = round(ent["sz"] * mult, 3)

            roster.append(ent)

        return roster

    # -- Scoring ----------------------------------------------------------------

    def score_entity(self, ent: Dict, cam_x: float, cam_y: float,
                     heading: float, vel_x: float, vel_y: float) -> float:
        """Score an entity for delivery priority. Lower = delivered first.

        Combines wake chain priority, distance band, FOV relevance, and
        velocity bias into a single scalar using config-driven weights.
        """
        w = self.config["scoring_weights"]

        # Wake priority: chain_index normalized to [0, 1]
        chain_idx = ent.get("_chain_index", self._max_chain)
        wake_score = chain_idx / max(self._max_chain, 1)

        # Distance band: [0, 1] where 0=touching, 1=at max wake radius
        dx = ent["x"] - cam_x
        dy = ent["y"] - cam_y
        dist = math.sqrt(dx * dx + dy * dy)
        max_wake = 60.0  # extended skeleton radius from brain_server
        dist_score = min(dist / max_wake, 1.0)

        # FOV relevance: dot product with camera forward vector
        # heading=0 in brain coords: camera faces -Y (Godot -Z)
        heading_rad = math.radians(heading)
        fwd_x = math.sin(heading_rad)
        fwd_y = -math.cos(heading_rad)
        if dist > 0.1:
            dot_fov = (dx * fwd_x + dy * fwd_y) / dist
        else:
            dot_fov = 1.0  # on top of camera = maximally relevant
        fov_score = (1.0 - dot_fov) * 0.5  # remap [-1,1] → [0,1]

        # Velocity bias: dot product with movement direction
        vel_mag = math.sqrt(vel_x * vel_x + vel_y * vel_y)
        if vel_mag > 0.1 and dist > 0.1:
            dot_vel = (dx * vel_x + dy * vel_y) / (dist * vel_mag)
            vel_score = (1.0 - dot_vel) * 0.5
        else:
            vel_score = 0.5  # no movement = neutral

        # Perceptual modifiers — trick the human eye
        # Emissive boost: light sources debut early (negative weight = lower score)
        emissive_mod = w.get("emissive_boost", 0.0) if ent.get("emissive", 0) > 0 else 0.0

        # Ground penalty: floor scatter debuts last
        ground_mod = w.get("ground_penalty", 0.0) if ent.get("kind", "") in _GROUND_KINDS else 0.0

        # Roster stability: incumbents stay in lineup, newcomers need a reason
        ent_key = (ent.get("kind", ""), ent.get("x", 0), ent.get("y", 0))
        if ent_key in self._prev_roster:
            roster_mod = w.get("roster_stability", 0.0)  # negative = stay
        else:
            roster_mod = w.get("newcomer_gate", 0.0)     # positive = harder to debut

        return (
            wake_score * w["wake_priority"]
            + dist_score * w["distance_band"]
            + fov_score * w["fov_relevance"]
            + vel_score * w["velocity_bias"]
            + emissive_mod
            + ground_mod
            + roster_mod
        )

    # -- Gating -----------------------------------------------------------------

    def gate(self, entities: List[Dict], cam_x: float, cam_y: float,
             heading: float, vel_x: float, vel_y: float) -> List[Dict]:
        """Score and gate entities per shell. Each shell has its own budget.

        The 7 render shells define concentric distance bands. Each band
        has a budget and a list of allowed kind_classes. Entities compete
        only within their shell — nearby ground scatter can't starve
        distant structural anchors. Mandatory kinds bypass all budgets.
        """
        if not entities:
            return []

        mandatory = self.config["mandatory_kinds"]
        shell_budgets = self.config.get("shell_budgets")

        # Fallback to flat budget if shell_budgets not configured
        if not shell_budgets:
            return self._gate_flat(entities, cam_x, cam_y, heading, vel_x, vel_y)

        # Bin entities by shell, filtering by kind_class permission
        n_shells = len(shell_budgets)
        shell_bins: List[List[Tuple[float, Dict]]] = [[] for _ in range(n_shells)]
        mandatory_ents = []

        for ent in entities:
            # Mandatory kinds always pass
            if ent["kind"] in mandatory:
                s = self.score_entity(ent, cam_x, cam_y, heading, vel_x, vel_y)
                mandatory_ents.append((s, ent))
                continue

            shell_idx = _assign_shell(ent, cam_x, cam_y)
            if shell_idx < 0 or shell_idx >= n_shells:
                continue

            # Check kind_class permission for this shell
            kind_class = KIND_RENDER_CLASS.get(ent["kind"], "scatter")
            if kind_class not in _SHELL_CLASSES[shell_idx]:
                continue

            s = self.score_entity(ent, cam_x, cam_y, heading, vel_x, vel_y)
            shell_bins[shell_idx].append((s, ent))

        # Gate each shell independently
        result = [ent for _, ent in mandatory_ents]
        for i, bin_list in enumerate(shell_bins):
            bin_list.sort(key=lambda x: x[0])
            budget = shell_budgets[i]
            result.extend(ent for _, ent in bin_list[:budget])

        # Sort final result by score for delivery order
        result.sort(key=lambda e: self.score_entity(e, cam_x, cam_y, heading, vel_x, vel_y))
        return result

    def _gate_flat(self, entities: List[Dict], cam_x: float, cam_y: float,
                   heading: float, vel_x: float, vel_y: float) -> List[Dict]:
        """Flat budget gating — fallback when shell_budgets not configured."""
        budget = self.config["delivery_budget"]
        mandatory = self.config["mandatory_kinds"]

        scored = []
        for ent in entities:
            s = self.score_entity(ent, cam_x, cam_y, heading, vel_x, vel_y)
            scored.append((s, ent))
        scored.sort(key=lambda x: x[0])

        mandatory_ents = []
        optional_scored = []
        for s, ent in scored:
            if ent["kind"] in mandatory:
                mandatory_ents.append((s, ent))
            else:
                optional_scored.append((s, ent))

        result = [ent for _, ent in mandatory_ents]
        remaining = budget - len(result)
        if remaining > 0:
            result.extend(ent for _, ent in optional_scored[:remaining])

        result.sort(key=lambda e: self.score_entity(e, cam_x, cam_y, heading, vel_x, vel_y))
        return result

    # -- Full delivery pipeline -------------------------------------------------

    def get_entities(self, cam_x: float, cam_y: float, cam_z: float,
                     heading: float, vel_x: float, vel_y: float) -> List[Dict]:
        """Full pipeline: ensure tiles → collect rosters → score → gate → deliver.

        Generates at most tiles_per_frame new tiles per call to prevent
        blocking the brain's TCP response loop. Cached tiles are always
        collected. New tiles fill in over subsequent frames.
        """
        ctx, cty = self._tile_key(cam_x, cam_y)
        r = self.prefetch_radius

        # Build prefetch grid sorted by distance from camera tile.
        # Nearest tiles generate first — the tile you're standing on
        # and the one directly ahead matter most.
        needed = []
        for dtx in range(-r, r + 1):
            for dty in range(-r, r + 1):
                key = (ctx + dtx, cty + dty)
                if key not in self._tile_cache:
                    needed.append((dtx * dtx + dty * dty, key))
        needed.sort()

        generated = 0
        for _, key in needed:
            if generated >= self.tiles_per_frame:
                break
            self.get_tile_roster(*key)
            generated += 1

        # Collect all entities within render horizon from cached tiles.
        render_horizon = self.config.get("render_horizon", 65.0)
        render_horizon_sq = render_horizon * render_horizon
        all_ents = []
        for (tx, ty), roster in self._tile_cache.items():
            # Quick tile-level distance check.
            # Entity placement (see _generate_tile) centers tile (tx, ty)
            # at world (tx*tile_size, ty*tile_size). Earlier versions used
            # `(tx + 0.5) * tile_size` which mis-modelled that center and
            # produced 144m skips at half-tile-aligned camera positions
            # — the "blank world past origin stamp" regression fixed
            # 2026-05-01.
            tile_cx = tx * self.tile_size
            tile_cy = ty * self.tile_size
            tile_dx = tile_cx - cam_x
            tile_dy = tile_cy - cam_y
            tile_dist_sq = tile_dx * tile_dx + tile_dy * tile_dy
            margin = render_horizon + self.tile_size * 0.71
            if tile_dist_sq > margin * margin:
                continue
            for ent in roster:
                dx = ent["x"] - cam_x
                dy = ent["y"] - cam_y
                d2 = dx * dx + dy * dy
                if d2 <= render_horizon_sq:
                    # Below-ground cull
                    if ent.get("z", 0.0) < -0.5 and ent.get("attachment_plane", "") != "ceiling":
                        continue
                    all_ents.append(ent)

        result = self.gate(all_ents, cam_x, cam_y, heading, vel_x, vel_y)

        # Update roster — who's "at bat" this frame becomes the incumbents next frame.
        self._prev_roster = {
            (e["kind"], e["x"], e["y"]) for e in result
        }

        return result
