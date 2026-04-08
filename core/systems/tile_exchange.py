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
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

from core.systems.biome_data import BIOME_REGISTRY
from core.systems.spatial_wake import WakeChain, WAKE_CHAINS
from core.systems.world_gen import generate_tile
from core.systems.macro_stamp import terrain_height, set_active_stamp
from core.systems.ambient_life import set_active_biome


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

        # Generate spawn tile
        self.get_tile_roster(0, 0)

    # -- Tile key ---------------------------------------------------------------

    def _tile_key(self, cam_x: float, cam_y: float) -> Tuple[int, int]:
        return (int(math.floor(cam_x / self.tile_size)),
                int(math.floor(cam_y / self.tile_size)))

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

        # Pre-pass: structural positions for this tile
        for spawn in tile_spawns:
            sk, (slx, sly), _, _, _ = spawn
            if sk in _STRUCTURAL_KINDS:
                sx_pos = slx - half + offset_x
                sy_pos = sly - half + offset_y
                self._structural_positions.append((sk, sx_pos, sy_pos))

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
                for ak, ax, ay in self._structural_positions:
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
                "collision_radius": COLLISION_RADII.get(kind, 0.0),
                "tile_variant": self._tile_variants.get((tx, ty), "standard"),
                "behavior_type": KIND_BEHAVIOR.get(kind, ""),
                "decay_stage": KIND_DECAY.get(kind, 0.0),
                "_chain_index": self.wake_chain.chain_index(kind),
            }

            # Ceiling attachment
            if kind in ("ceiling_moss", "hanging_vine"):
                ent["attachment_plane"] = "ceiling"

            # Stalactite inversion
            if kind in ("mega_column", "column"):
                variant_hash = abs(math.sin(x * 2.71 + y * 5.43))
                ent["attachment_plane"] = "ceiling" if variant_hash < 0.40 else "floor"

            # Emissive inversion
            if kind in ("crystal_cluster", "giant_fungus"):
                emissive_hash = abs(math.sin(x * 3.91 + y * 7.23))
                if emissive_hash < 0.30:
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
        """Score, sort, and truncate entities to delivery budget.

        Mandatory kinds are always included regardless of budget.
        """
        if not entities:
            return []

        budget = self.config["delivery_budget"]
        mandatory = self.config["mandatory_kinds"]

        # Score all entities
        scored = []
        for ent in entities:
            s = self.score_entity(ent, cam_x, cam_y, heading, vel_x, vel_y)
            scored.append((s, ent))
        scored.sort(key=lambda x: x[0])

        # Separate mandatory from optional
        mandatory_ents = []
        optional_scored = []
        for s, ent in scored:
            if ent["kind"] in mandatory:
                mandatory_ents.append((s, ent))
            else:
                optional_scored.append((s, ent))

        # Fill budget: mandatory first, then best-scored optional.
        # All entities arrive in one frame, sorted by perceptual priority.
        # The scoring handles delivery order; the budget handles the cap.
        result = [ent for _, ent in mandatory_ents]
        remaining = budget - len(result)
        if remaining > 0:
            result.extend(ent for _, ent in optional_scored[:remaining])

        # Sort final result by score for delivery order
        result.sort(key=lambda e: self.score_entity(e, cam_x, cam_y, heading, vel_x, vel_y))
        return result

    # -- Full delivery pipeline -------------------------------------------------

    def get_entities(self, cam_x: float, cam_y: float, cam_z: float,
                     heading: float, vel_x: float, vel_y: float) -> List[Dict]:
        """Full pipeline: ensure tiles → collect rosters → score → gate → deliver.

        This is the single call brain_server makes instead of
        ensure_tiles_around + wake query.
        """
        # Ensure tiles around camera
        ctx, cty = self._tile_key(cam_x, cam_y)
        r = self.prefetch_radius
        for dtx in range(-r, r + 1):
            for dty in range(-r, r + 1):
                self.get_tile_roster(ctx + dtx, cty + dty)

        # Collect all entities within render horizon. The scoring system
        # handles priority (near beats far, skeleton beats scatter) and the
        # budget caps total count. No per-kind wake radius cutoff — that
        # caused pop-in at 15-30m in clean room where you can see 100m+.
        render_horizon = self.config.get("render_horizon", 65.0)
        render_horizon_sq = render_horizon * render_horizon
        all_ents = []
        for (tx, ty), roster in self._tile_cache.items():
            # Quick tile-level distance check
            tile_cx = (tx + 0.5) * self.tile_size
            tile_cy = (ty + 0.5) * self.tile_size
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
