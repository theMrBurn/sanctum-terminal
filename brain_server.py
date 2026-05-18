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
import re
from typing import Any, Optional

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
from core.systems.spectrum import SpectrumEngine, set_active_biome
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
from core.systems import quests
from core.systems import scenario_ledger
from core.systems.quests import from_journal as quest_from_journal
from core.systems.quests import rewards as quest_rewards
from core.systems.quests import tick as quest_tick
from core.systems.consequences import signals as consequence_signals
from core.systems.consequences import tick as consequence_tick
from core.systems.reflective import ReflectiveState
from core.systems.reflective import state_machine as reflective_sm
from core.systems.quests.state import QuestState
from core.systems.journal import lexicon as journal_lexicon
from core.vault import vault as Vault
from core.systems import seed_commands
from core.systems import make_brain_commands
from core.systems import make_brain_registry
from core.systems.character_draft import CharacterDraft
from core.systems import activity_loop
from core.systems import biome_elevation as _biome_elevation
from core.systems import strike as strike_module
from core.systems import strike_runtime
from core.systems import weapons as weapons_pkg
from core.systems.character_sheet import CharacterSheet
from core.systems.dial_prompt import DialPrompt, to_manifest as dial_to_manifest
from core.systems.state_events import (
    StateEventBuffer,
    to_manifest as state_events_to_manifest,
    LOOP as REG_LOOP,
    RITUAL as REG_RITUAL,
    SYSTEM as REG_SYSTEM,
    TENSE as REG_TENSE,
)
from datetime import date


# ── Journal vault — Permanent Objects bridge ─────────────────────────
# Lazy module-level singleton. Constructed on first journal_entry cmd;
# matches the kind_config / state_events pattern (no constructor wiring
# through BrainWorld). vault._ensure_schema() is idempotent so this is
# safe to instantiate against an existing data/vault.db.

_VAULT: Vault | None = None


def _get_vault() -> Vault:
    global _VAULT
    if _VAULT is None:
        _VAULT = Vault()
    return _VAULT


def _make_brain_manifest_keys(biome_name: str) -> dict:
    """Pull top-level manifest keys from the active make-brain instance,
    if any. Returns {} for biomes that don't bind one — silent no-op for
    legacy biomes. Per `feat_make-brain-ping-pong.md` PR 3."""
    iid = BIOME_REGISTRY.get(biome_name, {}).get("make_brain_instance_id")
    if not iid:
        return {}
    try:
        spec = make_brain_registry.get(iid)
    except LookupError:
        # Activation hasn't run yet (e.g., test that imports BrainWorld
        # without booting). Silent — manifest just lacks the keys.
        return {}
    handler = spec.handler
    fn = getattr(handler, "manifest_keys", None)
    if fn is None or not callable(fn):
        return {}
    return fn()


def _journal_persist_entry(raw_note: str) -> int:
    """Insert one entry row, return its id. Severity/frequency take
    schema defaults — the planner UI's structured form lands later.
    Bridge harness only ever sends raw_note, so this is sufficient.

    Emits activity_loop WANDER signals based on lexicon discovery —
    each new term in the entry is a small discovery (intensity 1);
    the entry itself is a routine RITUAL act of journaling
    (intensity 1). Per PR 13.
    """
    import sqlite3
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    v = _get_vault()
    with sqlite3.connect(v.db_path) as conn:
        cur = conn.execute(
            "INSERT INTO entries (when_ts, raw_note, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (now, raw_note, now, now),
        )
        # Run lexicon update inside the same transaction so terms tie to
        # the just-inserted entry id.
        entry_id = cur.lastrowid
        lex_summary = journal_lexicon.update_lexicon(
            conn, entry_id, raw_note, vault=v,
        )
        conn.commit()
    # Activity-loop signals — fire AFTER commit so a transaction
    # rollback doesn't leave dangling counter bumps. Each new term =
    # one WANDER (discovery); each entry = one RITUAL (daily care).
    # Per PR 13.
    new_terms = int((lex_summary or {}).get("new_terms", 0))
    if new_terms > 0:
        activity_loop.emit_activity(
            activity_loop.ActivityClass.WANDER,
            intensity=new_terms,
            primitive="lexicon_term_discovered",
            source_brain="journal",
            payload={"entry_id": int(entry_id), "new_terms": new_terms},
        )
    activity_loop.emit_activity(
        activity_loop.ActivityClass.RITUAL,
        intensity=1,
        primitive="journal_entry_recorded",
        source_brain="journal",
        payload={"entry_id": int(entry_id)},
    )
    return entry_id


def _bridge_entry_to_quest(entry_id: int, raw_note: str, kind_set: set[str]):
    """Single bridge path used by both the live journal_entry cmd AND
    boot-time replay. Extracts lexicon terms, writes a PENDING scenario
    row to vault.scenarios (idempotent — replay re-derives the same
    deterministic provenance hash), and synthesizes the matching Quest
    with scenario_id back-reference.

    Returns (quest, scenario_id) on success, None when the entry yields
    no usable head term (degenerate case — caller skips silently).

    Calls quest_from_entry twice — once to derive the head term + kind
    match for scenario params, once to rebuild the Quest with
    scenario_id stamped into predicate_args. quest_from_entry is pure
    + sub-millisecond, so the double call is cheaper than refactoring
    _pick_term out of from_journal."""
    if not raw_note or not raw_note.strip():
        return None
    v = _get_vault()
    terms = journal_lexicon.extract_terms(raw_note, vault=v)
    preview = quest_from_journal.quest_from_entry(
        entry_id, raw_note, terms, kind_set)
    if preview is None:
        return None
    head_term = (preview.predicate_args.get("term")
                 or preview.predicate_args.get("kind", ""))
    kind_match = preview.predicate == "destroy_kind"
    params = {
        "raw_note":   raw_note,
        "head_term":  head_term,
        "kind_match": kind_match,
        "entry_id":   entry_id,
        "objective":  preview.name,
    }
    provenance = scenario_ledger.journal_provenance_hash(entry_id, raw_note)
    sid = scenario_ledger.create_pending(
        v, "journal", params, provenance, objective=preview.name)
    if sid is None:
        # Vault write failed in a way create_pending couldn't recover —
        # bail rather than register an orphan Quest.
        return None
    quest = quest_from_journal.quest_from_entry(
        entry_id, raw_note, terms, kind_set, scenario_id=sid)
    return (quest, sid) if quest is not None else None


def _replay_journal_quests(quest_state, kind_set: set[str]) -> int:
    """Boot-time replay: re-register a dynamic Quest for every persisted
    entry so the quest substrate survives brain restart even though the
    in-memory registry is fresh.

    Until V3 save lands (PR 2 of project_async_quest_refactor), the
    `completed` list is empty post-boot, so every replayed quest comes
    back as available. After V3 lands, the caller should hydrate
    quest_state.completed from save BEFORE calling this so already-done
    quests stay out of available.

    Cost: one spaCy pass per entry (~5-10ms each). Today's vault has
    O(few) entries; once she's been journaling for months we'll need a
    bound or a persisted Quest table. Flag for future revisit.

    Returns the number of quests replayed."""
    import sqlite3
    v = _get_vault()
    completed = set(quest_state.completed)
    replayed = 0
    try:
        with sqlite3.connect(v.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, raw_note FROM entries ORDER BY id"
            ).fetchall()
    except sqlite3.OperationalError:
        # entries table doesn't exist yet (vault never migrated). Bridge
        # is a no-op until the first journal_entry cmd triggers _get_vault.
        return 0

    for row in rows:
        entry_id = int(row["id"])
        raw_note = row["raw_note"] or ""
        bridged = _bridge_entry_to_quest(entry_id, raw_note, kind_set)
        if bridged is None:
            continue
        quest, _sid = bridged
        if quest.id in completed:
            continue
        quests.register_dynamic(quest)
        if (quest.id not in quest_state.available
                and quest.id not in quest_state.active):
            quest_state.available.append(quest.id)
        replayed += 1
    return replayed


# ── Quest completion side-effects ─────────────────────────────────────
# Brain-owned per `feedback_brain_owns_config`: the quests module is
# data-only; reward drops, StateEvent emission, and any save-trigger
# logic live here. Called by quest_tick.tick() once per resolved quest.

def _sync_quest_state_to_player(world) -> None:
    """V3 save bridge — copy the live quest_state lists onto world.player
    just before serialization. Keeps the source-of-truth in BrainWorld
    (where the tick evaluator owns it) and avoids drift between the two
    representations. Progress dicts intentionally aren't persisted in
    v1 — kill counts / element sets reset across save+load. Extending
    that needs a real schema decision."""
    world.player = world.player._replace(
        active_quests=tuple(world.quest_state.active),
        completed_quests=tuple(world.quest_state.completed),
    )


def _on_quest_complete(world, quest) -> None:
    rolled = quest_rewards.roll(quest.rewards)
    actually_added: list[str] = []
    for name in rolled:
        try:
            world.player = ps.add_item(world.player, Item(name=name))
            actually_added.append(name)
        except ValueError:
            print(f"  loot drop skipped (inventory full): {name}", flush=True)
    detail = ", ".join(actually_added) if actually_added else None
    world.state_events.emit(
        "quest_completed",
        f"QUEST COMPLETE — {quest.name.upper()}",
        detail,
        quest.register,
    )
    # Activity-loop signal — SOLVE class. Each completed quest is a
    # constrained-goal-met = solve. Intensity=2 (medium-heavy: more
    # than a single dial-finalize, less than a sealed pillar).
    # Telemetry payload carries quest id + name for post-hoc analysis
    # of which quest types the player favors. Per PR 14.
    activity_loop.emit_activity(
        activity_loop.ActivityClass.SOLVE,
        intensity=2,
        primitive="quest_completed",
        source_brain="quests",
        payload={
            "quest_id":   str(quest.id),
            "quest_name": str(quest.name),
            "loot":       list(actually_added),
        },
    )
    # Flip the persisted scenario row to COMPLETE for journal-derived
    # quests. Quests without scenario_id (legacy biome-seeded) skip
    # silently — they'll get scenario rows when full unification lands.
    sid = quest.predicate_args.get("scenario_id")
    if sid is not None:
        scenario_ledger.transition(
            _get_vault(), sid, scenario_ledger.COMPLETE,
            state_events=world.state_events)
    print(f"  quest completed: {quest.id} loot={actually_added}", flush=True)


def _strike_to_manifest(active, player_x, player_y, player_z):
    """Per-strike manifest entry. Carries enough for the client's
    strike_renderer to draw the per-mode visualization (ball, trail,
    chain, hitbox) without recomputing physics. Per feat/arpg-combat
    PR 6.

    Common fields: weapon_kind, mode, source, ball_radius, position,
    velocity, age, max_age. Mode-specific fields:
      - held: held_phase ("wind_up" / "active" / "cooldown"),
              hitbox_pos (player + forward × reach),
              arc_reach, held_verb
      - whip: player_pos (tether anchor — for chain-line render)
      - shot: nothing extra
    """
    out = {
        "weapon_kind":  active.strike.weapon_kind,
        "mode":         active.strike.mode,
        "source":       active.strike.source_actor,
        "ball_radius":  active.strike.profile.ball_radius,
        "x":            active.current_state.pos[0],
        "y":            active.current_state.pos[1],
        "z":            active.current_state.pos[2],
        "vx":           active.current_state.vel[0],
        "vy":           active.current_state.vel[1],
        "vz":           active.current_state.vel[2],
        "age_s":        active.age_seconds,
        "max_age_s":    active.max_age_s,
    }
    if active.strike.mode == "held":
        arc = active.strike.held_arc or {}
        wind_up = float(arc.get("wind_up_s",  0.0))
        active_s = float(arc.get("active_s",   0.0))
        if active.age_seconds < wind_up:
            phase = "wind_up"
        elif active.age_seconds < wind_up + active_s:
            phase = "active"
        else:
            phase = "cooldown"
        fwd = arc.get("spawn_forward") or [0.0, 1.0, 0.0]
        reach = float(arc.get("reach_m", 1.0))
        out["held_phase"] = phase
        out["arc_reach"]  = reach
        # PR 9: per-verb swept hitbox position lives on the active
        # strike (updated each frame in _tick_held). Read from there
        # when set; fall back to fixed forward × reach during
        # wind_up/cooldown phases when no sweep happens.
        hp = active.held_hitbox_pos
        if hp is not None:
            out["hitbox_x"] = hp[0]
            out["hitbox_y"] = hp[1]
            out["hitbox_z"] = hp[2]
        else:
            out["hitbox_x"] = active.current_state.pos[0] + float(fwd[0]) * reach
            out["hitbox_y"] = active.current_state.pos[1] + float(fwd[1]) * reach
            out["hitbox_z"] = active.current_state.pos[2] + float(fwd[2]) * reach
        out["held_verb"]  = (active.strike.held_verb.name
                              if active.strike.held_verb else None)
    elif active.strike.mode == "whip":
        # Anchor the tether line at the player's CURRENT position (the
        # player may have moved since swing-start). For V1, "player_pos"
        # = camera position on brain side. Brain space (y=forward, z=up).
        out["player_x"] = float(player_x)
        out["player_y"] = float(player_y)
        out["player_z"] = float(player_z)
        # Phase progress for retract animation hint
        arc = active.strike.held_arc or {}
        swing_s = float(arc.get("whip_swing_s", 0.45))
        out["whip_phase"] = "swing" if active.age_seconds < swing_s else "retract"
    return out


# weapon_class → activity-loop class + intensity mapping
# Per `design_arpg_combat_v1` activity-loop integration table (PR 7).
# magic_* emits SOLVE (precision-cast as problem-solving — wizard-heavy
# player gets puzzle-shaped tension via TensionCycle's pace consumer).
# melee_tether is heavier weapon class (intensity 2). Default = HUNT 1.
# Scan-gallery entities loaded at module import. Set via env
# SANCTUM_SCAN_GALLERY=<json_path>; empty otherwise. Static list —
# the manifest builder appends it every tick so the entities are
# stable visual fixtures, not roaming agents.
def _load_scan_gallery() -> list[dict]:
    import os as _os
    import json as _json
    path = _os.environ.get("SANCTUM_SCAN_GALLERY", "").strip()
    if not path:
        return []
    try:
        with open(path, "r") as f:
            data = _json.load(f)
        if isinstance(data, list):
            print(f"  scan_gallery: loaded {len(data)} entities from {path}",
                  flush=True)
            return data
    except Exception as exc:                          # noqa: BLE001
        print(f"  scan_gallery: load failed: {exc!r}", flush=True)
    return []


_SCAN_GALLERY_ENTITIES: list[dict] = _load_scan_gallery()


# Thing-library gallery — per `core/systems/thing_schema.py`.
# Loaded at module import; brain injects each Thing's expanded
# entities into the manifest every tick. Override the search dir
# via SANCTUM_THINGS_DIR env (default: <repo>/library/things/).
#
# This is the reliable-math counterpart to _SCAN_GALLERY_ENTITIES:
# instead of hand-tuned absolute-scale entries, each Thing has
# `real_size_m` + fractional positions. Brain expands them into N
# entities at world coords using thing_renderer.expand_thing.
_THING_GALLERY_THINGS: dict[str, Any] = {}     # name → Thing dataclass
_THING_GALLERY_PLACEMENT: dict[str, dict[str, Any]] = {}   # name → {gx, gy, idx}
_THING_GALLERY_DIR: "Any" = None               # Path; set on first load
# Per-thing runtime kick offset (dx, dy) — added on top of the static
# placement on every gallery expansion. Not persisted; resets on
# brain restart. Cleared when a thing is picked up.
_THING_GALLERY_KICK_OFFSETS: dict[str, tuple[float, float]] = {}
# Per-thing pickup tombstones — once picked up, the thing stops
# rendering this session. Not persisted; restart re-spawns.
_THING_GALLERY_PICKED_UP: set[str] = set()


def _load_thing_gallery() -> list[dict]:
    """Walk library/things/, parse each into a Thing dataclass, and
    cache (name → Thing) plus its grid placement. Returns the
    expanded entity list ready to merge into the manifest."""
    import os as _os
    from pathlib import Path as _P
    from core.systems import thing_schema, thing_renderer

    global _THING_GALLERY_THINGS, _THING_GALLERY_PLACEMENT, _THING_GALLERY_DIR

    raw = _os.environ.get("SANCTUM_THINGS_DIR", "").strip()
    if raw:
        things_dir = _P(raw).expanduser()
    else:
        things_dir = _P(__file__).parent / "library" / "things"
    _THING_GALLERY_DIR = things_dir

    if not things_dir.exists():
        _THING_GALLERY_THINGS = {}
        _THING_GALLERY_PLACEMENT = {}
        return []

    things = thing_schema.load_things_from_dir(things_dir)
    if not things:
        _THING_GALLERY_THINGS = {}
        _THING_GALLERY_PLACEMENT = {}
        return []

    _THING_GALLERY_THINGS = dict(things)
    _THING_GALLERY_PLACEMENT = {}
    spacing = 4.0
    forward = 6.0
    for idx, name in enumerate(sorted(things.keys())):
        col = idx % 5
        row = idx // 5
        _THING_GALLERY_PLACEMENT[name] = {
            "gx":  (col - 2.0) * spacing,
            "gy":  forward + row * spacing,
            "idx": idx,
        }

    out = _expand_thing_gallery()
    print(f"  thing_gallery: loaded {len(out)} entities from "
          f"{len(things)} things ({things_dir})", flush=True)

    # Sanity: query the Blender at boot so the synthesis loop is
    # visibly working before the user does anything.
    try:
        from core.systems.blender import default_blender
        from core.systems import thing_library
        bl = default_blender()
        tag_counts = thing_library.all_tags()
        weapons = bl.pick_thing(include_tags=["weapon"], seed=0)
        cavern = bl.things_for_biome("cavern", count=3, seed=0)
        print(f"  blender_sanity: {len(tag_counts)} distinct tags, "
              f"pick(weapon)={weapons.name if weapons else 'none'}, "
              f"cavern_picks={[t.name for t in cavern]}",
              flush=True)
    except Exception as exc:                          # noqa: BLE001
        print(f"  blender_sanity: failed: {exc!r}", flush=True)

    return out


def _expand_thing_gallery() -> list[dict]:
    """Expand all loaded Things → entity list at their current
    placements. Picked-up things are SKIPPED; kicked things have
    their gallery offset added to placement."""
    from core.systems import thing_renderer
    out: list[dict] = []
    for name, thing in _THING_GALLERY_THINGS.items():
        if name in _THING_GALLERY_PICKED_UP:
            continue                                    # thing is "in inventory"
        place = _THING_GALLERY_PLACEMENT.get(name)
        if place is None:
            continue
        ox, oy = _THING_GALLERY_KICK_OFFSETS.get(name, (0.0, 0.0))
        entities = thing_renderer.expand_thing_to_world_z(
            thing,
            origin_xy=(place["gx"] + ox, place["gy"] + oy),
            floor_z=0.0,
            yaw_deg=0.0,
            id_base=40_000,
            instance_id=place["idx"],
        )
        out.extend(entities)
    return out


# ── Live-edit handlers (B-mode tune) ─────────────────────────────


def thing_edit(thing_name: str, part_role: str, field: str,
                delta: list[float] | float) -> bool:
    """Mutate ONE part's field of an in-memory Thing, regenerate the
    gallery entity list, and return True on success.

    Supported fields: rel_position (vec3), rel_size (vec3),
    rotation_deg (scalar), color_base (vec3).

    Delta is added to current value; result clamped against the
    schema bounds. No-op if thing/part/field not found."""
    global _THING_GALLERY_ENTITIES
    thing = _THING_GALLERY_THINGS.get(thing_name)
    if thing is None:
        return False
    part = next((p for p in thing.parts if p.role == part_role), None)
    if part is None:
        return False

    if field == "rel_position":
        if not isinstance(delta, (list, tuple)) or len(delta) != 3:
            return False
        new = (
            _clamp(part.rel_position[0] + float(delta[0]), -0.5, 0.5),
            _clamp(part.rel_position[1] + float(delta[1]), -0.5, 0.5),
            _clamp(part.rel_position[2] + float(delta[2]), -0.5, 0.5),
        )
        part.rel_position = new
    elif field == "rel_size":
        if not isinstance(delta, (list, tuple)) or len(delta) != 3:
            return False
        new = (
            _clamp(part.rel_size[0] + float(delta[0]), 0.001, 1.0),
            _clamp(part.rel_size[1] + float(delta[1]), 0.001, 1.0),
            _clamp(part.rel_size[2] + float(delta[2]), 0.001, 1.0),
        )
        part.rel_size = new
    elif field == "rotation_deg":
        d = float(delta if not isinstance(delta, (list, tuple)) else delta[0])
        part.rotation_deg = (part.rotation_deg + d) % 360.0
    elif field == "color_base":
        if not isinstance(delta, (list, tuple)) or len(delta) != 3:
            return False
        base = part.color_base or (0.85, 0.66, 0.20)
        part.color_base = (
            _clamp(base[0] + float(delta[0]), 0.0, 1.0),
            _clamp(base[1] + float(delta[1]), 0.0, 1.0),
            _clamp(base[2] + float(delta[2]), 0.0, 1.0),
        )
    else:
        return False

    _THING_GALLERY_ENTITIES = _expand_thing_gallery()
    return True


def thing_save(thing_name: str) -> bool:
    """Write the in-memory Thing back to disk at
    library/things/<name>.json. Returns True on success."""
    import json
    from dataclasses import asdict
    thing = _THING_GALLERY_THINGS.get(thing_name)
    if thing is None or _THING_GALLERY_DIR is None:
        return False
    path = _THING_GALLERY_DIR / f"{thing_name}.json"
    try:
        # asdict-based serialization with tuples → lists for JSON
        out = {
            "name":         thing.name,
            "real_size_m":  list(thing.real_size_m),
            "anchor":       thing.anchor,
            "source":       thing.source or "live-tuned via B-mode",
            "tags":         list(thing.tags),
            "interactions": dict(thing.interactions),
            "parts": [
                _part_to_json(p) for p in thing.parts
            ],
        }
        path.write_text(json.dumps(out, indent=2) + "\n")
        return True
    except Exception as exc:                          # noqa: BLE001
        print(f"  thing_save({thing_name!r}) failed: {exc!r}", flush=True)
        return False


def _part_to_json(part) -> dict:
    out = {
        "primitive":     part.primitive,
        "role":          part.role,
        "rel_size":      [round(v, 4) for v in part.rel_size],
        "rel_position":  [round(v, 4) for v in part.rel_position],
        "rotation_deg":  round(part.rotation_deg, 2),
        "tier":          part.tier,
    }
    if part.color_base is not None:
        out["color_base"] = [round(v, 4) for v in part.color_base]
    if part.color_shadow is not None:
        out["color_shadow"] = [round(v, 4) for v in part.color_shadow]
    if part.color_accent is not None:
        out["color_accent"] = [round(v, 4) for v in part.color_accent]
    if part.negate:
        out["negate"] = True
    return out


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


_THING_GALLERY_ENTITIES: list[dict] = _load_thing_gallery()


# Biome-things entities — Blender-driven per-tile thing placements +
# greenhouse placeholder seeds for unfilled demand. Populated at
# run_server() boot via _build_biome_things(). Per
# `feat/biome-greenhouse` PR 3.
_BIOME_THINGS_ENTITIES: list[dict] = []

# Per-biome elevation field — {(tile_x, tile_y): integer_level}.
# Solved once at biome init via biome_elevation.solve_elevation_field.
# Things-on-tile-elevation + slope/wall rendering both query this
# dict. Per `feat/biome-greenhouse` elevation extension.
_BIOME_ELEVATION_FIELD: dict[tuple[int, int], int] = {}

# Terrain walls — wireframe boundaries between adjacent tiles at
# different elevations. Built from _BIOME_ELEVATION_FIELD at biome
# init. Static across the brain's lifetime.
_BIOME_TERRAIN_WALLS: list[dict] = []

# Precomputed biome-stamps — architecture assemblies (bridges,
# ladders, staircases, doorways) placed sparsely via
# BIOME_STAMP_CONFIG.tile_chance. Per the 2026-05-17 "stamps as data"
# PR. Shipped culled-by-camera per frame, same path as biome_things.
_BIOME_STAMPS_ENTITIES: list[dict] = []

# Variant deck state (variant_deck PR 2026-05-17). The deck is a
# bounded list of deterministic seed candidates per biome; player
# cycles through them with [/] keys; lock-in writes the chosen seed
# to vault.biome_locks for persistence. _active_variant_index = -1
# means "locked seed in use, not part of the cycling deck."
_VARIANT_DECK_SIZE: int = 7
_active_variant_index: int = 0


def _variant_seeds(biome: str, n: int = _VARIANT_DECK_SIZE) -> list[int]:
    """Return N deterministic seed candidates for a biome. Stable
    across brain restarts — variant 3 of cavern is always the same
    world. Used by the variant-deck UI so the player can browse and
    lock one in."""
    return [hash((biome, "variant", i)) & 0x7fffffff for i in range(n)]


# Lexicon placeholder substitution for interact response text.
# Per `design_lexicon_architecture` + `feedback_her_voice`: the player's
# wife's vocabulary is woven into world descriptions verbatim. The
# Blender's lexicon arm provides the data; this function does the
# string substitution at request time. Air-gap clean — no LLM in the
# path.
_LEXICON_PLACEHOLDER_RE = re.compile(r"\{lex(?::([\w_]+))?\}")


def _substitute_lexicon(text: str, rng_seed: int = 0) -> str:
    """Replace {lex} or {lex:CATEGORY} placeholders with a verbatim
    term from vault.lexicon. Falls back gracefully — if no matching
    term, the placeholder is removed (not left in)."""
    if "{lex" not in text:
        return text                # fast path
    try:
        import random as _rand
        rng = _rand.Random(rng_seed)
        vault = _get_vault()

        def repl(m: re.Match) -> str:
            category = m.group(1)
            try:
                terms = vault.lexicon_terms(
                    category=category,
                    min_occurrences=2,
                    limit=30,
                )
            except Exception:                              # noqa: BLE001
                return ""
            if not terms:
                return ""              # graceful: empty string, not leftover placeholder
            return str(rng.choice(terms)["term"])

        return _LEXICON_PLACEHOLDER_RE.sub(repl, text)
    except Exception:                                       # noqa: BLE001
        return text


_WEAPON_CLASS_TO_ACTIVITY: dict[str, tuple] = {
    "melee_blade":   (activity_loop.ActivityClass.HUNT,  1),
    "melee_blunt":   (activity_loop.ActivityClass.HUNT,  1),
    "melee_tether":  (activity_loop.ActivityClass.HUNT,  2),
    "ranged_thrown": (activity_loop.ActivityClass.HUNT,  1),
    "ranged_bow":    (activity_loop.ActivityClass.HUNT,  1),
    "magic_staff":   (activity_loop.ActivityClass.SOLVE, 1),
    "magic_wand":    (activity_loop.ActivityClass.SOLVE, 1),
}


def _engagement_state_manifest(active_engagement: dict | None) -> dict | None:
    """Build the manifest payload for the active engagement, or None.

    Reads the handler's live session for the dynamic bits (composed,
    attempt_count) so the client sees per-tick state without the brain
    re-copying. Returns None when no engagement is active.
    """
    if active_engagement is None:
        return None
    eng_type = active_engagement["engagement_type"]
    try:
        spec = make_brain_registry.get(eng_type)
        session = getattr(spec.handler, "session", None) or {}
    except LookupError:
        session = {}
    return {
        "engagement_type": eng_type,
        "kind":            active_engagement["kind"],
        "agent_id":        active_engagement["agent_id"],
        "engagement_id":   active_engagement["engagement_id"],
        "rule_args":       active_engagement.get("rule_args", {}),
        # Live handler session view (the client uses this for overlay state)
        "pool":            list(session.get("pool", [])),
        "composed":        list(session.get("composed", [])),
        "target_count":    session.get("target_count"),
        "max_attempts":    session.get("max_attempts"),
        "attempt_count":   session.get("attempt_count", 0),
    }


def _open_engagement(world, kind: str, agent_id: str, engagement_cfg: dict) -> None:
    """Open a creature engagement on contact / strike-to-creature.

    Wires four things in one call:
      1. Dispatch to the engagement_type's make-brain handler (begin()).
      2. Open the vault.engagements row for telemetry.
      3. Transition game_state HUB → ENGAGEMENT.
      4. Stamp world.active_engagement so manifest emit can find it.

    Raises if the engagement_type isn't registered. Caller wraps in
    try/except — partial state (e.g. handler open but vault failed)
    is cleaned up on the next end_engagement call which is defensive.
    """
    eng_type     = str(engagement_cfg.get("engagement_type", ""))
    rule_args    = dict(engagement_cfg.get("rule_args", {}) or {})

    spec = make_brain_registry.get(eng_type)      # raises LookupError
    handler = spec.handler

    began = handler.begin(agent_id=agent_id, kind=kind, rule_args=rule_args)
    if not began:
        raise RuntimeError(
            f"engagement_type {eng_type!r} handler refused begin "
            f"(another session already active on the same handler?)"
        )

    engagement_id = _get_vault().engagement_open(
        instance_id=eng_type,
        agent_id=agent_id,
        kind=kind,
    )

    world.game_state = gs.transition(world.game_state, gs.GameStateName.ENGAGEMENT)
    world.active_engagement = {
        "engagement_type": eng_type,
        "kind":            kind,
        "agent_id":        agent_id,
        "engagement_id":   engagement_id,
        "rule_args":       rule_args,
    }
    print(
        f"  engagement: opened {eng_type} (kind={kind}, agent={agent_id}, "
        f"row={engagement_id})",
        flush=True,
    )


def _close_engagement(world, terminal_state: str) -> None:
    """Close the active engagement and transition back to HUB.

    No-op if there's no active engagement (idempotent). terminal_state
    ∈ {"won", "lost", "aborted", "fled"} — passed straight through to
    the vault row + handler. Handler's `end()` returns the closed
    session dict so we can persist final metrics."""
    eng = world.active_engagement
    if eng is None:
        return
    eng_type = eng["engagement_type"]
    try:
        spec = make_brain_registry.get(eng_type)
        closed_session = spec.handler.end()
    except Exception as exc:                          # noqa: BLE001
        print(f"  engagement: handler end failed: {exc!r}", flush=True)
        closed_session = None

    metrics: dict = {}
    if isinstance(closed_session, dict):
        metrics = {
            "attempts":      closed_session.get("attempt_count"),
            "target_count":  closed_session.get("target_count"),
            "composed_len":  len(closed_session.get("composed", []) or []),
        }
    try:
        _get_vault().engagement_close(
            engagement_id=int(eng["engagement_id"]),
            terminal_state=terminal_state,
            metrics=metrics,
        )
    except Exception as exc:                          # noqa: BLE001
        print(f"  engagement: vault close failed: {exc!r}", flush=True)

    try:
        world.game_state = gs.transition(world.game_state, gs.GameStateName.HUB)
    except ValueError:
        # Already at HUB (shouldn't happen, but don't crash if it does)
        pass
    print(
        f"  engagement: closed {eng_type} → {terminal_state} "
        f"(metrics={metrics})",
        flush=True,
    )
    world.active_engagement = None


def _on_strike_resolve(world, active_strike, target_entity) -> None:
    """Resolve an ARPG combat Strike contact (feat/arpg-combat PR 2 + PR 7).

    Called per-resolution by `strike_runtime.tick_active_strikes`. Three
    outcome paths:

    1. `target_entity is None` — Strike faded at max-age. Emit
       `strike_missed` StateEvent. No damage / engagement / activity emit.

    2. `target_entity` has an `engagement` slot in kind_config — creature
       engagement trigger. Per `design_creature_engagement_v1` and
       `design_wont_tolerate` #5, hitting a creature does NOT damage HP.
       Strike opens the kind's engagement_type. V1 stub: emit StateEvent
       + weapon-class-specific activity signal.

    3. `target_entity` has no engagement slot — env damage. Generalize
       the existing kind_destroyed flow: push tick event for async-quest
       predicates, add to destroyed_entity_ids ledger, emit StateEvent
       toast, fire weapon-class-specific activity signal.

    PR 7 also closes the vault.combat_sessions row opened on weapon_use,
    differentiates HUNT vs SOLVE per weapon_class.
    """
    # weapon_class differentiates activity emission per spec table
    weapon_class = active_strike.weapon_class or ""
    activity_class, intensity = _WEAPON_CLASS_TO_ACTIVITY.get(
        weapon_class,
        (activity_loop.ActivityClass.HUNT, 1),       # default
    )

    if target_entity is None:
        # Faded
        world.state_events.emit(
            "strike_missed",
            f"{active_strike.strike.weapon_kind.upper()} — MISSED",
            None,
            REG_LOOP,
        )
        # Close combat_sessions row with "missed" outcome.
        if active_strike.session_id is not None:
            try:
                _get_vault().combat_session_close(
                    session_id=active_strike.session_id,
                    outcome="missed",
                )
            except Exception:                            # noqa: BLE001
                pass
        return

    target_kind = str(target_entity.get("kind", ""))
    target_id = target_entity.get("id")

    # Look up kind_config to determine env vs creature behavior
    kind_cfg = _kc.kind(target_kind) or {}
    has_engagement = "engagement" in kind_cfg

    if has_engagement:
        # Creature path — Strike triggers engagement. Only ONE engagement
        # at a time (V1 cap); subsequent strikes during an active
        # engagement just emit the StateEvent + activity, they don't open
        # a second session.
        eng_cfg = kind_cfg.get("engagement", {})
        already_engaged = world.active_engagement is not None
        if not already_engaged:
            try:
                _open_engagement(
                    world,
                    kind=target_kind,
                    agent_id=str(target_id) if target_id is not None else f"{target_kind}@unknown",
                    engagement_cfg=eng_cfg,
                )
            except Exception as exc:                     # noqa: BLE001
                # Fall through to legacy stub if dispatch fails; the
                # game shouldn't get stuck mid-engagement on a wiring bug.
                print(f"  engagement open failed: {exc!r}", flush=True)
        world.state_events.emit(
            "engagement_opened_via_strike",
            f"{active_strike.strike.weapon_kind.upper()} → {target_kind.upper()}",
            None,
            REG_TENSE,
        )
        activity_loop.emit_activity(
            activity_class,
            intensity=intensity,
            primitive="strike_to_creature",
            source_brain="arpg_combat",
            payload={
                "weapon":       active_strike.strike.weapon_kind,
                "weapon_class": weapon_class,
                "kind":         target_kind,
                "mode":         active_strike.strike.mode,
            },
        )
        # Close combat_sessions row.
        if active_strike.session_id is not None:
            try:
                _get_vault().combat_session_close(
                    session_id=active_strike.session_id,
                    outcome="engagement_triggered",
                    target_kind=target_kind,
                    target_id=int(target_id) if target_id is not None else None,
                )
            except Exception:                            # noqa: BLE001
                pass
        return

    # Env path — generalize kind_destroyed flow
    world.tick_events.append({
        "type": "kind_destroyed",
        "kind": target_kind,
    })
    if target_id is not None:
        try:
            world.destroyed_entity_ids.add(int(target_id))
        except (TypeError, ValueError):
            pass
    world.state_events.emit(
        "strike_landed",
        f"{active_strike.strike.weapon_kind.upper()} → {target_kind.upper()}",
        None,
        REG_LOOP,
    )
    activity_loop.emit_activity(
        activity_class,
        intensity=intensity,
        primitive="strike_destroyed_env",
        source_brain="arpg_combat",
        payload={
            "weapon":       active_strike.strike.weapon_kind,
            "weapon_class": weapon_class,
            "kind":         target_kind,
            "mode":         active_strike.strike.mode,
        },
    )
    # Close combat_sessions row with "landed" outcome.
    if active_strike.session_id is not None:
        try:
            from core.systems.strike_runtime import kinetic_energy as _ke
            _get_vault().combat_session_close(
                session_id=active_strike.session_id,
                outcome="landed",
                target_kind=target_kind,
                target_id=int(target_id) if target_id is not None else None,
                kinetic_energy=_ke(active_strike.current_state,
                                   active_strike.strike.profile.ball_mass),
            )
        except Exception:                                # noqa: BLE001
            pass


# ── Pillar formation geometry ─────────────────────────────────────────
# Per `design_seven_pillars` + `feedback_factor_of_7` + `design_meta_pixel_mote`:
# all 7 character-creation pillars arrange in a heptagonal ring south of
# spawn. Player walks among them; sealed pillars disappear so the formation
# thins as the ritual progresses.

_PILLAR_RING_CENTER = (0.0, -22.0)  # 8m south of spawn at (0, -14) — tight, visible
_PILLAR_RING_RADIUS = 6.0
_PILLAR_RING_START_ANGLE = math.pi / 2  # i=0 at top of ring (closest to spawn)

# Display order: starts with Name at the top (closest to spawn), wraps
# clockwise through the rest. Stub pillars interleave with interactive
# ones so player tests every input plumbing per session. Reflection is
# NOT in this list — it's the HUB meta-pillar.
_PILLAR_RING_ORDER = (
    "name",        # i=0, north — ritual entry point
    "days",        # i=1, NE — stub (pre-interactive)
    "years",       # i=2, NW — interactive (binary-narrow cascade)
    "first_path",  # i=3, W — stub
    "vow",         # i=4, SW — stub
    "standing",    # i=5, SE — stub
    "mark",        # i=6, E — stub
)

# Per-pillar color — distinguishes the seven at a glance.
# Themed: identity-amber, dawn-yellow, growth-green, bronze-relic,
# pale-ivory-vow, blood-effort-red, mystic-violet.
_PILLAR_COLORS: dict[str, tuple[float, float, float]] = {
    "name":       (1.00, 0.70, 0.00),  # amber gold
    "days":       (1.00, 0.86, 0.31),  # sun yellow
    "years":      (0.51, 0.78, 0.51),  # sage green
    "first_path": (0.78, 0.51, 0.20),  # bronze
    "vow":        (0.86, 0.86, 0.78),  # pale ivory
    "standing":   (0.78, 0.39, 0.31),  # terracotta
    "mark":       (0.71, 0.39, 0.90),  # violet
}


def _quest_bearings(world, player_x: float, player_y: float) -> dict[str, str]:
    """Compute compass bearing per active quest with a registered
    target resolver. Returns a `{qid: "NE"}` map. Active quests whose
    predicate has no resolver, or whose resolver returns None, are
    absent from the map — vector terminal HUD shows them without a
    bearing prefix.

    Per PR 4 of `project_async_quest_refactor` — fills the gap user
    FELT during 2026-04-30 UAT walk: active quests need direction.
    """
    from core.systems.bearing import bearing as _bearing
    from core.systems.quests import get as get_quest
    from core.systems.quests import predicates as _quest_predicates

    bearings: dict[str, str] = {}
    for qid in world.quest_state.active:
        quest = get_quest(qid)
        if quest is None:
            continue
        resolver = _quest_predicates.get_target(quest.predicate)
        if resolver is None:
            continue
        target = resolver(
            world,
            dict(quest.predicate_args),
            player_x,
            player_y,
        )
        if target is None:
            continue
        compass = _bearing((player_x, player_y), target)
        if compass:
            bearings[qid] = compass
    return bearings


def _reflective_to_manifest(world) -> dict:
    """Serialize world.reflective for the manifest. Called only when
    world.reflective.active is True. Includes the rule's player-facing
    instructions resolved from the rule registry.

    Per `design_brain_ground_truth`: brain ships truth (rule id, pool,
    composed list, attempt count). Vector terminal owns rendering
    (fridge background, magnet tray layout, canvas, key bindings).
    """
    from core.systems.reflective import rules as _rules

    state = world.reflective
    rule = _rules.get(state.current_rule_id)
    rule_block = None
    if rule is not None:
        rule_block = {
            "id": rule.id,
            "name": rule.name,
            "instructions": rule.instructions,
        }
    return {
        "active": True,
        "trigger": state.trigger,
        "rule": rule_block,
        "magnet_pool": list(state.magnet_pool),
        "composed": list(state.composed),
        "attempt_count": state.attempt_count,
    }


def _heptagon_position(i: int) -> tuple[float, float]:
    """Compute (x, y) in manifest coords for the i-th pillar in the ring."""
    angle = _PILLAR_RING_START_ANGLE + 2 * math.pi * i / 7
    cx, cy = _PILLAR_RING_CENTER
    return (
        cx + _PILLAR_RING_RADIUS * math.cos(angle),
        cy + _PILLAR_RING_RADIUS * math.sin(angle),
    )


# Ritual states clear non-pillar entities within this radius of spawn so
# the heptagonal formation reads cleanly. Mission states (IN_MISSION /
# RESULTS) keep natural geography for actual gameplay.
_RITUAL_CLEAR_RADIUS_M = 40.0
_SPAWN_X = 0.0
_SPAWN_Y = -14.0
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

        # Tension cycle — board immediately. Visible intensity is
        # dialed via TENSION_WET_MIX in the manifest builder, not by
        # gating the cycle's activity.
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
                f"quests={len(loaded_player.completed_quests)}, {sheet_status}",
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

        # StateEvent buffer — universal player-feedback primitive (per
        # `design_state_events` once memory is saved). Every state change
        # the player should know about emits an event; clients render toasts.
        self.state_events: StateEventBuffer = StateEventBuffer()

        # Activity loop — universal "what is the player doing" substrate
        # (per `feat_make-brain-ping-pong.md` PR 9). Saturating int[7]
        # counters with rotating slot-decay; producers emit one of seven
        # ActivityClass signals; the loop edge-detects threshold crossings
        # against REWARD_TABLE and fires StateEvents on rising edges.
        # Module-level singletons; `install()` returns the pair.
        # Vault binding enables activity_log telemetry per audit A6.
        self.prefs, self.activity_loop = activity_loop.install(
            self.state_events, vault=_get_vault(),
        )

        # UNWIND producer accumulator (PR 10) — pure-cumulative dwell-time
        # tracker. Decoupled from `dwell_time` (which decays on movement)
        # so an UNWIND emit fires for every DWELL_UNWIND_SLICE_SECONDS of
        # accumulated low-input time, even across active stretches.
        self._dwell_accum_for_unwind: float = 0.0

        # ARPG combat substrate (feat/arpg-combat PR 2). active_strikes
        # holds in-flight Strikes — physics-advanced each tick by
        # strike_runtime.tick_active_strikes. Cleared on resolution
        # (hit or fade); manifest exposes them for client rendering.
        self.active_strikes: list[strike_runtime.ActiveStrike] = []
        # Creature engagement state (feat/creature-engagement PR 4).
        # None when no engagement is in flight. Populated by
        # _open_engagement; cleared by _close_engagement. Only ONE
        # engagement at a time per V1.
        self.active_engagement: dict | None = None
        # Seed V1 weapon profiles (throwing_axe etc.) + register SHOT
        # dispatcher. Idempotent across brain restarts.
        weapons_pkg.activate_v1_weapons(_get_vault())

        # Creature engagement substrate — register compose_three handler.
        # Per `.claude/feature/feat_creature-engagement.md` PR 2.
        # Idempotent; PR 4 wires dispatch on creature contact.
        from core.systems.make_brains import compose_three as compose_three_mb
        compose_three_mb.activate(_get_vault())

        # Quest state — async ambient quest substrate per
        # `project_async_quest_refactor`. PR 1.2 keeps this in-memory on
        # BrainWorld; PR 2 (V3 save schema) promotes the persistent fields
        # onto PlayerState. Until then, quest progress resets each brain
        # boot (no real loss — substrate isn't player-facing yet).
        # `available` seeds from the biome's active_classes, mapping each
        # class name to its `_01` quest id; unknown ids skip silently.
        available_quest_ids = [
            f"{cls}_01"
            for cls in BIOME_EXPEDITIONS.get(biome_name, {}).get("active_classes", [])
            if quests.get(f"{cls}_01") is not None
        ]
        # V3 hydrate: pull persisted active + completed quest lists off
        # the loaded PlayerState. Both default to () for new/legacy
        # players. completed first (so seeded available can dedupe
        # against it below), then active.
        loaded_completed = (list(loaded_player.completed_quests)
                            if loaded_player is not None else [])
        loaded_active = (list(loaded_player.active_quests)
                         if loaded_player is not None else [])
        # Strip seeded ids that the player already finished or has active
        # — re-presenting a completed/active quest under "available" is
        # confusing and would let them re-toggle a closed loop.
        seeded_available = [
            qid for qid in available_quest_ids
            if qid not in loaded_completed and qid not in loaded_active
        ]
        self.quest_state = QuestState(
            available=seeded_available,
            active=loaded_active,
            completed=loaded_completed,
        )
        # Per-frame event accumulator. Cmd handlers push entries
        # (`kind_destroyed`, future `cast_landed` etc.); the per-tick
        # quest evaluator drains it and clears it each frame.
        self.tick_events: list[dict] = []

        # Live consequence instances on this world. The consequences
        # engine spawns instances when triggers fire, advances them
        # per tick, and removes them on resolution. Per
        # `design_reflective_loop` and `feedback_iterate_then_formalize`,
        # consequences hold dynamic resolution state — the shape of
        # what HP=0 (or any future trigger) actually does is in
        # `config/consequences.json`, not hardcoded here.
        self.consequences: list = []

        # Reflective-mode session state (the fridge + magnets). Session-
        # only; not persisted in V3 save schema. Populated by
        # state_machine.enter on HP=0 forced entry (via consequence
        # effect) or voluntary engage_fridge cmd. Cleared by
        # state_machine.exit. See `design_reflective_loop`.
        self.reflective: ReflectiveState = ReflectiveState()

        # Replay dynamic journal-derived quests from the vault. Closes
        # the "where'd my quest go" gap surfaced in 2026-04-30 UAT — the
        # in-memory registry is fresh on every boot, but vault.entries
        # persists, so we re-synthesize the same Quest deterministically
        # (raw_note + bridge logic = same id, same predicate, same
        # head term). Skips silently if the journal schema doesn't
        # exist yet (legacy vault.db without J1 migration applied).
        try:
            replayed = _replay_journal_quests(
                self.quest_state, set(_kc.all_kinds().keys()))
            if replayed:
                print(f"  replayed {replayed} journal quest(s) from vault",
                      flush=True)
        except Exception as exc:
            # Don't kill brain boot on a replay glitch — the live brain
            # still works without dynamic quests, just loses
            # cross-restart continuity until next journal_entry.
            print(f"  journal quest replay skipped: {exc}", flush=True)

        if loaded_sheet is not None:
            # Returning player with a sealed sheet — straight to HUB.
            self.game_state: GameState = GameState.initial()
        else:
            # Either no save at all, or a legacy V1 save without a sheet.
            # Either way, run the 7-pillar ritual to build a sheet. Stubs 2-7
            # auto-default so only Pillar 1 (Name) requires interaction.
            self.character_draft = self._init_creation_draft()
            self.game_state: GameState = GameState.fresh_character()

        # World regen support. world_revision bumps on every regen call;
        # clients watch it, re-dispatch spawn, and rebuild entity render
        # state. Post PR 6 there's no hub_seed — the active brain seed
        # persists for the whole session; reflective commits regen with
        # a fresh derived seed (`design_death_only_regen`).
        self.world_revision: int = 0

        # Smashed-entity ledger. Client `kind_destroyed` cmd pushes ids
        # in here; manifest emission filters them out so smashed pots
        # actually disappear. Cleared on world regen (next cycle's
        # spawns are fresh — including respawns of previously-destroyed
        # kinds at new procedural positions).
        self.destroyed_entity_ids: set[int] = set()

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
        """Empty draft — player walks all 7 pillars in the heptagonal
        formation. Stubbed pillars (2/4/5/6/7) commit their placeholder
        values via single-ENTER on their dial; interactive pillars
        (1 Name, 3 Years) take their real interaction.

        Every pillar engagement exercises the input plumbing for UAT.
        Each has its own toast on seal so the ritual feels real.
        """
        return CharacterDraft()

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
        # Clear smashed-entity ledger — fresh seed means fresh spawns,
        # nothing to filter out.
        self.destroyed_entity_ids = set()
        # Rebuild exchange with new seed (legacy-path safety).
        self.exchange = TileExchange(self.biome_name, new_seed, self.tile_size)
        # Re-prime spawn tile so non-stamp paths have entities.
        self._generate_tile(0, 0)


    def _tile_key(self, cam_x, cam_y):
        # Match TileExchange._tile_key — pick the tile whose center is
        # closest to (cam_x, cam_y). Entity placement uses
        # (lx - half + tx*tile_size) so tile (tx, ty) is centered on
        # (tx*tile_size, ty*tile_size). Floor-bucketing produces a
        # half-tile offset bug; see tile_exchange.py for the regression
        # this fixes (2026-05-01).
        half = self.tile_size / 2.0
        return (int(math.floor((cam_x + half) / self.tile_size)),
                int(math.floor((cam_y + half) / self.tile_size)))

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

        # Activity loop tick — slot-decay rotation + reward edge detection.
        # Runs BEFORE tension.tick so PR 15's hybrid pacing reads a
        # current dominant class. Producers across six brain surfaces
        # emit class signals; this is where the loop catches up + fires
        # reward StateEvents. Per `feat_make-brain-ping-pong.md` PR 9 +
        # activity_loop PRs 11-14.
        self.activity_loop.tick(dt)

        # Hybrid pacing (PR 15) — push the dominant-class pace multiplier
        # into TensionCycle BEFORE its tick. SANCTUM_TENSION_PACE_DISABLED=1
        # env flag forces 1.0 (disable knob if UAT exposes a regression).
        import os as _os
        if _os.environ.get("SANCTUM_TENSION_PACE_DISABLED") == "1":
            self.tension.set_pace_multiplier(1.0)
        else:
            self.tension.set_pace_multiplier(activity_loop.pace_multiplier())

        # Tension cycle tick (consumes pace multiplier set above)
        entity_count = len(exchange_entities)
        budget_max = self.tension._config.get("budget_max", 800)
        envelope = self.tension.tick(dt, entity_count, budget_max)

        # ARPG combat — advance in-flight Strikes (feat/arpg-combat PR 2).
        # Each ActiveStrike's BallisticsSolver runs one frame, then the
        # runtime checks per-strike entity collisions + age-fade. Resolved
        # strikes are filtered after the tick. on_resolve handles all
        # side effects (StateEvents, activity_loop, engagement triggers,
        # kind_destroyed event).
        if self.active_strikes:
            kc = _kc.all_kinds()
            strike_runtime.tick_active_strikes(
                self.active_strikes, exchange_entities, kc, dt,
                on_resolve=lambda act, target: _on_strike_resolve(self, act, target),
            )
            # Filter resolved strikes
            self.active_strikes = [a for a in self.active_strikes if not a.resolved]

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
        # Wet/dry on tension's visible output. 1.0 = full cycle effect,
        # 0.0 = cycle runs underneath but no visible modulation. Cycle
        # state (budget, dump events, telemetry) is unchanged either way.
        TENSION_WET_MIX = 0.5
        if self.tension.active and envelope:
            open_amb = self.tension._config.get("open", {}).get(
                "ambient", (0.5, 0.5, 0.5))
            open_avg = max(sum(open_amb) / 3.0, 0.01)
            tension_avg = sum(envelope.ambient) / 3.0
            raw_factor = max(tension_avg / open_avg, 0.05)
            factor = 1.0 + (raw_factor - 1.0) * TENSION_WET_MIX
            ambient = [
                max(ls["ambient"][0] * factor, AMBIENT_FLOOR[0]),
                max(ls["ambient"][1] * factor, AMBIENT_FLOOR[1]),
                max(ls["ambient"][2] * factor, AMBIENT_FLOOR[2]),
            ]
            # Fog: same scalar modulation on ls baseline, but tension
            # envelope's fog_near/fog_far ratios to "open" drive the curve.
            open_fog = self.tension._config.get("open", {}).get(
                "fog", (ls["fog_near"], ls["fog_far"]))
            raw_near = envelope.fog[0] / max(open_fog[0], 0.01)
            raw_far = envelope.fog[1] / max(open_fog[1], 0.01)
            near_factor = 1.0 + (raw_near - 1.0) * TENSION_WET_MIX
            far_factor = 1.0 + (raw_far - 1.0) * TENSION_WET_MIX
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
        # Ritual canvas clearing — during HUB and CHARACTER_CREATION,
        # remove non-pillar entities within _RITUAL_CLEAR_RADIUS_M of spawn
        # so the formation reads cleanly. The synthetic pillar injection
        # below adds back the colored pillars; everything else (cavern
        # geometry, walls, mushrooms, etc.) is filtered out near spawn.
        # Mission states keep all entities for gameplay.
        if self.game_state.state in (
            gs.GameStateName.CHARACTER_CREATION,
            gs.GameStateName.HUB,
        ):
            clear_sq = _RITUAL_CLEAR_RADIUS_M * _RITUAL_CLEAR_RADIUS_M
            visible = [
                e for e in visible
                if ((e["x"] - _SPAWN_X) ** 2 + (e["y"] - _SPAWN_Y) ** 2) > clear_sq
            ]

        # Heptagonal pillar formation per `design_seven_pillars` +
        # `feedback_factor_of_7` + `design_meta_pixel_mote`. Center sits
        # ~8m south of spawn (which is at (0, -14, 0) facing south); ring
        # radius 6 so the formation is visible immediately on connect.
        # i=0 is the "north" position (closest to spawn) — Pillar of Name
        # leads, 2m directly in front of the player.
        if (self.game_state.state == gs.GameStateName.CHARACTER_CREATION
                and self.character_draft is not None):
            progress = self.character_draft.progress()
            for i, pillar_id in enumerate(_PILLAR_RING_ORDER):
                if progress.get(pillar_id, False):
                    continue  # sealed pillars disappear from the formation
                x, y = _heptagon_position(i)
                r, g, b = _PILLAR_COLORS.get(pillar_id, (1.0, 0.7, 0.0))
                visible.append({
                    "id": -1000 - i,
                    "kind": f"pillar_{pillar_id}",
                    "x": x, "y": y, "z": 0.0,
                    "sx": 0.6, "sy": 0.6, "sz": 3.0,
                    "heading": 0.0,
                    "r": r, "g": g, "b": b,
                    "collision_radius": 0.6,
                })

        # Pillar of Reflection — meta re-do pillar, lives in HUB at the
        # heptagonal ring's center. Engaging it transitions back to
        # CHARACTER_CREATION so the player can walk through identity again.
        # Cooler hue distinguishes it from the amber creation pillars.
        if (self.game_state.state == gs.GameStateName.HUB
                and self.character_sheet is not None):
            cx, cy = _PILLAR_RING_CENTER
            # Per-biome fixture aliases — behavioral kind stays the same
            # (engage handlers in client check `kind == "pillar_reflection"`
            # / `kind == "fridge"`); the renderer reads `visual_kind` to
            # swap mesh + bounds + recipe per biome. Color/scale overrides
            # land via dict.update so missing keys fall through to defaults.
            biome_aliases = BIOME_REGISTRY.get(
                self.biome_name, {}
            ).get("fixture_aliases", {})

            pillar_ent = {
                "id": -1100,
                "kind": "pillar_reflection",
                "x": cx, "y": cy, "z": 0.0,
                "sx": 0.6, "sy": 0.6, "sz": 3.0,
                "heading": 0.0,
                "r": 0.7, "g": 0.5, "b": 1.0,
                "collision_radius": 0.6,
            }
            pillar_ent.update(biome_aliases.get("pillar_reflection", {}))
            visible.append(pillar_ent)

            # Fridge — voluntary reflective practice + forced HP=0 entry.
            # Spawned in HUB only, also gated on a finalized character
            # sheet. Per `design_reflective_loop`. Visual flexes per biome;
            # the `engage_fridge` verb stays the same.
            fridge_ent = {
                "id": -1200,
                "kind": "fridge",
                "x": cx + 4.0, "y": cy - 14.0, "z": 0.0,
                "sx": 0.7, "sy": 0.4, "sz": 1.4,
                "heading": 0.0,
                "r": 0.85, "g": 0.88, "b": 0.90,
                "collision_radius": 0.7,
            }
            fridge_ent.update(biome_aliases.get("fridge", {}))
            visible.append(fridge_ent)

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
            # Smashed-entity ledger filter — see `kind_destroyed` cmd
            # handler. Smashed ids drop out of the manifest until next
            # world regen. Filter is the last step so hub fixtures /
            # creation pillars still emit correctly (their negative
            # ids never collide with procedural entity ids).
            "entities": [
                e for e in visible
                if int(e.get("id", -1)) not in self.destroyed_entity_ids
            ],
            "planes": self.planes,
            "banner_layers": BIOME_REGISTRY.get(self.biome_name, {}).get("banner_layers", []),
            # Per `design_banner_layer_taxonomy` 2026-05-02 — distance-
            # only horizon concepts (moon, mountain ridge silhouettes,
            # stars, etc.) authored per biome. Vector terminal renders
            # via per-kind functions in horizon_objects.py.
            "horizon_objects": BIOME_REGISTRY.get(self.biome_name, {}).get("horizon_objects", []),
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
            },
            # Loop state — clients read to gate UI / input per phase.
            # Post PR 6: 3 states (CHARACTER_CREATION / HUB / REFLECTIVE),
            # picker fields gone, no more mission_id/seed/results ghost
            # fields once `to_manifest` is updated.
            "game_state": gs.to_manifest(self.game_state),
            # Character creation surface (`design_seven_pillars`, `design_dial_input`).
            # `dial_prompt` is the active engagement; `pillar_progress` shows
            # which pillars have sealed; `character_sheet` is the finalized
            # output once draft is complete. All three are None outside the
            # CHARACTER_CREATION → HUB transition path.
            # State events — universal player-feedback ring buffer.
            # Clients track watermark by event id; first connect syncs to
            # the latest id (no historical toast spam).
            "state_events": state_events_to_manifest(self.state_events),
            # Activity loop snapshot — per-class counters + reward
            # distance + dominant class + pace multiplier. HUD consumes
            # for "what is the player doing" diagnostic readout.
            # Per PR 15.
            "activity": activity_loop.summary(),
            # In-flight ARPG combat strikes (feat/arpg-combat PR 2).
            # Vector terminal renders these as ball + trail per mode
            # via clients/vector_terminal/strike_renderer.py. Empty list
            # when no strikes are active. Each entry mirrors what the
            # client needs to render: id, mode, weapon, position, vel.
            "active_strikes": [
                _strike_to_manifest(a, cam_x, cam_y, cam_z)
                for a in self.active_strikes
            ],
            # Reflective-mode surface — populated only while a session
            # is active. Vector terminal renders the fridge UI off this.
            # Per `design_reflective_loop` — the fridge is a state, not
            # a screen, but the surface gives the client everything it
            # needs to draw the moment.
            "reflective": (
                _reflective_to_manifest(self) if self.reflective.active else None
            ),
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
            # Per-tile elevation field — for client-side floor clamping
            # so player camera Y rests on tile floor. Per
            # `feat/biome-greenhouse` elevation extension. Empty for
            # flat biomes (workroom/hub/unknown).
            # Variant deck (variant_deck PR 2026-05-17). Tells the
            # client which seed is active, whether it's locked, and
            # how many candidates are in the cycle. The HUD shows
            # "variant N/7" so the player knows what they're looking
            # at; [/] cycles via variant_roll, \ commits via
            # variant_lock.
            "variant_deck": {
                "current_seed":     int(getattr(self, "base_seed", 0)),
                "active_index":     int(_active_variant_index),
                "deck_size":        int(_VARIANT_DECK_SIZE),
                "is_locked":        _active_variant_index < 0,
            },
            # Per-tile elevation field for client floor clamp. Spacing
            # is ELEV_TILE_M (12m) — decoupled from biome stamp
            # tile_size (288m) per the 2026-05-17 fix. Field is empty
            # for flat biomes (workroom/hub).
            "elevation": {
                "tile_size":       _biome_elevation.ELEV_TILE_M,
                "level_height_m":  1.0,
                "tiles":           [
                    [tx, ty, lvl]
                    for (tx, ty), lvl in _BIOME_ELEVATION_FIELD.items()
                ],
            },
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
            # Make-brain top-level keys — merged from the active instance
            # if the biome binds one (volley_chamber → ping_pong, future
            # archery_range → archery, etc.). Empty dict spread is a
            # silent no-op for legacy biomes. Per
            # `.claude/feature/feat_make-brain-ping-pong.md` PR 3.
            **_make_brain_manifest_keys(self.biome_name),
            # Creature engagement (feat/creature-engagement PR 4). When
            # an engagement is in flight, the manifest carries a snapshot
            # of the active session so the client can render the
            # appropriate overlay. Absent (None) when game_state != ENGAGEMENT.
            "engagement_state": _engagement_state_manifest(self.active_engagement),
        }

    def cycle_light_state(self):
        """Advance to next light state (L key)."""
        self.light_state_idx = (self.light_state_idx + 1) % len(self.light_state_names)
        name = self.light_state_names[self.light_state_idx]
        print(f"  Light state: {name}", flush=True)
        return name


# -- TCP server ---------------------------------------------------------------

def _build_biome_elevation(biome_name: str, base_seed: int,
                             tile_range: int | None = None) -> dict:
    """Solve a per-tile elevation field for the biome. Cached in
    _BIOME_ELEVATION_FIELD module-level dict for thing placement +
    future slope rendering. Per `feat/biome-greenhouse` elevation.

    Spacing uses biome_elevation.ELEV_TILE_M (12m by default) —
    independent of the biome's stamp tile_size (288m), so transitions
    appear close to spawn. Per the 2026-05-17 decouple fix.
    """
    from core.systems import biome_elevation
    if tile_range is None:
        tile_range = biome_elevation.ELEV_TILE_RANGE_DEFAULT
    field = biome_elevation.solve_elevation_field(
        biome_name, tile_range=tile_range, base_seed=base_seed,
    )
    desc = biome_elevation.describe_field(field)
    print(
        f"  biome_elevation: solved {desc['tile_count']} tiles "
        f"@ {biome_elevation.ELEV_TILE_M}m "
        f"(levels {desc['level_min']}..{desc['level_max']}, "
        f"transitions={desc['transitions']})",
        flush=True,
    )
    return field


def _build_terrain_walls(
    elevation_field: dict[tuple[int, int], int],
    tile_size: float | None = None,
) -> list[dict]:
    """Emit wireframe walls at every tile boundary where adjacent
    tiles differ in elevation. One wall per pair (4-connectivity,
    iterated via +x/+y to avoid double-emission).

    Per `feat/biome-greenhouse` elevation extension 2026-05-17 — the
    tiered transition visuals. Wall height = level_diff × LEVEL_HEIGHT_M.

    Spacing uses biome_elevation.ELEV_TILE_M (12m) by default —
    decoupled from biome stamp tile_size per the 2026-05-17 fix.
    Callers may pass an explicit tile_size for legacy tests.

    SKIPS the 'step' tier (level_diff = 1, ~1m): these auto-resolve
    via the client floor-clamp; emitting walls for them is cosmetic
    noise + manifest bloat. Ledges + cliffs + walls are kept since
    those need visual+collision presence.

    Walls carry collision_radius so the player gets pushed back when
    walking into one (V1 — cylindrical approximation; perfect wall
    collision is a future client refactor). Tier label stored on
    entity for client-side rendering decisions later (e.g. dim walls
    for steps vs bright for cliffs).
    """
    from core.systems import biome_elevation

    if tile_size is None:
        tile_size = biome_elevation.ELEV_TILE_M

    out: list[dict] = []
    for (tx, ty), level in elevation_field.items():
        for dx, dy in ((1, 0), (0, 1)):
            n_coord = (tx + dx, ty + dy)
            if n_coord not in elevation_field:
                continue
            n_level = elevation_field[n_coord]
            diff = abs(n_level - level)
            if diff == 0:
                continue
            if diff == 1:
                # step tier — auto-resolved by client floor clamp.
                # No wall needed. Per 2026-05-17 perf cleanup.
                continue
            tier = biome_elevation.classify_transition(diff)
            high_z = biome_elevation.field_to_floor_z(max(level, n_level))
            low_z  = biome_elevation.field_to_floor_z(min(level, n_level))
            wall_h = high_z - low_z
            tile_center_x = tx * tile_size
            tile_center_y = ty * tile_size
            if dx == 1:
                # boundary along +X (right edge of tile)
                wall_x = tile_center_x + tile_size * 0.5
                wall_y = tile_center_y
                wall_sx, wall_sy = 0.15, tile_size
            else:
                # boundary along +Y
                wall_x = tile_center_x
                wall_y = tile_center_y + tile_size * 0.5
                wall_sx, wall_sy = tile_size, 0.15

            # Tier-driven color: dim for steps, brighter for cliffs.
            tier_color = {
                "step":  (0.55, 0.42, 0.20),
                "ledge": (0.70, 0.52, 0.22),
                "cliff": (0.85, 0.60, 0.25),
                "wall":  (1.00, 0.70, 0.28),
            }.get(tier, (0.55, 0.42, 0.20))

            out.append({
                "id":       70_000 + (hash((tx, ty, dx, dy)) & 0xffff),
                "kind":     "scan_cube_terrain_wall",
                "x":        round(wall_x, 3),
                "y":        round(wall_y, 3),
                "z":        round(low_z + wall_h / 2.0, 3),
                "sx":       wall_sx, "sy": wall_sy, "sz": wall_h,
                "r":        tier_color[0],
                "g":        tier_color[1],
                "b":        tier_color[2],
                "collision_radius": max(wall_sx, wall_sy) / 2.0,
                "_terrain_wall":    True,
                "_tier":            tier,
                "_level_diff":      diff,
            })
    return out


_TERRAIN_STAMP_TAGS: dict[str, tuple[int, int]] = {
    # tag → (min_diff, max_diff) — which elevation transitions this
    # stamp belongs on. Per the 2026-05-17 terrain-aware placement PR.
    "bridge": (2, 2),     # ledge spans (2m drop)
    "stair":  (3, 3),     # cliff face (3m climb)
    "ladder": (4, 99),    # wall face (4m+ climb)
}


def _terrain_keyed_stamps(
    biome_name: str,
    base_seed: int,
    elevation_field: dict[tuple[int, int], int] | None = None,
) -> list[dict]:
    """Scan the elevation field for transitions; emit stamps keyed to
    matching tier (bridges on ledges, stairs on cliffs, ladders on
    walls). Per the 2026-05-17 terrain-aware placement PR.

    Stamps placed by this pass bypass the tile_chance gate — they're
    keyed to features that already exist. Capped per-tag to avoid
    clutter (max ~2 per tier in the visible area).

    `elevation_field` defaults to the brain module's
    `_BIOME_ELEVATION_FIELD` when None — pass an explicit dict in
    tests so the function is exercisable without brain globals.
    """
    import random as _rand
    from core.systems import thing_renderer, biome_elevation, thing_library

    field = (elevation_field if elevation_field is not None
             else _BIOME_ELEVATION_FIELD)
    if not field:
        return []

    # Index stamps by terrain tag — each tag → list[Thing].
    stamps_by_tag: dict[str, list] = {tag: [] for tag in _TERRAIN_STAMP_TAGS}
    for stamp in thing_library.get_all_stamps().values():
        for tag in stamp.tags or []:
            if tag in stamps_by_tag:
                stamps_by_tag[tag].append(stamp)

    # Walk every elev-tile pair, classify the transition.
    candidates_by_tag: dict[str, list[dict]] = {
        tag: [] for tag in _TERRAIN_STAMP_TAGS
    }
    elev_m = biome_elevation.ELEV_TILE_M
    for (tx, ty), level in field.items():
        for dx, dy in ((1, 0), (0, 1)):
            n_coord = (tx + dx, ty + dy)
            if n_coord not in field:
                continue
            n_level = field[n_coord]
            diff = abs(n_level - level)
            for tag, (lo, hi) in _TERRAIN_STAMP_TAGS.items():
                if lo <= diff <= hi and stamps_by_tag[tag]:
                    # Place at the midpoint of the transition; orient
                    # along the transition axis (90° if +Y boundary).
                    mid_x = (tx + dx * 0.5) * elev_m
                    mid_y = (ty + dy * 0.5) * elev_m
                    yaw = 90.0 if dy == 1 else 0.0
                    # World-Y reference deferred until we know the
                    # stamp's attach_mode (per 2026-05-18 attach_mode
                    # primitive PR). Default candidate carries both
                    # tile heights; the placement loop picks one based
                    # on the chosen stamp's attach_mode.
                    low_level = min(level, n_level)
                    high_level = max(level, n_level)
                    candidates_by_tag[tag].append({
                        "mid_x": mid_x, "mid_y": mid_y,
                        "yaw": yaw,
                        "lower_floor_z":
                            biome_elevation.field_to_floor_z(low_level),
                        "upper_floor_z":
                            biome_elevation.field_to_floor_z(high_level),
                        "diff": diff, "tag": tag,
                    })

    # Per-tag deterministic sample, capped to MAX_PER_TAG to avoid
    # clutter. Cap chosen low — these are landmarks, not density.
    MAX_PER_TAG = 2
    rng = _rand.Random(hash((biome_name, "terrain_stamps", base_seed))
                       & 0xffffffff)
    out: list[dict] = []
    for tag, cands in candidates_by_tag.items():
        if not cands or not stamps_by_tag[tag]:
            continue
        rng.shuffle(cands)
        chosen = cands[:MAX_PER_TAG]
        for idx, cand in enumerate(chosen):
            stamp = rng.choice(stamps_by_tag[tag])
            # Resolve world-floor reference from the stamp's
            # attach_mode (per 2026-05-18 attach_mode primitive PR).
            # 'upper_floor' = bbox-bottom on higher tile (bridges
            # whose deck must align with the destination tier).
            # 'water_surface' reserved — no fixtures yet, falls
            # through to lower_floor_z. 'floor' (default) = bbox-
            # bottom on lower tile.
            mode = getattr(stamp, "attach_mode", "floor")
            if mode == "upper_floor":
                floor_z = cand["upper_floor_z"]
            else:
                floor_z = cand["lower_floor_z"]
            entities = thing_renderer.expand_thing_to_world_z(
                stamp,
                origin_xy=(cand["mid_x"], cand["mid_y"]),
                floor_z=floor_z,
                yaw_deg=cand["yaw"],
                id_base=85_000,
                instance_id=hash((tag, idx, base_seed)) % 100_000,
            )
            for ent in entities:
                ent["_stamp"] = stamp.name
                ent["_stamp_placement"] = "terrain"
                ent["_stamp_tier"] = tag
            out.extend(entities)
    return out


def _build_biome_stamps(biome_name: str, base_seed: int, tile_size: float,
                          tile_range: int = 2) -> list[dict]:
    """Precompute biome-stamp entities — architecture assemblies.

    Two-pass placement (per 2026-05-17 terrain-aware PR):
      1. Terrain-keyed pass — bridges on ledges, stairs on cliffs,
         ladders on walls. Bypasses tile_chance gate.
      2. Random tile pass — gazebos/signposts/fences/logs/doors at
         random tile XY via BIOME_STAMP_CONFIG.tile_chance. Skips
         stamps that carry a terrain affinity tag (those only place
         via pass 1).
    """
    import random as _rand
    from core.systems import thing_renderer, biome_elevation
    from core.systems.blender import (
        default_blender, BIOME_STAMP_CONFIG, BIOME_STAMP_CONFIG_DEFAULT,
    )

    cfg = BIOME_STAMP_CONFIG.get(biome_name, BIOME_STAMP_CONFIG_DEFAULT)

    # Pass 1: terrain-keyed placements (independent of tile_chance).
    out = _terrain_keyed_stamps(biome_name, base_seed)
    terrain_count = len(out)

    if float(cfg.get("tile_chance", 0.0)) <= 0.0:
        if terrain_count:
            print(f"  biome_stamps: {terrain_count} terrain-keyed "
                  f"entities (random gate disabled)", flush=True)
        return out

    bl = default_blender()
    vault = _get_vault()
    total_picks = 0
    total_unfilled = 0
    edge_pad = max(2.0, tile_size * 0.15)

    for tx in range(-tile_range, tile_range + 1):
        for ty in range(-tile_range, tile_range + 1):
            try:
                picks, unfilled_profiles = bl.stamps_for_tile(
                    biome_name, tx, ty, base_seed=base_seed,
                )
            except Exception as exc:                          # noqa: BLE001
                print(f"  biome_stamps: stamps_for_tile({tx},{ty}) "
                      f"failed: {exc!r}", flush=True)
                continue

            if not picks and not unfilled_profiles:
                continue                                      # tile lost the gate

            place_rng = _rand.Random(
                hash((biome_name, tx, ty, base_seed, "stamp_place"))
                & 0xffffffff
            )
            tile_origin_x = tx * tile_size
            tile_origin_y = ty * tile_size

            for slot_idx, stamp in enumerate(picks):
                # Terrain-affinity stamps are placed by pass 1 only.
                # Skip them in the random pass to prevent doubling.
                stamp_tags = set(stamp.tags or [])
                if stamp_tags & set(_TERRAIN_STAMP_TAGS):
                    continue
                ox = place_rng.uniform(edge_pad, tile_size - edge_pad)
                oy = place_rng.uniform(edge_pad, tile_size - edge_pad)
                world_x = tile_origin_x + ox
                world_y = tile_origin_y + oy
                etx, ety = biome_elevation.world_xy_to_elev_tile(
                    world_x, world_y,
                )
                elev_level = _BIOME_ELEVATION_FIELD.get((etx, ety), 0)
                tile_floor_z = biome_elevation.field_to_floor_z(elev_level)
                entities = thing_renderer.expand_thing_to_world_z(
                    stamp,
                    origin_xy=(world_x, world_y),
                    floor_z=tile_floor_z,
                    id_base=80_000,                  # stamp id namespace
                    instance_id=hash((tx, ty, slot_idx, "stamp"))
                                 % 100_000,
                )
                for ent in entities:
                    ent["_tile"] = [tx, ty]
                    ent["_stamp"] = stamp.name
                    ent["_stamp_placement"] = "random"
                out.extend(entities)
                total_picks += 1

            for profile in unfilled_profiles:
                try:
                    vault.greenhouse_record_demand(
                        biome=biome_name,
                        tile_x=tx, tile_y=ty,
                        slot=999,                    # stamp slot sentinel
                        tag_profile=profile,
                    )
                except Exception as exc:                      # noqa: BLE001
                    print(f"  biome_stamps: greenhouse record failed: "
                          f"{exc!r}", flush=True)
                total_unfilled += 1

    print(
        f"  biome_stamps: precomputed {len(out)} entities — "
        f"{terrain_count} terrain-keyed + {total_picks} random picks "
        f"+ {total_unfilled} greenhouse demands across "
        f"{(2*tile_range+1)**2} tiles",
        flush=True,
    )
    return out


def _build_biome_things(biome_name: str, base_seed: int, tile_size: float,
                          tile_range: int = 2) -> list[dict]:
    """Precompute biome-things entities for a (2*tile_range+1)² tile grid
    around origin. Each tile gets Blender-picked things at deterministic
    procedural positions; unfilled slots become greenhouse demands +
    placeholder seeds.

    Things now sit at their tile's elevation (per `feat/biome-greenhouse`
    elevation extension 2026-05-17) — _BIOME_ELEVATION_FIELD must be
    populated before this is called.

    Per `feat/biome-greenhouse` PR 3. Runs once at biome init. V1 only;
    procedural per-tick expansion is V2.
    """
    import random as _rand
    from core.systems import thing_renderer, biome_elevation
    from core.systems.blender import default_blender, BIOME_THING_CONFIG

    cfg = BIOME_THING_CONFIG.get(biome_name, {})
    per_tile = int(cfg.get("per_tile", 0))
    if per_tile <= 0:
        # workroom or unknown biome — no procedural things.
        return []

    bl = default_blender()
    vault = _get_vault()
    out: list[dict] = []
    total_picks = 0
    total_unfilled = 0
    edge_pad = max(2.0, tile_size * 0.15)

    for tx in range(-tile_range, tile_range + 1):
        for ty in range(-tile_range, tile_range + 1):
            try:
                picks, unfilled_profiles = bl.things_for_tile(
                    biome_name, tx, ty, base_seed=base_seed,
                )
            except Exception as exc:                              # noqa: BLE001
                print(f"  biome_things: things_for_tile({tx},{ty}) "
                      f"failed: {exc!r}", flush=True)
                continue

            # Deterministic placement RNG seeded by tile coord.
            place_rng = _rand.Random(
                hash((biome_name, tx, ty, base_seed, "place")) & 0xffffffff
            )
            tile_origin_x = tx * tile_size
            tile_origin_y = ty * tile_size

            # Persisted per-tile state — pickup tombstones + kick offsets.
            tile_state = vault.biome_thing_state_for_tile(biome_name, tx, ty)

            for slot_idx, thing in enumerate(picks):
                tname = thing.name
                state = tile_state.get(tname, {})
                if state.get("picked_up"):
                    continue                                # already picked up
                ox = place_rng.uniform(edge_pad, tile_size - edge_pad)
                oy = place_rng.uniform(edge_pad, tile_size - edge_pad)
                # Apply persisted kick offset
                ox += float(state.get("kick_dx", 0.0))
                oy += float(state.get("kick_dy", 0.0))
                # Per-thing elevation lookup: the elevation grid is
                # finer (12m) than the things grid (288m), so each
                # thing within a stamp tile may land on a different
                # elevation. Decouple per 2026-05-17 fix.
                world_x = tile_origin_x + ox
                world_y = tile_origin_y + oy
                etx, ety = biome_elevation.world_xy_to_elev_tile(
                    world_x, world_y,
                )
                elev_level = _BIOME_ELEVATION_FIELD.get((etx, ety), 0)
                tile_floor_z = biome_elevation.field_to_floor_z(elev_level)
                entities = thing_renderer.expand_thing_to_world_z(
                    thing,
                    origin_xy=(world_x, world_y),
                    floor_z=tile_floor_z,
                    id_base=50_000,
                    instance_id=hash((tx, ty, slot_idx)) % 100_000,
                )
                # Stamp _tile on every entity for client-side targeting
                for ent in entities:
                    ent["_tile"] = [tx, ty]
                out.extend(entities)
                total_picks += 1

            for slot_idx, profile in enumerate(unfilled_profiles,
                                                start=len(picks)):
                # Demand log
                try:
                    vault.greenhouse_record_demand(
                        biome=biome_name,
                        tile_x=tx, tile_y=ty,
                        slot=slot_idx,
                        tag_profile=profile,
                    )
                except Exception as exc:                          # noqa: BLE001
                    print(f"  biome_things: greenhouse record failed: "
                          f"{exc!r}", flush=True)

                # Placeholder seed entity — a small heptagonal_mote
                # at waist height. Visible reminder, not scenery noise.
                ox = place_rng.uniform(edge_pad, tile_size - edge_pad)
                oy = place_rng.uniform(edge_pad, tile_size - edge_pad)
                world_x = tile_origin_x + ox
                world_y = tile_origin_y + oy
                etx, ety = biome_elevation.world_xy_to_elev_tile(
                    world_x, world_y,
                )
                ph_level = _BIOME_ELEVATION_FIELD.get((etx, ety), 0)
                ph_floor_z = biome_elevation.field_to_floor_z(ph_level)
                placeholder = {
                    "id":        60_000 + (hash((biome_name, tx, ty, slot_idx))
                                            & 0xffff),
                    "kind":      "scan_heptagonal_mote_greenhouse",
                    "x":         round(world_x, 3),
                    "y":         round(world_y, 3),
                    "z":         round(ph_floor_z + 0.35, 3),
                    "sx":        0.30, "sy": 0.30, "sz": 0.30,
                    "r":         0.55, "g": 0.42, "b": 0.20,
                    "_greenhouse":  True,
                    "_profile":     profile,
                    "_tile":        [tx, ty],
                    "_slot":        slot_idx,
                }
                out.append(placeholder)
                total_unfilled += 1

    print(
        f"  biome_things: precomputed {len(out)} entities — "
        f"{total_picks} library picks + {total_unfilled} greenhouse "
        f"placeholders across {(2*tile_range+1)**2} tiles",
        flush=True,
    )
    return out


def _rebuild_world_substrates(world) -> None:
    """Re-solve elevation field + terrain walls + biome-things +
    biome-stamps for the current world.base_seed. Updates module
    globals in place. Called at boot AND whenever the variant seed
    changes (variant_roll/variant_lock paths). Per 2026-05-17
    variant deck PR.
    """
    global _BIOME_ELEVATION_FIELD, _BIOME_TERRAIN_WALLS
    global _BIOME_THINGS_ENTITIES, _BIOME_STAMPS_ENTITIES

    biome_name = world.biome_name
    base_seed = getattr(world, "base_seed", 0)
    tile_size = getattr(world, "tile_size", 12.0)

    _BIOME_ELEVATION_FIELD = _build_biome_elevation(
        biome_name, base_seed=base_seed,
    )
    _BIOME_TERRAIN_WALLS = _build_terrain_walls(_BIOME_ELEVATION_FIELD)
    if _BIOME_TERRAIN_WALLS:
        print(f"  terrain_walls: built {len(_BIOME_TERRAIN_WALLS)} walls",
              flush=True)
    _BIOME_THINGS_ENTITIES = _build_biome_things(
        biome_name, base_seed=base_seed, tile_size=tile_size,
    )
    _BIOME_STAMPS_ENTITIES = _build_biome_stamps(
        biome_name, base_seed=base_seed, tile_size=tile_size,
    )


def run_server(biome_name, port=9877):
    # All module-globals this function reassigns. Hoisted so later
    # branches that do `global X` don't conflict with the first
    # assignment (Python: global declaration must precede all
    # assignments in the function).
    global _BIOME_THINGS_ENTITIES
    global _THING_GALLERY_ENTITIES
    global _BIOME_ELEVATION_FIELD
    global _BIOME_TERRAIN_WALLS
    global _BIOME_STAMPS_ENTITIES
    global _active_variant_index

    world = BrainWorld(biome_name)

    # Variant deck — check for persisted lock first. If locked,
    # override world.base_seed before any substrate is built. Per
    # 2026-05-17 variant deck PR.
    vault_inst = _get_vault()
    locked_seed = vault_inst.biome_locked_seed(biome_name)
    if locked_seed is not None:
        world.base_seed = locked_seed
        _active_variant_index = -1               # locked: not in cycle
        print(f"  variant_deck: biome {biome_name!r} locked at "
              f"seed {locked_seed}", flush=True)
    else:
        # Use variant 0 as the default unlocked seed. This makes
        # cycling start at a known location in the deck.
        world.base_seed = _variant_seeds(biome_name)[0]
        _active_variant_index = 0
        print(f"  variant_deck: biome {biome_name!r} unlocked, "
              f"variant {_active_variant_index + 1}/{_VARIANT_DECK_SIZE} "
              f"(seed {world.base_seed})", flush=True)

    _rebuild_world_substrates(world)

    # Make-brain activation — if the biome registry binds an instance_id
    # for this biome, instantiate + register the handler. Idempotent
    # across re-boots. Per `.claude/feature/feat_make-brain-ping-pong.md` PR 3.
    mb_instance_id = BIOME_REGISTRY.get(biome_name, {}).get("make_brain_instance_id")
    if mb_instance_id == "ping_pong":
        from core.systems.make_brains import ping_pong as ping_pong_brain
        ping_pong_brain.activate(_get_vault())
        print(f"Make-brain: activated ping_pong for biome {biome_name!r}",
              flush=True)

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
                    consequence_signals.push_hp_zero(world)
                    print(f"  damage_self: hp {old_hp} -> {world.player.hp}", flush=True)
                    last_wake_ids = set()
                    continue

                if msg.get("cmd") == "engagement_place":
                    # Player composed a magnet into the active engagement.
                    # No-op if no engagement is active.
                    if world.active_engagement is None:
                        continue
                    eng_type = world.active_engagement["engagement_type"]
                    magnet = str(msg.get("magnet", ""))
                    try:
                        ok = make_brain_registry.dispatch(
                            eng_type, "place_magnet", magnet)
                    except (LookupError, AttributeError) as exc:
                        print(f"  engagement_place failed: {exc!r}", flush=True)
                        continue
                    if not ok:
                        print(f"  engagement_place rejected: magnet={magnet!r}",
                              flush=True)
                    continue

                if msg.get("cmd") == "engagement_remove":
                    if world.active_engagement is None:
                        continue
                    eng_type = world.active_engagement["engagement_type"]
                    try:
                        index = int(msg.get("index", -1))
                    except (TypeError, ValueError):
                        continue
                    try:
                        make_brain_registry.dispatch(
                            eng_type, "remove_magnet", index)
                    except (LookupError, AttributeError) as exc:
                        print(f"  engagement_remove failed: {exc!r}", flush=True)
                    continue

                if msg.get("cmd") == "engagement_commit":
                    if world.active_engagement is None:
                        continue
                    eng_type = world.active_engagement["engagement_type"]
                    try:
                        outcome = make_brain_registry.dispatch(eng_type, "commit")
                    except (LookupError, AttributeError) as exc:
                        print(f"  engagement_commit failed: {exc!r}", flush=True)
                        continue
                    print(f"  engagement_commit: outcome={outcome}", flush=True)
                    if outcome in ("win", "exhausted"):
                        terminal = "won" if outcome == "win" else "lost"
                        _close_engagement(world, terminal)
                    continue

                if msg.get("cmd") == "engagement_abort":
                    if world.active_engagement is None:
                        continue
                    eng_type = world.active_engagement["engagement_type"]
                    try:
                        make_brain_registry.dispatch(eng_type, "abort")
                    except (LookupError, AttributeError) as exc:
                        print(f"  engagement_abort failed: {exc!r}", flush=True)
                    _close_engagement(world, "aborted")
                    continue

                if msg.get("cmd") == "thing_edit":
                    # B-mode tune — mutate one part of an in-memory Thing,
                    # regen its entities. Manifest re-emits on next tick.
                    tn = str(msg.get("thing_name", ""))
                    pr = str(msg.get("part_role", ""))
                    fd = str(msg.get("field", ""))
                    dl = msg.get("delta", 0.0)
                    ok = thing_edit(tn, pr, fd, dl)
                    if not ok:
                        print(f"  thing_edit rejected: {tn}/{pr}/{fd}",
                              flush=True)
                    last_wake_ids = set()        # force manifest re-emit
                    continue

                if msg.get("cmd") == "thing_save":
                    tn = str(msg.get("thing_name", ""))
                    ok = thing_save(tn)
                    print(f"  thing_save({tn!r}): {'ok' if ok else 'FAILED'}",
                          flush=True)
                    continue

                # Variant deck (variant_deck PR 2026-05-17).
                # variant_roll: cycle to next deterministic variant
                # seed for this biome, regen substrates, bump
                # world_revision so client re-spawns.
                if msg.get("cmd") == "variant_roll":
                    direction = int(msg.get("direction", 1))
                    if _active_variant_index < 0:
                        # Locked → leaving lock cycles back to variant 0.
                        _active_variant_index = 0
                    else:
                        _active_variant_index = (
                            (_active_variant_index + direction)
                            % _VARIANT_DECK_SIZE
                        )
                    seeds = _variant_seeds(world.biome_name)
                    new_seed = seeds[_active_variant_index]
                    world.regen_world(new_seed)
                    _rebuild_world_substrates(world)
                    last_wake_ids = set()        # force manifest re-emit
                    print(f"  variant_roll: → variant "
                          f"{_active_variant_index + 1}/{_VARIANT_DECK_SIZE} "
                          f"(seed {new_seed})", flush=True)
                    continue

                # variant_lock: persist current seed for this biome.
                # Locked seed survives brain restarts via vault.biome_locks.
                if msg.get("cmd") == "variant_lock":
                    _get_vault().biome_lock(world.biome_name,
                                              int(world.base_seed))
                    _active_variant_index = -1   # locked indicator
                    last_wake_ids = set()
                    print(f"  variant_lock: biome {world.biome_name!r} "
                          f"locked at seed {world.base_seed}", flush=True)
                    continue

                # variant_unlock: drop the persisted lock; resume the
                # variant cycle starting at variant 0.
                if msg.get("cmd") == "variant_unlock":
                    _get_vault().biome_unlock(world.biome_name)
                    _active_variant_index = 0
                    new_seed = _variant_seeds(world.biome_name)[0]
                    world.regen_world(new_seed)
                    _rebuild_world_substrates(world)
                    last_wake_ids = set()
                    print(f"  variant_unlock: biome {world.biome_name!r} "
                          f"reset to variant 1/{_VARIANT_DECK_SIZE} "
                          f"(seed {new_seed})", flush=True)
                    continue

                if msg.get("cmd") == "interact_request":
                    # NetHack-shaped: target a thing + verb → emit a
                    # StateEvent with the response text, then apply
                    # verb-specific mechanics. Per "old-dev cheats"
                    # 2026-05-14: crosshair is the verb selector,
                    # text does the work.
                    tn = str(msg.get("thing_name", ""))
                    verb = str(msg.get("verb", "examine"))
                    thing = _THING_GALLERY_THINGS.get(tn)
                    if thing is None:
                        continue
                    if tn in _THING_GALLERY_PICKED_UP:
                        continue          # picked up; nothing left to interact with
                    interactions = thing.interactions or {}
                    text = interactions.get(verb)
                    if not text:
                        continue
                    # Lexicon substitution — weave her verbatim phrases
                    # into the response when {lex} placeholders present.
                    text = _substitute_lexicon(text, rng_seed=hash((tn, verb)))
                    # Emit the response text as a StateEvent toast.
                    world.state_events.emit(
                        "interact_response",
                        text,
                        {"thing_name": tn, "verb": verb},
                        REG_LOOP,
                    )

                    # Per-verb side effects + activity emit.
                    if verb == "examine":
                        activity_loop.emit_activity(
                            activity_loop.ActivityClass.UNWIND,
                            intensity=1,
                            primitive="interact_examine",
                            source_brain="thing_library",
                            payload={"thing": tn},
                        )
                    elif verb == "pickup":
                        # Route by tile presence — biome-things persist
                        # state to vault; gallery items live in-memory.
                        raw_tile = msg.get("tile")
                        if raw_tile and len(raw_tile) == 2:
                            try:
                                tile_x = int(raw_tile[0])
                                tile_y = int(raw_tile[1])
                                _get_vault().biome_thing_state_set_picked_up(
                                    biome=world.biome_name,
                                    tile_x=tile_x, tile_y=tile_y,
                                    thing_name=tn,
                                )
                                _BIOME_THINGS_ENTITIES = _build_biome_things(
                                    world.biome_name,
                                    base_seed=getattr(world, "base_seed", 0),
                                    tile_size=getattr(world, "tile_size", 12.0),
                                )
                            except Exception as exc:                  # noqa: BLE001
                                print(f"  pickup persist failed: {exc!r}", flush=True)
                        else:
                            _THING_GALLERY_PICKED_UP.add(tn)
                            _THING_GALLERY_ENTITIES = _expand_thing_gallery()
                        activity_loop.emit_activity(
                            activity_loop.ActivityClass.MAKE,
                            intensity=1,
                            primitive="interact_pickup",
                            source_brain="thing_library",
                            payload={"thing": tn, "tile": raw_tile},
                        )
                        last_wake_ids = set()       # force manifest re-emit
                    elif verb == "kick":
                        raw_dir = msg.get("direction") or [0.0, 1.0]
                        try:
                            dx = float(raw_dir[0])
                            dy = float(raw_dir[1])
                        except (TypeError, ValueError, IndexError):
                            dx, dy = 0.0, 1.0
                        mag = (dx * dx + dy * dy) ** 0.5
                        if mag < 1e-6:
                            dx, dy = 0.0, 1.0
                            mag = 1.0
                        push_m = 0.5
                        kick_dx = dx / mag * push_m
                        kick_dy = dy / mag * push_m
                        raw_tile = msg.get("tile")
                        if raw_tile and len(raw_tile) == 2:
                            try:
                                tile_x = int(raw_tile[0])
                                tile_y = int(raw_tile[1])
                                _get_vault().biome_thing_state_add_kick(
                                    biome=world.biome_name,
                                    tile_x=tile_x, tile_y=tile_y,
                                    thing_name=tn,
                                    dx=kick_dx, dy=kick_dy,
                                )
                                _BIOME_THINGS_ENTITIES = _build_biome_things(
                                    world.biome_name,
                                    base_seed=getattr(world, "base_seed", 0),
                                    tile_size=getattr(world, "tile_size", 12.0),
                                )
                            except Exception as exc:                  # noqa: BLE001
                                print(f"  kick persist failed: {exc!r}", flush=True)
                        else:
                            cur = _THING_GALLERY_KICK_OFFSETS.get(tn, (0.0, 0.0))
                            _THING_GALLERY_KICK_OFFSETS[tn] = (
                                cur[0] + kick_dx,
                                cur[1] + kick_dy,
                            )
                            _THING_GALLERY_ENTITIES = _expand_thing_gallery()
                        activity_loop.emit_activity(
                            activity_loop.ActivityClass.HUNT,
                            intensity=1,
                            primitive="interact_kick",
                            source_brain="thing_library",
                            payload={"thing": tn, "tile": raw_tile,
                                     "offset": [kick_dx, kick_dy]},
                        )
                        last_wake_ids = set()
                    print(f"  interact: {tn}/{verb} → {text!r}", flush=True)
                    continue

                if msg.get("cmd") == "thing_revert":
                    # Reload one thing from disk, discarding in-memory edits.
                    tn = str(msg.get("thing_name", ""))
                    from core.systems import thing_schema
                    if _THING_GALLERY_DIR is not None:
                        path = _THING_GALLERY_DIR / f"{tn}.json"
                        try:
                            reloaded = thing_schema.load_thing(path)
                            _THING_GALLERY_THINGS[tn] = reloaded
                            _THING_GALLERY_ENTITIES = _expand_thing_gallery()
                            print(f"  thing_revert({tn!r}): reloaded", flush=True)
                        except Exception as exc:                  # noqa: BLE001
                            print(f"  thing_revert({tn!r}) failed: {exc!r}",
                                  flush=True)
                    last_wake_ids = set()
                    continue

                if msg.get("cmd") == "weapon_use":
                    # ARPG combat — player triggered a weapon use.
                    # Look up the weapon profile + spawn an ActiveStrike
                    # via the substrate. Per feat/arpg-combat PR 2 (SHOT)
                    # + PR 3 (HELD with verb arg).
                    weapon_kind = str(msg.get("weapon_kind", ""))
                    mode = str(msg.get("mode", "shot"))
                    cam = msg.get("camera_state") or {}
                    held_verb_name = msg.get("held_verb")
                    if not weapon_kind or "pos" not in cam or "forward" not in cam:
                        print(f"  weapon_use rejected: missing weapon_kind / camera fields",
                              flush=True)
                        continue
                    # WHIP single-instance lock (UAT 2026-05-11). Rapid
                    # repeat clicks while a whip is in flight = recall
                    # the active whip, don't spawn a new one. Player
                    # can re-press after recall to lash again.
                    if mode == "whip":
                        active_whips = [
                            a for a in world.active_strikes
                            if a.strike.mode == "whip"
                            and a.strike.source_actor == "player"
                            and not a.resolved
                        ]
                        if active_whips:
                            for a in active_whips:
                                a.resolved = True
                                a.resolved_kind = "interrupted"
                                if a.session_id is not None:
                                    try:
                                        _get_vault().combat_session_close(
                                            session_id=a.session_id,
                                            outcome="interrupted",
                                        )
                                    except Exception:    # noqa: BLE001
                                        pass
                            world.state_events.emit(
                                "whip_recalled",
                                "WHIP — RECALLED",
                                None,
                                REG_LOOP,
                            )
                            last_wake_ids = set()
                            continue
                    profile = _get_vault().profile_resolve("weapon", weapon_kind)
                    if not profile:
                        print(f"  weapon_use: unknown weapon {weapon_kind!r}", flush=True)
                        continue
                    profile["profile_name"] = weapon_kind   # for Strike telemetry
                    # Combo weapons (e.g. fire_staff) carry per-mode
                    # sub-profiles under `modes`. Extract the right one
                    # and pass it as the flat profile to strike.spawn.
                    # Per feat/arpg-combat PR 5.
                    from core.systems.weapons import magic_staff as _magic_staff
                    if _magic_staff.is_combo(profile):
                        sub = _magic_staff.sub_profile(profile, mode)
                        if sub is None:
                            print(f"  weapon_use: combo weapon {weapon_kind!r} has no "
                                  f"{mode!r} sub-mode", flush=True)
                            continue
                        profile = sub
                    held_verb = None
                    if held_verb_name and mode == "held":
                        try:
                            held_verb = strike_module.HeldVerb[str(held_verb_name).upper()]
                        except KeyError:
                            print(f"  weapon_use: unknown held_verb {held_verb_name!r}",
                                  flush=True)
                            continue
                    try:
                        s = strike_module.spawn(
                            weapon_profile=profile,
                            mode=mode,                # type: ignore[arg-type]
                            camera_state=cam,
                            source_actor="player",
                            held_verb=held_verb,
                        )
                    except (KeyError, ValueError) as exc:
                        print(f"  weapon_use rejected: {exc}", flush=True)
                        continue
                    active = strike_runtime.make_active(s)
                    # vault.combat_sessions telemetry — open per swing,
                    # close on resolution (feat/arpg-combat PR 7).
                    weapon_class = profile.get("weapon_class")
                    active.weapon_class = weapon_class
                    try:
                        active.session_id = _get_vault().combat_session_open(
                            source_actor="player",
                            weapon_kind=weapon_kind,
                            weapon_class=weapon_class,
                            mode=mode,
                        )
                    except Exception:                    # noqa: BLE001
                        pass                              # telemetry non-load-bearing
                    world.active_strikes.append(active)
                    last_wake_ids = set()
                    continue

                if msg.get("cmd") == "kind_destroyed":
                    # Player smashed (or otherwise destroyed) an entity.
                    # Two effects: (1) push a `kind_destroyed` tick event
                    # so async quests watching that kind can complete;
                    # (2) if `entity_id` was supplied, add it to the
                    # destroyed-ledger so subsequent manifests filter it
                    # out — the entity actually disappears from the
                    # world. Ledger clears on world regen.
                    trigger_kind = str(msg.get("kind", "unknown"))
                    entity_id = msg.get("entity_id")
                    world.tick_events.append({
                        "type": "kind_destroyed",
                        "kind": trigger_kind,
                    })
                    if entity_id is not None:
                        try:
                            world.destroyed_entity_ids.add(int(entity_id))
                        except (TypeError, ValueError):
                            pass
                    # Toast feedback for the player — universal verb shape.
                    world.state_events.emit(
                        "kind_destroyed",
                        f"SMASH {trigger_kind}",
                        None,
                        REG_LOOP,
                    )
                    last_wake_ids = set()
                    continue

                if msg.get("cmd") == "journal_toggle_quest":
                    # Async quest substrate per `project_async_quest_refactor`.
                    # Player toggles a quest between available ↔ active from
                    # the journal overlay (J key, lands client-side in PR 1.3).
                    # Completed quests are read-only (no re-activate via toggle).
                    quest_id = str(msg.get("quest_id", ""))
                    quest_obj = quests.get(quest_id)
                    if quest_obj is None:
                        print(f"  journal_toggle_quest rejected: unknown quest {quest_id!r}", flush=True)
                        continue
                    new_state = world.quest_state.toggle_active(quest_id)
                    # Mirror to vault.scenarios when the quest is journal-
                    # derived. PENDING ↔ ACTIVE follows the toggle 1:1;
                    # transition is a no-op when the new ledger state
                    # equals the existing one. Quests without a
                    # scenario_id (legacy biome-seeded ones) skip silently.
                    sid = quest_obj.predicate_args.get("scenario_id")
                    if sid is not None:
                        ledger_target = (scenario_ledger.ACTIVE
                                         if new_state == "active"
                                         else scenario_ledger.PENDING)
                        scenario_ledger.transition(
                            _get_vault(), sid, ledger_target,
                            state_events=world.state_events)
                    print(f"  journal: {quest_id} -> {new_state}", flush=True)
                    last_wake_ids = set()
                    continue

                if msg.get("cmd") == "journal_entry":
                    # Permanent Objects bridge — J3-min path.
                    # Persist raw_note + run lexicon update, then synthesize a
                    # Quest from the entry and register it dynamically. Push
                    # a `journal_entry` event onto tick_events so any active
                    # `journal_followup` quest can fire on the next tick.
                    # Per `feedback_her_voice` + `design_wont_tolerate`: the
                    # quest's name + description are verbatim slices of
                    # raw_note. No paraphrase, no LLM.
                    raw_note = str(msg.get("raw_note", "")).strip()
                    if not raw_note:
                        ack = json.dumps({"journal_entry_error": "empty raw_note"}) + "\n"
                        try:
                            client.sendall(ack.encode("utf-8"))
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        continue
                    try:
                        entry_id = _journal_persist_entry(raw_note)
                    except Exception as exc:
                        print(f"  journal_entry persist failed: {exc}", flush=True)
                        ack = json.dumps({"journal_entry_error": str(exc)}) + "\n"
                        try:
                            client.sendall(ack.encode("utf-8"))
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        continue

                    # Single bridge path — also writes a PENDING scenario
                    # row to vault.scenarios so the persisted ledger
                    # mirrors the in-memory Quest. Per the J6 design
                    # conversation, every journal-derived quest gets a
                    # scenario row; future side-load processes
                    # (auto-resolve, encounter spawn) consume vault
                    # directly without touching the Quest substrate.
                    kind_set = set(_kc.all_kinds().keys())
                    bridged = _bridge_entry_to_quest(
                        entry_id, raw_note, kind_set)
                    quest = bridged[0] if bridged is not None else None

                    if quest is not None:
                        quests.register_dynamic(quest)
                        if (quest.id not in world.quest_state.available
                                and quest.id not in world.quest_state.active
                                and quest.id not in world.quest_state.completed):
                            world.quest_state.available.append(quest.id)
                        world.state_events.emit(
                            "quest_available",
                            f"NEW QUEST — {quest.name.upper()}",
                            None,
                            REG_LOOP,
                        )

                    # Always push the journal event onto tick_events so any
                    # already-active journal_followup quest can complete on
                    # this same entry (the predicate self-skips birth ids).
                    world.tick_events.append({
                        "type": "journal_entry",
                        "entry_id": entry_id,
                        "raw_note": raw_note,
                    })
                    last_wake_ids = set()

                    sid = (quest.predicate_args.get("scenario_id")
                           if quest else None)
                    ack_payload = {
                        "journal_entry_ack": {
                            "entry_id": entry_id,
                            "quest_id": quest.id if quest else None,
                            "quest_name": quest.name if quest else None,
                            "scenario_id": sid,
                        }
                    }
                    try:
                        client.sendall((json.dumps(ack_payload) + "\n").encode("utf-8"))
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    print(
                        f"  journal_entry: id={entry_id} quest="
                        f"{quest.id if quest else 'none'} "
                        f"scenario={sid[:8] if sid else 'none'}",
                        flush=True,
                    )
                    continue


                if msg.get("cmd") == "state_transition_request":
                    # PR 5 collapse (2026-05-02): only CHARACTER_CREATION
                    # ↔ HUB ↔ REFLECTIVE survive. The MISSION_*-related
                    # branches (regen, mission_launched, RETURNING/RETURNED
                    # HOME) and the picker-selection lifecycle are gone.
                    # World regen is now strictly HP=0 / reflective-commit
                    # gated per `design_death_only_regen`.
                    target_str = str(msg.get("target", ""))
                    try:
                        target = gs.GameStateName(target_str)
                    except ValueError:
                        print(f"  state_transition rejected: unknown target {target_str!r}", flush=True)
                        continue
                    old = world.game_state
                    try:
                        new_state = gs.transition(old, target)
                    except ValueError as e:
                        print(f"  state_transition rejected: {e}", flush=True)
                        continue

                    world.game_state = new_state
                    print(f"  state: {old.state.value} -> {new_state.state.value}", flush=True)
                    world.state_events.emit(
                        "state_transition",
                        f"{old.state.value} -> {new_state.state.value}",
                        None,
                        REG_LOOP,
                    )

                    # PR 5 collapse (2026-05-02): autosave on RESULTS →
                    # HUB removed with the rest of the mission flow. The
                    # natural beat boundary is now reflective commit
                    # (REFLECTIVE → HUB via the consequences chain) —
                    # save fires there in the `commit_reflective` handler.
                    # Character-creation finalization save still fires
                    # via the post-creation hook below (~line 2079).

                    last_wake_ids = set()  # force manifest resend with new state
                    continue

                if msg.get("cmd") == "engage_pillar":
                    # Per `design_seven_pillars` + `design_dial_input`: player
                    # walks up to a pillar in the hub during CHARACTER_CREATION,
                    # presses F, brain returns the pillar's initial DialPrompt
                    # via manifest.dial_prompt. Client renders the dial.
                    pillar_id = str(msg.get("pillar", ""))
                    # Pillar of Reflection is the meta re-do pillar: it lives in
                    # HUB after a sheet is sealed, not in CHARACTER_CREATION.
                    is_reflection = pillar_id == "reflection"
                    if is_reflection:
                        if world.game_state.state != gs.GameStateName.HUB:
                            print(f"  engage reflection rejected: state={world.game_state.state.value}", flush=True)
                            continue
                        if world.character_sheet is None:
                            print(f"  engage reflection rejected: no character to reset", flush=True)
                            continue
                    else:
                        if world.game_state.state != gs.GameStateName.CHARACTER_CREATION:
                            print(f"  engage_pillar rejected: state={world.game_state.state.value}", flush=True)
                            continue
                        if world.character_draft is None:
                            print(f"  engage_pillar rejected: no draft", flush=True)
                            continue
                    handler = pillars_registry.get(pillar_id)
                    if handler is None:
                        print(f"  engage_pillar rejected: unknown pillar {pillar_id!r}", flush=True)
                        continue
                    # Build hint context for re-do flows. When a sheet
                    # already exists (re-do via Pillar of Reflection), pass
                    # previous values so handlers can seed defaults closer
                    # to the player's last answer (faster cascade convergence).
                    hint: dict | None = None
                    if world.character_sheet is not None:
                        hint = {
                            "previous_age": world.character_sheet.age,
                            "previous_birthday": world.character_sheet.birthday,
                        }
                    world.active_dial = handler.initial_prompt(
                        world.character_draft, hint=hint)
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
                    world.active_dial = None

                    # Pillar of Reflection special-case: triggers re-do flow
                    # rather than draft-append. The sentinel value drives state
                    # transition; we never write _reflection to the draft.
                    if pillar_id == "reflection":
                        if chosen_value == "reset":
                            world.character_draft = world._init_creation_draft()
                            old_state = world.game_state
                            world.game_state = gs.transition(
                                world.game_state, gs.GameStateName.CHARACTER_CREATION)
                            print(f"  reflection: BEGIN AGAIN — draft reset", flush=True)
                            print(f"  state: {old_state.state.value} -> {world.game_state.state.value}", flush=True)
                            world.state_events.emit(
                                "reflection_reset",
                                "BEGINNING AGAIN",
                                "the cavern remembers",
                                REG_RITUAL,
                            )
                        else:
                            print(f"  reflection: remain", flush=True)
                        last_wake_ids = set()
                        continue

                    world.character_draft.append(pillar_id, chosen_value)
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
                            world.state_events.emit(
                                "pillar_sealed",
                                f"PILLAR SEALED · {pillar_id.upper()}",
                                f"{world.character_sheet.name} · age {world.character_sheet.age}",
                                REG_RITUAL,
                            )
                            # Activity-loop signal — RITUAL class. Sealing
                            # a pillar is a sacred moment; intensity=3 marks
                            # it as heavy (parallel to boss-brick HUNT). The
                            # final-pillar seal also finalizes the sheet, so
                            # this emit captures the character-creation
                            # culmination. Per PR 12.
                            activity_loop.emit_activity(
                                activity_loop.ActivityClass.RITUAL,
                                intensity=3,
                                primitive="pillar_sealed",
                                source_brain="brain_world",
                                payload={
                                    "pillar_id": str(pillar_id),
                                    "final":     True,
                                    "name":      world.character_sheet.name,
                                    "age":       int(world.character_sheet.age),
                                },
                            )
                            world.state_events.emit(
                                "state_transition",
                                "RETURNING TO HUB",
                                None,
                                REG_LOOP,
                            )
                            # Autosave the sealed sheet so brain restart preserves
                            # identity (per "real game saves" — the sheet survives
                            # alongside PlayerState).
                            try:
                                _sync_quest_state_to_player(world)
                                written = save_state.save(world.player, world.character_sheet)
                                print(f"  autosave (post-creation): {written}", flush=True)
                                world.state_events.emit(
                                    "save_written", "SAVED", None, REG_SYSTEM)
                            except OSError as save_err:
                                print(f"  autosave failed: {save_err}", flush=True)
                        except Exception as e:
                            print(f"  finalize failed: {e}", flush=True)
                    else:
                        # Sealed a non-final pillar (in normal multi-pillar flow);
                        # emit a feedback event but don't transition or save.
                        world.state_events.emit(
                            "pillar_sealed",
                            f"PILLAR SEALED · {pillar_id.upper()}",
                            None,
                            REG_RITUAL,
                        )
                        # Activity-loop RITUAL signal for interim seals —
                        # same intensity as final, since each pillar is a
                        # sacred moment regardless of whether it completes
                        # the sheet.
                        activity_loop.emit_activity(
                            activity_loop.ActivityClass.RITUAL,
                            intensity=3,
                            primitive="pillar_sealed",
                            source_brain="brain_world",
                            payload={
                                "pillar_id": str(pillar_id),
                                "final":     False,
                            },
                        )

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

                # ── Reflective-mode cmd handlers (PR 3.5 step 8) ────
                # Voluntary entry, magnet placement, commit, abort.
                # Forced entry (HP=0) goes through the consequences
                # engine via signals.push_hp_zero — not a cmd handler.

                if msg.get("cmd") == "engage_fridge":
                    # Voluntary entry from the hub. Player chose to walk
                    # up and engage the fridge — pure ambient practice
                    # path. No proximity check on brain side; client UI
                    # gates affordance per `design_brain_ground_truth`.
                    if world.game_state.state != gs.GameStateName.HUB:
                        print(
                            f"  engage_fridge: ignored — game_state is "
                            f"{world.game_state.state.value}, not HUB",
                            flush=True,
                        )
                        continue
                    if not reflective_sm.enter(world, trigger="voluntary"):
                        print("  engage_fridge: no rules registered, skipped", flush=True)
                        continue
                    try:
                        world.game_state = gs.transition(
                            world.game_state,
                            gs.GameStateName.REFLECTIVE,
                        )
                    except ValueError as exc:
                        # Roll back so reflective state stays consistent
                        # with game_state.
                        reflective_sm.exit(world)
                        print(f"  engage_fridge: {exc}", flush=True)
                        continue
                    world.state_events.emit(
                        "reflective_entry",
                        "REFLECT",
                        None,
                        REG_RITUAL,
                    )
                    print(
                        f"  engage_fridge: rule="
                        f"{world.reflective.current_rule_id} "
                        f"pool_size={len(world.reflective.magnet_pool)}",
                        flush=True,
                    )
                    last_wake_ids = set()
                    continue

                if msg.get("cmd") == "place_magnet":
                    if world.game_state.state != gs.GameStateName.REFLECTIVE:
                        continue
                    magnet = str(msg.get("magnet", ""))
                    placed = reflective_sm.place_magnet(world, magnet)
                    if not placed:
                        print(
                            f"  place_magnet: rejected {magnet!r} "
                            f"(not in pool or already at limit)",
                            flush=True,
                        )
                    last_wake_ids = set()
                    continue

                if msg.get("cmd") == "remove_magnet":
                    if world.game_state.state != gs.GameStateName.REFLECTIVE:
                        continue
                    try:
                        index = int(msg.get("index", -1))
                    except (TypeError, ValueError):
                        continue
                    reflective_sm.remove_magnet(world, index)
                    last_wake_ids = set()
                    continue

                if msg.get("cmd") == "commit_reflective":
                    if world.game_state.state != gs.GameStateName.REFLECTIVE:
                        continue
                    trigger = world.reflective.trigger
                    success = reflective_sm.commit(world)
                    if success:
                        # Push trigger-specific event so the consequence
                        # engine resumes the right chain (resume vs
                        # voluntary). Both events resolve same tick.
                        if trigger == "hp_zero":
                            world.tick_events.append({
                                "type": "reflective_committed_from_hp_zero",
                            })
                        elif trigger == "voluntary":
                            world.tick_events.append({
                                "type": "reflective_committed_voluntary",
                            })
                        else:
                            print(
                                f"  commit_reflective: unknown trigger "
                                f"{trigger!r}, skipped event push",
                                flush=True,
                            )
                        # L5 autosave — natural beat boundary post PR 5
                        # collapse. Reflective commit is the new
                        # "completed something deliberate" moment that
                        # used to be RESULTS → HUB. Quest state syncs
                        # from BrainWorld onto the player record before
                        # serialization (same shape as the old path).
                        try:
                            _sync_quest_state_to_player(world)
                            written = save_state.save(
                                world.player, world.character_sheet)
                            print(f"  autosave (reflective commit): {written}", flush=True)
                            world.state_events.emit(
                                "save_written", "SAVED", None, REG_SYSTEM)
                        except OSError as save_err:
                            print(f"  autosave failed: {save_err}", flush=True)
                    else:
                        # AC failed — stay in reflective. attempt_count
                        # was incremented by sm.commit. V1 emits a
                        # generic "not yet" StateEvent; voice authoring
                        # for failure copy is a content-arc follow-up.
                        world.state_events.emit(
                            "reflective_attempt_failed",
                            "NOT YET",
                            None,
                            REG_LOOP,
                        )
                    last_wake_ids = set()
                    continue

                if msg.get("cmd") == "abort_reflective":
                    # V1: only voluntary entry can abort. HP=0 path
                    # locks until commit (low bar — compose_three).
                    if world.game_state.state != gs.GameStateName.REFLECTIVE:
                        continue
                    if world.reflective.trigger != "voluntary":
                        print(
                            "  abort_reflective: ignored — only voluntary "
                            "entry can abort",
                            flush=True,
                        )
                        continue
                    reflective_sm.exit(world)
                    try:
                        world.game_state = gs.transition(
                            world.game_state,
                            gs.GameStateName.HUB,
                        )
                    except ValueError as exc:
                        print(f"  abort_reflective: {exc}", flush=True)
                        continue
                    world.state_events.emit(
                        "reflective_aborted",
                        "LATER",
                        None,
                        REG_SYSTEM,
                    )
                    last_wake_ids = set()
                    continue

                # ---- Workroom seed CRUD ---------------------------------
                # Per `.claude/feature/feat_vector-workroom.md` PR 1.
                # Vault-backed seed table; handlers live in
                # core.systems.seed_commands so tests can hit them
                # directly. Mutations bump last_wake_ids so the next
                # manifest tick re-reads world_seeds for the active biome.

                _seed_cmd = msg.get("cmd")
                if _seed_cmd in (
                    "seed_create", "seed_update", "seed_delete", "seed_list",
                ):
                    handler = {
                        "seed_create": seed_commands.handle_seed_create,
                        "seed_update": seed_commands.handle_seed_update,
                        "seed_delete": seed_commands.handle_seed_delete,
                        "seed_list":   seed_commands.handle_seed_list,
                    }[_seed_cmd]
                    ack = handler(msg, _get_vault())
                    try:
                        client.sendall((json.dumps(ack) + "\n").encode("utf-8"))
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    if _seed_cmd != "seed_list" and ack.get("ok"):
                        last_wake_ids = set()
                    continue

                # ---- Make-brain profile commands ------------------------
                # Universal config dispatch for any make-brain instance.
                # Per `.claude/feature/feat_make-brain-ping-pong.md` PR 1.
                _mb_cmd = msg.get("cmd")
                if _mb_cmd in (
                    "profile_save", "profile_load", "profile_list",
                    "volley_serve", "volley_strike",
                    "volley_reset_rally", "volley_reset_match",
                    "console_exec",
                ):
                    mb_handler = {
                        "profile_save":       make_brain_commands.handle_profile_save,
                        "profile_load":       make_brain_commands.handle_profile_load,
                        "profile_list":       make_brain_commands.handle_profile_list,
                        "volley_serve":       make_brain_commands.handle_volley_serve,
                        "volley_strike":      make_brain_commands.handle_volley_strike,
                        "volley_reset_rally": make_brain_commands.handle_volley_reset_rally,
                        "volley_reset_match": make_brain_commands.handle_volley_reset_match,
                        "console_exec":       make_brain_commands.handle_console_exec,
                    }[_mb_cmd]
                    ack = mb_handler(msg, _get_vault())
                    try:
                        client.sendall((json.dumps(ack) + "\n").encode("utf-8"))
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    continue

                # Camera update — stash, only process the latest after drain
                latest_cam_msg = msg

            # Per-frame quest evaluation — runs every iteration of the recv
            # loop, NOT gated on a camera update. Async quests (per
            # `project_async_quest_refactor`) must fire even when no client
            # is streaming camera updates: a journal_entry pushed via the
            # harness, or a queued event from a previous tick, completes
            # the predicate without waiting for the player to move.
            if world.quest_state.active or world.tick_events:
                quest_tick.tick(
                    world,
                    world.tick_events,
                    lambda q: _on_quest_complete(world, q),
                )
            # Consequences engine — runs AFTER quest_tick so quests
            # observe their events first; runs BEFORE tick_events.clear()
            # so consequence triggers (e.g. hp_zero) see the same
            # accumulator. Per `design_reflective_loop` /
            # `design_virtual_hallucination` — HP=0 routes through this
            # engine, regens the world, restores HP, no perma-death.
            consequence_tick.tick(world, world.tick_events)
            world.tick_events.clear()

            # Make-brain per-frame physics tick. Runs at fixed 1/60 dt
            # regardless of client cadence — solver substeps handle any
            # per-frame velocity. Silent no-op for legacy biomes (no
            # registered handler).
            if mb_instance_id:
                try:
                    spec = make_brain_registry.get(mb_instance_id)
                    tick_fn = getattr(spec.handler, "on_tick", None)
                    if callable(tick_fn):
                        tick_fn(1.0 / 60.0)
                except LookupError:
                    pass

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
                    # UNWIND producer (PR 10) — pure-cumulative dwell
                    # accumulator emits one UNWIND tick per slice. The
                    # `while` drains accumulated time correctly when dt
                    # is large (paused brain catching up).
                    world._dwell_accum_for_unwind += dt
                    while world._dwell_accum_for_unwind >= activity_loop.DWELL_UNWIND_SLICE_SECONDS:
                        world._dwell_accum_for_unwind -= activity_loop.DWELL_UNWIND_SLICE_SECONDS
                        activity_loop.emit_activity(
                            activity_loop.ActivityClass.UNWIND, 1,
                            primitive="dwell_slice",
                            source_brain="brain_world",
                        )
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

                # Per-frame quest evaluation. (Moved out of the camera-gate
                # below — async quests must evaluate even when no client is
                # streaming camera updates, e.g. journal_followup firing on
                # a journal_entry pushed via the harness while Godot is off.)

                manifest = world.get_manifest(
                    cam_x, cam_y, cam_z, heading, pitch, dt)

                # Attach quest substrate to manifest per
                # `project_async_quest_refactor`. The registry is small and
                # stable; PR 1.3+ should cache it at connect rather than
                # ship it every tick. For now (handful of quests) shipping
                # in-line is simpler and matches the expedition pattern.
                #
                # PR 4: bearings map — for each active quest whose
                # predicate has a target resolver, compute a compass
                # bearing (E/NE/N/NW/W/SW/S/SE) from the player to the
                # nearest target. Quests with no resolver, or with no
                # current target (e.g. all entities of a kind already
                # destroyed), are absent from the map. Vector terminal
                # HUD prefixes active-quest rows with `[NE]` etc.
                bearings_map = _quest_bearings(
                    world, cam_x, cam_y,
                )
                manifest["quests"] = {
                    "registry": {
                        qid: {"name": q.name, "description": q.description}
                        for qid, q in quests.all_quests().items()
                    },
                    "available": list(world.quest_state.available),
                    "active": list(world.quest_state.active),
                    "completed": list(world.quest_state.completed),
                    "bearings": bearings_map,
                }

                # Workroom seeds for the active biome — vector-workroom PR 1.
                # Always shipped, even outside `workroom`, so other biomes
                # can adopt seed authoring without engine changes (V2).
                # Empty list when biome has no seeds.
                manifest["seeds"] = _get_vault().world_seeds_by_biome(
                    world.biome_name)

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

                # Scan-gallery injection — image-derived entities (see
                # tools/scan_to_kinds.py). Activated by env
                # SANCTUM_SCAN_GALLERY=<path-to-entities.json>. Bridge
                # experiment for `design_render_reuse_mandate`: do the
                # vector primitives compose into something recognizable
                # when fed arbitrary image classifications?
                if _SCAN_GALLERY_ENTITIES:
                    manifest.setdefault("entities", []).extend(
                        _SCAN_GALLERY_ENTITIES)

                # Thing-library injection — composed wireframe models
                # via `core/systems/thing_schema.py`. Each Thing's
                # bounding-box math expanded into N positioned entities
                # using `core/systems/thing_renderer.py`. Loaded at
                # module import; static across the brain's lifetime.
                if _THING_GALLERY_ENTITIES:
                    manifest.setdefault("entities", []).extend(
                        _THING_GALLERY_ENTITIES)

                # Biome-things injection — Blender-driven per-tile picks
                # + greenhouse placeholder seeds for unfilled demand.
                # Per `feat/biome-greenhouse` PR 3. Per-frame distance
                # cull (90m radius) — saves manifest bandwidth +
                # rendering work for things outside fog range.
                if _BIOME_THINGS_ENTITIES:
                    thing_cull_r2 = 90.0 * 90.0
                    nearby_things = [
                        t for t in _BIOME_THINGS_ENTITIES
                        if (t["x"] - cam_x) ** 2
                           + (t["y"] - cam_y) ** 2 <= thing_cull_r2
                    ]
                    if nearby_things:
                        manifest.setdefault("entities", []).extend(
                            nearby_things)

                # Terrain walls — wireframe boundaries between adjacent
                # tiles at different elevations. Per
                # `feat/biome-greenhouse` elevation extension.
                # Per-frame distance cull: only ship walls within a
                # generous draw radius around the camera. Saves
                # manifest bandwidth + client draw calls — the field
                # is 17×17 (~200m square) but only ~30 walls are ever
                # visible at once. Per 2026-05-17 perf fix.
                if _BIOME_TERRAIN_WALLS:
                    wall_cull_r2 = 90.0 * 90.0       # 90m radius²
                    nearby_walls = [
                        w for w in _BIOME_TERRAIN_WALLS
                        if (w["x"] - cam_x) ** 2
                           + (w["y"] - cam_y) ** 2 <= wall_cull_r2
                    ]
                    if nearby_walls:
                        manifest.setdefault("entities", []).extend(
                            nearby_walls)

                # Biome-stamps — architecture assemblies (bridges,
                # ladders, staircases, doorways). Per the 2026-05-17
                # "stamps as data" PR. Same 90m cull as things.
                # Stamps are sparse (tile_chance ~0.1) so the full
                # list is typically <30 entries; cull is still applied
                # for consistency + cost-bound on biome growth.
                if _BIOME_STAMPS_ENTITIES:
                    stamp_cull_r2 = 90.0 * 90.0
                    nearby_stamps = [
                        s for s in _BIOME_STAMPS_ENTITIES
                        if (s["x"] - cam_x) ** 2
                           + (s["y"] - cam_y) ** 2 <= stamp_cull_r2
                    ]
                    if nearby_stamps:
                        manifest.setdefault("entities", []).extend(
                            nearby_stamps)

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
                        # Player feedback — one toast per reaction. Universal
                        # verb shape: ELEMENT → KIND. Players see what their
                        # cast actually hit. Quiet on no-reaction casts so
                        # the toast queue doesn't spam during practice.
                        for re_evt in reaction_events:
                            world.state_events.emit(
                                "elemental_reaction",
                                f"{str(re_evt['element']).upper()} → "
                                f"{re_evt['kind']}",
                                None,
                                REG_LOOP,
                            )
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
                except BlockingIOError:
                    # Manifest grew faster than client could drain (e.g., a
                    # large scan-gallery entity list). Skip this tick rather
                    # than crash; next tick reapplies the manifest after the
                    # client catches up. Bumps last_wake_ids back so we re-
                    # send the full manifest next time instead of "unchanged".
                    print("  send backpressure — skipping tick", flush=True)
                    last_wake_ids = set()
                    continue
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
