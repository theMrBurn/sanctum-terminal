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
from typing import Optional

from core.systems.biome_data import (
    BIOME_REGISTRY,
    HARD_OBJECTS,
    RENDER_SHELLS, KIND_RENDER_CLASS,
)
from core.systems.spatial_wake import SpatialHash, WakeChain, WAKE_CHAINS
from core.systems.world_gen import generate_tile
from core.systems.tension_cycle import TensionCycle
from core.systems.plane_exchange import classify_all_entities, CAVERN_EXCHANGE_NODES
from core.systems.chronometer import Chronometer
from core.systems.ambient_life import SpectrumEngine, set_active_biome
from core.systems import player_state as ps
from core.systems.player_state import PlayerState, Item
from core.systems import game_state as gs
from core.systems.game_state import GameState
from core.systems import save_state
from core.systems.macro_stamp import (
    terrain_height, set_active_stamp, grid_density, grid_allowed,
)
from core.systems.biome_data import MACRO_STAMP_CAVERN_CHAMBER
from core.systems.tile_exchange import TileExchange
from core.systems.bucket_world import get_visible as bucket_get_visible
from core.systems.stamp_world import get_visible as stamp_get_visible

# Character creation primitives — `design_character_sheet`, `design_seven_pillars`,
# `design_dial_input`, `design_character_draft`. The schema, the dial input shape,
# the event-sourced draft, and the pillar handler registry.
from core.systems import pillars as pillars_registry
from core.systems.character_draft import CharacterDraft
from core.systems.character_sheet import CharacterSheet
from core.systems.dial_prompt import DialPrompt, to_manifest as dial_to_manifest
from datetime import date
from core.systems.expedition_engine import ExpeditionEngine
from core.systems.expedition_data import BIOME_EXPEDITIONS
from core.systems.encounter_session import EncounterSession
from core.systems.roaming_pool import RoamingPool
from core.systems import kind_config as _kc
from core.systems import verbs as _verbs
from pathlib import Path


# spatial_class derived sets — see tile_exchange.py for the rule.
# spike: inversion-capable per-instance (stalactites)
# companion: inherits attachment_plane from nearby spike host; never
# independently inverts. Kills incoherent mixed-orientation clusters.
_SPIKE_KINDS_SPATIAL = {k for k, v in _kc.all_kinds().items()
                        if v.get("spatial_class") == "spike"}
_COMPANION_KINDS_SPATIAL = {k for k, v in _kc.all_kinds().items()
                            if v.get("spatial_class") == "companion"}
_HOST_INHERIT_RADIUS_SQ = 8.0 * 8.0
_STALACTITE_HASH_THRESHOLD = 0.40


def _roll_spike_ceiling(x: float, y: float) -> bool:
    """Deterministic stalactite roll — same hash in tile_exchange + Godot."""
    return abs(math.sin(x * 2.71 + y * 5.43)) < _STALACTITE_HASH_THRESHOLD

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

# How close an entity must be to a cast's origin (meters, XZ) to trigger an
# elemental_reaction. Tuned wider than deposit proximity so aimed casts feel
# generous at encounter_test / shadow_lab fixtures. When encounters get
# surgical, migrate this to per-element or per-pattern config.
CAST_REACTION_RADIUS_M: float = 8.0

# Tartarus-style advantage-on-contact.
# Player's facing vector × orb-position vector: if player is lined up on the
# orb's back hemisphere, first_strike. Mirror for ambush.
CONTACT_FACING_DOT_THRESHOLD: float = 0.5    # ~60-degree cone


def _compute_contact_advantage(cam_x: float, cam_y: float,
                               player_rot_y_rad: float,
                               orb_x: float, orb_y: float,
                               orb_heading_rad: float) -> str:
    """Return 'first_strike' | 'ambush' | 'neutral' at the moment of contact.

    Brain XY convention: Godot's (x, z) = brain's (x, y). Camera forward
    vector in brain coords = (-sin(rot_y), -cos(rot_y)). Orb heading is
    already brain-native radians (see RoamingAgent.heading).
    """
    pfx = -math.sin(player_rot_y_rad)
    pfy = -math.cos(player_rot_y_rad)
    ofx = math.cos(orb_heading_rad)
    ofy = math.sin(orb_heading_rad)
    dx = orb_x - cam_x
    dy = orb_y - cam_y
    length = math.sqrt(dx * dx + dy * dy)
    if length < 0.01:
        return "neutral"
    ux, uy = dx / length, dy / length

    player_facing_orb = (pfx * ux + pfy * uy) > CONTACT_FACING_DOT_THRESHOLD
    orb_facing_player = (ofx * (-ux) + ofy * (-uy)) > CONTACT_FACING_DOT_THRESHOLD

    if player_facing_orb and not orb_facing_player:
        return "first_strike"
    if orb_facing_player and not player_facing_orb:
        return "ambush"
    return "neutral"


# -- Kind properties --------------------------------
# Phase 5: KIND_PROPS derived from kind_config.json. Single source of truth.
# In STAMP_MODE this dict is unused (stamp_world reads bucket_world.KIND_PROPS).
# Kept as a shim for any non-STAMP path that imports brain_server.KIND_PROPS.
from core.systems.bucket_world import KIND_PROPS  # noqa: E402  re-export

# Per-kind behavior type and decay stage (from kind_config.json)
KIND_BEHAVIOR = {
    "beetle": "scurry", "rat": "scurry", "spider": "crawl",
    "firefly": "drift", "leaf": "drift",
}
KIND_DECAY = {
    "dead_log": 0.3, "leaf_pile": 0.5, "bone_pile": 0.6,
}

# Phase 2: collision radii primary source is kind_config.json (physics
# block). HARD_OBJECTS in biome_data is now the FALLBACK for any kind
# missing the field. Phase 5 deletes HARD_OBJECTS entirely.
#
# Render-shell class (KIND_RENDER_CLASS) is NOT migrated this phase —
# it's a separate taxonomy from kind_config's semantic 'class' field
# (which keys shader/material selection: geological, organic_flora,
# crystalline). Render-shell membership is biome-rendering concern,
# stays in biome_data for now.
from core.systems import kind_config as _kc

def _collision_radius_for(kind: str) -> float:
    """Primary: kind_config physics.collision_radius. Fallback: HARD_OBJECTS.
    Deprecated path — only kept for legacy callers. New collision emission
    uses VISUAL_RADII × ent.sv per instance (see _make_entity paths)."""
    cfg_kind = _kc.kind(kind)
    cfg_radius = cfg_kind.get("physics", {}).get("collision_radius")
    if cfg_radius is not None:
        return float(cfg_radius)
    return float(HARD_OBJECTS.get(kind, 0.0))

COLLISION_RADII = {k: _collision_radius_for(k) for k in _kc.all_kinds().keys() | HARD_OBJECTS.keys()}

# VISUAL_RADII — nominal hull radius at sv=1.0 from kind_config.visual_radius.
# Single source for BOTH player-stop collision and spawn keep-out. Brain
# multiplies by ent.sv to get per-instance value. Kinds without visual_radius
# (doorframe, creatures, atmosphere) are implicit walk-through (0).
# Player stops only if per-instance radius >= PLAYER_STOP_THRESHOLD.
PLAYER_STOP_THRESHOLD = 0.5

VISUAL_RADII = {k: float(v.get("visual_radius", 0.0))
                for k, v in _kc.all_kinds().items()}


def _player_collision_radius(kind: str, sv: float) -> float:
    """Per-instance player-stop radius. visual_radius × sv, zeroed for
    walk-through kinds (small footprint companions like grass/moss)."""
    r = VISUAL_RADII.get(kind, 0.0) * sv
    return r if r >= PLAYER_STOP_THRESHOLD else 0.0


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
        cycle_cfg = BIOME_REGISTRY[biome_name]["cycle"]
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

        # Brain-global player state (PR 3 of the torch direction). Holds
        # inventory + currently-wielded item. Encounter sessions copy/restore
        # against this on entry/exit (refactor pending). Streamed to Godot
        # via manifest.player so the viewer can render the camera-parented
        # equipped item without round-tripping every frame.
        #
        # L5 — try to load an existing save. If it loads, use it; otherwise
        # build a fresh player and seed it with the UAT fixtures. The load
        # path is silent on missing-file (None return); print on actual hit.
        loaded = save_state.load()
        loaded_player = loaded.player if loaded is not None else None
        loaded_sheet = loaded.character_sheet if loaded is not None else None
        if loaded_player is not None:
            self.player = loaded_player
            sheet_status = (f"sheet={loaded_sheet.name!r} (age {loaded_sheet.age})"
                            if loaded_sheet is not None else "sheet=<none, will run pillar creation>")
            print(
                f"  loaded save: {len(loaded_player.inventory)} items, "
                f"equipped={loaded_player.equipped!r}, "
                f"missions={len(loaded_player.completed_missions)}, {sheet_status}",
                flush=True,
            )
        else:
            self.player = PlayerState.new(seed=base_seed)
            # PR 4 manual UAT — auto-equip a torch + pre-fill 2 healing potions
            # so first-boot exercises the equipped-render and use-key paths.
            # Once a save exists these injections are skipped (the saved
            # inventory drives instead).
            self.player = ps.add_item(self.player, Item(name="torch_handcrafted"))
            self.player = ps.equip(self.player, "torch_handcrafted")
            for _ in range(2):
                self.player = ps.add_item(self.player, Item(name="healing_potion"))

        # Character creation state — `design_seven_pillars`. New player without
        # a save (or a legacy V1 save without a sheet) enters CHARACTER_CREATION
        # with a CharacterDraft. Stub-pillars 2-7 auto-default so player only
        # engages Pillar 1 (Name) for the initial UAT. Real interactive pillars
        # replace stubs in later sessions.
        self.character_sheet: CharacterSheet | None = loaded_sheet
        self.character_draft: CharacterDraft | None = None
        self.active_dial: DialPrompt | None = None

        if loaded_sheet is not None:
            # Returning player with a sealed sheet — straight to HUB.
            self.game_state: GameState = GameState.initial()
        else:
            # Either no save at all, or a legacy V1 save without a sheet.
            # Either way, run the 7-pillar ritual to build a sheet. Stubs 2-7
            # auto-default so only Pillar 1 (Name) requires interaction.
            self.character_draft = self._init_creation_draft()
            self.game_state: GameState = GameState.fresh_character()

        # World regen support (L2). hub_seed preserves the canonical hub world
        # so RESULTS → HUB returns to the same staging area each time. Mission
        # transitions assign a fresh mission_seed that overrides base_seed
        # while IN_MISSION. world_revision bumps on every regen — Godot
        # watches it, re-dispatches spawn, and rebuilds entity render state.
        self.hub_seed: int = base_seed
        self.world_revision: int = 0

        # Mission picker (L6). Derived from BIOME_EXPEDITIONS[biome]. Each
        # active class becomes a mission_id by appending "_01" — same shape
        # the L7 reward path already records into completed_missions, so the
        # picker plugs in without reshaping persistence.
        # selected_mission_id is None outside MISSION_SELECT; set on entry,
        # cycled by mission_select_cycle, consumed at launch.
        self.available_missions: list[str] = [
            f"{cls}_01"
            for cls in BIOME_EXPEDITIONS.get(biome_name, {}).get("active_classes", [])
        ]
        self.selected_mission_id: Optional[str] = None

        # Ceiling height — resolved from biome planes config.
        # Ceiling_moss and hanging_vine attach relative to this.
        self.ceiling_y = 15.0  # fallback
        for plane in self.planes:
            if plane.get("kind") == "ceiling":
                self.ceiling_y = plane.get("offset", 15.0)
                break

        # Light states — starting state looked up by name so biomes with
        # differently-ordered light_states dicts stay stable across refactors.
        biome_reg = BIOME_REGISTRY[biome_name]
        self.light_states = biome_reg["light_states"]
        self.light_state_names = list(self.light_states.keys())
        default_state = biome_reg["default_light_state"]
        self.light_state_idx = self.light_state_names.index(default_state)

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

    def _init_creation_draft(self) -> CharacterDraft:
        """Build a draft pre-stuffed with stub answers for pillars 2-7 so
        the first interactive session only requires Pillar 1 (Name) to
        complete and finalize. As real pillar implementations land, the
        corresponding stub append disappears here; the player then engages
        the real pillar instead. Per `design_seven_pillars` UAT scope.
        """
        draft = CharacterDraft()
        today = date.today()
        draft.append("days", (today.month, today.day))
        draft.append("years", 30)
        draft.append("first_path", "rogue")
        draft.append("vow", "remain")
        draft.append("standing", ["DEX", "WIS", "CHA"])
        draft.append("mark", ["Quiet Tread"])
        return draft

    def regen_world(self, new_seed: int) -> None:
        """Wipe cached world state and reset to a fresh seed (L2).

        The active stamp_world path is pure-function — just updating
        self.base_seed makes the next get_visible() call use the new seed.
        Legacy/exchange paths cache tile data, so we also clear those so
        a non-stamp run regenerates correctly.

        Increments world_revision so Godot can detect the regen and
        re-dispatch spawn (teleport player to spawn location) and rebuild
        its entity render state.
        """
        self.base_seed = new_seed
        self.world_revision += 1
        self.entities.clear()
        self.spawns.clear()
        self.loaded_tiles.clear()
        self.tile_variants.clear()
        self.spatial = SpatialHash(cell_size=20.0)
        self._structural_positions = []
        self.next_eid = 0
        # Rebuild exchange with new seed (legacy-path safety).
        self.exchange = TileExchange(self.biome_name, new_seed, self.tile_size)
        # Re-prime spawn tile so non-stamp paths have entities.
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
        # boulder proximity + companion host-inheritance can reference them.
        # Spike kinds also get their stalactite roll decided here so companion
        # inheritance can read it during the main spawn loop.
        _STRUCTURAL_KINDS = {"column", "mega_column", "buttress"}
        for spawn in tile_spawns:
            sk, (slx, sly), _, _, _ = spawn
            if sk in _STRUCTURAL_KINDS or sk in _SPIKE_KINDS_SPATIAL:
                sx_pos = slx - half + offset_x
                sy_pos = sly - half + offset_y
                is_ceiling = sk in _SPIKE_KINDS_SPATIAL and _roll_spike_ceiling(sx_pos, sy_pos)
                self._structural_positions.append((sk, sx_pos, sy_pos, is_ceiling))

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
                for ak, ax, ay, _ac in self._structural_positions:
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
                "collision_radius": _player_collision_radius(kind, sv),
                "tile_variant": self.tile_variants.get((tx, ty), "standard"),
                "behavior_type": KIND_BEHAVIOR.get(kind, ""),
                "decay_stage": KIND_DECAY.get(kind, 0.0),
            }

            # Ceiling-attached kinds — tag so Godot skips contact shadows
            if kind in ("ceiling_moss", "hanging_vine"):
                ent["attachment_plane"] = "ceiling"

            # Spike inversion — authoritative stalactite roll for the spike
            # spatial_class (mega_column, column, stalagmite). Decision is
            # already in _structural_positions so companions can inherit.
            if kind in _SPIKE_KINDS_SPATIAL:
                ent["attachment_plane"] = "ceiling" if _roll_spike_ceiling(x, y) else "floor"

            # Companion host-inheritance — fungus, grass, moss, etc never
            # flip independently. Find the nearest spike host within
            # _HOST_INHERIT_RADIUS_SQ; if the host is ceiling-attached, the
            # companion inherits ceiling and re-positions below the ceiling
            # plane. Kills the old "upside-down fungus beside upright fungus"
            # incoherence AND enables hanging grass/fungus on stalactite hosts.
            elif kind in _COMPANION_KINDS_SPATIAL:
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

        # Tension modulates scalar-wise onto the light-state baseline, so
        # pressing L (day/dusk/night) stays visually authoritative while
        # tension drives dramatic damping. "open" is the identity state
        # (factor ≈ 1.0); deeper states (tunnel/dump) dim toward darkness.
        #
        # Factor = envelope_ambient_avg / open_state_ambient_avg. Applied as
        # a multiplier on ls["ambient"] so hue stays true to time-of-day
        # and intensity follows tension. Same multiplier reshapes fog.
        AMBIENT_FLOOR = (0.04, 0.04, 0.05)  # silhouettes still read at night
        FOG_NEAR_CEIL = 2.0    # don't let fog touch the camera
        FOG_FAR_FLOOR = 6.0    # always leave a few meters of visibility
        if self.tension.active and envelope:
            open_amb = self.tension._config.get("open", {}).get(
                "ambient", (0.5, 0.5, 0.5))
            open_avg = max(sum(open_amb) / 3.0, 0.01)
            tension_avg = sum(envelope.ambient) / 3.0
            factor = max(tension_avg / open_avg, 0.05)
            ambient = [
                max(ls["ambient"][0] * factor, AMBIENT_FLOOR[0]),
                max(ls["ambient"][1] * factor, AMBIENT_FLOOR[1]),
                max(ls["ambient"][2] * factor, AMBIENT_FLOOR[2]),
            ]
            # Fog: same scalar modulation on ls baseline, but tension
            # envelope's fog_near/fog_far ratios to "open" drive the curve.
            open_fog = self.tension._config.get("open", {}).get(
                "fog", (ls["fog_near"], ls["fog_far"]))
            near_factor = envelope.fog[0] / max(open_fog[0], 0.01)
            far_factor = envelope.fog[1] / max(open_fog[1], 0.01)
            fog_near = max(ls["fog_near"] * near_factor, FOG_NEAR_CEIL)
            fog_far = max(ls["fog_far"] * far_factor, FOG_FAR_FLOOR)
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

        # Synthetic character-creation pillar entities (per `design_seven_pillars`).
        # Injected after exchange_entities so they pass through the manifest
        # the same way ordinary entities do. Only Pillar 1 (Name) is interactive
        # in this build — the others are pre-stubbed in _init_creation_draft so
        # the draft can finalize on Pillar 1 commit alone. Future sessions add
        # real pillars and this synthetic injection grows accordingly.
        if (self.game_state.state == gs.GameStateName.CHARACTER_CREATION
                and self.character_draft is not None):
            progress = self.character_draft.progress()
            if not progress.get("name", False):
                # Spawn is at (0, -14) facing south (heading 180°). Pillar
                # at y=-20 sits ~6m in front of the player at first frame so
                # it's immediately visible without turning around.
                visible.append({
                    "id": -1000,
                    "kind": "pillar_name",
                    "x": 0.0, "y": -20.0, "z": 0.0,
                    "sx": 0.6, "sy": 0.6, "sz": 3.0,
                    "heading": 0.0,
                    "r": 1.0, "g": 0.7, "b": 0.0,
                    "collision_radius": 0.6,
                })

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
            # Atmosphere config streamed so Godot's _update_atmosphere can
            # parameterize off data instead of biome-name branches.
            "atmosphere": BIOME_REGISTRY.get(self.biome_name, {}).get("atmosphere", {}),
            # Spawn behavior — Godot reads mode + location to pick hub vs
            # legacy landmark framing. Single callsite in _spawn_player_start.
            "spawn": {
                "mode": BIOME_REGISTRY.get(self.biome_name, {}).get("spawn_mode", "legacy_landmark"),
                "location": BIOME_REGISTRY.get(self.biome_name, {}).get("spawn_location", {}),
            },
            "playable_envelope": {
                "radius": BIOME_REGISTRY.get(self.biome_name, {}).get("playable_radius", 0.0),
                "softness": BIOME_REGISTRY.get(self.biome_name, {}).get("playable_softness", 1.0),
            },
            # Player state surfaced for Godot's equipped-render path. Inventory
            # is a flat list of {name, slot_cost} so the viewer can populate a
            # HUD; equipped is the name of the currently-wielded item (or null).
            # Mutated brain-side via give_item / take_item / equip / unequip;
            # streamed every manifest update so Godot's equipped composite
            # primitive stays in sync without per-frame round-trips.
            "player": {
                "inventory": [
                    {"name": item.name, "slot_cost": item.slot_cost}
                    for item in self.player.inventory
                ],
                "equipped": self.player.equipped,
                "hp": self.player.hp,
                "max_hp": self.player.max_hp,
                "completed_missions": list(self.player.completed_missions),
            },
            # Loop state — Godot reads to gate UI / input / render mode per
            # phase (HUB / MISSION_SELECT / IN_MISSION / RESULTS). Mutated
            # brain-side via state_transition_request and mission_complete
            # effect; streamed every tick so transitions land within one
            # manifest cycle. Picker fields (available_missions,
            # selected_mission_id) merge in here rather than living on the
            # immutable GameState type — selection is transient session UI
            # state, not part of the validated transition graph.
            "game_state": {
                **gs.to_manifest(self.game_state),
                "available_missions": list(self.available_missions),
                "selected_mission_id": self.selected_mission_id,
            },
            # Character creation surface (`design_seven_pillars`, `design_dial_input`).
            # `dial_prompt` is the active engagement; `pillar_progress` shows
            # which pillars have sealed; `character_sheet` is the finalized
            # output once draft is complete. All three are None outside the
            # CHARACTER_CREATION → HUB transition path.
            "dial_prompt": (
                dial_to_manifest(self.active_dial)
                if self.active_dial is not None
                else None
            ),
            "pillar_progress": (
                self.character_draft.progress()
                if self.character_draft is not None
                else None
            ),
            "character_sheet": (
                {
                    "name": self.character_sheet.name,
                    "age": self.character_sheet.age,
                    "level": self.character_sheet.level,
                    "background": (
                        f"{self.character_sheet.class_history[-1].name.title()}"
                        if self.character_sheet.class_history else "Wanderer"
                    ),
                    "stats": {
                        "DEX": self.character_sheet.dex,
                        "WIS": self.character_sheet.wis,
                        "INT": self.character_sheet.int_,
                        "CHA": self.character_sheet.cha,
                        "STR": self.character_sheet.str_,
                        "CON": self.character_sheet.con,
                    },
                    "selected_abilities": list(self.character_sheet.selected_abilities),
                    "verbs_known": list(self.character_sheet.verbs_known),
                }
                if self.character_sheet is not None
                else None
            ),
            # Bumped each regen_world call. Godot watches for change and
            # re-dispatches spawn + clears entity caches so the world
            # transition lands within one manifest cycle.
            "world_revision": self.world_revision,
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
    encounter: EncounterSession | None = None
    roaming: RoamingPool | None = None

    # Lifecycle bookkeeping for passive auto-arm — see
    # BIOME_EXPEDITIONS[biome]['lifecycle']. last_complete_t enforces the
    # cooldown_s grace window after EXPEDITION COMPLETE; rotation_idx
    # cycles through the configured class rotation so successive auto-
    # arms can run different scout types if the rotation declares them.
    last_complete_t: float = 0.0
    rotation_idx: int = 0
    in_hub_last: bool = False  # rising-edge detect — arm on entering, not staying

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
    # Elemental reactions — queued casts resolved against the next manifest.
    # Each cast_event is appended here by the cmd handler; the manifest-build
    # step computes reactions (scan entities near cast origin, look up per-
    # kind elemental_reactions, attach to manifest["reaction_events"]).
    pending_casts: list[dict] = []

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
                    # EXPEDITION_CLASS env var picks the class. Default
                    # anomaly_hunt; set to "cast_trial" to exercise the
                    # CAST_TRIAL loop (press 1/2/3/4 in Godot to cast
                    # fire/ice/electric/light at the axis_mundi).
                    exp_class_id: str = os.environ.get(
                        "EXPEDITION_CLASS", "anomaly_hunt")
                    try:
                        expedition = ExpeditionEngine.from_class_id(
                            exp_class_id, biome_name)
                        expedition.on_session_start(time.time())
                        print(f"  Expedition: {exp_class_id} (biome={biome_name})",
                              flush=True)
                    except Exception as exc:
                        expedition = None
                        print(f"  Expedition disabled: {exc}", flush=True)

                    # Fresh encounter session per connection — UAT-1
                    # Watcher tiles pre-placed near hub, HP/depth/saves
                    # authoritative brain-side. Godot renders snapshot.
                    encounter = EncounterSession(seed=42)
                    print("  Encounter session: UAT-1 Watcher ready",
                          flush=True)

                    # Roaming pool — Tartarus-mode encounters. Watchers
                    # wander the cavern; camera contact fires a session.
                    roaming = RoamingPool(
                        actor_id="watcher", biome=biome_name,
                        target_count=3, seed=42)
                    # Seed spawn happens on first camera update so orbs
                    # appear around the player, not at the world origin.
                    print("  Roaming pool: watcher x3", flush=True)
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
                    encounter = None
                    roaming = None
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

                if msg.get("cmd") == "use_request":
                    # L8 — activate a use_effects-bearing item. If a name is
                    # supplied, use that specific item; otherwise find the
                    # first item in inventory that has use_effects (typical
                    # case: KEY_F = "use the next consumable").
                    item_name = str(msg.get("name", ""))
                    target_item = None
                    target_kcfg = None
                    for it in world.player.inventory:
                        if item_name and it.name != item_name:
                            continue
                        kcfg_it = _kc.kind(it.name)
                        if kcfg_it.get("use_effects"):
                            target_item = it
                            target_kcfg = kcfg_it
                            break
                    if target_item is None:
                        print(f"  use_request: no usable item found (filter={item_name!r})", flush=True)
                        continue

                    # Apply each use_effect. For now the only use-handler
                    # implemented at brain level is heal_player; others fall
                    # through with a warning until a brain-side _apply_effects
                    # dispatcher lands (mirrors EncounterSession's pattern).
                    old_hp = world.player.hp
                    applied: list[str] = []
                    for eff in target_kcfg.get("use_effects", []):
                        et = str(eff.get("type", ""))
                        if et == "heal_player":
                            world.player = ps.heal(world.player, int(eff.get("amount", 0)))
                            applied.append(et)
                        else:
                            print(f"  use_request: effect {et!r} not implemented at brain level", flush=True)

                    # Consume if the item is flagged consumable.
                    consumed = False
                    if target_kcfg.get("consumable", False):
                        try:
                            world.player = ps.remove_item(world.player, target_item)
                            consumed = True
                        except ValueError:
                            pass  # already gone — race with another use? skip.

                    print(f"  used {target_item.name}: hp {old_hp} -> {world.player.hp}, consumed={consumed}, effects={applied}", flush=True)
                    last_wake_ids = set()
                    continue

                if msg.get("cmd") == "damage_self":
                    # Debug — lets the user damage themselves to test healing.
                    # Remove once real damage paths exist (encounter combat,
                    # tool reactions, environmental hazards).
                    amt = int(msg.get("amount", 2))
                    old_hp = world.player.hp
                    world.player = ps.take_damage(world.player, amt)
                    print(f"  damage_self: hp {old_hp} -> {world.player.hp}", flush=True)
                    last_wake_ids = set()
                    continue

                if msg.get("cmd") == "mission_complete_trigger":
                    # Godot fires when a mission objective resolves (L3: a
                    # destructible kind shattering inside IN_MISSION state).
                    # Brain validates we're actually in a mission, rolls
                    # loot from kind_config[trigger_kind].mission_loot,
                    # mutates player inventory, builds results payload, and
                    # transitions to RESULTS.
                    if world.game_state.state != gs.GameStateName.IN_MISSION:
                        continue
                    trigger_kind = str(msg.get("trigger_kind", "unknown"))

                    # L7 — roll loot from kind_config and add to inventory.
                    # Each entry: a string name (guaranteed) or {name, weight}
                    # (rolled). Brain is authoritative on what landed.
                    loot_dropped: list[str] = []
                    kcfg = _kc.kind(trigger_kind)
                    for entry in kcfg.get("mission_loot", []):
                        if isinstance(entry, str):
                            name = entry
                        elif isinstance(entry, dict):
                            weight = float(entry.get("weight", 1.0))
                            if random.random() > weight:
                                continue
                            name = str(entry.get("name", ""))
                        else:
                            continue
                        if not name:
                            continue
                        try:
                            world.player = ps.add_item(world.player, Item(name=name))
                            loot_dropped.append(name)
                        except ValueError as e:
                            # Inventory full — drop the item, keep going.
                            print(f"  loot drop skipped (inventory full): {name}", flush=True)

                    payload = {
                        "mission_id": world.game_state.mission_id,
                        "trigger_kind": trigger_kind,
                        "loot": loot_dropped,
                        "xp": int(msg.get("xp", 25)),
                    }
                    try:
                        world.game_state = gs.transition(
                            world.game_state, gs.GameStateName.RESULTS,
                            results=payload)
                        # L5 — append the just-completed mission so the next
                        # autosave (RESULTS → HUB) carries it. Append-only;
                        # duplicate ids are fine (the player ran the same
                        # mission twice).
                        if world.game_state.mission_id is not None:
                            new_completed = (world.player.completed_missions
                                             + (world.game_state.mission_id,))
                            world.player = world.player._replace(
                                completed_missions=new_completed)
                        last_wake_ids = set()
                        print(f"  mission complete: {trigger_kind} -> RESULTS {payload}", flush=True)
                    except ValueError as e:
                        print(f"  mission_complete rejected: {e}", flush=True)
                    continue

                if msg.get("cmd") == "mission_select_cycle":
                    # L6 — cycle the picker selection while in MISSION_SELECT.
                    # Outside that state the command is meaningless, so reject
                    # rather than silently mutating selection. Wraps modulo
                    # available_missions length; missing/unknown current
                    # selection resets to index 0.
                    if world.game_state.state != gs.GameStateName.MISSION_SELECT:
                        print(f"  mission_select_cycle rejected: state={world.game_state.state.value}", flush=True)
                        continue
                    if not world.available_missions:
                        print("  mission_select_cycle rejected: no available missions", flush=True)
                        continue
                    delta = int(msg.get("delta", 1))
                    try:
                        idx = world.available_missions.index(world.selected_mission_id)
                    except ValueError:
                        idx = 0
                    new_idx = (idx + delta) % len(world.available_missions)
                    world.selected_mission_id = world.available_missions[new_idx]
                    last_wake_ids = set()
                    print(f"  mission picker: -> {world.selected_mission_id} ({new_idx + 1}/{len(world.available_missions)})", flush=True)
                    continue

                if msg.get("cmd") == "state_transition_request":
                    target_str = str(msg.get("target", ""))
                    try:
                        target = gs.GameStateName(target_str)
                    except ValueError:
                        print(f"  state_transition rejected: unknown target {target_str!r}", flush=True)
                        continue
                    old = world.game_state
                    try:
                        # Mission transitions need an id + seed. The id comes
                        # from the picker's current selection (L6); msg may
                        # override for tests/headless flows that bypass the
                        # picker. Falls through to a sensible default if both
                        # are unset (no available missions).
                        kwargs = {}
                        if target == gs.GameStateName.IN_MISSION:
                            picked = (world.selected_mission_id
                                      or (world.available_missions[0] if world.available_missions else "anomaly_hunt_01"))
                            kwargs["mission_id"] = str(msg.get("mission_id", picked))
                            kwargs["mission_seed"] = int(msg.get("mission_seed", random.randint(1, 999_999)))
                        elif target == gs.GameStateName.RESULTS:
                            kwargs["results"] = msg.get("results", {})
                        new_state = gs.transition(old, target, **kwargs)
                    except ValueError as e:
                        print(f"  state_transition rejected: {e}", flush=True)
                        continue

                    world.game_state = new_state
                    print(f"  state: {old.state.value} -> {new_state.state.value}", flush=True)

                    # L6 — picker selection lifecycle. Initialize on entering
                    # MISSION_SELECT (so the player sees a default highlight),
                    # clear on any path back to HUB or forward to IN_MISSION
                    # (selection is consumed at launch).
                    if new_state.state == gs.GameStateName.MISSION_SELECT:
                        if world.selected_mission_id not in world.available_missions:
                            world.selected_mission_id = (
                                world.available_missions[0]
                                if world.available_missions else None
                            )
                    else:
                        world.selected_mission_id = None

                    # Side effects per transition.
                    # Launching: regen world with the mission seed.
                    # Returning to HUB from a mission/results: regen with hub seed.
                    # Cancel from MISSION_SELECT: no regen (still in hub world).
                    if (old.state == gs.GameStateName.MISSION_SELECT
                            and new_state.state == gs.GameStateName.IN_MISSION):
                        world.regen_world(new_state.mission_seed)
                        print(f"  world regen: mission seed={new_state.mission_seed}", flush=True)
                    elif (old.state in (gs.GameStateName.IN_MISSION, gs.GameStateName.RESULTS)
                            and new_state.state == gs.GameStateName.HUB):
                        world.regen_world(world.hub_seed)
                        print(f"  world regen: hub seed={world.hub_seed}", flush=True)

                    # L5 autosave — write player state to disk on the natural
                    # mission boundary (RESULTS → HUB). Other transitions
                    # don't need to save: HUB ↔ MISSION_SELECT mutates nothing
                    # persistent; MISSION_SELECT → IN_MISSION is pre-mission;
                    # IN_MISSION → HUB (abort) intentionally drops mission
                    # progress and reverts to the last known-good autosave.
                    if (old.state == gs.GameStateName.RESULTS
                            and new_state.state == gs.GameStateName.HUB):
                        try:
                            written = save_state.save(world.player, world.character_sheet)
                            print(f"  autosave: {written}", flush=True)
                        except OSError as e:
                            print(f"  autosave failed: {e}", flush=True)

                    last_wake_ids = set()  # force manifest resend with new state
                    continue

                if msg.get("cmd") == "engage_pillar":
                    # Per `design_seven_pillars` + `design_dial_input`: player
                    # walks up to a pillar in the hub during CHARACTER_CREATION,
                    # presses F, brain returns the pillar's initial DialPrompt
                    # via manifest.dial_prompt. Client renders the dial.
                    if world.game_state.state != gs.GameStateName.CHARACTER_CREATION:
                        print(f"  engage_pillar rejected: state={world.game_state.state.value}", flush=True)
                        continue
                    if world.character_draft is None:
                        print(f"  engage_pillar rejected: no draft", flush=True)
                        continue
                    pillar_id = str(msg.get("pillar", ""))
                    handler = pillars_registry.get(pillar_id)
                    if handler is None:
                        print(f"  engage_pillar rejected: unknown pillar {pillar_id!r}", flush=True)
                        continue
                    world.active_dial = handler.initial_prompt(world.character_draft)
                    last_wake_ids = set()
                    print(f"  engaged pillar:{pillar_id}", flush=True)
                    continue

                if msg.get("cmd") == "dial_cancel":
                    # Player closed the dial without committing (Esc during dial).
                    # Brain just clears active_dial; player can re-engage the
                    # same pillar later. The draft is unaffected.
                    if world.active_dial is not None:
                        print(f"  dial cancelled: {world.active_dial.source}", flush=True)
                        world.active_dial = None
                        last_wake_ids = set()
                    continue

                if msg.get("cmd") == "dial_response":
                    # Universal dial commit. Player picked option `answer_idx`
                    # from the active dial. For narrow-mode dials (binary CAT)
                    # this may emit a follow-up prompt; for select-mode it
                    # commits the value via the pillar's apply() and appends
                    # to the draft. Once the draft is complete, brain finalizes
                    # the CharacterSheet and transitions CHARACTER_CREATION → HUB.
                    if world.active_dial is None:
                        print(f"  dial_response rejected: no active dial", flush=True)
                        continue
                    answer_idx = int(msg.get("answer_idx", world.active_dial.default_index))
                    source = world.active_dial.source
                    if not source.startswith("pillar:"):
                        print(f"  dial_response: non-pillar source {source!r} not yet routed", flush=True)
                        continue
                    pillar_id = source.split(":", 1)[1]
                    handler = pillars_registry.get(pillar_id)
                    if handler is None:
                        print(f"  dial_response: handler missing for {pillar_id}", flush=True)
                        world.active_dial = None
                        continue
                    if not (0 <= answer_idx < len(world.active_dial.options)):
                        print(f"  dial_response: answer_idx {answer_idx} out of range", flush=True)
                        continue

                    follow_up = handler.next_prompt(
                        world.character_draft, world.active_dial, answer_idx)
                    if follow_up is not None:
                        world.active_dial = follow_up
                        last_wake_ids = set()
                        continue

                    chosen_value = world.active_dial.options[answer_idx].value
                    world.character_draft.append(pillar_id, chosen_value)
                    world.active_dial = None
                    print(f"  pillar {pillar_id!r} sealed: {chosen_value!r}", flush=True)

                    if world.character_draft.is_complete():
                        try:
                            world.character_sheet = world.character_draft.finalize(
                                pillars_registry.all_handlers())
                            old_state = world.game_state
                            world.game_state = gs.transition(
                                world.game_state, gs.GameStateName.HUB)
                            print(f"  character sealed: {world.character_sheet.name} (age {world.character_sheet.age})", flush=True)
                            print(f"  state: {old_state.state.value} -> {world.game_state.state.value}", flush=True)
                            # Autosave the sealed sheet so brain restart preserves
                            # identity (per "real game saves" — the sheet survives
                            # alongside PlayerState).
                            try:
                                written = save_state.save(world.player, world.character_sheet)
                                print(f"  autosave (post-creation): {written}", flush=True)
                            except OSError as save_err:
                                print(f"  autosave failed: {save_err}", flush=True)
                        except Exception as e:
                            print(f"  finalize failed: {e}", flush=True)

                    last_wake_ids = set()
                    continue

                if msg.get("cmd") == "equip_request":
                    item_name = str(msg.get("name", ""))
                    try:
                        world.player = ps.equip(world.player, item_name)
                        last_wake_ids = set()
                        print(f"  equipped: {item_name}", flush=True)
                    except ValueError as e:
                        print(f"  equip rejected: {e}", flush=True)
                    continue

                if msg.get("cmd") == "holster_request":
                    if world.player.equipped is not None:
                        prev = world.player.equipped
                        world.player = ps.unequip(world.player)
                        last_wake_ids = set()
                        print(f"  holstered: {prev}", flush=True)
                    continue

                if msg.get("cmd") == "cast_event":
                    cast = msg.get("cast", {})
                    # Taxonomy gate — reject casts with unknown trajectory/
                    # effect combos per config/verbs.json. Soft warn + drop
                    # rather than hard fail so a malformed cast doesn't kill
                    # the session mid-playtest.
                    traj = cast.get("trajectory", "straight")
                    elem = cast.get("element", "")
                    if not _verbs.validate_cast(traj, elem):
                        print(f"  cast_event rejected: unknown "
                              f"trajectory={traj!r} effect={elem!r}",
                              flush=True)
                        continue
                    if expedition is not None:
                        expedition.on_cast_event(cast, time.time())
                    # Queue for elemental-reaction resolution in the next
                    # manifest build. Kept orthogonal to expedition: the
                    # engine cares about tag_log deposits; elementals care
                    # about spatial proximity to entities.
                    pending_casts.append(dict(cast))
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

                # ---- Encounter commands (UAT-1) ------------------------
                # Godot detects tile crossings via manifest['encounter']
                # ['tiles']; resolution happens brain-side. See
                # core/systems/encounter_session.py.

                if msg.get("cmd") == "encounter_action":
                    if encounter is not None:
                        action = msg.get("action", "")
                        try:
                            result = encounter.on_action(action)
                            ack = json.dumps({"encounter_action": result}) + "\n"
                            client.sendall(ack.encode("utf-8"))
                        except (ValueError, RuntimeError) as exc:
                            ack = json.dumps({"encounter_error": str(exc)}) + "\n"
                            client.sendall(ack.encode("utf-8"))
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        last_wake_ids = set()
                    continue

                if msg.get("cmd") == "encounter_portal":
                    if encounter is not None:
                        result = encounter.on_portal()
                        try:
                            ack = json.dumps({"encounter_portal": result}) + "\n"
                            client.sendall(ack.encode("utf-8"))
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        last_wake_ids = set()
                    continue

                if msg.get("cmd") == "encounter_hub_arrival":
                    if encounter is not None:
                        result = encounter.on_hub_arrival()
                        try:
                            ack = json.dumps(
                                {"encounter_consolidate": result}) + "\n"
                            client.sendall(ack.encode("utf-8"))
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        last_wake_ids = set()
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
                            # Return to endless roam: null out the expedition so
                            # subsequent manifests ship without the overlay.
                            # world.get_manifest() keeps streaming scenery — the
                            # cavern is the substrate, the scout was an
                            # overlay. Godot player hits `begin_scout` to
                            # re-arm a fresh engine, OR the lifecycle.auto_arm
                            # config below picks up the next scout passively.
                            expedition = None
                            last_complete_t = time.time()
                            print("  → endless roam; [P] or hub-return arms next scout",
                                  flush=True)
                        try:
                            ack = json.dumps(result) + "\n"
                            client.sendall(ack.encode("utf-8"))
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        last_wake_ids = set()  # force final manifest
                    continue

                if msg.get("cmd") == "begin_scout":
                    # Mock quest-accept — spin up a new ExpeditionEngine in the
                    # current biome. Default class from env (same as fresh
                    # connect). Request body may override with "class_id".
                    # If a scout is already active, no-op (send a courtesy ack).
                    if expedition is not None:
                        try:
                            ack = json.dumps({
                                "scout_status": "already_active",
                                "class_id": expedition.class_id,
                                "state": expedition.state.value,
                            }) + "\n"
                            client.sendall(ack.encode("utf-8"))
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        continue
                    exp_class_id = msg.get("class_id") or os.environ.get(
                        "EXPEDITION_CLASS", "anomaly_hunt")
                    try:
                        expedition = ExpeditionEngine.from_class_id(
                            exp_class_id, biome_name)
                        expedition.on_session_start(time.time())
                        print(f"  → New scout: {exp_class_id} (biome={biome_name})",
                              flush=True)
                        ack_payload = {
                            "scout_status": "started",
                            "class_id": exp_class_id,
                        }
                    except Exception as exc:
                        expedition = None
                        print(f"  Scout start failed: {exc}", flush=True)
                        ack_payload = {
                            "scout_status": "error",
                            "error": str(exc),
                        }
                    last_wake_ids = set()  # force next manifest so Godot sees overlay
                    try:
                        ack = json.dumps(ack_payload) + "\n"
                        client.sendall(ack.encode("utf-8"))
                    except (BrokenPipeError, ConnectionResetError):
                        pass
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

                # -- Passive auto-arm — config-driven scout reacquisition ----
                # When no expedition is active, watch for the trigger declared
                # in BIOME_EXPEDITIONS[biome]['lifecycle']['auto_arm']. Rising-
                # edge for hub_return so we arm on cross, not on dwell. Honors
                # cooldown_s as a minimum dead-air window after the previous
                # complete. Rotation lets future biomes cycle multiple classes.
                if expedition is None:
                    auto = BIOME_EXPEDITIONS.get(biome_name, {}).get(
                        "lifecycle", {}).get("auto_arm", {})
                    if auto.get("enabled", False):
                        trig = auto.get("on", "hub_return")
                        now_t = time.time()
                        cooldown_ok = (
                            now_t - last_complete_t >= auto.get("cooldown_s", 0.0))
                        should_arm = False
                        if trig == "hub_return":
                            hx, hy = auto.get("hub_pos", [0.0, -14.0])
                            hr = auto.get("hub_radius", 12.0)
                            dx_h = cam_x - hx
                            dy_h = cam_y - hy
                            in_hub_now = (dx_h * dx_h + dy_h * dy_h) <= hr * hr
                            # Rising edge — arm only when crossing INTO hub.
                            if in_hub_now and not in_hub_last and cooldown_ok:
                                should_arm = True
                            in_hub_last = in_hub_now
                        elif trig == "complete":
                            # Instant chain — arm as soon as cooldown clears.
                            if cooldown_ok and last_complete_t > 0.0:
                                should_arm = True
                        elif trig == "cooldown":
                            # Time-only — arm whenever cooldown elapsed since
                            # last complete (or session start if no complete yet).
                            if cooldown_ok:
                                should_arm = True
                        if should_arm:
                            rotation = auto.get("rotation", ["anomaly_hunt"])
                            next_class = rotation[rotation_idx % len(rotation)]
                            try:
                                expedition = ExpeditionEngine.from_class_id(
                                    next_class, biome_name)
                                expedition.on_session_start(now_t)
                                rotation_idx += 1
                                last_wake_ids = set()  # force a manifest with overlay
                                print(f"  → auto-armed scout: {next_class} "
                                      f"(trigger={trig})", flush=True)
                            except Exception as exc:
                                print(f"  Auto-arm failed: {exc}", flush=True)
                else:
                    # Expedition active — reset hub edge so we can re-fire after
                    # next completion + leaving + returning.
                    in_hub_last = False

                manifest = world.get_manifest(
                    cam_x, cam_y, cam_z, heading, pitch, dt)

                # Attach expedition snapshot to manifest. This is the
                # render-manifest doctrine: brain owns state, manifest
                # carries it, Godot paints what it sees. Godot has no
                # recipe-specific knowledge — it reads
                # manifest['expedition'] and draws generically.
                #
                if expedition is not None:
                    manifest["expedition"] = expedition.snapshot()

                # Decrement encounter cooldown — without this, once the
                # engine sets _cooldown_remaining, it stays > 0 forever and
                # all subsequent contacts are silently blocked.
                if encounter is not None:
                    encounter.engine.tick_cooldown(dt)

                # Roaming pool — Tartarus mode. Orbs drift around the
                # player; on contact, the encounter session begins with
                # the agent's actor_id, and the agent is consumed.
                if roaming is not None:
                    if not roaming.agents:
                        roaming.ensure_population(center=(cam_x, cam_y))
                    roaming.tick(dt, player_pos=(cam_x, cam_y))

                    # Contact detection only fires when no encounter active.
                    if (encounter is not None
                            and encounter.engine.active_encounter is None
                            and not encounter.engine.on_cooldown):
                        agent = roaming.detect_contact(cam_x, cam_y)
                        if agent is not None:
                            # Compute Tartarus-style advantage from headings.
                            advantage = _compute_contact_advantage(
                                cam_x, cam_y,
                                math.radians(heading),
                                agent.x, agent.y, agent.heading)
                            result = encounter.on_orb_contact(
                                actor_id=agent.actor_id,
                                advantage=advantage,
                                orb_id=agent.id,
                                hp_bonus=agent.hp_bonus)
                            if result.get("triggered"):
                                roaming.consume(agent.id)
                                last_wake_ids = set()
                            elif result.get("reason") == "silence":
                                # Silence path still consumes — Frieren
                                # model: the world moves on.
                                roaming.consume(agent.id)

                    manifest.setdefault("entities", []).extend(
                        roaming.snapshot())

                # Encounter session snapshot (HUD/orb/log data).
                if encounter is not None:
                    manifest["encounter"] = encounter.snapshot()

                # Resolve any queued casts into reaction_events for this
                # manifest. Single pass: for each pending cast, find the
                # nearest entity within CAST_REACTION_RADIUS_M whose kind
                # config carries elemental_reactions[element]; emit a
                # reaction_event keyed by (kind, x, y) so Godot can map
                # back to the spawned node. Godot handles the visual.
                if pending_casts:
                    reaction_events: list[dict] = []
                    ents = manifest.get("entities", [])
                    for cast in pending_casts:
                        origin = cast.get("origin", [0.0, 0.0, 0.0])
                        element = cast.get("element", "")
                        # Godot origin is (x, altitude, z). Brain entities
                        # are (x, y=depth, z=altitude). Match on XZ plane:
                        # entity.x ↔ origin[0], entity.y ↔ origin[2].
                        ox = float(origin[0]) if len(origin) > 0 else 0.0
                        oz = float(origin[2]) if len(origin) > 2 else 0.0
                        best = None
                        best_d2 = (CAST_REACTION_RADIUS_M
                                   * CAST_REACTION_RADIUS_M)
                        for e in ents:
                            ek = e.get("kind", "")
                            kcfg = _kc.kind(ek)
                            er = kcfg.get("elemental_reactions") or {}
                            if element not in er:
                                continue
                            ex = float(e.get("x", 0.0))
                            ey = float(e.get("y", 0.0))
                            d2 = (ex - ox) ** 2 + (ey - oz) ** 2
                            if d2 < best_d2:
                                best_d2 = d2
                                best = (e, er[element])
                        if best is not None:
                            e, pattern_id = best
                            reaction_events.append({
                                "kind": e.get("kind", ""),
                                "x": float(e.get("x", 0.0)),
                                "y": float(e.get("y", 0.0)),
                                "pattern": pattern_id,
                                "element": element,
                                "t": time.time(),
                            })
                    if reaction_events:
                        manifest["reaction_events"] = reaction_events
                    pending_casts.clear()

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
                    # Mirror the no-data and reset disconnect paths above —
                    # use `continue` so the outer accept loop survives. The
                    # previous `break` exited the `while True:` entirely and
                    # the brain process died. Reproduced multiple times this
                    # session whenever Godot reloaded the scene mid-write.
                    print("  Godot disconnected (write)", flush=True)
                    client.close()
                    client = None
                    expedition = None
                    encounter = None
                    roaming = None
                    continue

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
    # Config-lock #6: schema + version + snapshot preflight before boot.
    # Raises PreflightError on schema/version failure; prints snapshot drift
    # as WARN and proceeds. Bypass with SANCTUM_SKIP_CONFIG_VALIDATION=1.
    from core.systems import config_preflight
    config_preflight.assert_valid_config_state()

    biome_name = sys.argv[1] if len(sys.argv) > 1 else "outdoor"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9877
    run_server(biome_name, port)


if __name__ == "__main__":
    main()
