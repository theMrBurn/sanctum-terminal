"""
brain_server.py

Live brain server: generates world, streams manifests to Godot via TCP.

Protocol:
    Godot connects to localhost:9877
    Godot sends: JSON line with {"cam_x", "cam_y", "cam_z", "heading", "pitch", "dt"}\n
    Server sends: JSON line with full manifest (entities, fog, ambient)\n

    Manifest only updates when wake set changes or tension state changes.
    Otherwise sends {"unchanged": true}\n to save bandwidth.

Usage:
    PYTHONPATH=. ./.venv/bin/python brain_server.py [outdoor|cavern]
    make brain
"""

import json
import math
import os
import random
import select
import socket
import sys
import time

from core.systems.biome_data import (
    BIOME_REGISTRY,
    OUTDOOR_LIGHT_STATES, CAVERN_LIGHT_STATES,
    HARD_OBJECTS,
    RENDER_SHELLS, KIND_RENDER_CLASS,
)
from core.systems.spatial_wake import SpatialHash, WakeChain, WAKE_CHAINS
from core.systems.world_gen import generate_tile
from core.systems.tension_cycle import TensionCycle, OUTDOOR_CYCLE, CAVERN_CYCLE
from core.systems.plane_exchange import classify_all_entities, CAVERN_EXCHANGE_NODES
from core.systems.chronometer import Chronometer
from core.systems.ambient_life import SpectrumEngine, set_active_biome
from core.systems.macro_stamp import (
    terrain_height, set_active_stamp, grid_density, grid_allowed,
)
from core.systems.biome_data import MACRO_STAMP_CAVERN_CHAMBER
from core.systems.tile_exchange import TileExchange
from core.systems.bucket_world import get_visible as bucket_get_visible
from core.systems.stamp_world import get_visible as stamp_get_visible
from core.systems.expedition_engine import ExpeditionEngine
from pathlib import Path

# Where expedition session logs land. Ignored by git (.gitignore
# addition lands alongside commit 10). Each completed expedition
# writes sessions/expedition_<timestamp>.json which is the post-
# mortem artifact for visual triage.
SESSIONS_DIR: Path = Path(__file__).parent / "sessions"

# Entity delivery mode — A/B/C testing.
#   default: TileExchange (cached tiles, scored, gated, shells)
#   SANCTUM_BUCKET=1: random density per 16m bucket (pure function)
#   SANCTUM_STAMP=1:  authored stamp library per 16m slot (pure function)
BUCKET_MODE = os.environ.get("SANCTUM_BUCKET", "").strip() in ("1", "true", "yes")
STAMP_MODE = os.environ.get("SANCTUM_STAMP", "").strip() in ("1", "true", "yes")


# -- Kind properties (same as godot_export.py) --------------------------------

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

# Per-kind behavior type and decay stage (from kind_config.json)
KIND_BEHAVIOR = {
    "beetle": "scurry", "rat": "scurry", "spider": "crawl",
    "firefly": "drift", "leaf": "drift",
}
KIND_DECAY = {
    "dead_log": 0.3, "leaf_pile": 0.5, "bone_pile": 0.6,
}

COLLISION_RADII = {k: v for k, v in HARD_OBJECTS.items()}


# -- Multi-tile world ---------------------------------------------------------

class BrainWorld:
    """Manages multiple tiles, spatial hash, wake chain, and tension cycle."""

    def __init__(self, biome_name, base_seed=42, tile_size=288.0):
        self.biome_name = biome_name
        self.base_seed = base_seed
        self.tile_size = tile_size

        # Set active biome for SpectrumEngine profile lookup
        set_active_biome(biome_name)

        # Activate macro stamp for terrain elevation
        biome_reg = BIOME_REGISTRY.get(biome_name, {})
        macro_stamps = biome_reg.get("macro_stamps", [])
        if macro_stamps:
            set_active_stamp(macro_stamps[0], tile_size)

        # Spatial indexing
        chain_key = biome_name if biome_name in WAKE_CHAINS else "outdoor"
        self.wake_chain = WakeChain(WAKE_CHAINS[chain_key])
        self.spatial = SpatialHash(cell_size=20.0)

        # Tension cycle — board immediately for live atmosphere
        cycle_cfg = OUTDOOR_CYCLE if biome_name == "outdoor" else CAVERN_CYCLE
        self.tension = TensionCycle(cycle_cfg)
        self.tension.board()

        # Chronometer — real-time binding, no game clock
        self.chronometer = Chronometer()

        # SpectrumEngine elapsed counter (for hue drift)
        self.spectrum_elapsed = 0.0

        # Tile variant tracking — per (tx,ty) → variant name
        self.tile_variants = {}

        # Dissociation state — tracked per frame, read by get_manifest
        self.dwell_time = 0.0
        self.dissociation_pressure = 0.0

        # Plane-attachment architecture (Design Law #14, Phase 3).
        # Biome-declared planes streamed to the viewer; renderer instantiates
        # one MeshInstance3D per entry. Adding a plane is a pure config edit.
        self.planes = BIOME_REGISTRY.get(biome_name, {}).get("planes", [])

        # Ceiling height — resolved from biome planes config.
        # Ceiling_moss and hanging_vine attach relative to this.
        self.ceiling_y = 15.0  # fallback
        for plane in self.planes:
            if plane.get("kind") == "ceiling":
                self.ceiling_y = plane.get("offset", 15.0)
                break

        # Light states
        self.light_states = OUTDOOR_LIGHT_STATES if biome_name == "outdoor" else CAVERN_LIGHT_STATES
        self.light_state_names = list(self.light_states.keys())
        self.light_state_idx = 1 if biome_name == "outdoor" else 0  # dusk / cave

        # Entity storage (legacy — kept for compatibility with non-exchange paths)
        self.entities = {}       # eid → entity dict (for manifest)
        self.spawns = {}         # eid → (kind, x, y, z, heading, seed)
        self.loaded_tiles = set()
        self.next_eid = 0
        # Structural anchor positions — for boulder proximity checks.
        # Built incrementally as tiles load. (kind, x, y)
        self._structural_positions = []

        # TileExchange — the endocrine system. Generates, caches, scores,
        # and gates entity delivery. Replaces ensure_tiles_around + wake query.
        self.exchange = TileExchange(biome_name, base_seed, tile_size)

        # Generate center tile (legacy path seeds spatial hash for extended skeleton query)
        self._generate_tile(0, 0)

    def _tile_key(self, cam_x, cam_y):
        return (int(math.floor(cam_x / self.tile_size)),
                int(math.floor(cam_y / self.tile_size)))

    def _generate_tile(self, tx, ty):
        if (tx, ty) in self.loaded_tiles:
            return
        self.loaded_tiles.add((tx, ty))

        # Deterministic seed per tile
        seed = self.base_seed + tx * 7919 + ty * 6271
        rng = random.Random(seed)

        # Pick macro stamp for this tile — spawn tile gets first pattern,
        # others rotate through available patterns by seed.
        biome_reg = BIOME_REGISTRY.get(self.biome_name, {})
        macro_stamps = biome_reg.get("macro_stamps", [])
        ms = None
        if macro_stamps:
            ms = macro_stamps[0] if (tx == 0 and ty == 0) else \
                 macro_stamps[seed % len(macro_stamps)]

        variant_name, tile_spawns = generate_tile(
            seed=seed, biome_name=self.biome_name, tile_size=self.tile_size,
            is_spawn_tile=(tx == 0 and ty == 0), macro_stamp=ms)
        self.tile_variants[(tx, ty)] = variant_name

        offset_x = tx * self.tile_size
        offset_y = ty * self.tile_size
        half = self.tile_size / 2.0

        # Pre-pass: collect structural anchor positions for this tile so
        # boulder proximity logic can reference them. O(n) over tile spawns.
        _STRUCTURAL_KINDS = {"column", "mega_column", "buttress"}
        for spawn in tile_spawns:
            sk, (slx, sly), _, _, _ = spawn
            if sk in _STRUCTURAL_KINDS:
                sx_pos = slx - half + offset_x
                sy_pos = sly - half + offset_y
                self._structural_positions.append((sk, sx_pos, sy_pos))

        for spawn in tile_spawns:
            # Spawns are 5-tuples: (kind, (x,y), heading, seed, metadata_or_None)
            kind, (lx, ly), heading, kseed, meta = spawn
            props = KIND_PROPS.get(kind)
            if not props:
                continue

            # World-space position (centered tiles)
            x = lx - half + offset_x
            y = ly - half + offset_y
            z = terrain_height(x, y)  # rolling elevation field
            if kind == "leaf":
                z = 3.0
            elif kind == "ceiling_moss":
                # Attach to ceiling plane — hang just below the surface.
                # Small offset variance so they don't form a flat grid.
                z = self.ceiling_y - rng.uniform(0.5, 2.0)
            elif kind == "hanging_vine":
                # Vines dangle from ceiling, tips reach lower than moss
                z = self.ceiling_y - rng.uniform(3.0, 8.0)
            elif kind == "filament":
                z = rng.uniform(1.0, 4.0)
            elif kind == "firefly":
                z = rng.uniform(0.5, 2.5)

            # Per-seed variation
            srng = random.Random(kseed)
            sv = srng.uniform(0.75, 1.25) * 1.30  # global scale boost — exaggerated but believable

            # Boulder 75/25 split: 25% stay small IF near a structural anchor.
            # Small boulders read as debris at the base of columns/mega_columns.
            # The 75% that aren't near anchors get full (upgraded) scale.
            if kind == "boulder":
                near_anchor = False
                for ak, ax, ay, *_ in self._structural_positions:
                    dx, dy = x - ax, y - ay
                    if dx * dx + dy * dy < 64.0:  # 8m radius
                        near_anchor = True
                        break
                if near_anchor and srng.random() < 0.75:
                    # Shrink to ~80% of original pre-upgrade size
                    sv *= 0.64

            # Crystal size variation: 10% render as small fragments (0.5x scale).
            # Creates geological scatter — big formations + small debris.
            if kind == "crystal_cluster" and srng.random() < 0.10:
                sv *= 0.5

            # Vine/moss attachment: snap to nearest structural surface.
            # Instead of floating mid-air, drape on the closest column/stalag.
            if kind in ("hanging_vine", "ceiling_moss"):
                best_dist2 = 900.0  # 30m max search radius
                snap_x, snap_y = x, y
                for ak, ax, ay in self._structural_positions:
                    dx, dy = x - ax, y - ay
                    d2 = dx * dx + dy * dy
                    if d2 < best_dist2 and d2 > 1.0:  # not ON the anchor
                        best_dist2 = d2
                        # Snap toward anchor surface — offset by ~2m from center
                        dist = math.sqrt(d2)
                        frac = min(1.0, 2.5 / dist)  # move toward anchor
                        snap_x = x + (ax - x) * frac
                        snap_y = y + (ay - y) * frac
                x, y = snap_x, snap_y

            sx, sy_s, sz = props["scale"]
            r, g, b = props["color"]

            # Light hue index — which color from LIGHT_LAYERS this emissive rolls
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
                "tile_variant": self.tile_variants.get((tx, ty), "standard"),
                "behavior_type": KIND_BEHAVIOR.get(kind, ""),
                "decay_stage": KIND_DECAY.get(kind, 0.0),
            }

            # Ceiling-attached kinds — tag so Godot skips contact shadows
            if kind in ("ceiling_moss", "hanging_vine"):
                ent["attachment_plane"] = "ceiling"

            # Stalactite inversion — brain owns this decision so buttresses
            # and other formation logic can respect it. Same hash Godot used
            # to use, now authoritative from the brain side.
            if kind in ("mega_column", "column"):
                variant_hash = abs(math.sin(x * 2.71 + y * 5.43))
                if variant_hash < 0.40:
                    ent["attachment_plane"] = "ceiling"
                else:
                    ent["attachment_plane"] = "floor"

            # Emissive inversion — stagger light sources between floor and
            # ceiling planes. Same competing strategy as column/stalactite.
            # ~30% of crystal_cluster and giant_fungus flip to ceiling.
            # Creates the bloom-from-above that competes with floor pools.
            if kind in ("crystal_cluster", "giant_fungus"):
                emissive_hash = abs(math.sin(x * 3.91 + y * 7.23))
                if emissive_hash < 0.30:
                    ent["attachment_plane"] = "ceiling"
                    ent["z"] = round(self.ceiling_y - rng.uniform(0.5, 2.0), 2)

            # Buttress metadata — lean angle, stretch axes (for renderer tilt)
            if meta and kind == "buttress":
                ent["lean_angle"] = round(meta.get("lean_angle", 0.0), 1)
                ent["scale_x"] = round(meta.get("scale_x", 1.0), 3)
                ent["scale_y"] = round(meta.get("scale_y", 1.0), 3)
                ent["scale_z"] = round(meta.get("scale_z", 1.0), 3)
                ent["formation"] = meta.get("formation", "")

            # Formation-scaled mega_column — columns inside formations get shrunk
            # so buttress arms dominate the silhouette (column is the PEAK, not the mass)
            if meta and kind == "mega_column" and "formation_scale_mult" in meta:
                mult = meta["formation_scale_mult"]
                ent["sx"] = round(ent["sx"] * mult, 3)
                ent["sy"] = round(ent["sy"] * mult, 3)
                ent["sz"] = round(ent["sz"] * mult, 3)
                ent["formation"] = meta.get("formation", "")

            # Overhead cluster z-offset (hanging_vine / ceiling_moss from ceilings)
            if meta and "cluster_z_offset" in meta:
                ent["z"] = round(ent["z"] + meta["cluster_z_offset"], 2)

            # Satellite scale multiplier (fungus satellites, etc.)
            if meta and "scale_mult" in meta and kind != "mega_column":
                mult = meta["scale_mult"]
                ent["sx"] = round(ent["sx"] * mult, 3)
                ent["sy"] = round(ent["sy"] * mult, 3)
                ent["sz"] = round(ent["sz"] * mult, 3)

            # Colony center tag — ceiling_moss primary blobs get beacon preference
            if meta and meta.get("colony_center"):
                ent["colony_center"] = True

            # Stamp composition scale multiplier
            if meta and "stamp_scale_mult" in meta:
                mult = meta["stamp_scale_mult"]
                ent["sx"] = round(ent["sx"] * mult, 3)
                ent["sy"] = round(ent["sy"] * mult, 3)
                ent["sz"] = round(ent["sz"] * mult, 3)

            eid = self.next_eid
            self.next_eid += 1
            self.entities[eid] = ent
            self.spawns[eid] = (kind, x, y, z, heading, kseed)

            chain_idx = self.wake_chain.chain_index(kind)
            self.spatial.insert(eid, x, y, chain_index=chain_idx)

    def ensure_tiles_around(self, cam_x, cam_y, radius=1):
        """Generate tiles in a grid around camera position."""
        ctx, cty = self._tile_key(cam_x, cam_y)
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                self._generate_tile(ctx + dx, cty + dy)

    def get_manifest(self, cam_x, cam_y, cam_z, heading, pitch, dt):
        """Compute visible entities and atmosphere for current camera.

        Entity delivery is handled by the TileExchange — it generates tiles,
        caches rosters, scores entities by priority, and gates to budget.
        This method handles the per-frame work: render shells, spectrum drift,
        tension, beacon clustering, light baking, and manifest assembly.
        """
        # Camera velocity estimate (for exchange scoring)
        if not hasattr(self, '_prev_cam'):
            self._prev_cam = (cam_x, cam_y)
        vel_x = (cam_x - self._prev_cam[0]) / max(dt, 0.001)
        vel_y = (cam_y - self._prev_cam[1]) / max(dt, 0.001)
        self._prev_cam = (cam_x, cam_y)

        # Entity delivery — three modes, A/B/C testable.
        if STAMP_MODE:
            radius = self.exchange.config.get("render_horizon", 49)
            exchange_entities = stamp_get_visible(
                cam_x, cam_y, radius, self.base_seed, self.biome_name)
        elif BUCKET_MODE:
            radius = self.exchange.config.get("render_horizon", 49)
            exchange_entities = bucket_get_visible(
                cam_x, cam_y, radius, self.base_seed, self.biome_name)
        else:
            # Deep copy: brain mutates entities (render_shell, spectrum_state,
            # render_tier) and those mutations must NOT bleed back into the
            # exchange cache. Shallow dict copy per entity is sufficient —
            # nested values (lists) are replaced not mutated.
            exchange_entities = [
                dict(e) for e in self.exchange.get_entities(
                    cam_x, cam_y, cam_z, heading, vel_x, vel_y)
            ]

        # Accumulate elapsed time for spectrum drift
        self.spectrum_elapsed += dt

        # Chronometer — real time of day
        chrono_state = self.chronometer.read()

        # Tension cycle tick
        entity_count = len(exchange_entities)
        budget_max = self.tension._config.get("budget_max", 800)
        envelope = self.tension.tick(dt, entity_count, budget_max)

        # Current light state (base values)
        ls = self.light_states[self.light_state_names[self.light_state_idx]]

        # Tension envelope overrides fog/ambient when active,
        # but clamped to floors so player can always navigate the scene.
        # Min ambient keeps silhouettes readable; min fog_far keeps depth usable.
        AMBIENT_FLOOR = (0.30, 0.28, 0.25)
        FOG_FAR_FLOOR = 55.0
        FOG_NEAR_CEIL = 12.0  # don't let fog pull closer than 12m
        if self.tension.active and envelope:
            fog_near = max(envelope.fog[0], FOG_NEAR_CEIL)
            fog_far = max(envelope.fog[1], FOG_FAR_FLOOR)
            amb = envelope.ambient
            ambient = [
                max(amb[0], AMBIENT_FLOOR[0]),
                max(amb[1], AMBIENT_FLOOR[1]),
                max(amb[2], AMBIENT_FLOOR[2]),
            ]
        else:
            fog_near = ls["fog_near"]
            fog_far = ls["fog_far"]
            ambient = list(ls["ambient"])

        # Build entity list with baked light tints
        EMISSIVE_LIGHT_COLORS = {
            "crystal_cluster": (0.25, 0.30, 0.55),
            "giant_fungus":    (0.15, 0.25, 0.08),
            "moss_patch":      (0.08, 0.30, 0.06),
            "firefly":         (0.50, 0.40, 0.15),
            "filament":        (0.20, 0.30, 0.40),
            "ceiling_moss":    (0.40, 0.28, 0.10),
        }

        # Spectrum profile mapping — emissive kind → SpectrumEngine profile name
        SPECTRUM_MAP = {
            "crystal_cluster": "crystal", "filament": "crystal",
            "exit_lure": "crystal",
            "giant_fungus": "fungus", "ceiling_moss": "fungus",
            "moss_patch": "moss", "firefly": "moss",
        }

        # Exchange already delivered scored, gated, below-ground-culled entities.
        # Now apply per-frame render processing: shells, spectrum, emissive tagging.
        # Strip exchange-internal fields before streaming to Godot.
        visible = []
        emissives = []
        for ent in exchange_entities:
            ent.pop("_chain_index", None)
            # Render shell assignment — distance + kind class determines
            # which shell this entity belongs to.
            dx_s = ent["x"] - cam_x
            dy_s = ent["y"] - cam_y
            dist = (dx_s * dx_s + dy_s * dy_s) ** 0.5
            kind_class = KIND_RENDER_CLASS.get(ent["kind"], "scatter")
            shell_idx = 6  # default: outermost (void)
            for si, shell in enumerate(RENDER_SHELLS):
                if dist <= shell["radius"]:
                    shell_idx = si
                    break
            # Skip if this kind class isn't rendered in this shell
            if kind_class not in RENDER_SHELLS[shell_idx]["kind_classes"]:
                continue
            ent["render_shell"] = shell_idx
            ent["render_mode"] = RENDER_SHELLS[shell_idx]["mode"]

            # Spectrum state for emissive kinds — hue drift via SpectrumEngine
            spec_profile = SPECTRUM_MAP.get(ent["kind"])
            if spec_profile and ent.get("emissive", 0) > 0:
                seed = hash((ent["x"], ent["y"])) & 0xFFFF
                r_s, g_s, b_s = SpectrumEngine.drift(
                    spec_profile, self.spectrum_elapsed, seed)
                ent["spectrum_state"] = [
                    round(r_s, 4), round(g_s, 4), round(b_s, 4)]
            visible.append(ent)
            if ent["kind"] in EMISSIVE_LIGHT_COLORS:
                emissives.append((ent["x"], ent["y"], EMISSIVE_LIGHT_COLORS[ent["kind"]]))

        # Phase 1.5: Merkabah plane-attachment — annotate each visible entity
        # with its layer membership based on distance to the observer (camera).
        # classify_all_entities mutates entities in place, adding a
        # 'layer_membership' dict (e.g. {"near": 1.0} or {"mid": 0.5, "far": 0.5}).
        # The wheels turn: entities migrate between Hekhalot halls as the throne moves.
        classify_all_entities(visible, observer_x=cam_x, observer_y=cam_y,
                              nodes=CAVERN_EXCHANGE_NODES)

        # Beacon hierarchy — tag emissive entities with render_tier based on
        # distance to camera and angle to forward vector. Godot uses this to
        # allocate expensive rendering (lights, decals, motes) only to beacons.
        # tier 0 = beacon (full treatment), 1 = mid (decal only), 2 = far (glow only)
        heading_rad = math.radians(heading)
        fwd_x = math.sin(heading_rad)
        fwd_y = -math.cos(heading_rad)
        emissive_scored = []
        for ent in visible:
            if ent.get("emissive", 0) <= 0:
                continue
            dx = ent["x"] - cam_x
            dy = ent["y"] - cam_y
            dist = (dx*dx + dy*dy) ** 0.5
            if dist < 0.1:
                dist = 0.1
            # Dot product with forward vector — prefer emissives in view
            dot_fwd = (dx * fwd_x + dy * fwd_y) / dist
            # Score: closer + more forward = lower score = higher priority
            score = dist * (1.0 - dot_fwd * 0.3)
            emissive_scored.append((score, dist, ent))
        emissive_scored.sort(key=lambda x: x[0])

        # Cluster emissives before assigning beacons — nearby emissives share
        # one beacon slot instead of each burning a slot individually. One
        # OmniLight at the cluster center covers 3-4 glowing objects.
        CLUSTER_RADIUS = 8.0  # meters — emissives within this share a beacon
        clusters = []  # list of {"center": (x,y,z), "members": [ent...], "score": float, "is_ceiling": bool}
        clustered = set()
        for idx, (score, dist, ent) in enumerate(emissive_scored):
            if idx in clustered:
                continue
            cx, cy, cz = ent["x"], ent["y"], ent.get("z", 0.0)
            is_ceil = ent.get("attachment_plane", "") == "ceiling"
            members = [ent]
            clustered.add(idx)
            # Pull in nearby same-plane emissives
            for j, (s2, d2, e2) in enumerate(emissive_scored):
                if j in clustered:
                    continue
                if (e2.get("attachment_plane", "") == "ceiling") != is_ceil:
                    continue  # don't mix floor and ceiling
                ddx, ddy = e2["x"] - cx, e2["y"] - cy
                if ddx * ddx + ddy * ddy < CLUSTER_RADIUS * CLUSTER_RADIUS:
                    members.append(e2)
                    clustered.add(j)
            # Cluster center = average position of members
            avg_x = sum(e["x"] for e in members) / len(members)
            avg_y = sum(e["y"] for e in members) / len(members)
            avg_z = sum(e.get("z", 0.0) for e in members) / len(members)
            clusters.append({
                "center": (avg_x, avg_y, avg_z),
                "members": members,
                "score": score,  # use best member's score
                "is_ceiling": is_ceil,
                "size": len(members),
            })

        # Sort clusters: prefer larger clusters (more bang per beacon slot)
        # and closer ones. Score = original_score / sqrt(member_count).
        for c in clusters:
            c["beacon_score"] = c["score"] / (c["size"] ** 0.5)
        clusters.sort(key=lambda c: c["beacon_score"])

        # Guarantee ceiling representation: at least 2 ceiling, at least 2 floor
        ceil_clusters = [c for c in clusters if c["is_ceiling"]]
        floor_clusters = [c for c in clusters if not c["is_ceiling"]]

        beacon_clusters = []
        for c in ceil_clusters[:2]:
            beacon_clusters.append(c)
        for c in floor_clusters:
            if len(beacon_clusters) >= 6:
                break
            beacon_clusters.append(c)
        # Fill remaining with best overall
        for c in clusters:
            if len(beacon_clusters) >= 6:
                break
            if c not in beacon_clusters:
                beacon_clusters.append(c)

        # Assign tiers: beacon cluster members get tier 0, rest get 1 or 2
        beacon_member_ids = set()
        for c in beacon_clusters:
            for e in c["members"]:
                e["render_tier"] = 0
                # Store cluster center so Godot can use it for light placement
                e["cluster_center"] = list(c["center"])
                beacon_member_ids.add(id(e))

        for score, dist, ent in emissive_scored:
            if id(ent) in beacon_member_ids:
                continue
            if dist < 25.0:
                ent["render_tier"] = 1
            else:
                ent["render_tier"] = 2

        # Bake light influence: tint non-emissive entities from nearby emissives
        for i in range(len(visible)):
            ent = visible[i]
            if ent.get("emissive", 0) > 0:
                continue
            lr, lg, lb = 0.0, 0.0, 0.0
            ex, ey = ent["x"], ent["y"]
            for lx, ly, (cr, cg, cb) in emissives:
                dx, dy = ex - lx, ey - ly
                dist = (dx*dx + dy*dy) ** 0.5
                if dist < 12.0:
                    influence = (1.0 - dist / 12.0) ** 2 * 0.35
                    lr += cr * influence
                    lg += cg * influence
                    lb += cb * influence
            if lr > 0.001 or lg > 0.001 or lb > 0.001:
                tinted = dict(ent)
                tinted["r"] = round(min(1.0, ent["r"] + lr), 3)
                tinted["g"] = round(min(1.0, ent["g"] + lg), 3)
                tinted["b"] = round(min(1.0, ent["b"] + lb), 3)
                visible[i] = tinted

        return {
            "camera": {"x": cam_x, "y": cam_y, "z": cam_z,
                       "heading": heading, "pitch": pitch,
                       "terrain_z": terrain_height(cam_x, cam_y)},
            "fog": {
                "near": fog_near,
                "far": fog_far,
                "color": list(ls["fog_color"]),
            },
            "ambient": ambient,
            "bg_color": list(ls["bg_color"]),
            "sun": {
                "color": list(ls.get("sun_color", [0, 0, 0])),
                "scale": ls.get("sun_scale", 0.0),
            },
            "moon": {
                "color": list(ls.get("moon_color", [0, 0, 0])),
                "scale": ls.get("moon_scale", 0.0),
            },
            "entities": visible,
            "planes": self.planes,
            "banner_layers": BIOME_REGISTRY.get(self.biome_name, {}).get("banner_layers", []),
            "biome": self.biome_name,
            "tension_state": self.tension.state,
            "tension_budget": round(self.tension.budget, 3),
            "tension_envelope": {
                "lerp_t": round(envelope.lerp_t, 3) if envelope else 1.0,
                "transitioning": envelope.transitioning if envelope else False,
                "should_dump": envelope.should_dump if envelope else False,
                "dissociating": self.dwell_time > 7.0,
                "dwell_time": round(self.dwell_time, 1),
                "pressure": round(self.dissociation_pressure, 3),
            },
            "chronometer": {
                "time_of_day": round(chrono_state["time_of_day"], 4),
                "day_phase": chrono_state["day_phase"],
                "night_weight": round(chrono_state["night_weight"], 3),
                "dawn_weight": round(chrono_state["dawn_weight"], 3),
                "dusk_weight": round(chrono_state["dusk_weight"], 3),
                "moon_approx": round(chrono_state["moon_approx"], 3),
                "season": round(chrono_state["season"], 3),
            },
            "stats": {
                "visible": len(visible),
                "total": sum(len(r) for r in self.exchange._tile_cache.values()),
                "tiles": len(self.exchange._tile_cache),
                "exchange_budget": self.exchange.config["delivery_budget"],
            },
        }

    def cycle_light_state(self):
        """Advance to next light state (L key)."""
        self.light_state_idx = (self.light_state_idx + 1) % len(self.light_state_names)
        name = self.light_state_names[self.light_state_idx]
        print(f"  Light state: {name}", flush=True)
        return name


# -- TCP server ---------------------------------------------------------------

def run_server(biome_name, port=9877):
    world = BrainWorld(biome_name)

    # Expedition engine — authored encounter/session loop that rides
    # on top of the manifest. Lazily built per client connection so
    # each brain→Godot session gets a fresh state machine. v1 ships
    # anomaly_hunt for cavern; outdoor binding is stubbed empty and
    # will raise at construction until the outdoor hub lands, which
    # is the correct fail-fast behavior.
    expedition: ExpeditionEngine | None = None

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)
    sock.setblocking(False)

    stats = world.get_manifest(0, 0, 2.5, 0, 0, 0)["stats"]
    print(f"Brain server ready on :{port} | {biome_name} | "
          f"{stats['total']} entities, {stats['tiles']} tiles", flush=True)
    print("Waiting for Godot to connect...", flush=True)

    client = None
    buf = b""
    last_wake_ids = set()

    # Dissociation detector — tension triggered by absence of input
    prev_cam = (0.0, 0.0, 0.0, 0.0)  # x, y, heading, pitch
    DWELL_THRESHOLD = 0.15    # movement+look delta below this = "still"
    DISSOCIATE_ONSET = 7.0    # seconds before tension starts building
    DISSOCIATE_RATE = 0.08    # budget push per second while dissociating

    try:
        while True:
            # Accept new connections
            if client is None:
                try:
                    client, addr = sock.accept()
                    client.setblocking(False)
                    buf = b""
                    last_wake_ids = set()
                    print(f"  Godot connected from {addr}", flush=True)

                    # Fresh expedition engine per session. Failure to
                    # instantiate (e.g. biome has no anchor bindings
                    # declared yet) is non-fatal — the brain just
                    # runs without an expedition this session and
                    # Godot sees an absent manifest['expedition'].
                    try:
                        expedition = ExpeditionEngine.from_class_id(
                            "anomaly_hunt", biome_name)
                        expedition.on_session_start(time.time())
                        print(f"  Expedition: anomaly_hunt (biome={biome_name})",
                              flush=True)
                    except Exception as exc:
                        expedition = None
                        print(f"  Expedition disabled: {exc}", flush=True)
                except BlockingIOError:
                    time.sleep(0.016)
                    continue

            # Read from client
            try:
                data = client.recv(8192)
                if not data:
                    print("  Godot disconnected", flush=True)
                    client.close()
                    client = None
                    expedition = None
                    continue
                buf += data
            except BlockingIOError:
                pass
            except (ConnectionResetError, BrokenPipeError):
                print("  Godot disconnected (reset)", flush=True)
                client.close()
                client = None
                expedition = None
                continue

            # Process complete lines — drain all, but only act on the
            # LATEST camera update. Commands (light_cycle etc.) are processed
            # immediately. This prevents stall cascades: if tile generation
            # takes 1s, 10 queued camera updates are skipped to the newest.
            latest_cam_msg = None
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Handle commands immediately (they're rare and cheap)
                if msg.get("cmd") == "light_cycle":
                    name = world.cycle_light_state()
                    last_wake_ids = set()
                    continue

                if msg.get("cmd") == "tension_toggle":
                    # If dissociating, B is the release valve — snap out of it
                    if world.dissociation_pressure > 0.01:
                        world.dissociation_pressure = 0.0
                        world.tension._dissociation_pressure = 0.0
                        world.dwell_time = 0.0
                        world.tension.force_state("rebirth")
                        print("  Tension RELEASED (dissociation broken)", flush=True)
                    else:
                        world.tension.toggle()
                        print(f"  Tension: {'ON' if world.tension.active else 'OFF'}", flush=True)
                    last_wake_ids = set()
                    continue

                if msg.get("cmd") == "tension_advance":
                    world.tension.force_advance()
                    print(f"  Tension → {world.tension.state}", flush=True)
                    last_wake_ids = set()
                    continue

                # ---- Expedition commands -------------------------------
                # These ride on the same wire as the other cmd handlers
                # above; no new socket, no new protocol. The payload
                # shapes match what expedition_engine expects.

                if msg.get("cmd") == "tag_event":
                    if expedition is not None:
                        tag = msg.get("tag", {})
                        expedition.on_tag_event(tag, time.time())
                        # Force manifest resend so snapshot's updated
                        # last_message reaches Godot immediately.
                        last_wake_ids = set()
                    continue

                if msg.get("cmd") == "deposit_intent":
                    if expedition is not None:
                        result = expedition.on_deposit_intent(
                            msg.get("deposit_id", ""),
                            int(msg.get("tag_id", -1)),
                            time.time())
                        # Ack includes the deposit delta so Godot can
                        # update locally without waiting for the next
                        # manifest if needed.
                        try:
                            ack = json.dumps({
                                "deposit_result": result,
                            }) + "\n"
                            client.sendall(ack.encode("utf-8"))
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        last_wake_ids = set()  # force manifest refresh
                    continue

                if msg.get("cmd") == "walk_through":
                    if expedition is not None:
                        result = expedition.on_walk_through(
                            time.time(), SESSIONS_DIR)
                        if result.get("resolution") == "complete":
                            # The post-mortem trigger line I watch for
                            # in `make brain-cavern` console output.
                            tag_count = len(expedition.tag_log)
                            log_path = result.get("log_path", "<none>")
                            print(
                                f">>> EXPEDITION COMPLETE: {tag_count} tags, "
                                f"{log_path}", flush=True)
                        try:
                            ack = json.dumps(result) + "\n"
                            client.sendall(ack.encode("utf-8"))
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        last_wake_ids = set()  # force final manifest
                    continue

                # Camera update — stash, only process the latest after drain
                latest_cam_msg = msg

            # Process only the latest camera update (skip stale queued ones)
            if latest_cam_msg is not None:
                msg = latest_cam_msg
                latest_cam_msg = None

                cam_x = msg.get("cam_x", 0.0)
                cam_y = msg.get("cam_y", 0.0)
                cam_z = msg.get("cam_z", 2.5)
                heading = msg.get("heading", 0.0)
                pitch = msg.get("pitch", 0.0)
                dt = msg.get("dt", 0.016)

                # Dissociation detection — the cave notices you stopped
                dx = abs(cam_x - prev_cam[0])
                dy = abs(cam_y - prev_cam[1])
                dh = abs(heading - prev_cam[2])
                if dh > 180.0:
                    dh = 360.0 - dh
                dp = abs(pitch - prev_cam[3])
                input_delta = dx + dy + dh * 0.05 + dp * 0.05
                prev_cam = (cam_x, cam_y, heading, pitch)

                if input_delta < DWELL_THRESHOLD:
                    world.dwell_time += dt
                    if world.dwell_time > DISSOCIATE_ONSET and world.tension.active:
                        world.dissociation_pressure += DISSOCIATE_RATE * dt
                        world.tension._dissociation_pressure = world.dissociation_pressure
                else:
                    world.dwell_time = max(0.0, world.dwell_time - dt * 3.0)
                    world.dissociation_pressure = max(
                        0.0, world.dissociation_pressure - dt * 0.5)
                    world.tension._dissociation_pressure = world.dissociation_pressure

                manifest = world.get_manifest(
                    cam_x, cam_y, cam_z, heading, pitch, dt)

                # Attach expedition snapshot to manifest. This is the
                # render-manifest doctrine: brain owns state, manifest
                # carries it, Godot paints what it sees. Godot has no
                # recipe-specific knowledge — it reads
                # manifest['expedition'] and draws generically.
                #
                # Diagnostic gate: set SANCTUM_EXPEDITION=0 to disable
                # the manifest field (engine still runs brain-side, but
                # Godot doesn't see it). Isolates expedition-side
                # crashes from rendering crashes.
                expedition_visible = os.environ.get("SANCTUM_EXPEDITION", "1") != "0"
                if expedition is not None and expedition_visible:
                    manifest["expedition"] = expedition.snapshot()

                wake_ids = frozenset(
                    (e.get("kind",""), round(e.get("x",0),1), round(e.get("y",0),1))
                    for e in manifest["entities"])
                # If expedition has a pending message, force a full
                # resend so Godot gets the toast without waiting for
                # the wake set to change. Also clear the pending
                # message key after the send so the next frame's
                # snapshot has last_message=None and we don't toast
                # twice for the same key.
                has_pending_message = (
                    expedition is not None
                    and expedition.pending_message_key is not None)
                if wake_ids == last_wake_ids and not has_pending_message:
                    response = json.dumps({"unchanged": True}) + "\n"
                else:
                    last_wake_ids = wake_ids
                    response = json.dumps(manifest) + "\n"

                try:
                    client.sendall(response.encode("utf-8"))
                except (BrokenPipeError, ConnectionResetError):
                    print("  Godot disconnected (write)", flush=True)
                    client.close()
                    client = None
                    expedition = None
                    break

                # After the full manifest has shipped, clear the
                # expedition's pending message so it's not re-toasted
                # on the next frame.
                if expedition is not None and has_pending_message:
                    expedition.consume_message()

    except KeyboardInterrupt:
        print("\nShutting down...", flush=True)
    finally:
        if client:
            client.close()
        sock.close()


def main():
    biome_name = sys.argv[1] if len(sys.argv) > 1 else "outdoor"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9877
    run_server(biome_name, port)


if __name__ == "__main__":
    main()
