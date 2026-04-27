"""Save / load player progress to disk.

JSON file at ``save/player.json`` (relative to repo root) by default. The
location is overridable via the ``SANCTUM_SAVE_PATH`` env var so tests
can isolate without polluting real saves.

Save fires on every ``RESULTS → HUB`` transition (mission completion is
the natural autosave point) — see brain_server's state_transition_request
handler. Load fires once on brain boot if the file exists.

Schema is versioned. Loads of incompatible schema versions return None
and the brain proceeds with a fresh PlayerState — no crash, no silent
corruption. Bump _SCHEMA_VERSION when the data shape changes; add a
migration in ``_migrate`` if back-compat matters.

Pure data + I/O. No game logic. PlayerState is the source-of-truth type;
this module is the thin disk layer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from core.systems.player_state import Item, PlayerState


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SAVE_PATH = _REPO_ROOT / "save" / "player.json"
_SAVE_PATH_ENV = "SANCTUM_SAVE_PATH"
_SCHEMA_VERSION = 1


def _resolve_path(path: Optional[Path]) -> Path:
    """Pick the save path: explicit arg → env var → default."""
    if path is not None:
        return path
    env = os.environ.get(_SAVE_PATH_ENV)
    if env:
        return Path(env)
    return _DEFAULT_SAVE_PATH


def to_dict(player: PlayerState) -> dict[str, Any]:
    """Serialize a PlayerState into the JSON-friendly dict shape."""
    return {
        "version": _SCHEMA_VERSION,
        "player": {
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
        },
    }


def from_dict(data: dict[str, Any]) -> PlayerState:
    """Reconstruct a PlayerState from a previously-saved dict.

    Defensive on missing fields — if a save predates a field, the
    PlayerState default applies. Item slot_cost defaults to 1 to match
    Item's NamedTuple default.
    """
    p = data.get("player", {})
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


def save(player: PlayerState, path: Optional[Path] = None) -> Path:
    """Write the player's state atomically. Returns the path written.

    Atomic write: write to a temp file, then rename. Prevents half-written
    saves from a crash mid-flush corrupting future loads.
    """
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(to_dict(player), indent=2))
    tmp.replace(target)
    return target


def load(path: Optional[Path] = None) -> Optional[PlayerState]:
    """Read player state from disk. Returns None if no save exists OR the
    save is unreadable / from an incompatible schema version.

    Brain boot calls this once; if it returns None, the brain proceeds with
    a fresh PlayerState.new() — no crash, no silent corruption, just a
    clean fallback.
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
    if version != _SCHEMA_VERSION:
        # Future: route to _migrate. For now refuse to load incompatible
        # saves — better to start fresh than to corrupt.
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
