"""Character sheet primitive — the master shape for every character.

Same dataclass for PCs and NPCs per `design_character_sheet`. Multi-class
prestige via `class_history`; 6 stats; 3-ability cap; level=age (Cairn
canonical). The interactive character creation flow lives in
`design_seven_pillars` and writes to this schema; the generator below is
the programmatic substrate (used in tests, NPC instantiation, and
post-pillar finalization).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.systems.abilities import Ability
from core.systems.character_classes import (
    CLASSES,
    DEFAULT_STARTING_VERBS,
)
from core.systems.player_state import Item


@dataclass
class ClassEntry:
    name: str             # class name (key into CLASSES)
    levels: int           # levels gained in this class
    started_at_age: int   # character's age when entering this class


@dataclass
class CharacterSheet:
    name: str
    birthday: tuple[int, int]              # (month, day)
    age: int                               # ticks at each birthday; level = age
    class_history: list[ClassEntry]

    # 6 stats
    dex: int
    wis: int
    int_: int
    cha: int
    str_: int
    con: int

    # 3-cap selection from earned pool
    selected_abilities: list[str]
    earned_abilities: list[Ability]
    verbs_known: list[str]

    # Existing fields (preserved from PlayerState shape)
    hp: int = 6
    max_hp: int = 6
    inventory: list[Item] = field(default_factory=list)
    equipped: str | None = None
    completed_missions: list[str] = field(default_factory=list)

    @property
    def level(self) -> int:
        return self.age

    def stat(self, name: str) -> int:
        """Lookup a stat by canonical name (DEX/WIS/INT/CHA/STR/CON)."""
        return {
            "DEX": self.dex, "WIS": self.wis, "INT": self.int_,
            "CHA": self.cha, "STR": self.str_, "CON": self.con,
        }[name.upper()]


# ── Generation primitives ────────────────────────────────────────────────


# Prestige class kicks in at age 32 by Sean's template. Generic players
# default to this; NPCs and overrides supply their own class_history.
DEFAULT_PRESTIGE_AGE = 32


def default_class_history(age: int) -> list[ClassEntry]:
    """Sean's template: rogue → monk at the prestige age. Younger characters
    are pure rogue. NPCs / custom characters override with their own list."""
    if age < DEFAULT_PRESTIGE_AGE:
        return [ClassEntry("rogue", levels=age, started_at_age=0)]
    return [
        ClassEntry("rogue", levels=DEFAULT_PRESTIGE_AGE, started_at_age=0),
        ClassEntry("monk", levels=age - DEFAULT_PRESTIGE_AGE,
                   started_at_age=DEFAULT_PRESTIGE_AGE),
    ]


def earned_from_class_history(class_history: list[ClassEntry]) -> list[Ability]:
    """Aggregate the unique abilities granted by every class in the history.
    Order preserved; duplicates by name suppressed."""
    abilities: list[Ability] = []
    seen: set[str] = set()
    for entry in class_history:
        cls = CLASSES.get(entry.name)
        if cls is None:
            continue
        for ab in cls.abilities:
            if ab.name not in seen:
                abilities.append(ab)
                seen.add(ab.name)
    return abilities


def default_selected_abilities(
    earned: list[Ability],
    max_n: int = 3,
) -> list[str]:
    """One active per class_origin first, then pad with passives if room.
    Mirrors design_character_sheet's "carry one from each chapter of life"
    intuition."""
    actives_by_class: dict[str, list[str]] = {}
    for ab in earned:
        if ab.kind == "active":
            actives_by_class.setdefault(ab.class_origin, []).append(ab.name)

    selected: list[str] = []
    for names in actives_by_class.values():
        if len(selected) < max_n and names:
            selected.append(names[0])

    if len(selected) < max_n:
        for ab in earned:
            if ab.kind == "passive" and ab.name not in selected:
                selected.append(ab.name)
                if len(selected) == max_n:
                    break

    return selected


def stat_preset_for_history(class_history: list[ClassEntry]) -> dict[str, int]:
    """Most recent class wins (you ARE who you most recently became).
    Returns the canonical 6-stat preset dict."""
    if not class_history:
        return CLASSES["rogue"].stat_preset
    most_recent = class_history[-1].name
    cls = CLASSES.get(most_recent)
    return cls.stat_preset if cls is not None else CLASSES["rogue"].stat_preset


def generate_character_sheet(
    name: str,
    birthday: tuple[int, int],
    age: int,
    class_history: list[ClassEntry] | None = None,
    selected_abilities: list[str] | None = None,
) -> CharacterSheet:
    """Programmatic factory. Pillar-based interactive creation calls this
    at finalization with all fields supplied; tests and NPC instantiation
    use it with defaults."""
    history = class_history if class_history is not None else default_class_history(age)
    earned = earned_from_class_history(history)
    selected = (
        selected_abilities
        if selected_abilities is not None
        else default_selected_abilities(earned)
    )
    preset = stat_preset_for_history(history)

    return CharacterSheet(
        name=name,
        birthday=birthday,
        age=age,
        class_history=history,
        dex=preset["DEX"],
        wis=preset["WIS"],
        int_=preset["INT"],
        cha=preset["CHA"],
        str_=preset["STR"],
        con=preset["CON"],
        selected_abilities=selected,
        earned_abilities=earned,
        verbs_known=list(DEFAULT_STARTING_VERBS),
    )
