"""Character sheet generator — defaults, class history, derived properties."""
from __future__ import annotations

import pytest

from core.systems.character_classes import (
    ALL_VERBS,
    CLASSES,
    DEFAULT_STARTING_VERBS,
)
from core.systems.character_sheet import (
    ClassEntry,
    CharacterSheet,
    DEFAULT_PRESTIGE_AGE,
    default_class_history,
    default_selected_abilities,
    earned_from_class_history,
    generate_character_sheet,
    stat_preset_for_history,
)


# ── default_class_history ──


def test_young_character_is_pure_rogue():
    history = default_class_history(20)
    assert len(history) == 1
    assert history[0].name == "rogue"
    assert history[0].levels == 20
    assert history[0].started_at_age == 0


def test_age_at_prestige_threshold_is_first_year_of_monk():
    history = default_class_history(DEFAULT_PRESTIGE_AGE)
    assert len(history) == 2
    assert history[0].name == "rogue" and history[0].levels == DEFAULT_PRESTIGE_AGE
    assert history[1].name == "monk" and history[1].levels == 0


def test_seans_template_at_45():
    history = default_class_history(45)
    assert [(e.name, e.levels) for e in history] == [("rogue", 32), ("monk", 13)]


def test_history_levels_sum_to_age():
    for age in (5, 20, 32, 45, 100):
        history = default_class_history(age)
        assert sum(e.levels for e in history) == age


# ── earned_from_class_history ──


def test_pure_rogue_earns_only_rogue_abilities():
    history = [ClassEntry("rogue", 20, 0)]
    earned = earned_from_class_history(history)
    assert {ab.class_origin for ab in earned} == {"rogue"}
    assert len(earned) == 4


def test_rogue_to_monk_earns_both_pools():
    history = default_class_history(45)
    earned = earned_from_class_history(history)
    origins = {ab.class_origin for ab in earned}
    assert "rogue" in origins
    assert "monk" in origins
    assert len(earned) == 8  # 4 rogue + 4 monk


def test_unknown_class_in_history_is_skipped_not_crash():
    history = [ClassEntry("rogue", 5, 0), ClassEntry("not-a-real-class", 5, 5)]
    earned = earned_from_class_history(history)
    assert {ab.class_origin for ab in earned} == {"rogue"}


# ── default_selected_abilities ──


def test_selection_picks_one_active_per_class():
    history = default_class_history(45)
    earned = earned_from_class_history(history)
    selected = default_selected_abilities(earned, max_n=3)
    # We should have at least one rogue active and one monk active
    selected_origins = []
    for name in selected:
        for ab in earned:
            if ab.name == name:
                selected_origins.append(ab.class_origin)
                break
    assert "rogue" in selected_origins
    assert "monk" in selected_origins


def test_selection_caps_at_max_n():
    history = default_class_history(45)
    earned = earned_from_class_history(history)
    selected = default_selected_abilities(earned, max_n=3)
    assert len(selected) <= 3


def test_pure_rogue_selection_pads_with_passives_if_short():
    history = [ClassEntry("rogue", 20, 0)]
    earned = earned_from_class_history(history)
    selected = default_selected_abilities(earned, max_n=3)
    assert len(selected) == 3  # one active + two passives expected


# ── stat_preset_for_history ──


def test_stat_preset_uses_most_recent_class():
    history = default_class_history(45)  # rogue → monk
    preset = stat_preset_for_history(history)
    assert preset == CLASSES["monk"].stat_preset


def test_stat_preset_fallback_to_rogue_for_empty_history():
    preset = stat_preset_for_history([])
    assert preset == CLASSES["rogue"].stat_preset


# ── generate_character_sheet ──


def test_seans_default_sheet():
    sheet = generate_character_sheet(name="Sean", birthday=(3, 25), age=45)
    assert sheet.name == "Sean"
    assert sheet.birthday == (3, 25)
    assert sheet.age == 45
    assert sheet.level == 45  # property
    # Class history matches Sean's template
    assert [(e.name, e.levels) for e in sheet.class_history] == [("rogue", 32), ("monk", 13)]
    # Stats match monk preset
    assert sheet.dex == 14
    assert sheet.wis == 16
    assert sheet.int_ == 13
    assert sheet.cha == 14
    assert sheet.str_ == 8
    assert sheet.con == 10
    # 3-cap on selection
    assert len(sheet.selected_abilities) <= 3
    # All starter verbs are known
    assert sheet.verbs_known == list(DEFAULT_STARTING_VERBS)
    # Earned pool has both class libraries
    assert len(sheet.earned_abilities) == 8


def test_young_pure_rogue_default():
    sheet = generate_character_sheet(name="A Young One", birthday=(1, 1), age=10)
    assert sheet.age == 10
    assert len(sheet.class_history) == 1
    assert sheet.class_history[0].name == "rogue"
    # Stats use rogue preset
    assert sheet.dex == 14
    assert sheet.wis == 12  # rogue preset


def test_npc_with_custom_history():
    """Watcher NPC uses the same factory."""
    sheet = generate_character_sheet(
        name="The Threadbare Watcher",
        birthday=(11, 1),
        age=147,
        class_history=[ClassEntry("watcher", 147, 0)],
    )
    assert sheet.name == "The Threadbare Watcher"
    assert sheet.age == 147
    # Watcher stats applied
    assert sheet.wis == 18  # watcher preset
    assert sheet.cha == 16
    # Watcher has empty ability library currently
    assert sheet.earned_abilities == []
    assert sheet.selected_abilities == []


def test_hp_and_slots_are_universal():
    """Per design_character_sheet: HP=6, slots=10 fixed for everyone."""
    sheet = generate_character_sheet(name="Sean", birthday=(3, 25), age=45)
    assert sheet.hp == 6
    assert sheet.max_hp == 6


def test_selected_abilities_override():
    """Caller can supply a custom selection."""
    sheet = generate_character_sheet(
        name="Sean", birthday=(3, 25), age=45,
        selected_abilities=["Sneak Attack", "Patient Eye", "Margin Note"],
    )
    assert sheet.selected_abilities == ["Sneak Attack", "Patient Eye", "Margin Note"]


def test_stat_lookup_method():
    sheet = generate_character_sheet(name="Sean", birthday=(3, 25), age=45)
    assert sheet.stat("DEX") == 14
    assert sheet.stat("dex") == 14  # case-insensitive
    assert sheet.stat("WIS") == 16


def test_stat_lookup_invalid_raises():
    sheet = generate_character_sheet(name="Sean", birthday=(3, 25), age=45)
    with pytest.raises(KeyError):
        sheet.stat("LUCK")  # not a real stat


def test_starting_verbs_are_subset_of_seven():
    sheet = generate_character_sheet(name="Sean", birthday=(3, 25), age=45)
    for verb in sheet.verbs_known:
        assert verb in ALL_VERBS


def test_starting_verbs_count_is_four():
    """Per design_seven_pillars: start with 4, earn 3 more through play."""
    sheet = generate_character_sheet(name="Sean", birthday=(3, 25), age=45)
    assert len(sheet.verbs_known) == 4
    assert len(ALL_VERBS) == 7
