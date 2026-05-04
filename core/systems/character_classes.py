"""Class definitions for character generation — Sanctum-thematic six.

Each class has a stat preset (deterministic) and a tuple of class abilities.
The most recent class in a CharacterSheet's class_history wins for the
stat profile; earned_abilities aggregates across the full history.

Per `design_character_sheet`: PC playable paths are rogue/monk/philosopher;
NPC archetypes are watcher/scout/scholar. NPC ability lists are TBD —
they grow as encounters demand them per the "grow as-needed" rule.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.systems.abilities import (
    Ability,
    MONK_ABILITIES,
    PHILOSOPHER_ABILITIES,
    ROGUE_ABILITIES,
)


@dataclass(frozen=True)
class ClassDefinition:
    name: str
    stat_preset: dict[str, int]
    abilities: tuple[Ability, ...]


# Stat presets are 6-stat dicts keyed by the canonical names.
# Range is D&D-flavored 8-18. STR/CON baseline for non-physical archetypes.


CLASSES: dict[str, ClassDefinition] = {
    "rogue": ClassDefinition(
        name="rogue",
        stat_preset={"DEX": 14, "WIS": 12, "INT": 12, "CHA": 12, "STR": 8, "CON": 10},
        abilities=ROGUE_ABILITIES,
    ),
    "monk": ClassDefinition(
        name="monk",
        stat_preset={"DEX": 14, "WIS": 16, "INT": 13, "CHA": 14, "STR": 8, "CON": 10},
        abilities=MONK_ABILITIES,
    ),
    "philosopher": ClassDefinition(
        name="philosopher",
        stat_preset={"DEX": 10, "WIS": 14, "INT": 16, "CHA": 14, "STR": 8, "CON": 10},
        abilities=PHILOSOPHER_ABILITIES,
    ),
    # NPC archetypes — abilities TBD per design_character_sheet's grow-as-needed
    "watcher": ClassDefinition(
        name="watcher",
        stat_preset={"DEX": 10, "WIS": 18, "INT": 14, "CHA": 16, "STR": 8, "CON": 10},
        abilities=(),
    ),
    "scout": ClassDefinition(
        name="scout",
        stat_preset={"DEX": 14, "WIS": 14, "INT": 12, "CHA": 12, "STR": 10, "CON": 12},
        abilities=(),
    ),
    "scholar": ClassDefinition(
        name="scholar",
        stat_preset={"DEX": 10, "WIS": 14, "INT": 16, "CHA": 12, "STR": 8, "CON": 10},
        abilities=(),
    ),
}


# Default starting verbs — players begin knowing 4 of the 7 canonical verbs.
# The remaining 3 (KINDLE, MEDITATE, INSCRIBE) earn through play per
# design_seven_pillars: KINDLE on first torch, MEDITATE on first rest,
# INSCRIBE on first journal entry / pillar interaction.
DEFAULT_STARTING_VERBS: tuple[str, ...] = ("OBSERVE", "MARK", "PARLEY", "REMEMBER")


# Canonical full set of 7 verbs (per design_cairn_substrate).
ALL_VERBS: tuple[str, ...] = (
    "OBSERVE", "MEDITATE", "MARK", "PARLEY", "KINDLE", "REMEMBER", "INSCRIBE",
)
