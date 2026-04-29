"""Pure helpers for input dispatch — keeps main.py's loop readable.

`next_inventory_name` cycles through the player's inventory each time E is
pressed; `action_for_key_index` resolves a 0-indexed encounter action key
press to its action name regardless of whether action_options[] holds
strings or dicts (brain schema is loose here).
"""
from __future__ import annotations

from typing import Any


def next_inventory_name(inventory: list[dict], equipped: str | None) -> str | None:
    """Return the next item name to equip, cycling through inventory.

    None if inventory is empty. Wraps from last → first.
    """
    names = [str(item.get("name", "")) for item in inventory if item.get("name")]
    if not names:
        return None
    if equipped is None or equipped not in names:
        return names[0]
    idx = names.index(equipped)
    return names[(idx + 1) % len(names)]


def action_for_key_index(action_options: list[Any], key_index: int) -> str | None:
    """Resolve a 0-indexed key press to an action name.

    Brain may emit action_options as strings or as dicts with a `name`
    or `action` key — handle both.
    """
    if key_index < 0 or key_index >= len(action_options):
        return None
    opt = action_options[key_index]
    if isinstance(opt, str):
        return opt
    if isinstance(opt, dict):
        for k in ("name", "action", "id"):
            v = opt.get(k)
            if isinstance(v, str) and v:
                return v
    return None
