"""Build a combat encounter roster from a bumped creature + nearby scene.

Pack logic: pack kinds (pack_size_max > 1) pull packmates of the same
kind within pack_radius_m. Solo kinds (pack_size_max == 1) never pull.
Both paths consume the same combat_profile data — "interchangeable
logic" for both archetypes.

Pure function. Caller supplies the player Participant separately (or
None) so this module stays focused on the enemy-building piece.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from core.systems.combat import Participant


def _make_enemy(ent: dict, profile: dict) -> Participant:
    x = float(ent.get("x", 0.0))
    y = float(ent.get("y", 0.0))
    kind = ent.get("kind", "?")
    # Stable id from kind + rounded coords — keeps packmates distinct
    # across runs with deterministic world seeds.
    eid = f"{kind}|{x:.2f}|{y:.2f}"
    return Participant(
        id=eid,
        name=kind,
        hp=int(profile["hp"]),
        max_hp=int(profile["max_hp"]),
        str_=int(profile["str_"]),
        dex=int(profile["dex"]),
        wil=int(profile["wil"]),
        speed=int(profile["speed"]),
        defense=int(profile["defense"]),
        element_mods=dict(profile.get("element_mods", {})),
        side="enemy",
        inventory=(),
        status={},
        alive=True,
    )


def build_encounter(
    bumped_ent: dict,
    visible_ents: List[dict],
    kind_cfgs: Dict[str, dict],
    player: Optional[Participant] = None,
) -> List[Participant]:
    """Return the encounter roster (player first if supplied, then enemies).

    Empty list if the bumped entity isn't a combat-ready creature
    (no `combat_profile` in its kind config).
    """
    kind = bumped_ent.get("kind", "")
    kcfg = kind_cfgs.get(kind, {})
    profile = kcfg.get("combat_profile")
    if not profile:
        return []

    roster: List[Participant] = []
    if player is not None:
        roster.append(player)

    pack_max = int(profile.get("pack_size_max", 1))
    bumped = _make_enemy(bumped_ent, profile)
    roster.append(bumped)

    if pack_max <= 1:
        return roster

    # Pull packmates: same kind, within pack_radius_m, skip the bumped
    # entity itself (matched by exact position). Sort by distance so the
    # "closest first" when the cap trims extras.
    radius = float(profile.get("pack_radius_m", 0.0))
    r_sq = radius * radius
    bx = float(bumped_ent.get("x", 0.0))
    by = float(bumped_ent.get("y", 0.0))

    candidates: List[tuple[float, dict]] = []
    for ent in visible_ents:
        if ent is bumped_ent:
            continue
        if ent.get("kind") != kind:
            continue
        ex = float(ent.get("x", 0.0))
        ey = float(ent.get("y", 0.0))
        d_sq = (ex - bx) ** 2 + (ey - by) ** 2
        if d_sq <= r_sq:
            candidates.append((d_sq, ent))

    candidates.sort(key=lambda t: t[0])
    remaining = pack_max - 1  # bumped already counted
    for _, ent in candidates[:remaining]:
        roster.append(_make_enemy(ent, profile))

    return roster
