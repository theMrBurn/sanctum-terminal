"""Ability primitives — the 3-cap pool for character sheets.

Per `design_character_sheet`: every character carries up to 3 selected
abilities chosen from their earned pool. Active abilities trigger via verb
or encounter action; passives apply always-on bonuses to checks/saves.

The starter library is intentionally small (4 per class) per
`design_character_sheet`'s "grow as-needed" directive — abilities earn
their place by being demanded by encounters, not authored speculatively.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Ability:
    name: str
    kind: Literal["active", "passive"]
    class_origin: str               # "rogue", "monk", "philosopher", ...
    stat: str                       # primary stat: "DEX", "WIS", "INT", "CHA", "STR", "CON"
    description: str
    verb: str | None = None         # which of 7 verbs invokes (active only)
    target_save: str | None = None  # what target rolls vs (active only, if applicable)
    bonus: dict[str, int] = field(default_factory=dict)  # passive-only modifiers


# ── Starter library — 4 per class, mixed active/passive ────────────────────


ROGUE_ABILITIES: tuple[Ability, ...] = (
    Ability(
        name="Sneak Attack",
        kind="active",
        class_origin="rogue",
        stat="DEX",
        description="Bonus damage vs an unaware target.",
        target_save="DEX",
    ),
    Ability(
        name="Pilfer",
        kind="active",
        class_origin="rogue",
        stat="DEX",
        description="Take an item from a container without sound.",
        verb="MARK",
        target_save="WIS",
    ),
    Ability(
        name="Quiet Tread",
        kind="passive",
        class_origin="rogue",
        stat="DEX",
        description="No detection on rough terrain.",
        bonus={"stealth_check": 3},
    ),
    Ability(
        name="Evasion",
        kind="passive",
        class_origin="rogue",
        stat="DEX",
        description="A successful DEX save reduces damage to zero.",
        bonus={"dex_save": 2},
    ),
)


MONK_ABILITIES: tuple[Ability, ...] = (
    Ability(
        name="Stunning Insight",
        kind="active",
        class_origin="monk",
        stat="WIS",
        description="Target rolls INT save or is stunned for one round.",
        verb="OBSERVE",
        target_save="INT",
    ),
    Ability(
        name="Stillness",
        kind="active",
        class_origin="monk",
        stat="WIS",
        description="Meditate to recover HP and clear status effects.",
        verb="MEDITATE",
    ),
    Ability(
        name="Patient Eye",
        kind="passive",
        class_origin="monk",
        stat="WIS",
        description="Sees what was hidden from casual notice.",
        bonus={"perception_check": 3},
    ),
    Ability(
        name="Inner Calm",
        kind="passive",
        class_origin="monk",
        stat="WIS",
        description="Immune to fear and awe effects.",
        bonus={"wis_save": 2},
    ),
)


PHILOSOPHER_ABILITIES: tuple[Ability, ...] = (
    Ability(
        name="Margin Note",
        kind="active",
        class_origin="philosopher",
        stat="INT",
        description="Inscribe an entity into your journal for later recall.",
        verb="INSCRIBE",
    ),
    Ability(
        name="Cite",
        kind="active",
        class_origin="philosopher",
        stat="CHA",
        description="Quote an NPC's words back as evidence; target rolls CHA save.",
        verb="PARLEY",
        target_save="CHA",
    ),
    Ability(
        name="Perfect Recall",
        kind="passive",
        class_origin="philosopher",
        stat="INT",
        description="Can REMEMBER any inscribed thing without a check.",
        bonus={"int_check": 3},
    ),
    Ability(
        name="Citation",
        kind="passive",
        class_origin="philosopher",
        stat="CHA",
        description="Bonus to dialog with NPCs you have cited before.",
        bonus={"cha_check": 2},
    ),
)


# Lookup helpers — keep simple, derive when needed rather than caching.


def find_ability(name: str, pool: list[Ability]) -> Ability | None:
    for ab in pool:
        if ab.name == name:
            return ab
    return None


def abilities_by_kind(pool: list[Ability], kind: str) -> list[Ability]:
    return [ab for ab in pool if ab.kind == kind]
