"""Load config/attacks.json into a dict of AttackDef records. Consumed
by combat.resolve_round. Keep this module tiny — the library is data."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict

from core.systems.combat import AttackDef, Formula


_PATH = Path(__file__).parent.parent.parent / "config" / "attacks.json"


def _parse_formula(raw: dict) -> Formula:
    return Formula(
        dice=(int(raw["dice"][0]), int(raw["dice"][1])),
        stat=raw.get("stat"),
        const=int(raw.get("const", 0)),
    )


@lru_cache(maxsize=1)
def load() -> Dict[str, AttackDef]:
    """Parse attacks.json into {name: AttackDef}. Cached."""
    with _PATH.open() as f:
        data = json.load(f)
    lib: Dict[str, AttackDef] = {}
    for name, entry in data.items():
        if name.startswith("_"):
            continue
        lib[name] = AttackDef(
            name=name,
            verb=entry["verb"],
            element=entry["element"],
            hit_formula=_parse_formula(entry["hit_formula"]),
            damage_formula=_parse_formula(entry["damage_formula"]),
            target_stat=entry["target_stat"],
            status=entry.get("status"),
        )
    return lib


def get(name: str) -> AttackDef:
    """Lookup by name. Raises KeyError if missing — attacks referenced
    by combat_profile or player actions must exist in the library."""
    lib = load()
    if name not in lib:
        raise KeyError(f"unknown attack {name!r}; known: {sorted(lib)}")
    return lib[name]
