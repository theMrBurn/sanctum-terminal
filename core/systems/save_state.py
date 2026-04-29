"""Save / load player progress to disk.

JSON file at ``save/player.json`` (relative to repo root) by default. The
location is overridable via the ``SANCTUM_SAVE_PATH`` env var so tests
can isolate without polluting real saves.

Save fires on every ``RESULTS → HUB`` transition (mission completion is
the natural autosave point) AND on ``CHARACTER_CREATION → HUB`` so the
sealed character sheet survives a brain restart. See brain_server's
state_transition_request handler + dial_response finalize path.

Schema is versioned. Loads of incompatible schema versions return None
and the brain proceeds with a fresh PlayerState — no crash, no silent
corruption. V1 → V2 migrates inline (V1 saves just gain a null
character_sheet field, brain enters CHARACTER_CREATION on next launch).

Pure data + I/O. No game logic. PlayerState + CharacterSheet are the
source-of-truth types; this module is the thin disk layer.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from core.systems.abilities import Ability
from core.systems.character_sheet import (
    CharacterSheet,
    ClassEntry,
    earned_from_class_history,
)
from core.systems.player_state import Item, PlayerState


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SAVE_PATH = _REPO_ROOT / "save" / "player.json"
_SAVE_PATH_ENV = "SANCTUM_SAVE_PATH"
_SCHEMA_VERSION = 2  # bumped from 1 — character_sheet field added


# ── Container for a complete saved game ──────────────────────────────


@dataclass
class Saved:
    """The whole save payload — PlayerState (active gameplay state) plus
    optional CharacterSheet (identity / abilities / verbs).

    A V1 save (legacy) loads with character_sheet=None — brain enters
    CHARACTER_CREATION so the player runs Pillar 1 once and gets a sheet
    on next save. New players also start with character_sheet=None.
    """
    player: PlayerState
    character_sheet: CharacterSheet | None = None


# ── Path resolution ──────────────────────────────────────────────────


def _resolve_path(path: Optional[Path]) -> Path:
    """Pick the save path: explicit arg → env var → default."""
    if path is not None:
        return path
    env = os.environ.get(_SAVE_PATH_ENV)
    if env:
        return Path(env)
    return _DEFAULT_SAVE_PATH


# ── PlayerState ↔ dict ───────────────────────────────────────────────


def _player_to_dict(player: PlayerState) -> dict[str, Any]:
    return {
        "name": player.name,
        "hp": player.hp,
        "max_hp": player.max_hp,
        "str_save": player.str_save,
        "dex_save": player.dex_save,
        "wil_save": player.wil_save,
        "slots": player.slots,
        "inventory": [
            {"name": i.name, "slot_cost": i.slot_cost}
            for i in player.inventory
        ],
        "equipped": player.equipped,
        "completed_missions": list(player.completed_missions),
    }


def _player_from_dict(p: dict[str, Any]) -> PlayerState:
    inventory = tuple(
        Item(name=str(it["name"]), slot_cost=int(it.get("slot_cost", 1)))
        for it in p.get("inventory", [])
    )
    return PlayerState(
        name=str(p.get("name", "Wanderer")),
        hp=int(p.get("hp", 6)),
        max_hp=int(p.get("max_hp", 6)),
        str_save=int(p.get("str_save", 10)),
        dex_save=int(p.get("dex_save", 10)),
        wil_save=int(p.get("wil_save", 10)),
        slots=int(p.get("slots", 10)),
        inventory=inventory,
        equipped=p.get("equipped"),
        completed_missions=tuple(p.get("completed_missions", [])),
    )


# ── CharacterSheet ↔ dict ────────────────────────────────────────────


def _sheet_to_dict(sheet: CharacterSheet) -> dict[str, Any]:
    """Serialize the identity-shaped fields of CharacterSheet.

    Skips fields that overlap PlayerState (hp, max_hp, inventory,
    equipped, completed_missions) — those are the player's, not the
    sheet's. Skips earned_abilities (computed from class_history on load).
    """
    return {
        "name": sheet.name,
        "birthday": list(sheet.birthday),
        "age": sheet.age,
        "class_history": [
            {"name": e.name, "levels": e.levels, "started_at_age": e.started_at_age}
            for e in sheet.class_history
        ],
        "stats": {
            "DEX": sheet.dex, "WIS": sheet.wis, "INT": sheet.int_,
            "CHA": sheet.cha, "STR": sheet.str_, "CON": sheet.con,
        },
        "selected_abilities": list(sheet.selected_abilities),
        "verbs_known": list(sheet.verbs_known),
    }


def _sheet_from_dict(s: dict[str, Any]) -> CharacterSheet:
    """Reconstruct a CharacterSheet from a saved dict.

    earned_abilities is recomputed from class_history rather than stored
    (deterministic given class_history; per `design_character_sheet`).
    """
    history = [
        ClassEntry(
            name=str(e.get("name", "rogue")),
            levels=int(e.get("levels", 0)),
            started_at_age=int(e.get("started_at_age", 0)),
        )
        for e in s.get("class_history", [])
    ]
    earned: list[Ability] = earned_from_class_history(history)
    stats = s.get("stats", {})
    birthday_raw = s.get("birthday", [1, 1])
    return CharacterSheet(
        name=str(s.get("name", "Wanderer")),
        birthday=(int(birthday_raw[0]), int(birthday_raw[1])),
        age=int(s.get("age", 30)),
        class_history=history,
        dex=int(stats.get("DEX", 10)),
        wis=int(stats.get("WIS", 10)),
        int_=int(stats.get("INT", 10)),
        cha=int(stats.get("CHA", 10)),
        str_=int(stats.get("STR", 10)),
        con=int(stats.get("CON", 10)),
        selected_abilities=list(s.get("selected_abilities", [])),
        earned_abilities=earned,
        verbs_known=list(s.get("verbs_known", [])),
    )


# ── Whole-save serialization ─────────────────────────────────────────


def to_dict(player: PlayerState, character_sheet: CharacterSheet | None = None) -> dict[str, Any]:
    """Serialize a Saved into the JSON-friendly dict shape."""
    return {
        "version": _SCHEMA_VERSION,
        "player": _player_to_dict(player),
        "character_sheet": _sheet_to_dict(character_sheet) if character_sheet is not None else None,
    }


def from_dict(data: dict[str, Any]) -> Saved:
    """Reconstruct a Saved from a previously-saved dict.

    Schema migration: V1 (no character_sheet field) loads with
    character_sheet=None. Brain treats that as "legacy player; run
    Pillar 1 to get a sheet."
    """
    player = _player_from_dict(data.get("player", {}))
    sheet_data = data.get("character_sheet")
    sheet = _sheet_from_dict(sheet_data) if sheet_data else None
    return Saved(player=player, character_sheet=sheet)


# ── Disk I/O ─────────────────────────────────────────────────────────


def save(
    player: PlayerState,
    character_sheet: CharacterSheet | None = None,
    path: Optional[Path] = None,
) -> Path:
    """Write the player's state atomically. Returns the path written.

    Atomic write: write to a temp file, then rename. Prevents half-written
    saves from a crash mid-flush corrupting future loads.
    """
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(to_dict(player, character_sheet), indent=2))
    tmp.replace(target)
    return target


def load(path: Optional[Path] = None) -> Optional[Saved]:
    """Read a saved game from disk. Returns None if no save exists OR the
    save is unreadable. V1 saves migrate inline (character_sheet=None)
    so legacy players don't lose progress on the schema bump.
    """
    target = _resolve_path(path)
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"[save] failed to read {target}: {e}", flush=True)
        return None

    version = data.get("version")
    if version == 1:
        # V1 → V2 migration: V1 saves had no character_sheet field. Inject
        # null so the loader treats this as legacy-player-without-sheet.
        # Brain enters CHARACTER_CREATION on next boot to give them a sheet.
        data["character_sheet"] = None
        data["version"] = _SCHEMA_VERSION
    elif version != _SCHEMA_VERSION:
        print(
            f"[save] incompatible schema version {version!r} "
            f"(expected {_SCHEMA_VERSION}); ignoring save", flush=True
        )
        return None

    try:
        return from_dict(data)
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        print(f"[save] malformed save data: {e}", flush=True)
        return None


def delete(path: Optional[Path] = None) -> bool:
    """Remove a save file. Returns True if a file was actually deleted."""
    target = _resolve_path(path)
    if target.exists():
        target.unlink()
        return True
    return False
