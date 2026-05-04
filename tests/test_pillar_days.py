"""Pillar of Days — sundial month → day SELECT cascade.

Verifies the two-turn pattern: initial_prompt offers the 12 months;
choosing one cascades to a day picker sized to that month; choosing a
day commits a (month, day) tuple to the draft as `birthday`.
"""
from __future__ import annotations

from datetime import date

from core.systems import pillars
from core.systems.character_draft import CharacterDraft
from core.systems.dial_prompt import RITUAL, SELECT
from core.systems.pillars.days import DaysHandler, _STAGE_DAY, _STAGE_MONTH


def test_days_handler_registered():
    h = pillars.get("days")
    assert h is not None
    assert h.pillar_id == "days"


def test_initial_prompt_offers_twelve_months():
    h = DaysHandler()
    p = h.initial_prompt(CharacterDraft())
    assert p.mode == SELECT
    assert p.register == RITUAL
    assert p.source == "pillar:days"
    assert len(p.options) == 12
    assert p.pivot_value == _STAGE_MONTH


def test_initial_prompt_default_is_current_month():
    h = DaysHandler()
    p = h.initial_prompt(CharacterDraft())
    today = date.today()
    assert p.default_index == today.month - 1
    assert p.options[p.default_index].value == today.month


def test_initial_prompt_uses_previous_birthday_hint():
    """Re-do flow via Reflection seeds the cascade with the prior birthday's
    month so the player can ENTER through if they want the same date."""
    h = DaysHandler()
    p = h.initial_prompt(CharacterDraft(), hint={"previous_birthday": (3, 15)})
    assert p.default_index == 2  # March
    assert p.options[p.default_index].value == 3


def test_initial_prompt_falls_back_when_hint_invalid():
    h = DaysHandler()
    p = h.initial_prompt(CharacterDraft(), hint={"previous_birthday": (99, 99)})
    today = date.today()
    assert p.default_index == today.month - 1


def test_month_choice_cascades_to_day_dial():
    h = DaysHandler()
    initial = h.initial_prompt(CharacterDraft())
    # Pick March (idx 2).
    follow = h.next_prompt(CharacterDraft(), initial, 2)
    assert follow is not None
    assert follow.mode == SELECT
    assert follow.pivot_value == _STAGE_DAY
    assert "MAR" in follow.label


def test_day_dial_size_matches_calendar():
    h = DaysHandler()
    initial = h.initial_prompt(CharacterDraft())
    # April (idx 3) → 30 days
    apr = h.next_prompt(CharacterDraft(), initial, 3)
    assert len(apr.options) == 30
    # December (idx 11) → 31 days
    dec = h.next_prompt(CharacterDraft(), initial, 11)
    assert len(dec.options) == 31


def test_february_offers_29_days_for_leap_safety():
    """Leap day must always be selectable; whether 2/29 ticks each year is
    handled by the aging system, not the picker."""
    h = DaysHandler()
    initial = h.initial_prompt(CharacterDraft())
    feb = h.next_prompt(CharacterDraft(), initial, 1)
    assert len(feb.options) == 29


def test_day_dial_default_is_today_when_current_month():
    h = DaysHandler()
    initial = h.initial_prompt(CharacterDraft())
    today = date.today()
    follow = h.next_prompt(CharacterDraft(), initial, today.month - 1)
    assert follow.default_index == today.day - 1


def test_day_dial_default_is_first_when_other_month():
    """Picking a month other than today's has no meaningful 'today' anchor;
    default to the 1st so the cursor sits at the calendar's start."""
    h = DaysHandler()
    initial = h.initial_prompt(CharacterDraft())
    today = date.today()
    other_month_idx = (today.month % 12)  # next month's idx
    follow = h.next_prompt(CharacterDraft(), initial, other_month_idx)
    assert follow.default_index == 0


def test_day_choice_returns_none_for_commit():
    """Brain reads None from next_prompt as 'commit via apply()'."""
    h = DaysHandler()
    initial = h.initial_prompt(CharacterDraft())
    day_dial = h.next_prompt(CharacterDraft(), initial, 2)  # March
    assert h.next_prompt(CharacterDraft(), day_dial, 14) is None


def test_apply_with_valid_tuple_returns_birthday():
    h = DaysHandler()
    delta = h.apply((3, 15))
    assert delta == {"birthday": (3, 15)}


def test_apply_with_list_also_works():
    """JSON wire-protocol may decode tuples as lists — handler accepts either."""
    h = DaysHandler()
    delta = h.apply([7, 4])
    assert delta == {"birthday": (7, 4)}


def test_apply_rejects_invalid_month():
    h = DaysHandler()
    assert h.apply((13, 1)) == {}
    assert h.apply((0, 1)) == {}


def test_apply_rejects_invalid_day():
    h = DaysHandler()
    assert h.apply((4, 31)) == {}  # April only has 30
    assert h.apply((2, 30)) == {}  # Feb only has 29


def test_apply_rejects_non_tuple():
    h = DaysHandler()
    assert h.apply("today") == {}
    assert h.apply(15) == {}
    assert h.apply(None) == {}


def test_full_cascade_resolves_to_birthday():
    """End-to-end: initial → month idx → day idx → commit value."""
    h = DaysHandler()
    initial = h.initial_prompt(CharacterDraft())
    # Pick September (idx 8)
    sept_day_dial = h.next_prompt(CharacterDraft(), initial, 8)
    # Pick the 22nd (idx 21)
    chosen_value = sept_day_dial.options[21].value
    assert chosen_value == (9, 22)
    # Sealed via apply
    assert h.apply(chosen_value) == {"birthday": (9, 22)}
